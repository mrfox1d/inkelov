import aiosqlite
from datetime import datetime
from db.db_guard import get_connection

DB_PATH = "db/database.db"

class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    async def init_db(self) -> None:
        """Создать все таблицы при запуске бота."""
        async with get_connection(self.db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id     INTEGER PRIMARY KEY,
                    balance     INTEGER NOT NULL DEFAULT 0,
                    bank        INTEGER NOT NULL DEFAULT 0,
                    warnings    INTEGER NOT NULL DEFAULT 0,
                    xp          INTEGER NOT NULL DEFAULT 0,
                    level       INTEGER NOT NULL DEFAULT 1,
                    daily_last  TEXT,
                    work_last   TEXT,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS shop (
                    item_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    NOT NULL,
                    description TEXT,
                    price       INTEGER NOT NULL,
                    role_id     INTEGER,
                    stock       INTEGER DEFAULT -1,
                    is_active   INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    inv_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    item_id     INTEGER NOT NULL,
                    bought_at   TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (item_id) REFERENCES shop(item_id)
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    tx_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    amount      INTEGER NOT NULL,
                    reason      TEXT,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS warns (
                    warn_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    mod_id      INTEGER NOT NULL,
                    reason      TEXT,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS panels (
                    panel_key   TEXT PRIMARY KEY,
                    guild_id    INTEGER NOT NULL,
                    channel_id  INTEGER NOT NULL,
                    message_id  INTEGER NOT NULL
                );

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

                CREATE TABLE IF NOT EXISTS security_whitelist (
                    user_id     INTEGER PRIMARY KEY,
                    added_by    INTEGER NOT NULL,
                    added_at    TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS antiraid_incidents (
                    incident_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id      INTEGER NOT NULL,
                    actor_id      INTEGER NOT NULL,
                    action_type   TEXT NOT NULL,
                    action_count  INTEGER NOT NULL,
                    punishment    TEXT NOT NULL,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS counting_state (
                    channel_id      INTEGER PRIMARY KEY,
                    current_count   INTEGER NOT NULL DEFAULT 0,
                    last_user_id    INTEGER,
                    initialized     INTEGER NOT NULL DEFAULT 0
                );
            """)
            await db.commit()

    # ──────────────────────────── USERS / ECONOMY ────────────────────────────

    async def get_user(self, user_id: int) -> dict | None:
        """Получить пользователя. Возвращает dict или None."""
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def ensure_user(self, user_id: int) -> dict:
        """Получить пользователя, создав его если не существует."""
        async with get_connection(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)
            )
            await db.commit()
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ) as cur:
                return dict(await cur.fetchone())

    async def get_balance(self, user_id: int) -> tuple[int, int]:
        """Вернуть (balance, bank) пользователя."""
        user = await self.ensure_user(user_id)
        return user["balance"], user["bank"]

    async def set_balance(self, user_id: int, amount: int) -> None:
        """Установить баланс (кошелёк)."""
        await self.ensure_user(user_id)
        async with get_connection(self.db_path) as db:
            await db.execute(
                "UPDATE users SET balance = ? WHERE user_id = ?", (max(0, amount), user_id)
            )
            await db.commit()

    async def add_balance(self, user_id: int, amount: int, reason: str = None) -> int:
        """Добавить/вычесть из баланса. Возвращает новый баланс."""
        user = await self.ensure_user(user_id)
        new_balance = max(0, user["balance"] + amount)
        async with get_connection(self.db_path) as db:
            await db.execute(
                "UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id)
            )
            await db.execute(
                "INSERT INTO transactions (user_id, amount, reason) VALUES (?, ?, ?)",
                (user_id, amount, reason),
            )
            await db.commit()
        return new_balance

    async def deposit(self, user_id: int, amount: int) -> tuple[int, int]:
        """Положить amount из кошелька в банк. Возвращает (новый баланс, новый банк)."""
        user = await self.ensure_user(user_id)
        amount = min(amount, user["balance"])
        new_bal = user["balance"] - amount
        new_bank = user["bank"] + amount
        async with get_connection(self.db_path) as db:
            await db.execute(
                "UPDATE users SET balance = ?, bank = ? WHERE user_id = ?",
                (new_bal, new_bank, user_id),
            )
            await db.commit()
        return new_bal, new_bank

    async def withdraw(self, user_id: int, amount: int) -> tuple[int, int]:
        """Вытащить amount из банка в кошелёк. Возвращает (новый баланс, новый банк)."""
        user = await self.ensure_user(user_id)
        amount = min(amount, user["bank"])
        new_bal = user["balance"] + amount
        new_bank = user["bank"] - amount
        async with get_connection(self.db_path) as db:
            await db.execute(
                "UPDATE users SET balance = ?, bank = ? WHERE user_id = ?",
                (new_bal, new_bank, user_id),
            )
            await db.commit()
        return new_bal, new_bank

    async def get_leaderboard(self, limit: int = 10) -> list[dict]:
        """Топ пользователей по (balance + bank)."""
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT user_id, balance, bank, (balance + bank) AS total
                FROM users ORDER BY total DESC LIMIT ?""",
                (limit,),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def get_transaction_history(self, user_id: int, limit: int = 10) -> list[dict]:
        """Последние транзакции пользователя."""
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM transactions WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def can_claim_daily(self, user_id: int) -> bool:
        """True если прошли сутки с последнего /daily."""
        user = await self.ensure_user(user_id)
        last = user["daily_last"]
        if not last:
            return True
        diff = datetime.utcnow() - datetime.fromisoformat(last)
        return diff.total_seconds() >= 86400

    async def set_daily_claimed(self, user_id: int) -> None:
        async with get_connection(self.db_path) as db:
            await db.execute(
                "UPDATE users SET daily_last = ? WHERE user_id = ?",
                (datetime.utcnow().isoformat(), user_id),
            )
            await db.commit()

    async def can_work(self, user_id: int, cooldown_seconds: int = 3600) -> bool:
        """True если кулдаун /work истёк."""
        user = await self.ensure_user(user_id)
        last = user["work_last"]
        if not last:
            return True
        diff = datetime.utcnow() - datetime.fromisoformat(last)
        return diff.total_seconds() >= cooldown_seconds

    async def set_work_done(self, user_id: int) -> None:
        async with get_connection(self.db_path) as db:
            await db.execute(
                "UPDATE users SET work_last = ? WHERE user_id = ?",
                (datetime.utcnow().isoformat(), user_id),
            )
            await db.commit()

    def xp_for_level(self, level: int) -> int:
        """XP, нужный для следующего уровня."""
        return 100 * (level ** 2)

    async def add_xp(self, user_id: int, amount: int) -> dict:
        """
        Добавить XP. Возвращает dict:
        {"leveled_up": bool, "level": int, "xp": int}
        """
        user = await self.ensure_user(user_id)
        new_xp = user["xp"] + amount
        level = user["level"]
        leveled_up = False

        while new_xp >= self.xp_for_level(level):
            new_xp -= self.xp_for_level(level)
            level += 1
            leveled_up = True

        async with get_connection(self.db_path) as db:
            await db.execute(
                "UPDATE users SET xp = ?, level = ? WHERE user_id = ?",
                (new_xp, level, user_id),
            )
            await db.commit()

        return {"leveled_up": leveled_up, "level": level, "xp": new_xp}

    # ──────────────────────────── WARNS ────────────────────────────

    async def add_warning(self, user_id: int, mod_id: int, reason: str = None) -> int:
        """Выдать варн. Возвращает новое кол-во варнов."""
        await self.ensure_user(user_id)
        async with get_connection(self.db_path) as db:
            await db.execute(
                "INSERT INTO warns (user_id, mod_id, reason) VALUES (?, ?, ?)",
                (user_id, mod_id, reason),
            )
            await db.execute(
                "UPDATE users SET warnings = warnings + 1 WHERE user_id = ?", (user_id,)
            )
            await db.commit()
            async with db.execute(
                "SELECT warnings FROM users WHERE user_id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()
                return row[0]

    async def remove_warning(self, user_id: int) -> int:
        """Снять один варн (удаляет последний). Возвращает новое кол-во."""
        async with get_connection(self.db_path) as db:
            async with db.execute(
                "SELECT warn_id FROM warns WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
            if row:
                await db.execute("DELETE FROM warns WHERE warn_id = ?", (row[0],))
                await db.execute(
                    "UPDATE users SET warnings = MAX(0, warnings - 1) WHERE user_id = ?",
                    (user_id,),
                )
                await db.commit()
            async with db.execute(
                "SELECT warnings FROM users WHERE user_id = ?", (user_id,)
            ) as cur:
                r = await cur.fetchone()
                return r[0] if r else 0

    async def clear_warnings(self, user_id: int) -> None:
        """Сбросить все варны пользователя."""
        async with get_connection(self.db_path) as db:
            await db.execute("DELETE FROM warns WHERE user_id = ?", (user_id,))
            await db.execute(
                "UPDATE users SET warnings = 0 WHERE user_id = ?", (user_id,)
            )
            await db.commit()

    async def get_warnings(self, user_id: int) -> list[dict]:
        """Список всех варнов пользователя."""
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM warns WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    # ──────────────────────────── SHOP / INVENTORY ────────────────────────────

    async def add_item(
        self,
        name: str,
        price: int,
        description: str = None,
        role_id: int = None,
        stock: int = -1,
    ) -> int:
        """Добавить товар. Возвращает item_id."""
        async with get_connection(self.db_path) as db:
            cur = await db.execute(
                """INSERT INTO shop (name, description, price, role_id, stock)
                VALUES (?, ?, ?, ?, ?)""",
                (name, description, price, role_id, stock),
            )
            await db.commit()
            return cur.lastrowid

    async def get_item(self, item_id: int) -> dict | None:
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM shop WHERE item_id = ? AND is_active = 1", (item_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_all_items(self, only_active: bool = True) -> list[dict]:
        """Все товары в магазине."""
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM shop"
            if only_active:
                query += " WHERE is_active = 1"
            query += " ORDER BY price ASC"
            async with db.execute(query) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def delete_item(self, item_id: int) -> None:
        """Мягкое удаление товара (is_active = 0)."""
        async with get_connection(self.db_path) as db:
            await db.execute(
                "UPDATE shop SET is_active = 0 WHERE item_id = ?", (item_id,)
            )
            await db.commit()

    async def edit_item(self, item_id: int, **kwargs) -> None:
        """
        Редактировать поля товара. Допустимые ключи:
        name, description, price, role_id, stock, is_active
        """
        allowed = {"name", "description", "price", "role_id", "stock", "is_active"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [item_id]
        async with get_connection(self.db_path) as db:
            await db.execute(f"UPDATE shop SET {set_clause} WHERE item_id = ?", values)
            await db.commit()

    async def buy_item(self, user_id: int, item_id: int) -> dict:
        """
        Купить товар. Возвращает dict:
        {"success": bool, "reason": str | None, "new_balance": int}
        """
        user = await self.ensure_user(user_id)
        item = await self.get_item(item_id)

        if not item:
            return {"success": False, "reason": "Товар не найден", "new_balance": user["balance"]}
        if item["stock"] == 0:
            return {"success": False, "reason": "Товар закончился", "new_balance": user["balance"]}
        if user["balance"] < item["price"]:
            return {"success": False, "reason": "Недостаточно средств", "new_balance": user["balance"]}

        new_balance = user["balance"] - item["price"]
        async with get_connection(self.db_path) as db:
            await db.execute(
                "UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id)
            )
            await db.execute(
                "INSERT INTO inventory (user_id, item_id) VALUES (?, ?)", (user_id, item_id)
            )
            if item["stock"] > 0:
                await db.execute(
                    "UPDATE shop SET stock = stock - 1 WHERE item_id = ?", (item_id,)
                )
            await db.execute(
                "INSERT INTO transactions (user_id, amount, reason) VALUES (?, ?, ?)",
                (user_id, -item["price"], f"Покупка: {item['name']}"),
            )
            await db.commit()

        return {"success": True, "reason": None, "new_balance": new_balance}

    async def get_inventory(self, user_id: int) -> list[dict]:
        """Инвентарь пользователя с данными о товарах."""
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT i.inv_id, i.bought_at, s.item_id, s.name, s.description,
                        s.price, s.role_id
                FROM inventory i
                JOIN shop s ON i.item_id = s.item_id
                WHERE i.user_id = ?
                ORDER BY i.bought_at DESC""",
                (user_id,),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    # ──────────────────────────── PANELS ────────────────────────────

    async def set_panel(self, panel_key: str, guild_id: int, channel_id: int, message_id: int) -> None:
        """Сохранить/обновить местоположение закреплённой панели (например 'shop')."""
        async with get_connection(self.db_path) as db:
            await db.execute(
                """INSERT INTO panels (panel_key, guild_id, channel_id, message_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(panel_key) DO UPDATE SET
                    guild_id = excluded.guild_id,
                    channel_id = excluded.channel_id,
                    message_id = excluded.message_id""",
                (panel_key, guild_id, channel_id, message_id),
            )
            await db.commit()

    async def get_panel(self, panel_key: str) -> dict | None:
        """Получить местоположение панели по ключу. None если панель не создавалась."""
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM panels WHERE panel_key = ?", (panel_key,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    # ──────────────────────────── GIVEAWAYS ────────────────────────────

    async def create_giveaway(
        self, guild_id: int, channel_id: int, message_id: int, host_id: int,
        prize: str, winners_count: int, ends_at: str,
        min_role_id: int = None, min_level: int = 0,
    ) -> int:
        async with get_connection(self.db_path) as db:
            cur = await db.execute(
                """INSERT INTO giveaways
                (guild_id, channel_id, message_id, host_id, prize, winners_count, ends_at, min_role_id, min_level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (guild_id, channel_id, message_id, host_id, prize, winners_count, ends_at, min_role_id, min_level),
            )
            await db.commit()
            return cur.lastrowid

    async def get_giveaway(self, giveaway_id: int) -> dict | None:
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM giveaways WHERE giveaway_id = ?", (giveaway_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_giveaway_by_message(self, message_id: int) -> dict | None:
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM giveaways WHERE message_id = ?", (message_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_active_giveaways(self) -> list[dict]:
        """Все розыгрыши со статусом 'active' — используется для восстановления таймеров после рестарта."""
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM giveaways WHERE status = 'active'") as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def set_giveaway_status(self, giveaway_id: int, status: str) -> None:
        """status: 'active' | 'ended' | 'cancelled'"""
        async with get_connection(self.db_path) as db:
            await db.execute("UPDATE giveaways SET status = ? WHERE giveaway_id = ?", (status, giveaway_id))
            await db.commit()

    async def add_giveaway_entry(self, giveaway_id: int, user_id: int) -> bool:
        """Добавить участника. True если добавлен, False если уже участвовал."""
        async with get_connection(self.db_path) as db:
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
        async with get_connection(self.db_path) as db:
            cur = await db.execute(
                "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
                (giveaway_id, user_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def get_giveaway_entries(self, giveaway_id: int) -> list[int]:
        """Список user_id участников розыгрыша."""
        async with get_connection(self.db_path) as db:
            async with db.execute(
                "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
            ) as cur:
                rows = await cur.fetchall()
                return [r[0] for r in rows]

    async def get_giveaway_entry_count(self, giveaway_id: int) -> int:
        async with get_connection(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def is_entered(self, giveaway_id: int, user_id: int) -> bool:
        async with get_connection(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
                (giveaway_id, user_id),
            ) as cur:
                return await cur.fetchone() is not None

    # ──────────────────────────── SECURITY WHITELIST ────────────────────────────

    async def add_to_security_whitelist(self, user_id: int, added_by: int) -> bool:
        """Добавить юзера в вайтлист. False если уже там."""
        async with get_connection(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO security_whitelist (user_id, added_by) VALUES (?, ?)",
                    (user_id, added_by),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def remove_from_security_whitelist(self, user_id: int) -> bool:
        """Убрать юзера из вайтлиста. True если был удалён."""
        async with get_connection(self.db_path) as db:
            cur = await db.execute("DELETE FROM security_whitelist WHERE user_id = ?", (user_id,))
            await db.commit()
            return cur.rowcount > 0

    async def is_security_whitelisted(self, user_id: int) -> bool:
        async with get_connection(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM security_whitelist WHERE user_id = ?", (user_id,)
            ) as cur:
                return await cur.fetchone() is not None

    async def get_security_whitelist(self) -> list[dict]:
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM security_whitelist ORDER BY added_at ASC"
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    # ──────────────────────────── ANTIRAID ────────────────────────────

    async def log_antiraid_incident(
        self, guild_id: int, actor_id: int, action_type: str, action_count: int, punishment: str
    ) -> int:
        async with get_connection(self.db_path) as db:
            cur = await db.execute(
                """INSERT INTO antiraid_incidents (guild_id, actor_id, action_type, action_count, punishment)
                VALUES (?, ?, ?, ?, ?)""",
                (guild_id, actor_id, action_type, action_count, punishment),
            )
            await db.commit()
            return cur.lastrowid

    async def get_recent_antiraid_incidents(self, guild_id: int, limit: int = 10) -> list[dict]:
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM antiraid_incidents WHERE guild_id = ?
                ORDER BY created_at DESC LIMIT ?""",
                (guild_id, limit),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def get_counting_state(self, channel_id: int) -> dict | None:
        async with get_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM counting_state WHERE channel_id = ?", (channel_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None
    
    
    async def init_counting_state(self, channel_id: int, current_count: int) -> None:
        """Вызывается один раз — при первом запуске, когда счёт восстановлен из истории канала."""
        async with get_connection(self.db_path) as db:
            await db.execute(
                """INSERT INTO counting_state (channel_id, current_count, last_user_id, initialized)
                VALUES (?, ?, NULL, 1)
                ON CONFLICT(channel_id) DO UPDATE SET
                    current_count = excluded.current_count,
                    initialized = 1""",
                (channel_id, current_count),
            )
            await db.commit()
    
    
    async def set_counting_state(self, channel_id: int, current_count: int, last_user_id: int) -> None:
        async with get_connection(self.db_path) as db:
            await db.execute(
                """INSERT INTO counting_state (channel_id, current_count, last_user_id, initialized)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(channel_id) DO UPDATE SET
                    current_count = excluded.current_count,
                    last_user_id = excluded.last_user_id""",
                (channel_id, current_count, last_user_id),
            )
            await db.commit()
    
    
    async def reset_counting_state(self, channel_id: int) -> None:
        async with get_connection(self.db_path) as db:
            await db.execute(
                """UPDATE counting_state SET current_count = 0, last_user_id = NULL
                WHERE channel_id = ?""",
                (channel_id,),
            )
            await db.commit()
