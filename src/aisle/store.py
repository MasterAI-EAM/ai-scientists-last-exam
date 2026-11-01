"""SQLite is the authoritative ledger, outside ephemeral agent sandboxes."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from time import time

from aisle.contracts import canonical


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, doc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, key TEXT NOT NULL,
                    doc TEXT NOT NULL, UNIQUE(run_id,key));
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    ts REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS selections (id TEXT PRIMARY KEY, doc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, doc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS samples (
                    lab_id TEXT NOT NULL, sample_id TEXT NOT NULL, order_id TEXT NOT NULL,
                    UNIQUE(lab_id,sample_id));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "ledger.sqlite", timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def get(db, table, ident):
        if table not in {"runs", "orders", "selections", "campaigns"}:
            raise ValueError("unknown ledger table")
        row = db.execute(f"SELECT doc FROM {table} WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise KeyError(ident)
        return json.loads(row["doc"])

    @staticmethod
    def put(db, table, doc):
        if table not in {"runs", "orders", "selections", "campaigns"}:
            raise ValueError("unknown ledger table")
        if table == "orders":
            db.execute(
                "INSERT INTO orders VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET doc=excluded.doc",
                (doc["id"], doc["run_id"], doc["key"], canonical(doc)),
            )
        else:
            db.execute(
                f"INSERT INTO {table} VALUES(?,?) ON CONFLICT(id) DO UPDATE SET doc=excluded.doc",
                (doc["id"], canonical(doc)),
            )

    @staticmethod
    def event(db, run_id, kind, payload):
        db.execute(
            "INSERT INTO events(run_id,ts,kind,payload) VALUES(?,?,?,?)",
            (run_id, time(), kind, canonical(payload)),
        )

    def read(self, table, ident):
        with self.connect() as db:
            return self.get(db, table, ident)

    def list(self, table):
        if table not in {"runs", "orders", "selections", "campaigns"}:
            raise ValueError("unknown ledger table")
        with self.connect() as db:
            return [json.loads(r["doc"]) for r in db.execute(f"SELECT doc FROM {table}")]

    def evidence(self, data: bytes) -> dict:
        import hashlib

        checksum = hashlib.sha256(data).hexdigest()
        path = self.root / "evidence" / checksum
        path.parent.mkdir(exist_ok=True)
        if not path.exists():
            with path.open("xb") as output:
                output.write(data)
        return {"sha256": checksum, "bytes": len(data), "path": f"evidence/{checksum}"}
