from pathlib import Path

from plural.bridge.model import Person, Place
from plural.bridge.store import PAIRING_CHARS, PAIRING_TTL_S, BridgeStore

ME = Person("1", "Tamirlan")


def test_only_the_printed_code_pairs_and_only_once(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path, "telegram")
    code = store.pairing_code()

    assert len(code) == PAIRING_CHARS
    assert not store.pair(ME, "wrong")
    assert not store.pair(ME, "код")
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


def test_wrong_tries_neither_replace_the_code_nor_lock_the_owner_out(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path, "telegram")
    code = store.pairing_code()

    for _ in range(100):
        assert not store.pair(Person("2", "Stranger"), "wrong")

    assert store.pairing_code() == code
    assert store.pair(ME, f" {code.lower()} ")


def test_a_try_never_makes_a_code(tmp_path: Path) -> None:
    now = [1_000.0]
    store = BridgeStore(tmp_path, "telegram", clock=lambda: now[0])
    assert store.pair(ME, store.pairing_code())

    assert not store.pair(Person("2", "Stranger"), "wrong")
    assert store.active_pairing() is None

    store.pairing_code()
    now[0] += PAIRING_TTL_S
    assert not store.pair(Person("2", "Stranger"), "wrong")
    assert store.active_pairing() is None


def test_a_removed_owner_loses_the_session_their_private_chat_followed(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path, "telegram")
    other = Person("2", "Askar")
    home, topic = Place("telegram", "1", None, True), Place("telegram", "1", "7", True)
    others, group = Place("telegram", "2", None, True), Place("telegram", "-100")
    for person, place in ((ME, home), (other, others)):
        assert store.pair(person, store.pairing_code(renew=True))
        store.remember_home(person, place)
    for place in (home, topic, others, group):
        store.link(place, "r_a")

    store.unpair(ME.id)

    assert store.places_of("r_a") == [others, group]


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
