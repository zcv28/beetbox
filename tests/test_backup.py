from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from beetbox import backup
from beetbox.backup import Backups


def _db(path, value):
    with sqlite3.connect(path) as c:
        c.execute("create table t (v text)")
        c.execute("insert into t values (?)", (value,))
    return path


def _read(path):
    with sqlite3.connect(path) as c:
        return [r[0] for r in c.execute("select v from t")]


@pytest.fixture
def backups(tmp_path):
    dbs = {"library.db": _db(tmp_path / "lib.db", "lib"), "state.db": _db(tmp_path / "st.db", "st")}
    return Backups(tmp_path / "backups", dbs, hours=24, keep=3)


T0 = datetime(2026, 11, 15, 3, 0, 0)


def test_copies_both_databases(backups):
    folder = backups.run_once(T0)
    assert folder.name == "2026-11-15_030000"
    assert _read(folder / "library.db") == ["lib"]
    assert _read(folder / "state.db") == ["st"]


def test_copy_is_consistent_while_open_for_writing(backups, tmp_path):
    writer = sqlite3.connect(tmp_path / "lib.db")
    writer.execute("insert into t values ('more')")
    writer.commit()
    writer.execute("insert into t values ('uncommitted')")  # left open
    folder = backups.run_once(T0)
    writer.rollback()
    writer.close()
    assert _read(folder / "library.db") == ["lib", "more"]


def test_keeps_only_the_newest(backups):
    for d in range(5):
        backups.run_once(T0 + timedelta(days=d))
    assert [p.name[:10] for _, p in backups.copies()] == [
        "2026-11-17",
        "2026-11-18",
        "2026-11-19",
    ]


def test_due_after_the_newest_copy(backups):
    assert backups.due(T0) == T0  # none yet: now
    backups.run_once(T0)
    assert backups.due(T0) == T0 + timedelta(hours=24)


def test_failed_copy_leaves_nothing_behind(backups, monkeypatch):
    def boom(src, dest):
        raise OSError("disk full")

    monkeypatch.setattr(backup, "copy_db", boom)
    with pytest.raises(OSError):
        backups.run_once(T0)
    assert list(backups.folder.iterdir()) == []
    assert backups.due(T0) == T0


def test_off_when_hours_is_zero(tmp_path):
    b = Backups(tmp_path / "backups", {}, hours=0, keep=7)
    b.start()
    assert not b.enabled and b._thread is None
