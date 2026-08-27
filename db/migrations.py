"""
migrations.py — авто-миграция схемы БД.

Проблема: CREATE TABLE IF NOT EXISTS не добавляет новые колонки в уже
существующую таблицу. Если бэкап был сделан ДО того, как в код добавили
новую колонку, восстановленный файл не будет иметь этой колонки — и
любой INSERT/UPDATE/SELECT с ней упадёт с "no such column".

Решение: описываем эталонную схему (какие колонки должны быть в каждой
таблице), и при каждом init_db() сверяем её с текущим состоянием БД
через PRAGMA table_info — недостающие колонки добавляются ALTER TABLE.

Это применяется ПОСЛЕ executescript() с CREATE TABLE IF NOT EXISTS —
то есть сначала гарантируем, что таблицы вообще есть, потом дозаполняем
недостающие колонки в старых версиях этих таблиц.
"""

import aiosqlite

# Эталонная схема: таблица -> [(имя_колонки, SQL-тип с DEFAULT), ...]
# ВАЖНО: колонка должна иметь DEFAULT, иначе ALTER TABLE ADD COLUMN
# с NOT NULL без DEFAULT упадёт на непустой таблице.
SCHEMA = {
    "users": [
        ("balance", "INTEGER NOT NULL DEFAULT 0"),
        ("bank", "INTEGER NOT NULL DEFAULT 0"),
        ("warnings", "INTEGER NOT NULL DEFAULT 0"),
        ("xp", "INTEGER NOT NULL DEFAULT 0"),
        ("level", "INTEGER NOT NULL DEFAULT 1"),
        ("daily_last", "TEXT"),
        ("work_last", "TEXT"),
        ("created_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
        ("rob_last", "TEXT"),
    	("fish_last", "TEXT"),
    	("mine_last", "TEXT"),
        ("message_count", "INTEGER NOT NULL DEFAULT 0"),
        ("voice_seconds", "INTEGER NOT NULL DEFAULT 0"),
        ("voice_join_at", "TEXT"),
        ("last_xp_message_at", "TEXT"),

    ],
    "shop": [
        ("name", "TEXT NOT NULL DEFAULT ''"),
        ("description", "TEXT"),
        ("price", "INTEGER NOT NULL DEFAULT 0"),
        ("role_id", "INTEGER"),
        ("stock", "INTEGER DEFAULT -1"),
        ("is_active", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "inventory": [
        ("user_id", "INTEGER"),
        ("item_id", "INTEGER"),
        ("bought_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
    ],
    "transactions": [
        ("user_id", "INTEGER"),
        ("amount", "INTEGER NOT NULL DEFAULT 0"),
        ("reason", "TEXT"),
        ("created_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
    ],
    "warns": [
        ("user_id", "INTEGER"),
        ("mod_id", "INTEGER"),
        ("reason", "TEXT"),
        ("created_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
    ],
    "panels": [
        ("guild_id", "INTEGER NOT NULL DEFAULT 0"),
        ("channel_id", "INTEGER NOT NULL DEFAULT 0"),
        ("message_id", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "giveaways": [
        ("guild_id", "INTEGER NOT NULL DEFAULT 0"),
        ("channel_id", "INTEGER NOT NULL DEFAULT 0"),
        ("message_id", "INTEGER NOT NULL DEFAULT 0"),
        ("host_id", "INTEGER NOT NULL DEFAULT 0"),
        ("prize", "TEXT NOT NULL DEFAULT ''"),
        ("winners_count", "INTEGER NOT NULL DEFAULT 1"),
        ("ends_at", "TEXT NOT NULL DEFAULT ''"),
        ("min_role_id", "INTEGER"),
        ("min_level", "INTEGER NOT NULL DEFAULT 0"),
        ("status", "TEXT NOT NULL DEFAULT 'active'"),
        ("created_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
    ],
    "giveaway_entries": [
        ("giveaway_id", "INTEGER"),
        ("user_id", "INTEGER"),
        ("entered_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
    ],
    "security_whitelist": [
        ("added_by", "INTEGER NOT NULL DEFAULT 0"),
        ("added_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
    ],
    "antiraid_incidents": [
        ("guild_id", "INTEGER NOT NULL DEFAULT 0"),
        ("actor_id", "INTEGER NOT NULL DEFAULT 0"),
        ("action_type", "TEXT NOT NULL DEFAULT ''"),
        ("action_count", "INTEGER NOT NULL DEFAULT 0"),
        ("punishment", "TEXT NOT NULL DEFAULT ''"),
        ("created_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
    ],
    "counting_state": [
        ("current_count", "INTEGER NOT NULL DEFAULT 0"),
        ("last_user_id", "INTEGER"),
        ("initialized", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "promocodes": [
        ("reward_type", "TEXT NOT NULL DEFAULT 'balance'"),
        ("reward_amount", "INTEGER"),
        ("reward_item_id", "INTEGER"),
        ("max_uses", "INTEGER NOT NULL DEFAULT -1"),
        ("uses_count", "INTEGER NOT NULL DEFAULT 0"),
        ("expires_at", "TEXT"),
        ("created_by", "INTEGER NOT NULL DEFAULT 0"),
        ("created_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
        ("is_active", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "promocode_redemptions": [
        ("code", "TEXT NOT NULL DEFAULT ''"),
        ("user_id", "INTEGER NOT NULL DEFAULT 0"),
        ("redeemed_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
    ],
}


async def run_migrations(db: aiosqlite.Connection) -> list[str]:
    """
    Сверяет текущую схему БД с эталонной SCHEMA и добавляет недостающие
    колонки через ALTER TABLE. Вызывать сразу после executescript()
    с CREATE TABLE IF NOT EXISTS (то есть все таблицы уже существуют).

    Возвращает список примененных изменений (для логирования).
    """
    applied = []

    for table, columns in SCHEMA.items():
        # таблица могла ещё не быть создана, если её нет в текущей версии
        # executescript — пропускаем на всякий случай
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ) as cur:
            if await cur.fetchone() is None:
                continue

        async with db.execute(f"PRAGMA table_info({table})") as cur:
            existing_columns = {row[1] for row in await cur.fetchall()}

        for col_name, col_def in columns:
            if col_name in existing_columns:
                continue
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                applied.append(f"{table}.{col_name}")
            except aiosqlite.OperationalError as e:
                # на случай гонки/повторного запуска — не фатально
                print(f"[migrations] Не удалось добавить {table}.{col_name}: {e}")

    if applied:
        await db.commit()

    return applied