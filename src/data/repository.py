from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

UTC = timezone.utc
WORD_PATTERN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass
class ReviewWord:
    id: int
    word: str
    interval_days: int
    ease_factor: float
    due_at: datetime


class WordbookRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL UNIQUE,
                contexts TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                review_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                interval_days INTEGER NOT NULL DEFAULT 1,
                ease_factor REAL NOT NULL DEFAULT 2.5,
                due_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                result INTEGER NOT NULL,
                reviewed_at TEXT NOT NULL,
                FOREIGN KEY(word_id) REFERENCES words(id)
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert_words_from_text(self, text: str, context: str | None = None) -> int:
        words = self._extract_words(text)
        if not words:
            return 0

        now = utc_now()
        inserted = 0
        for word in words:
            row = self.conn.execute(
                "SELECT id, contexts FROM words WHERE word = ?",
                (word,),
            ).fetchone()

            if row is None:
                due = to_iso(now)
                self.conn.execute(
                    """
                    INSERT INTO words(word, contexts, first_seen_at, last_seen_at, due_at)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (word, context or "", to_iso(now), to_iso(now), due),
                )
                inserted += 1
                continue

            contexts = row["contexts"] or ""
            merged = self._merge_context(contexts, context)
            self.conn.execute(
                """
                UPDATE words
                SET last_seen_at = ?, contexts = ?
                WHERE id = ?
                """,
                (to_iso(now), merged, row["id"]),
            )

        self.conn.commit()
        return inserted

    def get_due_word(self) -> ReviewWord | None:
        now_str = to_iso(utc_now())
        row = self.conn.execute(
            """
            SELECT id, word, interval_days, ease_factor, due_at
            FROM words
            WHERE due_at <= ?
            ORDER BY due_at ASC, review_count ASC
            LIMIT 1
            """,
            (now_str,),
        ).fetchone()
        if row is None:
            return None

        return ReviewWord(
            id=row["id"],
            word=row["word"],
            interval_days=row["interval_days"],
            ease_factor=row["ease_factor"],
            due_at=from_iso(row["due_at"]),
        )

    def record_review(self, word_id: int, remembered: bool) -> None:
        now = utc_now()
        row = self.conn.execute(
            """
            SELECT review_count, success_count, interval_days, ease_factor
            FROM words WHERE id = ?
            """,
            (word_id,),
        ).fetchone()
        if row is None:
            return

        review_count = int(row["review_count"])
        success_count = int(row["success_count"])
        interval_days = int(row["interval_days"])
        ease_factor = float(row["ease_factor"])

        if remembered:
            review_count += 1
            success_count += 1
            interval_days = max(1, round(interval_days * ease_factor))
            ease_factor = min(3.0, ease_factor + 0.08)
        else:
            review_count += 1
            interval_days = 1
            ease_factor = max(1.3, ease_factor - 0.2)

        next_due = now + timedelta(days=interval_days)

        self.conn.execute(
            """
            UPDATE words
            SET review_count = ?,
                success_count = ?,
                interval_days = ?,
                ease_factor = ?,
                due_at = ?
            WHERE id = ?
            """,
            (
                review_count,
                success_count,
                interval_days,
                ease_factor,
                to_iso(next_due),
                word_id,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO reviews(word_id, result, reviewed_at)
            VALUES(?, ?, ?)
            """,
            (word_id, 1 if remembered else 0, to_iso(now)),
        )
        self.conn.commit()

    def get_word_context(self, word_id: int) -> str:
        row = self.conn.execute(
            "SELECT contexts FROM words WHERE id = ?",
            (word_id,),
        ).fetchone()
        if row is None:
            return ""
        return str(row["contexts"] or "")

    def stats(self) -> dict[str, int]:
        total = self.conn.execute("SELECT COUNT(1) AS c FROM words").fetchone()["c"]
        due = self.conn.execute(
            "SELECT COUNT(1) AS c FROM words WHERE due_at <= ?",
            (to_iso(utc_now()),),
        ).fetchone()["c"]
        return {"total": int(total), "due": int(due)}

    @staticmethod
    def _extract_words(text: str) -> list[str]:
        lowered = (match.group(0).lower() for match in WORD_PATTERN.finditer(text))
        unique = list(dict.fromkeys(lowered))
        return unique

    @staticmethod
    def _merge_context(existing: str, new_context: str | None) -> str:
        if not new_context:
            return existing
        if not existing:
            return new_context[:300]
        items: list[str] = [part for part in existing.split(" || ") if part]
        if new_context not in items:
            items.append(new_context[:300])
        return " || ".join(items[-3:])
