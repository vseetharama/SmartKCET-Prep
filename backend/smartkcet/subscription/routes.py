"""FastAPI routes for subscription management.

This module defines the API endpoints for subscription operations:
- Subscription selection and activation
- Subscription status queries
- Subscription upgrades and cancellations
- Subscription reactivation
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db.session import get_async_session as get_session
from ..middleware.rbac import current_user, require_authenticated
from .models import (
    BillingPeriod,
    EffectiveSubscriptionStatus,
    SubscriptionCreate,
    SubscriptionReactivate,
    SubscriptionResponse,
    SubscriptionUpgrade,
)
from .service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


@router.post("/select", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def select_subscription_plan(
    request: Request,
    data: SubscriptionCreate,
    payload: Annotated[dict, Depends(require_authenticated)],
    db: Session = Depends(get_session),
):
    """Select and activate a subscription plan (trial or pro) for the authenticated user.
    
    This endpoint handles initial subscription selection when a user first logs in.
    It is idempotent - if a subscription already exists, it returns the existing one.
    
    **Requirements:** 1.1, 1.2, 1.3, 1.4, 1.6, 1.7, 1.8
    
    Args:
        request: FastAPI request object
        data: Subscription creation data (plan_type, billing_period, trial_duration_days)
        payload: JWT payload from authentication middleware
        db: Database session
        
    Returns:
        Created or existing subscription details
        
    Raises:
        HTTPException: 
            - 400 if validation fails
            - 401 if user not found
            - 503 if database error occurs (retry-friendly)
    """
    user = current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "auth_required", "message": "User not found"},
        )
    
    service = SubscriptionService(db)
    
    try:
        if data.plan_type == "trial":
            # Activate Free Trial subscription
            trial_duration = data.trial_duration_days or 7
            subscription = service.activate_trial(user.id, trial_duration)
            logger.info(f"Activated trial subscription for user {user.id}")
        
        elif data.plan_type == "pro":
            # Activate Pro subscription
            if not data.billing_period:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "validation_error",
                        "field": "billing_period",
                        "message": "billing_period is required for Pro subscriptions",
                    },
                )
            subscription = service.activate_pro(user.id, data.billing_period)
            logger.info(
                f"Activated Pro subscription ({data.billing_period.value}) for user {user.id}"
            )
        
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "validation_error",
                    "field": "plan_type",
                    "message": f"Invalid plan_type: {data.plan_type}. Must be 'trial' or 'pro'",
                },
            )
        
        return SubscriptionResponse.model_validate(subscription)
    
    except ValueError as e:
        # Service-level validation errors — distinguish trial-abuse from other errors
        logger.warning(f"Validation error in subscription selection: {e}")
        msg = str(e)
        # Trial already used — return 409 Conflict with a clear message
        if "once per account" in msg or "already" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "trial_already_used",
                    "message": msg,
                },
            ) from e
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "validation_error",
                "message": msg,
            },
        ) from e
    
    except SQLAlchemyError as e:
        # Database errors - return 503 for retry-friendly response
        logger.error(f"Database error during subscription activation: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Could not complete subscription activation. Please retry.",
                "retry_after_sec": 5,
            },
        ) from e


@router.post("/activate-free", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def activate_free_plan(
    request: Request,
    payload: Annotated[dict, Depends(require_authenticated)],
    db: Session = Depends(get_session),
):
    """Activate Free plan (₹0) for a personal student.

    Business rules:
    - Allowed only when user has NO active subscription (status null, expired,
      or cancelled).
    - Blocked when user already has an active subscription with status in
      ['trial', 'active', 'trialing', 'grace_period'].  Returns 400 in that case.
    - The free plan provides limited access: 3–5 mock tests, limited question
      bank, and basic score analytics.

    Args:
        request: FastAPI request object
        payload: JWT payload from authentication middleware
        db: Database session

    Returns:
        Created subscription details (HTTP 201)

    Raises:
        HTTPException:
            - 400 if user already has an active subscription
            - 401 if user not found / unauthenticated
            - 404 if Free plan not configured in database
            - 503 if database error occurs (retry-friendly)
    """
    user = current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "auth_required", "message": "User not found"},
        )

    # ── Business rule: block if an active subscription already exists ──────
    from ..db.subscription_models import Subscription as SubscriptionModel
    ACTIVE_STATUSES = ["trial", "active", "trialing", "grace_period"]

    existing_active = (
        db.query(SubscriptionModel)
        .filter(
            SubscriptionModel.user_id == user.id,
            SubscriptionModel.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )

    if existing_active:
        logger.info(
            f"Free plan blocked for user {user.id} — active subscription "
            f"exists (status={existing_active.status})"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "subscription_active",
                "message": (
                    "Current subscription active. "
                    "Free plan available after expiry."
                ),
            },
        )

    service = SubscriptionService(db)

    try:
        logger.info("[activate-free] endpoint hit — activating free plan for user %s", user.id)
        subscription = service.activate_free(user.id)
        logger.info(f"Activated Free plan for user {user.id}")
        return SubscriptionResponse.model_validate(subscription)

    except ValueError as e:
        msg = str(e)
        logger.warning(f"Free plan activation validation error for user {user.id}: {msg}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "plan_not_found",
                "message": msg,
            },
        ) from e

    except SQLAlchemyError as e:
        logger.error(f"Database error during free plan activation: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Could not complete free plan activation. Please retry.",
                "retry_after_sec": 5,
            },
        ) from e


@router.get("/status", response_model=EffectiveSubscriptionStatus)
async def get_subscription_status(
    request: Request,
    payload: Annotated[dict, Depends(require_authenticated)],
    db: Session = Depends(get_session),
):
    """Get the effective subscription status for the authenticated user.
    
    Returns comprehensive subscription information including:
    - Current subscription status
    - Plan type and billing period
    - Trial attempts remaining (if applicable)
    - Renewal dates and grace period information
    - Institution linkage (if applicable)
    
    **Requirements:** 1.1, 1.5, 13.6, 13.7
    
    Args:
        request: FastAPI request object
        payload: JWT payload from authentication middleware
        db: Database session
        
    Returns:
        Effective subscription status with all details
        
    Raises:
        HTTPException: 
            - 401 if user not found
            - 503 if database error occurs (retry-friendly)
    """
    user = current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "auth_required", "message": "User not found"},
        )
    
    service = SubscriptionService(db)
    
    try:
        effective_status = service.get_effective_status(user.id)
        logger.debug(f"Retrieved subscription status for user {user.id}")
        return effective_status
    
    except SQLAlchemyError as e:
        # Database errors - return 503 for retry-friendly response
        logger.error(f"Database error retrieving subscription status: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Could not retrieve subscription status. Please retry.",
                "retry_after_sec": 5,
            },
        ) from e


@router.post("/upgrade", response_model=SubscriptionResponse)
async def upgrade_subscription(
    request: Request,
    data: SubscriptionUpgrade,
    payload: Annotated[dict, Depends(require_authenticated)],
    db: Session = Depends(get_session),
):
    """Upgrade from trial to Pro subscription.
    
    Converts the user's current Free Trial subscription to a Pro subscription
    with the specified billing period. All existing exam history and analytics
    data are preserved.
    
    **Requirements:** 4.5, 4.6
    
    Args:
        request: FastAPI request object
        data: Upgrade request data (billing_period)
        payload: JWT payload from authentication middleware
        db: Database session
        
    Returns:
        Updated subscription details
        
    Raises:
        HTTPException: 
            - 400 if user doesn't have an active trial subscription
            - 401 if user not found
            - 402 if payment fails (simulated for now)
            - 503 if database error occurs (retry-friendly)
    """
    user = current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "auth_required", "message": "User not found"},
        )
    
    service = SubscriptionService(db)
    
    try:
        # Payment is now handled via the Razorpay payment flow:
        # POST /api/payments/create-order  → POST /api/payments/webhook → activation
        # This endpoint still exists for backward compat but now requires
        # the plan to already be activated via webhook.
        # Direct upgrade (no payment) is only allowed in dev mode.
        import os
        dev_mode = os.getenv("SMARTKCET_DEV_MODE", "0") == "1"

        if dev_mode:
            subscription = service.upgrade_trial_to_pro(user.id, data.billing_period)
            logger.info(
                f"DEV MODE — upgraded trial to Pro ({data.billing_period.value}) for user {user.id}"
            )
        else:
            # In production, upgrades go through the payment flow
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "payment_required",
                    "message": "Please use the subscription pricing page to upgrade your plan.",
                    "redirect": "/subscription",
                },
            )
        return SubscriptionResponse.model_validate(subscription)
    
    except ValueError as e:
        # Service-level errors (e.g., no trial subscription found)
        logger.warning(f"Upgrade failed for user {user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "upgrade_failed",
                "message": str(e),
            },
        ) from e
    
    except SQLAlchemyError as e:
        # Database errors - return 503 for retry-friendly response
        logger.error(f"Database error during subscription upgrade: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Could not complete subscription upgrade. Please retry.",
                "retry_after_sec": 5,
            },
        ) from e


@router.post("/cancel", response_model=SubscriptionResponse)
async def cancel_subscription(
    request: Request,
    payload: Annotated[dict, Depends(require_authenticated)],
    db: Session = Depends(get_session),
):
    """Cancel the authenticated user's subscription.
    
    The subscription will be marked for cancellation but will remain active
    until the end of the current billing period. Full access is maintained
    until that date.
    
    **Requirements:** 4.7
    
    Args:
        request: FastAPI request object
        payload: JWT payload from authentication middleware
        db: Database session
        
    Returns:
        Updated subscription details
        
    Raises:
        HTTPException: 
            - 401 if user not found
            - 404 if no active subscription found
            - 503 if database error occurs (retry-friendly)
    """
    user = current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "auth_required", "message": "User not found"},
        )
    
    service = SubscriptionService(db)
    
    try:
        # Get the user's current active subscription
        from ..db.subscription_models import Subscription
        
        active_subscription = (
            db.query(Subscription)
            .filter(
                Subscription.user_id == user.id,
                Subscription.status.in_(["trial", "active", "overdue", "grace_period"])
            )
            .first()
        )
        
        if not active_subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "subscription_not_found",
                    "message": "No active subscription found to cancel",
                },
            )
        
        subscription = service.cancel_subscription(active_subscription.id)
        logger.info(f"Cancelled subscription for user {user.id}")
        return SubscriptionResponse.model_validate(subscription)
    
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    
    except ValueError as e:
        # Service-level errors
        logger.warning(f"Cancellation failed for user {user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "cancellation_failed",
                "message": str(e),
            },
        ) from e
    
    except SQLAlchemyError as e:
        # Database errors - return 503 for retry-friendly response
        logger.error(f"Database error during subscription cancellation: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Could not complete subscription cancellation. Please retry.",
                "retry_after_sec": 5,
            },
        ) from e


@router.post("/reactivate", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def reactivate_subscription(
    request: Request,
    data: SubscriptionReactivate,
    payload: Annotated[dict, Depends(require_authenticated)],
    db: Session = Depends(get_session),
):
    """Reactivate an expired or cancelled subscription.
    
    Creates a new active Pro subscription for users who previously had a
    subscription that expired or was cancelled. All existing exam history
    and analytics data are preserved.
    
    **Requirements:** 4.8
    
    Args:
        request: FastAPI request object
        data: Reactivation request data (billing_period)
        payload: JWT payload from authentication middleware
        db: Database session
        
    Returns:
        New subscription details
        
    Raises:
        HTTPException: 
            - 400 if user already has an active subscription
            - 401 if user not found
            - 402 if payment fails (simulated for now)
            - 503 if database error occurs (retry-friendly)
    """
    user = current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "auth_required", "message": "User not found"},
        )
    
    service = SubscriptionService(db)

    try:
        import os
        dev_mode = os.getenv("SMARTKCET_DEV_MODE", "0") == "1"

        if dev_mode:
            subscription = service.reactivate(user.id, data.billing_period)
            logger.info(f"DEV MODE — reactivated subscription ({data.billing_period.value}) for user {user.id}")
        else:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "payment_required",
                    "message": "Please use the subscription pricing page to reactivate your plan.",
                    "redirect": "/subscription",
                },
            )
        return SubscriptionResponse.model_validate(subscription)
    
    except ValueError as e:
        # Service-level errors (e.g., already has active subscription)
        logger.warning(f"Reactivation failed for user {user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "reactivation_failed",
                "message": str(e),
            },
        ) from e
    
    except SQLAlchemyError as e:
        # Database errors - return 503 for retry-friendly response
        logger.error(f"Database error during subscription reactivation: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Could not complete subscription reactivation. Please retry.",
                "retry_after_sec": 5,
            },
        ) from e


@router.get("/remaining-attempts")
async def get_remaining_attempts(
    request: Request,
    payload: Annotated[dict, Depends(require_authenticated)],
    db: Session = Depends(get_session),
):
    """Get remaining exam attempts for the authenticated user.
    
    Returns information about exam attempt quota for display on dashboard
    and exam selection screens.
    
    **Requirements:** 2.4
    
    Args:
        request: FastAPI request object
        payload: JWT payload from authentication middleware
        db: Database session
        
    Returns:
        Remaining attempts information
        
    Raises:
        HTTPException: 
            - 401 if user not found
            - 503 if database error occurs (retry-friendly)
    """
    user = current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "auth_required", "message": "User not found"},
        )
    
    from .access_control import SubscriptionAccessControl
    
    access_control = SubscriptionAccessControl(db)
    
    try:
        remaining = access_control.get_remaining_attempts(user.id)
        logger.debug(f"Retrieved remaining attempts for user {user.id}")
        return remaining
    
    except SQLAlchemyError as e:
        # Database errors - return 503 for retry-friendly response
        logger.error(f"Database error retrieving remaining attempts: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Could not retrieve remaining attempts. Please retry.",
                "retry_after_sec": 5,
            },
        ) from e


__all__ = ["router"]

