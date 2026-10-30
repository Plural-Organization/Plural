from datetime import UTC, datetime, timedelta

from plural.security.replay import ReplayGuard

START = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def test_a_key_is_fresh_once_and_forgotten_after_the_window() -> None:
    guard = ReplayGuard(timedelta(minutes=2))
    assert guard.fresh("a", START)
    assert not guard.fresh("a", START + timedelta(minutes=1))
    assert guard.fresh("b", START + timedelta(minutes=1))
    assert guard.fresh("a", START + timedelta(minutes=3))
