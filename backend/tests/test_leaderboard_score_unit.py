"""Unit tests for smartkcet.leaderboard.score module.

Tests cover:
- compute_composite with normal cohort values
- compute_composite with cohort-empty fallbacks (REQ-11.1)
- consistency = 100 when attempt_count == 1
- is_eligible filter (REQ-10.2, REQ-11.2)
"""

import math

import pytest

from smartkcet.leaderboard.score import (
    CohortStats,
    StudentStats,
    compute_composite,
    is_eligible,
)


class TestComputeComposite:
    """Tests for the composite score algorithm."""

    def test_basic_computation(self):
        """Standard case with multiple attempts and non-zero cohort stats."""
        student = StudentStats(
            average_score=80.0,
            attempt_count=5,
            scores=[70.0, 80.0, 85.0, 90.0, 75.0],
            submission_count=5,
            overall_average_score=80.0,
        )
        cohort = CohortStats(max_attempts_in_cohort=10, max_std_dev_in_cohort=15.0)

        result = compute_composite(student, cohort)

        # avg=80, attempt_norm=(5/10)*100=50, std_dev≈7.07, consistency=100-(7.07/15)*100≈52.86
        # composite = 80*0.6 + 50*0.2 + 52.86*0.2 ≈ 48 + 10 + 10.57 ≈ 68.57
        assert result == pytest.approx(68.57, abs=0.1)

    def test_single_attempt_consistency_is_100(self):
        """When student has exactly 1 attempt, consistency must be 100."""
        student = StudentStats(
            average_score=75.0,
            attempt_count=1,
            scores=[75.0],
            submission_count=1,
            overall_average_score=75.0,
        )
        cohort = CohortStats(max_attempts_in_cohort=10, max_std_dev_in_cohort=20.0)

        result = compute_composite(student, cohort)

        # avg=75, attempt_norm=(1/10)*100=10, consistency=100
        # composite = 75*0.6 + 10*0.2 + 100*0.2 = 45 + 2 + 20 = 67
        assert result == pytest.approx(67.0, abs=0.01)

    def test_cohort_max_attempts_zero_fallback(self):
        """When max_attempts_in_cohort == 0, divisor falls back to 1."""
        student = StudentStats(
            average_score=90.0,
            attempt_count=3,
            scores=[85.0, 90.0, 95.0],
            submission_count=3,
            overall_average_score=90.0,
        )
        cohort = CohortStats(max_attempts_in_cohort=0, max_std_dev_in_cohort=10.0)

        result = compute_composite(student, cohort)

        # att_div=1 (fallback), attempt_norm=(3/1)*100=300
        # std_dev of [85,90,95] ≈ 4.08, consistency=100-(4.08/10)*100=59.18
        # composite = 90*0.6 + 300*0.2 + 59.18*0.2 = 54 + 60 + 11.84 = 125.84
        assert result == pytest.approx(125.84, abs=0.1)

    def test_cohort_max_std_dev_zero_fallback(self):
        """When max_std_dev_in_cohort == 0, divisor falls back to 1."""
        student = StudentStats(
            average_score=60.0,
            attempt_count=2,
            scores=[55.0, 65.0],
            submission_count=2,
            overall_average_score=60.0,
        )
        cohort = CohortStats(max_attempts_in_cohort=5, max_std_dev_in_cohort=0.0)

        result = compute_composite(student, cohort)

        # std_dev of [55,65] = 5.0, std_div=1 (fallback)
        # consistency = 100 - (5.0/1)*100 = 100 - 500 = -400
        # attempt_norm = (2/5)*100 = 40
        # composite = 60*0.6 + 40*0.2 + (-400)*0.2 = 36 + 8 + (-80) = -36
        assert result == pytest.approx(-36.0, abs=0.1)

    def test_both_cohort_values_zero_fallback(self):
        """When both cohort values are 0, both divisors fall back to 1."""
        student = StudentStats(
            average_score=90.0,
            attempt_count=1,
            scores=[90.0],
            submission_count=1,
            overall_average_score=90.0,
        )
        cohort = CohortStats(max_attempts_in_cohort=0, max_std_dev_in_cohort=0.0)

        result = compute_composite(student, cohort)

        # Single attempt → consistency=100
        # att_div=1 (fallback), attempt_norm=(1/1)*100=100
        # composite = 90*0.6 + 100*0.2 + 100*0.2 = 54 + 20 + 20 = 94
        assert result == pytest.approx(94.0, abs=0.01)

    def test_perfect_score_max_attempts(self):
        """Student with perfect scores and max attempts in cohort."""
        student = StudentStats(
            average_score=100.0,
            attempt_count=10,
            scores=[100.0] * 10,
            submission_count=10,
            overall_average_score=100.0,
        )
        cohort = CohortStats(max_attempts_in_cohort=10, max_std_dev_in_cohort=20.0)

        result = compute_composite(student, cohort)

        # avg=100, attempt_norm=(10/10)*100=100, std_dev=0 → consistency=100
        # composite = 100*0.6 + 100*0.2 + 100*0.2 = 60 + 20 + 20 = 100
        assert result == pytest.approx(100.0, abs=0.01)

    def test_zero_average_score(self):
        """Student with 0 average score."""
        student = StudentStats(
            average_score=0.0,
            attempt_count=3,
            scores=[0.0, 0.0, 0.0],
            submission_count=3,
            overall_average_score=0.0,
        )
        cohort = CohortStats(max_attempts_in_cohort=10, max_std_dev_in_cohort=15.0)

        result = compute_composite(student, cohort)

        # avg=0, attempt_norm=(3/10)*100=30, std_dev=0 → consistency=100
        # composite = 0*0.6 + 30*0.2 + 100*0.2 = 0 + 6 + 20 = 26
        assert result == pytest.approx(26.0, abs=0.01)


