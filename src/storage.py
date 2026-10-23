"""SQLite persistence for Bulters, explicit memories and auditable missions.

Inputs: Validated objects. Outputs: JSON-compatible records.
Assumptions: One local application process; files are private to the current user.
Author: Carter Tan.
"""

import json
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path


class Store:
    """Small document store with parameterized SQL and atomic record updates."""

    def __init__(self, path: Path) -> None:
        """Initialize private storage without opening unrelated files."""
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))")
        path.chmod(0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived connection; callers close via context manager."""
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def all(self, kind: str) -> list[dict]:
        """Return all records of the requested kind in insertion order."""
        with self.connect() as db:
            rows = db.execute("SELECT body FROM records WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get(self, kind: str, record_id: str) -> dict | None:
        """Return an identified record, or None when absent."""
        with self.connect() as db:
            row = db.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, kind: str, record: dict) -> dict:
        """Insert or replace one record atomically."""
        with self.connect() as db:
            db.execute("INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
                       (kind, record["id"], json.dumps(record)))
        return record
