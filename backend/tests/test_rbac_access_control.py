"""Unit tests for RBAC access control matrix (Task 8.6).

Tests the check_feature_access function and require_active_subscription dependency.

**Requirements:** 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 7.5, 7.6, 7.7, 7.8, 11.5
"""

import pytest
from fastapi import HTTPException

from smartkcet.middleware.rbac import (
    check_feature_access,
    require_active_subscription,
)


class TestCheckFeatureAccess:
    """Test access control matrix evaluation."""
    
    def test_platform_admin_has_full_access(self):
        """Test that platform_admin has access to all features."""
        payload = {"role": "platform_admin", "sub": "admin@example.com"}
        
        # Platform admin should have access to all features
        assert check_feature_access(payload, "exam_access") is True
        assert check_feature_access(payload, "full_analytics") is True
        assert check_feature_access(payload, "basic_analytics") is True
        assert check_feature_access(payload, "leaderboard") is True
        assert check_feature_access(payload, "question_management") is True
        assert check_feature_access(payload, "institution_management") is True
        assert check_feature_access(payload, "platform_settings") is True
    
    def test_institution_admin_access(self):
        """Test institution_admin access to features."""
        payload = {
            "role": "institution_admin",
            "sub": "inst_admin@example.com",
            "institution_id": "inst-123",
        }
        
        # Institution admin should have access to question and institution management
        assert check_feature_access(payload, "question_management") is True
        assert check_feature_access(payload, "institution_management") is True
        
        # But not to other features
        assert check_feature_access(payload, "exam_access") is False
        assert check_feature_access(payload, "full_analytics") is False
        assert check_feature_access(payload, "basic_analytics") is False
        assert check_feature_access(payload, "leaderboard") is False
        assert check_feature_access(payload, "platform_settings") is False
    
    def test_student_trial_access(self):
        """Test Free Trial student access restrictions."""
        payload = {
            "role": "student",
            "sub": "TEST001",
            "student_subtype": "direct_subscriber",
            "subscription_status": "trial",
        }
        
        # Trial students can access exams (with 5 attempt limit enforced elsewhere)
        assert check_feature_access(payload, "exam_access") is True
        
        # Trial students get basic analytics only
        assert check_feature_access(payload, "basic_analytics") is True
        assert check_feature_access(payload, "full_analytics") is False
        
        # Trial students cannot see leaderboard
        assert check_feature_access(payload, "leaderboard") is False
        
        # Trial students cannot manage questions or institutions
        assert check_feature_access(payload, "question_management") is False
        assert check_feature_access(payload, "institution_management") is False
        assert check_feature_access(payload, "platform_settings") is False
    
    def test_student_pro_active_access(self):
        """Test Pro subscription (active) student access."""
        payload = {
            "role": "student",
            "sub": "TEST002",
            "student_subtype": "direct_subscriber",
            "subscription_status": "active",
        }
        
        # Pro students have unlimited exam access
        assert check_feature_access(payload, "exam_access") is True
        
        # Pro students get full analytics
        assert check_feature_access(payload, "basic_analytics") is True
        assert check_feature_access(payload, "full_analytics") is True
        
        # Pro students can see leaderboard
        assert check_feature_access(payload, "leaderboard") is True
        
        # Pro students still cannot manage questions or institutions
        assert check_feature_access(payload, "question_management") is False
        assert check_feature_access(payload, "institution_management") is False
        assert check_feature_access(payload, "platform_settings") is False
    
    def test_student_grace_period_access(self):
        """Test student in grace period maintains Pro access."""
        payload = {
            "role": "student",
            "sub": "TEST003",
            "student_subtype": "direct_subscriber",
            "subscription_status": "grace_period",
        }
        
        # Grace period students maintain full access
        assert check_feature_access(payload, "exam_access") is True
        assert check_feature_access(payload, "basic_analytics") is True
        assert check_feature_access(payload, "full_analytics") is True
        assert check_feature_access(payload, "leaderboard") is True
    
    def test_student_expired_no_access(self):
        """Test expired subscription student has no access."""
        payload = {
            "role": "student",
            "sub": "TEST004",
            "student_subtype": "direct_subscriber",
            "subscription_status": "expired",
        }
        
        # Expired students have no access
        assert check_feature_access(payload, "exam_access") is False
        assert check_feature_access(payload, "basic_analytics") is False
        assert check_feature_access(payload, "full_analytics") is False
        assert check_feature_access(payload, "leaderboard") is False
    
    def test_student_cancelled_no_access(self):
        """Test cancelled subscription student has no access."""
        payload = {
            "role": "student",
            "sub": "TEST005",
            "student_subtype": "direct_subscriber",
            "subscription_status": "cancelled",
        }
        
        # Cancelled students have no access
        assert check_feature_access(payload, "exam_access") is False
        assert check_feature_access(payload, "basic_analytics") is False
        assert check_feature_access(payload, "full_analytics") is False
        assert check_feature_access(payload, "leaderboard") is False
    
    def test_institution_linked_student_access(self):
        """Test institution-linked student access."""
        payload = {
            "role": "student",
            "sub": "TEST006",
            "student_subtype": "institution_linked",
            "subscription_status": "active",
            "institution_id": "inst-123",
        }
        
        # Institution students have access based on institution plan
        assert check_feature_access(payload, "exam_access") is True
        assert check_feature_access(payload, "basic_analytics") is True
        assert check_feature_access(payload, "full_analytics") is True
        assert check_feature_access(payload, "leaderboard") is True
    
    def test_dual_subscription_higher_permission(self):
        """Test dual subscription gets higher permission level."""
        payload = {
            "role": "student",
            "sub": "TEST007",
            "student_subtype": "dual",
            "subscription_status": "trial",  # Individual is trial
            "institution_id": "inst-123",
        }
        
        # Dual subscription should get Pro-level access (higher of two)
        # For MVP, dual is treated as active
        assert check_feature_access(payload, "exam_access") is True
        assert check_feature_access(payload, "full_analytics") is True
        assert check_feature_access(payload, "leaderboard") is True
    
    def test_unknown_feature_denies_access(self):
        """Test that unknown features are denied by default."""
        payload = {
            "role": "student",
            "sub": "TEST008",
            "student_subtype": "direct_subscriber",
            "subscription_status": "active",
        }
        
        # Unknown feature should be denied
        assert check_feature_access(payload, "unknown_feature") is False
    
    def test_missing_role_denies_access(self):
        """Test that missing role denies access."""
        payload = {"sub": "TEST009"}
        
        # Missing role should deny access
        assert check_feature_access(payload, "exam_access") is False