class TestIsEligible:
    """Tests for the eligibility filter."""

    def test_eligible_student(self):
        """Student with submissions >= 1 and average >= 30 is eligible."""
        student = StudentStats(
            average_score=50.0,
            attempt_count=3,
            scores=[50.0, 50.0, 50.0],
            submission_count=3,
            overall_average_score=50.0,
        )
        assert is_eligible(student) is True

    def test_ineligible_zero_submissions(self):
        """Student with 0 submissions is ineligible."""
        student = StudentStats(
            average_score=80.0,
            attempt_count=0,
            scores=[],
            submission_count=0,
            overall_average_score=80.0,
        )
        assert is_eligible(student) is False

    def test_ineligible_low_average(self):
        """Student with average < 30 is ineligible regardless of attempts."""
        student = StudentStats(
            average_score=25.0,
            attempt_count=10,
            scores=[25.0] * 10,
            submission_count=10,
            overall_average_score=25.0,
        )
        assert is_eligible(student) is False

    def test_eligible_at_boundary_30(self):
        """Student with exactly 30 average and 1 submission is eligible."""
        student = StudentStats(
            average_score=30.0,
            attempt_count=1,
            scores=[30.0],
            submission_count=1,
            overall_average_score=30.0,
        )
        assert is_eligible(student) is True

    def test_ineligible_just_below_30(self):
        """Student with average just below 30 is ineligible."""
        student = StudentStats(
            average_score=29.99,
            attempt_count=5,
            scores=[29.99] * 5,
            submission_count=5,
            overall_average_score=29.99,
        )
        assert is_eligible(student) is False

    def test_ineligible_both_conditions_fail(self):
        """Student with 0 submissions and low average is ineligible."""
        student = StudentStats(
            average_score=10.0,
            attempt_count=0,
            scores=[],
            submission_count=0,
            overall_average_score=10.0,
        )
        assert is_eligible(student) is False
