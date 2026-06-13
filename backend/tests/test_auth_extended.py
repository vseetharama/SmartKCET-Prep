"""Tests for extended auth service with three-role system."""

import pytest
from smartkcet.auth.tokens import issue_token, decode_token, Role


class TestExtendedTokenGeneration:
    """Test extended JWT token generation with new claims."""

    def test_student_token_with_extended_claims(self):
        """Test that student tokens include extended claims."""
        token, jti, iat, exp = issue_token(
            sub="KCET0001",
            role="student",
            student_subtype="direct_subscriber",
            subscription_status="trial",
        )

        payload = decode_token(token)
        assert payload["sub"] == "KCET0001"
        assert payload["role"] == "student"
        assert payload["student_subtype"] == "direct_subscriber"
        assert payload["subscription_status"] == "trial"
        assert payload["jti"] == jti
        assert payload["iat"] == iat
        assert payload["exp"] == exp

    def test_student_token_with_institution_id(self):
        """Test that institution-linked student tokens include institution_id."""
        token, jti, iat, exp = issue_token(
            sub="KCET0002",
            role="student",
            student_subtype="institution_linked",
            institution_id="123e4567-e89b-12d3-a456-426614174000",
            subscription_status="active",
        )

        payload = decode_token(token)
        assert payload["sub"] == "KCET0002"
        assert payload["role"] == "student"
        assert payload["student_subtype"] == "institution_linked"
        assert payload["institution_id"] == "123e4567-e89b-12d3-a456-426614174000"
        assert payload["subscription_status"] == "active"

    def test_dual_student_token(self):
        """Test that dual student tokens include institution_id."""
        token, jti, iat, exp = issue_token(
            sub="KCET0003",
            role="student",
            student_subtype="dual",
            institution_id="123e4567-e89b-12d3-a456-426614174000",
            subscription_status="active",
        )

        payload = decode_token(token)
        assert payload["sub"] == "KCET0003"
        assert payload["role"] == "student"
        assert payload["student_subtype"] == "dual"
        assert payload["institution_id"] == "123e4567-e89b-12d3-a456-426614174000"

    def test_platform_admin_token(self):
        """Test that platform_admin tokens work correctly."""
        token, jti, iat, exp = issue_token(
            sub="admin@platform.com",
            role="platform_admin",
        )

        payload = decode_token(token)
        assert payload["sub"] == "admin@platform.com"
        assert payload["role"] == "platform_admin"
        assert "student_subtype" not in payload
        assert "institution_id" not in payload

    def test_institution_admin_token(self):
        """Test that institution_admin tokens include institution_id."""
        token, jti, iat, exp = issue_token(
            sub="admin@institution.com",
            role="institution_admin",
            institution_id="123e4567-e89b-12d3-a456-426614174000",
        )

        payload = decode_token(token)
        assert payload["sub"] == "admin@institution.com"
        assert payload["role"] == "institution_admin"
        assert payload["institution_id"] == "123e4567-e89b-12d3-a456-426614174000"
        assert "student_subtype" not in payload

    def test_role_type_validation(self):
        """Test that Role type accepts all three roles."""
        # This is a compile-time check, but we can verify at runtime
        roles: list[Role] = ["platform_admin", "institution_admin", "student"]
        for role in roles:
            token, _, _, _ = issue_token(sub="test@test.com", role=role)
            payload = decode_token(token)
            assert payload["role"] == role
