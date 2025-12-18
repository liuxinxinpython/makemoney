from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Tuple

DEFAULT_WATCHLIST_DB = Path(__file__).resolve().parent / "watchlists.db"


class WatchlistStore:
    def __init__(self, db_path: Path = DEFAULT_WATCHLIST_DB) -> None:
        self.db_path = Path(db_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist_symbols (
                    watchlist_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    name TEXT,
                    added_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (watchlist_id, symbol),
                    FOREIGN KEY (watchlist_id) REFERENCES watchlists(id) ON DELETE CASCADE
                );
                """
            )

    def list_watchlists(self) -> List[Tuple[int, str]]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT id, name FROM watchlists ORDER BY id ASC;")
            return cur.fetchall()

    def create_watchlist(self, name: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("INSERT OR IGNORE INTO watchlists(name) VALUES (?);", (name.strip(),))
            conn.commit()
            if cur.lastrowid:
                return int(cur.lastrowid)
            cur = conn.execute("SELECT id FROM watchlists WHERE name=?;", (name.strip(),))
            row = cur.fetchone()
            return int(row[0]) if row else -1

    def delete_watchlist(self, watchlist_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM watchlists WHERE id=?;", (watchlist_id,))
            conn.execute("DELETE FROM watchlist_symbols WHERE watchlist_id=?;", (watchlist_id,))
            conn.commit()

    def rename_watchlist(self, watchlist_id: int, new_name: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE watchlists SET name=? WHERE id=?;", (new_name.strip(), watchlist_id))
            conn.commit()

    def list_symbols(self, watchlist_id: int) -> List[Tuple[str, str]]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT symbol, IFNULL(name,'') FROM watchlist_symbols WHERE watchlist_id=? ORDER BY added_at DESC;",
                (watchlist_id,),
            )
            return cur.fetchall()

    def add_symbols(self, watchlist_id: int, items: List[Tuple[str, str]]) -> None:
        if not items:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO watchlist_symbols(watchlist_id, symbol, name) VALUES (?, ?, ?);",
                [(watchlist_id, sym, name) for sym, name in items],
            )
            conn.commit()

    def remove_symbol(self, watchlist_id: int, symbol: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM watchlist_symbols WHERE watchlist_id=? AND symbol=?;", (watchlist_id, symbol))
            conn.commit()


__all__ = ["WatchlistStore", "DEFAULT_WATCHLIST_DB"]
