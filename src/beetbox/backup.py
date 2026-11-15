"""Copies of the beets library database and beetbox's own state.

beetbox makes bulk changes to library.db (romanizing, primary artists, upgrades, console
commands). Undo covers single edits; these copies cover the rest. One is taken at start
when the newest is older than the interval, then once per interval, and only the newest
``keep`` are kept. SQLite's backup API copies a consistent snapshot while beets writes.

Each copy is a folder ``backups/YYYY-MM-DD_HHMMSS`` holding ``library.db`` and
``state.db``. To restore one, stop the container and copy the files back.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

STAMP = "%Y-%m-%d_%H%M%S"
PARTIAL = ".partial-"


def copy_db(src: Path, dest: Path) -> None:
    """Copy one SQLite database to ``dest`` without stopping its writers."""
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source:
        target = sqlite3.connect(dest)
        try:
            source.backup(target)
        finally:
            target.close()


class Backups:
    def __init__(self, folder: Path, databases: dict[str, Path], hours: int, keep: int):
        self.folder = folder
        self.databases = databases  # file name in a copy -> database to copy
        self.interval = timedelta(hours=hours)
        self.keep = max(1, keep)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return self.interval > timedelta(0)

    def copies(self) -> list[tuple[datetime, Path]]:
        """Finished copies, oldest first."""
        found = []
        if self.folder.is_dir():
            for p in self.folder.iterdir():
                try:
                    found.append((datetime.strptime(p.name, STAMP), p))
                except ValueError:
                    continue  # a partial copy, or something the owner put there
        return sorted(found)

    def due(self, now: datetime) -> datetime:
        copies = self.copies()
        return copies[-1][0] + self.interval if copies else now

    def run_once(self, now: datetime | None = None) -> Path | None:
        now = now or datetime.now()
        final = self.folder / now.strftime(STAMP)
        if final.exists():
            return None
        partial = self.folder / (PARTIAL + final.name)
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        try:
            for name, src in self.databases.items():
                if src.exists():
                    copy_db(src, partial / name)
            partial.rename(final)
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise
        self.prune()
        log.info("backed up %s to %s", ", ".join(self.databases), final)
        return final

    def prune(self) -> None:
        copies = self.copies()
        for _, path in copies[: max(0, len(copies) - self.keep)]:
            shutil.rmtree(path, ignore_errors=True)
        if self.folder.is_dir():  # leftovers from a copy cut short by a restart
            for p in self.folder.glob(PARTIAL + "*"):
                shutil.rmtree(p, ignore_errors=True)

    def start(self) -> None:
        if self.enabled and not self._thread:
            self._thread = threading.Thread(target=self._run, name="beetbox-backup", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            wait = (self.due(datetime.now()) - datetime.now()).total_seconds()
            if wait > 0:
                self._stop.wait(min(wait, 3600))  # wake hourly, in case the clock jumps
                continue
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - try again next interval
                log.exception("backup failed")
                self._stop.wait(self.interval.total_seconds())


def library_path(lib) -> Path:
    return Path(os.fsdecode(lib.path))
