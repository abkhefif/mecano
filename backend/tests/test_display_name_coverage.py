"""Coverage tests for display_name.py — targeting uncovered lines 7, 9."""
from unittest.mock import MagicMock

from app.utils.display_name import get_display_name


def test_display_name_first_name_only():
    """Falls back to first_name alone when last_name is missing."""
    user = MagicMock()
    user.first_name = "Alice"
    user.last_name = ""
    user.email = "alice@test.com"
    assert get_display_name(user) == "Alice"


def test_display_name_email_fallback():
    """Falls back to email prefix when no first/last name."""
    user = MagicMock()
    user.first_name = ""
    user.last_name = ""
    user.email = "john.doe@example.com"
    assert get_display_name(user) == "john.doe"


def test_display_name_full_name():
    """Returns full name when both first and last are set."""
    user = MagicMock()
    user.first_name = "Jean"
    user.last_name = "Dupont"
    user.email = "jean@test.com"
    assert get_display_name(user) == "Jean Dupont"
