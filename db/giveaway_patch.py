# ─────────────────────────────────────────────────────────────────
# ПАТЧ для db/interaction.py — добавь в класс Database
# ─────────────────────────────────────────────────────────────────

# 1) В executescript() внутри init_db() добавь:
"""
CREATE TABLE IF NOT EXISTS giveaways (
    giveaway_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    channel_id    INTEGER NOT NULL,
    message_id    INTEGER NOT NULL,
    host_id       INTEGER NOT NULL,
    prize         TEXT NOT NULL,
    winners_count INTEGER NOT NULL DEFAULT 1,
    ends_at       TEXT NOT NULL,
    min_role_id   INTEGER,
    min_level     INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS giveaway_entries (
    entry_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    giveaway_id   INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    entered_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(giveaway_id, user_id),
    FOREIGN KEY (giveaway_id) REFERENCES giveaways(giveaway_id)
);
"""

# 2) Добавь эти методы в класс Database:

async def create_giveaway(
    self, guild_id: int, channel_id: int, message_id: int, host_id: int,
    prize: str, winners_count: int, ends_at: str,
    min_role_id: int = None, min_level: int = 0,
) -> int:
    async with aiosqlite.connect(self.db_path) as db:
        cur = await db.execute(
            """INSERT INTO giveaways
               (guild_id, channel_id, message_id, host_id, prize, winners_count, ends_at, min_role_id, min_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, channel_id, message_id, host_id, prize, winners_count, ends_at, min_role_id, min_level),
        )
        await db.commit()
        return cur.lastrowid


async def get_giveaway(self, giveaway_id: int) -> dict | None:
    async with aiosqlite.connect(self.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM giveaways WHERE giveaway_id = ?", (giveaway_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_giveaway_by_message(self, message_id: int) -> dict | None:
    async with aiosqlite.connect(self.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM giveaways WHERE message_id = ?", (message_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_active_giveaways(self) -> list[dict]:
    """Все розыгрыши со статусом 'active' — используется для восстановления таймеров после рестарта."""
    async with aiosqlite.connect(self.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM giveaways WHERE status = 'active'") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def set_giveaway_status(self, giveaway_id: int, status: str) -> None:
    """status: 'active' | 'ended' | 'cancelled'"""
    async with aiosqlite.connect(self.db_path) as db:
        await db.execute("UPDATE giveaways SET status = ? WHERE giveaway_id = ?", (status, giveaway_id))
        await db.commit()


async def add_giveaway_entry(self, giveaway_id: int, user_id: int) -> bool:
    """Добавить участника. True если добавлен, False если уже участвовал."""
    async with aiosqlite.connect(self.db_path) as db:
        try:
            await db.execute(
                "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
                (giveaway_id, user_id),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_giveaway_entry(self, giveaway_id: int, user_id: int) -> bool:
    """Убрать участника (повторный клик = отмена участия). True если был удалён."""
    async with aiosqlite.connect(self.db_path) as db:
        cur = await db.execute(
            "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_giveaway_entries(self, giveaway_id: int) -> list[int]:
    """Список user_id участников розыгрыша."""
    async with aiosqlite.connect(self.db_path) as db:
        async with db.execute(
            "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


async def get_giveaway_entry_count(self, giveaway_id: int) -> int:
    async with aiosqlite.connect(self.db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def is_entered(self, giveaway_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(self.db_path) as db:
        async with db.execute(
            "SELECT 1 FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id),
        ) as cur:
            return await cur.fetchone() is not None