import aiosqlite
from datetime import datetime, timezone
from pathlib import Path


class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    inviter_id INTEGER,
                    joined INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    joined_at TEXT
                )
            """)
            await db.commit()

    async def register_user(self, user_id: int, username: str | None,
                            full_name: str, inviter_id: int | None) -> None:
        if inviter_id == user_id:
            inviter_id = None
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO users(user_id, username, full_name, inviter_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name,
                    inviter_id = CASE
                        WHEN users.inviter_id IS NULL AND users.joined = 0
                        THEN excluded.inviter_id
                        ELSE users.inviter_id
                    END
            """, (user_id, username, full_name, inviter_id, now))
            await db.commit()

    async def mark_joined(self, user_id: int) -> tuple[int | None, bool]:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT inviter_id, joined FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if not row or row[1]:
                await db.commit()
                return (row[0] if row else None), False
            await db.execute(
                "UPDATE users SET joined = 1, joined_at = ? WHERE user_id = ?",
                (now, user_id),
            )
            await db.commit()
            return row[0], True

    async def referral_stats(self, inviter_id: int) -> tuple[int, int]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""
                SELECT COUNT(*), COALESCE(SUM(joined), 0)
                FROM users WHERE inviter_id = ?
            """, (inviter_id,))
            row = await cursor.fetchone()
            return int(row[0]), int(row[1])

    async def global_stats(self) -> tuple[int, int, int]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""
                SELECT COUNT(*), COALESCE(SUM(joined), 0),
                       COUNT(DISTINCT CASE WHEN inviter_id IS NOT NULL THEN inviter_id END)
                FROM users
            """)
            row = await cursor.fetchone()
            return int(row[0]), int(row[1]), int(row[2])

    async def top_referrers(self, limit: int = 10) -> list[tuple]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""
                SELECT p.user_id, p.username, p.full_name,
                       COUNT(c.user_id) AS leads,
                       COALESCE(SUM(c.joined), 0) AS joined_count
                FROM users p
                JOIN users c ON c.inviter_id = p.user_id
                GROUP BY p.user_id
                ORDER BY joined_count DESC, leads DESC
                LIMIT ?
            """, (limit,))
            return await cursor.fetchall()

    async def all_users(self) -> list[tuple]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""
                SELECT user_id, username, full_name, inviter_id, joined,
                       created_at, joined_at
                FROM users ORDER BY created_at DESC
            """)
            return await cursor.fetchall()
