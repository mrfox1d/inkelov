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
            """)
            await db.commit()

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