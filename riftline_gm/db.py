from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from riftline_gm.models import Campaign, CharacterDraft, ImageRequest, Player


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaigns (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    game_profile TEXT NOT NULL DEFAULT 'cyberpunk_2077',
                    language TEXT NOT NULL,
                    content_preset TEXT NOT NULL,
                    text_model TEXT,
                    image_model TEXT,
                    summary TEXT NOT NULL DEFAULT '',
                    spotlight_user_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS players (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    display_name TEXT NOT NULL,
                    experience_mode TEXT NOT NULL DEFAULT 'newbie',
                    active INTEGER NOT NULL DEFAULT 1,
                    handle TEXT,
                    role TEXT,
                    style TEXT,
                    stats_json TEXT,
                    skills_json TEXT,
                    gear TEXT,
                    hp INTEGER,
                    humanity INTEGER,
                    cyberware TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_chat_id_id ON messages(chat_id, id);

                CREATE TABLE IF NOT EXISTS image_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    original_prompt TEXT NOT NULL,
                    drafted_prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    image_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_image_requests_chat_created
                ON image_requests(chat_id, created_at);

                CREATE TABLE IF NOT EXISTS cost_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_cost REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS character_drafts (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    game_profile TEXT NOT NULL,
                    current_field TEXT,
                    topic_thread_id INTEGER,
                    topic_name TEXT,
                    data_json TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                );
                """
            )
            self._ensure_column("campaigns", "game_profile", "TEXT NOT NULL DEFAULT 'cyberpunk_2077'")
            self._ensure_column("campaigns", "text_model", "TEXT")
            self._ensure_column("campaigns", "image_model", "TEXT")
            self._ensure_column("character_drafts", "topic_thread_id", "INTEGER")
            self._ensure_column("character_drafts", "topic_name", "TEXT")

    def _ensure_column(self, table: str, column: str, column_type: str) -> None:
        columns = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def get_or_create_campaign(
        self,
        chat_id: int,
        *,
        title: str,
        default_game_profile: str,
        default_language: str,
        content_preset: str,
    ) -> Campaign:
        now = utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO campaigns
                (chat_id, title, active, game_profile, language, content_preset, summary, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?, ?, '', ?, ?)
                """,
                (chat_id, title, default_game_profile, default_language, content_preset, now, now),
            )
            self._conn.execute(
                "UPDATE campaigns SET title = ?, updated_at = ? WHERE chat_id = ?",
                (title, now, chat_id),
            )
        return self.get_campaign(chat_id)

    def get_campaign(self, chat_id: int) -> Campaign:
        row = self._one("SELECT * FROM campaigns WHERE chat_id = ?", (chat_id,))
        if row is None:
            raise KeyError(f"No campaign for chat {chat_id}")
        return _campaign(row)

    def update_campaign(self, chat_id: int, **fields: Any) -> Campaign:
        allowed = {
            "active",
            "game_profile",
            "language",
            "content_preset",
            "text_model",
            "image_model",
            "summary",
            "spotlight_user_id",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get_campaign(chat_id)
        updates["updated_at"] = utc_now()
        columns = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [chat_id]
        with self._lock, self._conn:
            self._conn.execute(f"UPDATE campaigns SET {columns} WHERE chat_id = ?", values)
        return self.get_campaign(chat_id)

    def upsert_player(
        self,
        *,
        chat_id: int,
        user_id: int,
        username: str | None,
        display_name: str,
    ) -> Player:
        now = utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO players
                (chat_id, user_id, username, display_name, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = excluded.display_name,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (chat_id, user_id, username, display_name, now, now),
            )
        return self.get_player(chat_id, user_id)

    def deactivate_player(self, chat_id: int, user_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE players SET active = 0, updated_at = ? WHERE chat_id = ? AND user_id = ?",
                (utc_now(), chat_id, user_id),
            )

    def get_player(self, chat_id: int, user_id: int) -> Player:
        row = self._one("SELECT * FROM players WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        if row is None:
            raise KeyError(f"No player {user_id} in chat {chat_id}")
        return _player(row)

    def maybe_player(self, chat_id: int, user_id: int) -> Player | None:
        row = self._one("SELECT * FROM players WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return _player(row) if row else None

    def list_active_players(self, chat_id: int) -> list[Player]:
        rows = self._all(
            "SELECT * FROM players WHERE chat_id = ? AND active = 1 ORDER BY display_name COLLATE NOCASE",
            (chat_id,),
        )
        return [_player(row) for row in rows]

    def count_active_players(self, chat_id: int) -> int:
        row = self._one("SELECT COUNT(*) AS count FROM players WHERE chat_id = ? AND active = 1", (chat_id,))
        return int(row["count"] if row else 0)

    def update_player_experience(self, chat_id: int, user_id: int, experience_mode: str) -> Player:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE players
                SET experience_mode = ?, updated_at = ?
                WHERE chat_id = ? AND user_id = ?
                """,
                (experience_mode, utc_now(), chat_id, user_id),
            )
        return self.get_player(chat_id, user_id)

    def update_player_sheet(self, chat_id: int, user_id: int, **fields: Any) -> Player:
        allowed = {"handle", "role", "style", "stats_json", "skills_json", "gear", "hp", "humanity", "cyberware", "notes"}
        updates = {key: _json_field(value) if key.endswith("_json") else value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get_player(chat_id, user_id)
        updates["updated_at"] = utc_now()
        columns = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [chat_id, user_id]
        with self._lock, self._conn:
            self._conn.execute(f"UPDATE players SET {columns} WHERE chat_id = ? AND user_id = ?", values)
        return self.get_player(chat_id, user_id)

    def upsert_character_draft(
        self,
        *,
        chat_id: int,
        user_id: int,
        game_profile: str,
        current_field: str | None,
        topic_thread_id: int | None = None,
        topic_name: str | None = None,
        data: dict[str, Any] | None = None,
        active: bool = True,
    ) -> CharacterDraft:
        now = utc_now()
        data_json = json.dumps(data or {}, ensure_ascii=False, sort_keys=True)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO character_drafts
                (chat_id, user_id, game_profile, current_field, topic_thread_id, topic_name, data_json, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    game_profile = excluded.game_profile,
                    current_field = excluded.current_field,
                    topic_thread_id = COALESCE(excluded.topic_thread_id, character_drafts.topic_thread_id),
                    topic_name = COALESCE(excluded.topic_name, character_drafts.topic_name),
                    data_json = excluded.data_json,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (chat_id, user_id, game_profile, current_field, topic_thread_id, topic_name, data_json, int(active), now, now),
            )
        return self.get_character_draft(chat_id, user_id)

    def get_character_draft(self, chat_id: int, user_id: int) -> CharacterDraft:
        row = self._one("SELECT * FROM character_drafts WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        if row is None:
            raise KeyError(f"No character draft for player {user_id} in chat {chat_id}")
        return _character_draft(row)

    def maybe_character_draft(self, chat_id: int, user_id: int, *, active_only: bool = True) -> CharacterDraft | None:
        if active_only:
            row = self._one(
                "SELECT * FROM character_drafts WHERE chat_id = ? AND user_id = ? AND active = 1",
                (chat_id, user_id),
            )
        else:
            row = self._one("SELECT * FROM character_drafts WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return _character_draft(row) if row else None

    def maybe_character_draft_by_topic(
        self,
        chat_id: int,
        topic_thread_id: int,
        *,
        active_only: bool = True,
    ) -> CharacterDraft | None:
        if active_only:
            row = self._one(
                """
                SELECT * FROM character_drafts
                WHERE chat_id = ? AND topic_thread_id = ? AND active = 1
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (chat_id, topic_thread_id),
            )
        else:
            row = self._one(
                """
                SELECT * FROM character_drafts
                WHERE chat_id = ? AND topic_thread_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (chat_id, topic_thread_id),
            )
        return _character_draft(row) if row else None

    def update_character_draft(
        self,
        chat_id: int,
        user_id: int,
        *,
        current_field: str | None = None,
        topic_thread_id: int | None = None,
        topic_name: str | None = None,
        data: dict[str, Any] | None = None,
        active: bool | None = None,
    ) -> CharacterDraft:
        draft = self.get_character_draft(chat_id, user_id)
        merged_data = draft.data if data is None else data
        updates: dict[str, Any] = {
            "current_field": current_field,
            "data_json": json.dumps(merged_data, ensure_ascii=False, sort_keys=True),
            "updated_at": utc_now(),
        }
        if active is not None:
            updates["active"] = int(active)
        if topic_thread_id is not None:
            updates["topic_thread_id"] = topic_thread_id
        if topic_name is not None:
            updates["topic_name"] = topic_name
        columns = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [chat_id, user_id]
        with self._lock, self._conn:
            self._conn.execute(f"UPDATE character_drafts SET {columns} WHERE chat_id = ? AND user_id = ?", values)
        return self.get_character_draft(chat_id, user_id)

    def cancel_character_draft(self, chat_id: int, user_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE character_drafts SET active = 0, current_field = NULL, updated_at = ? WHERE chat_id = ? AND user_id = ?",
                (utc_now(), chat_id, user_id),
            )

    def add_message(self, chat_id: int, *, role: str, content: str, user_id: int | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages (chat_id, user_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (chat_id, user_id, role, content, utc_now()),
            )

    def recent_messages(self, chat_id: int, *, limit: int = 18) -> list[sqlite3.Row]:
        rows = self._all(
            """
            SELECT * FROM messages
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        return list(reversed(rows))

    def message_count(self, chat_id: int) -> int:
        row = self._one("SELECT COUNT(*) AS count FROM messages WHERE chat_id = ?", (chat_id,))
        return int(row["count"] if row else 0)

    def create_image_request(
        self,
        *,
        chat_id: int,
        user_id: int,
        original_prompt: str,
        drafted_prompt: str,
    ) -> ImageRequest:
        now = utc_now()
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO image_requests
                (chat_id, user_id, original_prompt, drafted_prompt, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (chat_id, user_id, original_prompt, drafted_prompt, now, now),
            )
            image_id = int(cursor.lastrowid)
        return self.get_image_request(image_id)

    def get_image_request(self, image_request_id: int) -> ImageRequest:
        row = self._one("SELECT * FROM image_requests WHERE id = ?", (image_request_id,))
        if row is None:
            raise KeyError(f"No image request {image_request_id}")
        return _image_request(row)

    def update_image_request(self, image_request_id: int, *, status: str, image_url: str | None = None) -> ImageRequest:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE image_requests
                SET status = ?, image_url = COALESCE(?, image_url), updated_at = ?
                WHERE id = ?
                """,
                (status, image_url, utc_now(), image_request_id),
            )
        return self.get_image_request(image_request_id)

    def count_generated_images_since(self, chat_id: int, since: datetime) -> int:
        row = self._one(
            """
            SELECT COUNT(*) AS count FROM image_requests
            WHERE chat_id = ? AND status = 'generated' AND created_at >= ?
            """,
            (chat_id, since.isoformat(timespec="seconds")),
        )
        return int(row["count"] if row else 0)

    def latest_image_created_at(self, chat_id: int) -> datetime | None:
        row = self._one(
            """
            SELECT created_at FROM image_requests
            WHERE chat_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id,),
        )
        if row is None:
            return None
        return datetime.fromisoformat(row["created_at"])

    def add_cost_log(
        self,
        *,
        chat_id: int,
        model: str,
        kind: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_cost: float,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO cost_logs
                (chat_id, model, kind, prompt_tokens, completion_tokens, total_cost, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (chat_id, model, kind, prompt_tokens, completion_tokens, total_cost, utc_now()),
            )

    def _one(self, query: str, params: Iterable[Any]) -> sqlite3.Row | None:
        with self._lock:
            cursor = self._conn.execute(query, tuple(params))
            return cursor.fetchone()

    def _all(self, query: str, params: Iterable[Any]) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self._conn.execute(query, tuple(params))
            return cursor.fetchall()


def _campaign(row: sqlite3.Row) -> Campaign:
    return Campaign(
        chat_id=int(row["chat_id"]),
        title=str(row["title"]),
        active=bool(row["active"]),
        game_profile=str(row["game_profile"]),
        language=str(row["language"]),
        content_preset=str(row["content_preset"]),
        text_model=row["text_model"],
        image_model=row["image_model"],
        summary=str(row["summary"] or ""),
        spotlight_user_id=int(row["spotlight_user_id"]) if row["spotlight_user_id"] is not None else None,
    )


def _player(row: sqlite3.Row) -> Player:
    return Player(
        chat_id=int(row["chat_id"]),
        user_id=int(row["user_id"]),
        username=row["username"],
        display_name=str(row["display_name"]),
        experience_mode=str(row["experience_mode"]),
        active=bool(row["active"]),
        handle=row["handle"],
        role=row["role"],
        style=row["style"],
        stats_json=row["stats_json"],
        skills_json=row["skills_json"],
        gear=row["gear"],
        hp=int(row["hp"]) if row["hp"] is not None else None,
        humanity=int(row["humanity"]) if row["humanity"] is not None else None,
        cyberware=row["cyberware"],
        notes=row["notes"],
    )


def _image_request(row: sqlite3.Row) -> ImageRequest:
    return ImageRequest(
        id=int(row["id"]),
        chat_id=int(row["chat_id"]),
        user_id=int(row["user_id"]),
        original_prompt=str(row["original_prompt"]),
        drafted_prompt=str(row["drafted_prompt"]),
        status=str(row["status"]),
        image_url=row["image_url"],
    )


def _character_draft(row: sqlite3.Row) -> CharacterDraft:
    try:
        data = json.loads(row["data_json"] or "{}")
    except json.JSONDecodeError:
        data = {}
    return CharacterDraft(
        chat_id=int(row["chat_id"]),
        user_id=int(row["user_id"]),
        game_profile=str(row["game_profile"]),
        current_field=row["current_field"],
        topic_thread_id=int(row["topic_thread_id"]) if row["topic_thread_id"] is not None else None,
        topic_name=row["topic_name"],
        data=data,
        active=bool(row["active"]),
    )


def _json_field(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def start_of_utc_day() -> datetime:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, now.day, tzinfo=UTC)


def cooldown_remaining(last_created_at: datetime | None, cooldown_seconds: int) -> int:
    if last_created_at is None or cooldown_seconds <= 0:
        return 0
    elapsed = datetime.now(UTC) - last_created_at
    remaining = timedelta(seconds=cooldown_seconds) - elapsed
    return max(0, int(remaining.total_seconds()))
