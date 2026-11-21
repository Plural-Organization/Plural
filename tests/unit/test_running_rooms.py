import os
from pathlib import Path

from plural.storage.running import announce, running_dir, running_rooms, withdraw


def test_a_room_is_listed_while_its_host_lives_and_gone_after(tmp_path: Path) -> None:
    path = announce(tmp_path, room="r_a", host_link="ws://h/r_a?token=t", workspace=Path("/w"))

    assert [entry.room for entry in running_rooms(tmp_path)] == ["r_a"]
    assert path.stat().st_mode & 0o777 == 0o600
    withdraw(path)
    assert running_rooms(tmp_path) == []


def test_a_file_left_by_a_dead_host_is_cleaned_up(tmp_path: Path) -> None:
    path = announce(tmp_path, room="r_b", host_link="ws://h/r_b", workspace=Path("/w"))
    path.write_text(path.read_text().replace(f'"pid":{os.getpid()}', '"pid":999999'))

    assert running_rooms(tmp_path) == []
    assert list(running_dir(tmp_path).iterdir()) == []
