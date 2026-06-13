"""Platform Admin API routes.

This module defines FastAPI routes for Platform Admin operations including:
- Admin authentication
- Subscription plan CRUD
- Institution management
- Aggregate analytics
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db.session import get_session
from ..middleware.rbac import require_platform_admin
from .platform_admin_models import (
    AdminLoginRequest,
    AdminLoginResponse,
    AggregateAnalyticsResponse,
    CreateSubscriptionPlanRequest,
    InstitutionListResponse,
    InstitutionResponse,
    SubscriptionPlanResponse,
    SuccessResponse,
    UpdateSubscriptionPlanRequest,
)
from .platform_admin_service import PlatformAdminService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/platform", tags=["Platform Admin"])


# -----------------------------------------------------------------------------
# Admin Authentication
# -----------------------------------------------------------------------------


@router.post("/check-config", response_model=AdminLoginResponse)
def check_admin_config(db: Session = Depends(get_session)) -> AdminLoginResponse:
    """Check if Platform Admin is configured.
    
    This endpoint checks if ADMIN_EMAIL and ADMIN_PASSWORD_HASH environment
    variables are set. It does not require authentication.
    """
    service = PlatformAdminService(db)
    is_configured = service.is_admin_configured()
    
    if is_configured:
        return AdminLoginResponse(
            success=True,
            message="Platform Admin is configured",
            admin_configured=True,
        )
    else:
        return AdminLoginResponse(
            success=False,
            message="Platform Admin is not configured. Set ADMIN_EMAIL and ADMIN_PASSWORD_HASH environment variables.",
            admin_configured=False,
        )


# -----------------------------------------------------------------------------
# Subscription Plan CRUD
# -----------------------------------------------------------------------------


@router.post("/subscription-plans", response_model=SubscriptionPlanResponse, status_code=status.HTTP_201_CREATED)
def create_subscription_plan(
    request: CreateSubscriptionPlanRequest,
    db: Session = Depends(get_session),
    _: dict = Depends(require_platform_admin),
) -> SubscriptionPlanResponse:
    """Create a new subscription plan.
    
    Requires Platform Admin authentication.
    """
    service = PlatformAdminService(db)
    
    try:
        plan = service.create_subscription_plan(
            name=request.name,
            plan_type=request.plan_type,
            billing_period=request.billing_period,
            price=request.price,
            max_test_attempts_per_period=request.max_test_attempts_per_period,
            max_student_seats=request.max_student_seats,
            feature_flags=request.feature_flags,
        )
        return SubscriptionPlanResponse.model_validate(plan)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/subscription-plans/{plan_id}", response_model=SubscriptionPlanResponse)
def get_subscription_plan(
    plan_id: UUID,
    db: Session = Depends(get_session),
    _: dict = Depends(require_platform_admin),
) -> SubscriptionPlanResponse:
    """Get a subscription plan by ID.
    
    Requires Platform Admin authentication.
    """
    service = PlatformAdminService(db)
    plan = service.get_subscription_plan(plan_id)
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription plan {plan_id} not found",
        )
    
    return SubscriptionPlanResponse.model_validate(plan)


@router.get("/subscription-plans", response_model=List[SubscriptionPlanResponse])
def list_subscription_plans(
    plan_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_session),
    _: dict = Depends(require_platform_admin),
) -> List[SubscriptionPlanResponse]:
    """List all subscription plans with optional filters.
    
    Requires Platform Admin authentication.
    """
    service = PlatformAdminService(db)
    plans = service.list_subscription_plans(
        plan_type=plan_type,
        is_active=is_active,
    )
    
    return [SubscriptionPlanResponse.model_validate(plan) for plan in plans]


@router.patch("/subscription-plans/{plan_id}", response_model=SubscriptionPlanResponse)
def update_subscription_plan(
    plan_id: UUID,
    request: UpdateSubscriptionPlanRequest,
    db: Session = Depends(get_session),
    _: dict = Depends(require_platform_admin),
) -> SubscriptionPlanResponse:
    """Update a subscription plan.
    
    Requires Platform Admin authentication.
    """
    service = PlatformAdminService(db)
    
    try:
        plan = service.update_subscription_plan(
            plan_id=plan_id,
            name=request.name,
            price=request.price,
            max_test_attempts_per_period=request.max_test_attempts_per_period,
            max_student_seats=request.max_student_seats,
            feature_flags=request.feature_flags,
            is_active=request.is_active,
        )
        return SubscriptionPlanResponse.model_validate(plan)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/subscription-plans/{plan_id}", response_model=SuccessResponse)
def delete_subscription_plan(
    plan_id: UUID,
    db: Session = Depends(get_session),
    _: dict = Depends(require_platform_admin),
) -> SuccessResponse:
    """Delete a subscription plan.
    
    Rejects deletion if the plan has active subscribers.
    Requires Platform Admin authentication.
    """
    service = PlatformAdminService(db)
    
    try:
        service.delete_subscription_plan(plan_id)
        return SuccessResponse(
            success=True,
            message=f"Subscription plan {plan_id} deleted successfully",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# -----------------------------------------------------------------------------
# Institution Management
# -----------------------------------------------------------------------------


@router.post("/institutions/{institution_id}/activate", response_model=InstitutionResponse)
def activate_institution(
    institution_id: UUID,
    db: Session = Depends(get_session),
    _: dict = Depends(require_platform_admin),
) -> InstitutionResponse:
    """Activate an institution.
    
    Requires Platform Admin authentication.
    """
    service = PlatformAdminService(db)
    
    try:
        institution = service.activate_institution(institution_id)
        return InstitutionResponse.model_validate(institution)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.post("/institutions/{institution_id}/suspend", response_model=InstitutionResponse)
def suspend_institution(
    institution_id: UUID,
    db: Session = Depends(get_session),
    _: dict = Depends(require_platform_admin),
) -> InstitutionResponse:
    """Suspend an institution.
    
    Requires Platform Admin authentication.
    """
    service = PlatformAdminService(db)
    
    try:
        institution = service.suspend_institution(institution_id)
        return InstitutionResponse.model_validate(institution)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.delete("/institutions/{institution_id}", response_model=SuccessResponse)
def remove_institution(
    institution_id: UUID,
    db: Session = Depends(get_session),
    _: dict = Depends(require_platform_admin),
) -> SuccessResponse:
    """Remove an institution.
    
    This will cascade delete all related data (subscriptions, invitations, etc.)
    Requires Platform Admin authentication.
    """
    service = PlatformAdminService(db)
    
    try:
        service.remove_institution(institution_id)
        return SuccessResponse(
            success=True,
            message=f"Institution {institution_id} removed successfully",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.get("/institutions", response_model=InstitutionListResponse)
def list_institutions(
    subscription_status: Optional[str] = None,
    db: Session = Depends(get_session),
    _: dict = Depends(require_platform_admin),
) -> InstitutionListResponse:
    """List all institutions with optional filters.
    
    Requires Platform Admin authentication.
    """
    service = PlatformAdminService(db)
    institutions = service.list_institutions(subscription_status=subscription_status)
    
    return InstitutionListResponse(
        institutions=[InstitutionResponse.model_validate(inst) for inst in institutions],
        total=len(institutions),
    )


# -----------------------------------------------------------------------------
# Aggregate Analytics
# -----------------------------------------------------------------------------


@router.get("/analytics", response_model=AggregateAnalyticsResponse)
def get_aggregate_analytics(
    db: Session = Depends(get_session),
    _: dict = Depends(require_platform_admin),
) -> AggregateAnalyticsResponse:
    """Get aggregate analytics for the entire platform.
    
    Includes:
    - Active users count by role and subscription status
    - Subscription distribution by status and type
    - Exam attempt statistics
    - Revenue statistics
    
    Requires Platform Admin authentication.
    """
    service = PlatformAdminService(db)
    analytics = service.get_aggregate_analytics()
    
    return AggregateAnalyticsResponse(**analytics)


__all__ = ["router"]
