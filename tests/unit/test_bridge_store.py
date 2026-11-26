from pathlib import Path

from plural.bridge.model import Person, Place
from plural.bridge.store import PAIRING_MAX_FAILURES, PAIRING_TTL_S, BridgeStore

ME = Person("1", "Tamirlan")


def test_only_the_printed_code_pairs_and_only_once(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path, "telegram")
    code = store.pairing_code()

    assert not store.pair(ME, "000000" if code != "000000" else "111111")
    assert store.pair(ME, code)
    assert not store.pair(Person("2", "Other"), code)
    assert BridgeStore(tmp_path, "telegram").is_owner(ME)


def test_pairing_code_expires_after_ten_minutes(tmp_path: Path) -> None:
    now = [1_000.0]
    store = BridgeStore(tmp_path, "telegram", clock=lambda: now[0])
    expired = store.pairing_code()

    now[0] += PAIRING_TTL_S

    assert not store.pair(ME, expired)
    assert store.pairing_code() != expired


def test_too_many_wrong_attempts_rotate_the_pairing_code(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path, "telegram")
    original = store.pairing_code()
    wrong = "000000" if original != "000000" else "111111"

    for _ in range(PAIRING_MAX_FAILURES):
        assert not store.pair(ME, wrong)

    assert store.pairing_code() != original
    assert not store.pair(ME, original)


def test_many_chats_can_follow_one_room_and_each_follows_one(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path, "telegram")
    group, topic = Place("telegram", "-100"), Place("telegram", "-100", "42")
    store.link(group, "r_a")
    store.link(topic, "r_a")
    store.link(group, "r_b")

    again = BridgeStore(tmp_path, "telegram")
    assert again.room_of(group) == "r_b"
    assert again.places_of("r_a") == [topic]
    assert again.rooms == {"r_a", "r_b"}
    assert (tmp_path / "bridge" / "telegram.json").stat().st_mode & 0o777 == 0o600
