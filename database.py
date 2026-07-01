import aiosqlite
from datetime import datetime
from typing import Optional
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_type TEXT NOT NULL,
                text TEXT,
                media_type TEXT NOT NULL DEFAULT 'none',
                media_file_id TEXT,
                local_media_path TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                scheduled_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                published_at TEXT,
                telegram_message_id INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                title TEXT,
                added_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_messages (
                source_username TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                processed_at TEXT NOT NULL,
                PRIMARY KEY (source_username, message_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                sources_used TEXT,
                raw_posts TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                published_at TEXT,
                telegram_message_id INTEGER
            )
        """)
        await db.commit()


# ─── Posts ───────────────────────────────────────────────────────────────────

async def create_post(
    post_type: str,
    text: Optional[str] = None,
    media_type: str = "none",
    media_file_id: Optional[str] = None,
    local_media_path: Optional[str] = None,
    status: str = "draft",
    scheduled_at: Optional[str] = None,
) -> int:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO posts
               (post_type, text, media_type, media_file_id, local_media_path,
                status, scheduled_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (post_type, text, media_type, media_file_id, local_media_path,
             status, scheduled_at, now, now),
        )
        await db.commit()
        return cursor.lastrowid


async def get_post(post_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_post(post_id: int, **kwargs) -> None:
    kwargs["updated_at"] = datetime.utcnow().isoformat()
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [post_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE posts SET {fields} WHERE id = ?", values)
        await db.commit()


async def get_posts_by_status(status: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM posts WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_scheduled_posts() -> list[dict]:
    return await get_posts_by_status("scheduled")


async def get_draft_posts() -> list[dict]:
    return await get_posts_by_status("draft")


async def get_published_posts(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM posts WHERE status = 'published' ORDER BY published_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def delete_post(post_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        await db.commit()


# ─── Sources ──────────────────────────────────────────────────────────────────

async def get_active_sources() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sources WHERE active = 1 ORDER BY added_at"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def add_source(username: str, title: Optional[str] = None) -> int:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO sources (username, title, added_at) VALUES (?, ?, ?)",
            (username, title, now),
        )
        await db.commit()
        return cursor.lastrowid


async def get_source(source_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_source_by_username(username: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sources WHERE username = ?", (username,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def remove_source(source_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        await db.commit()


# ─── Seen messages ────────────────────────────────────────────────────────────

async def get_seen_keys(source_usernames: list[str]) -> set:
    if not source_usernames:
        return set()
    placeholders = ",".join("?" * len(source_usernames))
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT source_username, message_id FROM seen_messages "
            f"WHERE source_username IN ({placeholders})",
            source_usernames,
        ) as cur:
            rows = await cur.fetchall()
            return {f"{r[0]}:{r[1]}" for r in rows}


async def mark_seen(source_username: str, message_id: int) -> None:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen_messages (source_username, message_id, processed_at) "
            "VALUES (?, ?, ?)",
            (source_username, message_id, now),
        )
        await db.commit()


# ─── Digests ──────────────────────────────────────────────────────────────────

async def create_digest(
    text: str,
    sources_used: Optional[str] = None,
    raw_posts_json: Optional[str] = None,
) -> int:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO digests (text, sources_used, raw_posts, status, created_at)
               VALUES (?, ?, ?, 'draft', ?)""",
            (text, sources_used, raw_posts_json, now),
        )
        await db.commit()
        return cursor.lastrowid


async def get_digest(digest_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM digests WHERE id = ?", (digest_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_digest(digest_id: int, **kwargs) -> None:
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [digest_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE digests SET {fields} WHERE id = ?", values)
        await db.commit()


async def delete_digest(digest_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM digests WHERE id = ?", (digest_id,))
        await db.commit()
