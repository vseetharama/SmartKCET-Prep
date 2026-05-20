"""Unit tests for smartkcet.leaderboard.rank module.

Tests cover:
- Basic ranking (descending by composite score)
- Tie-breaking: equal scores share the same rank (REQ-11.3)
- Rank-skipping: next rank after a tie skips by the tie group size (REQ-11.3)
- Edge cases: empty list, single student, all tied
"""

import pytest

from smartkcet.leaderboard.rank import assign_ranks


class TestAssignRanks:
    """Tests for the assign_ranks function."""

    def test_basic_descending_order(self):
        """Students are ranked in descending order of composite score."""
        students = [("A", 95.0), ("B", 80.0), ("C", 90.0)]
        result = assign_ranks(students)

        assert result == [("A", 1, 95.0), ("C", 2, 90.0), ("B", 3, 80.0)]

    def test_tied_scores_share_rank(self):
        """Students with equal composite scores share the same rank."""
        students = [("A", 95.0), ("B", 90.0), ("C", 90.0), ("D", 80.0)]
        result = assign_ranks(students)

        assert result == [
            ("A", 1, 95.0),
            ("B", 2, 90.0),
            ("C", 2, 90.0),
            ("D", 4, 80.0),
        ]

    def test_rank_skipping_after_tie(self):
        """After a tie of N students at rank R, the next rank is R + N."""
        students = [
            ("A", 100.0),
            ("B", 100.0),
            ("C", 100.0),
            ("D", 50.0),
        ]
        result = assign_ranks(students)

        # Three students tied at rank 1, next rank is 4
        assert result == [
            ("A", 1, 100.0),
            ("B", 1, 100.0),
            ("C", 1, 100.0),
            ("D", 4, 50.0),
        ]

    def test_multiple_tie_groups(self):
        """Multiple groups of ties are handled correctly."""
        students = [
            ("A", 90.0),
            ("B", 90.0),
            ("C", 70.0),
            ("D", 70.0),
            ("E", 50.0),
        ]
        result = assign_ranks(students)

        assert result == [
            ("A", 1, 90.0),
            ("B", 1, 90.0),
            ("C", 3, 70.0),
            ("D", 3, 70.0),
            ("E", 5, 50.0),
        ]

    def test_empty_list(self):
        """Empty input returns empty output."""
        result = assign_ranks([])
        assert result == []

    def test_single_student(self):
        """Single student gets rank 1."""
        result = assign_ranks([("A", 75.0)])
        assert result == [("A", 1, 75.0)]

    def test_all_students_tied(self):
        """When all students have the same score, all share rank 1."""
        students = [("A", 80.0), ("B", 80.0), ("C", 80.0)]
        result = assign_ranks(students)

        assert result == [
            ("A", 1, 80.0),
            ("B", 1, 80.0),
            ("C", 1, 80.0),
        ]

    def test_no_ties(self):
        """When all scores are distinct, ranks are sequential 1..N."""
        students = [("A", 100.0), ("B", 90.0), ("C", 80.0), ("D", 70.0)]
        result = assign_ranks(students)

        assert result == [
            ("A", 1, 100.0),
            ("B", 2, 90.0),
            ("C", 3, 80.0),
            ("D", 4, 70.0),
        ]

    def test_two_students_tied_at_top(self):
        """Two students tied at rank 1, next student gets rank 3."""
        students = [("A", 95.0), ("B", 95.0), ("C", 60.0)]
        result = assign_ranks(students)

        assert result == [
            ("A", 1, 95.0),
            ("B", 1, 95.0),
            ("C", 3, 60.0),
        ]

    def test_result_contains_correct_types(self):
        """Each result tuple has (str, int, float) types."""
        students = [("KCET0001", 85.5), ("KCET0002", 72.3)]
        result = assign_ranks(students)

        for student_id, rank, score in result:
            assert isinstance(student_id, str)
            assert isinstance(rank, int)
            assert isinstance(score, float)
