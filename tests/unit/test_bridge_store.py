from pathlib import Path

from plural.bridge.model import Person, Place
from plural.bridge.store import BridgeStore

ME = Person("1", "Tamirlan")


def test_only_the_printed_code_pairs_and_only_once(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path, "telegram")
    code = store.pairing_code()

    assert not store.pair(ME, "000000" if code != "000000" else "111111")
    assert store.pair(ME, code)
    assert not store.pair(Person("2", "Other"), code)
    assert BridgeStore(tmp_path, "telegram").is_owner(ME)


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
