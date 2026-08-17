from __future__ import annotations

from pathlib import Path

from podcast_fetcher.state import read_json, write_json_atomic


def test_read_json_returns_default_when_file_missing(tmp_path: Path) -> None:
    result = read_json(tmp_path / "nope.json", default={"processed": {}})
    assert result == {"processed": {}}


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "state" / "processed.json"
    data = {"processed": {"guid-1": {"feed": "Odd Lots", "title": "Ep 1"}}}
    write_json_atomic(path, data)
    assert read_json(path, default=None) == data


def test_write_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "state.json"
    write_json_atomic(path, {"a": 1})
    assert path.exists()


def test_write_leaves_no_temp_files_behind(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    write_json_atomic(path, {"a": 1})
    leftovers = [p for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == []


def test_second_write_overwrites_first(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    write_json_atomic(path, {"version": 1})
    write_json_atomic(path, {"version": 2})
    assert read_json(path, default=None) == {"version": 2}
