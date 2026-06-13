"""Integration tests for main application setup.

Tests that all routers and startup events are properly registered.
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

# Add backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_main_app_imports():
    """Test that the main application imports successfully."""
    import os
    os.environ["SMARTKCET_SKIP_STARTUP_GUARD"] = "1"
    
    from smartkcet.main import app
    
    assert app is not None
    assert app.title == "ExamForge Backend"


def test_subscription_router_registered():
    """Test that subscription router is registered with correct routes."""
    import os
    os.environ["SMARTKCET_SKIP_STARTUP_GUARD"] = "1"
    
    from smartkcet.main import app
    
    # Get all route paths
    route_paths = [route.path for route in app.routes if hasattr(route, "path")]
    
    # Verify subscription routes are registered
    assert "/api/subscription/select" in route_paths
    assert "/api/subscription/status" in route_paths
    assert "/api/subscription/upgrade" in route_paths
    assert "/api/subscription/cancel" in route_paths
    assert "/api/subscription/reactivate" in route_paths
    assert "/api/subscription/remaining-attempts" in route_paths


def test_institution_router_registered():
    """Test that institution router is registered with correct routes."""
    import os
    os.environ["SMARTKCET_SKIP_STARTUP_GUARD"] = "1"
    
    from smartkcet.main import app
    
    # Get all route paths
    route_paths = [route.path for route in app.routes if hasattr(route, "path")]
    
    # Verify institution routes are registered
    assert "/api/institution/register" in route_paths
    assert "/api/institution/invite" in route_paths
    assert "/api/institution/accept-invite" in route_paths
    assert "/api/institution/students" in route_paths
    assert "/api/institution/analytics" in route_paths
    assert "/api/institution/subscription/select" in route_paths


def test_scheduler_startup_handler_registered():
    """Test that scheduler startup handler is registered."""
    import os
    os.environ["SMARTKCET_SKIP_STARTUP_GUARD"] = "1"
    
    from smartkcet.main import app
    
    # Verify startup handlers are registered
    assert len(app.router.on_startup) >= 1
    
    # Verify scheduler startup handler is present
    handler_names = [h.__name__ for h in app.router.on_startup]
    assert "startup_scheduler" in handler_names


def test_scheduler_shutdown_handler_registered():
    """Test that scheduler shutdown handler is registered."""
    import os
    os.environ["SMARTKCET_SKIP_STARTUP_GUARD"] = "1"
    
    from smartkcet.main import app
    
    # Verify shutdown handlers are registered
    assert len(app.router.on_shutdown) >= 1
    
    # Verify scheduler shutdown handler is present
    handler_names = [h.__name__ for h in app.router.on_shutdown]
    assert "shutdown_scheduler" in handler_names


def test_scheduler_module_imports():
    """Test that scheduler module imports successfully."""
    from smartkcet.subscription.scheduler import (
        SubscriptionScheduler,
        get_scheduler_interval,
        start_subscription_scheduler,
        stop_subscription_scheduler,
    )
    
    # Verify functions are callable
    assert callable(start_subscription_scheduler)
    assert callable(stop_subscription_scheduler)
    assert callable(get_scheduler_interval)
    
    # Verify default interval
    interval = get_scheduler_interval()
    assert interval == 60  # Default 60 minutes


def test_scheduler_interval_configurable():
    """Test that scheduler interval is configurable via environment variable."""
    import os
    
    # Test custom interval
    os.environ["SUBSCRIPTION_SCHEDULER_INTERVAL_MINUTES"] = "30"
    
    from smartkcet.subscription.scheduler import get_scheduler_interval
    
    interval = get_scheduler_interval()
    assert interval == 30
    
    # Clean up
    del os.environ["SUBSCRIPTION_SCHEDULER_INTERVAL_MINUTES"]


def test_all_required_modules_importable():
    """Test that all required modules can be imported."""
    # Subscription module
    from smartkcet.subscription import router as subscription_router
    from smartkcet.subscription.service import SubscriptionService
    from smartkcet.subscription.scheduler import (
        start_subscription_scheduler,
        stop_subscription_scheduler,
    )
    
    # Institution module
    from smartkcet.institution import router as institution_router
    from smartkcet.institution.service import InstitutionService
    
    # Verify routers are APIRouter instances
    from fastapi import APIRouter
    assert isinstance(subscription_router, APIRouter)
    assert isinstance(institution_router, APIRouter)
    
    # Verify services are classes
    assert callable(SubscriptionService)
    assert callable(InstitutionService)
    
    # Verify scheduler functions are callable
    assert callable(start_subscription_scheduler)
    assert callable(stop_subscription_scheduler)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