class TestRequireActiveSubscription:
    """Test require_active_subscription dependency."""
    
    def test_active_subscription_allowed(self):
        """Test that active subscription is allowed."""
        payload = {
            "role": "student",
            "sub": "TEST010",
            "subscription_status": "active",
        }
        
        # Should not raise
        result = require_active_subscription(payload)
        assert result == payload
    
    def test_trial_subscription_allowed(self):
        """Test that trial subscription is allowed."""
        payload = {
            "role": "student",
            "sub": "TEST011",
            "subscription_status": "trial",
        }
        
        # Should not raise
        result = require_active_subscription(payload)
        assert result == payload
    
    def test_grace_period_subscription_allowed(self):
        """Test that grace period subscription is allowed."""
        payload = {
            "role": "student",
            "sub": "TEST012",
            "subscription_status": "grace_period",
        }
        
        # Should not raise
        result = require_active_subscription(payload)
        assert result == payload
    
    def test_expired_subscription_denied(self):
        """Test that expired subscription is denied."""
        payload = {
            "role": "student",
            "sub": "TEST013",
            "subscription_status": "expired",
        }
        
        # Should raise 403
        with pytest.raises(HTTPException) as exc_info:
            require_active_subscription(payload)
        
        assert exc_info.value.status_code == 403
        assert "subscription_required" in str(exc_info.value.detail)
    
    def test_cancelled_subscription_denied(self):
        """Test that cancelled subscription is denied."""
        payload = {
            "role": "student",
            "sub": "TEST014",
            "subscription_status": "cancelled",
        }
        
        # Should raise 403
        with pytest.raises(HTTPException) as exc_info:
            require_active_subscription(payload)
        
        assert exc_info.value.status_code == 403
        assert "subscription_required" in str(exc_info.value.detail)
    
    def test_non_student_role_denied(self):
        """Test that non-student roles are denied."""
        payload = {
            "role": "platform_admin",
            "sub": "admin@example.com",
        }
        
        # Should raise 403
        with pytest.raises(HTTPException) as exc_info:
            require_active_subscription(payload)
        
        assert exc_info.value.status_code == 403
    
    def test_missing_subscription_status_denied(self):
        """Test that missing subscription status is denied."""
        payload = {
            "role": "student",
            "sub": "TEST015",
        }
        
        # Should raise 403
        with pytest.raises(HTTPException) as exc_info:
            require_active_subscription(payload)
        
        assert exc_info.value.status_code == 403


class TestAccessControlEdgeCases:
    """Test edge cases in access control."""
    
    def test_empty_payload_denies_all(self):
        """Test that empty payload denies all access."""
        payload = {}
        
        assert check_feature_access(payload, "exam_access") is False
        assert check_feature_access(payload, "full_analytics") is False
        assert check_feature_access(payload, "question_management") is False
    
    def test_malformed_role_denies_all(self):
        """Test that malformed role denies all access."""
        payload = {"role": "invalid_role", "sub": "test"}
        
        assert check_feature_access(payload, "exam_access") is False
        assert check_feature_access(payload, "full_analytics") is False
        assert check_feature_access(payload, "question_management") is False
    
    def test_student_without_subscription_status_denied(self):
        """Test that student without subscription status is denied."""
        payload = {
            "role": "student",
            "sub": "TEST016",
            "student_subtype": "direct_subscriber",
        }
        
        # Missing subscription_status should deny access
        assert check_feature_access(payload, "exam_access") is False
        assert check_feature_access(payload, "full_analytics") is False
