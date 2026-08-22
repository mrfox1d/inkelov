import os
import asyncio
import aiosqlite
import disnake

BACKUP_CHANNEL_ID = 1540312888546427030
ALERT_CHANNEL_ID = 1540313688064532480

_bot = None

_restore_lock = asyncio.Lock()
_last_restore_notice_sent = False


def set_bot(bot):
    """Вызови один раз в main.py после создания bot, до bot.start()."""
    global _bot
    _bot = bot


async def _restore_from_backup(db_path: str) -> bool:
    """Качает последний бэкап из канала в db_path. Возвращает True при успехе."""
    global _last_restore_notice_sent

    if _bot is None:
        print("[db_guard] Бот не привязан (вызови set_bot) — восстановление невозможно.")
        return False

    await _bot.wait_until_ready()

    backup_channel = _bot.get_channel(BACKUP_CHANNEL_ID)
    if backup_channel is None:
        print("[db_guard] Канал бэкапов не найден.")
        return False

    last_backup_msg = None
    async for message in backup_channel.history(limit=200):
        if message.author.id != _bot.user.id:
            continue
        if not message.attachments:
            continue
        if not message.attachments[0].filename.endswith(".db"):
            continue
        last_backup_msg = message
        break

    if last_backup_msg is None:
        print("[db_guard] Бэкапов не найдено в канале.")
        return False

    parent_dir = os.path.dirname(db_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    attachment = last_backup_msg.attachments[0]
    await attachment.save(db_path)
    print(f"[db_guard] БД восстановлена из бэкапа от {last_backup_msg.created_at}")

    if not _last_restore_notice_sent:
        _last_restore_notice_sent = True
        alert_channel = _bot.get_channel(ALERT_CHANNEL_ID)
        if alert_channel:
            formatted_dt = disnake.utils.format_dt(last_backup_msg.created_at, style="F")
            relative_dt = disnake.utils.format_dt(last_backup_msg.created_at, style="R")
            try:
                await alert_channel.send(embed=disnake.Embed(
                    title="⚠️ База данных была восстановлена из бэкапа",
                    description=(
                        f"Файл базы данных пропал во время работы бота — обнаружено "
                        f"при обращении к БД в реальном времени. Автоматически "
                        f"выполнен откат до последнего доступного бэкапа.\n\n"
                        f"**Дата бэкапа:** {formatted_dt} ({relative_dt})\n\n"
                        f"Все изменения (балансы, покупки, розыгрыши и т.д.), сделанные после "
                        f"этой даты, могут быть потеряны. Приносим извинения за неудобства."
                    ),
                    color=0xFFAA00,
                ))
            except disnake.HTTPException:
                pass

    return True


async def _ensure_db_ready(db_path: str):
    """Проверяет наличие файла БД. Если файла нет — восстанавливает из бэкапа."""
    if os.path.exists(db_path):
        return

    async with _restore_lock:
        if os.path.exists(db_path):
            return
        await _restore_from_backup(db_path)


def get_connection(db_path: str):
    """
    Возвращает контекстный менеджер подключения к БД, аналогичный
    aiosqlite.connect(db_path), но с предварительной проверкой наличия
    файла и восстановлением из бэкапа при необходимости.

    Использование идентично aiosqlite.connect:
        async with get_connection(self.db_path) as db:
            await db.execute(...)
    """
    return _GuardedConnection(db_path)


class _GuardedConnection:
    """Обёртка, которая перед открытием реального соединения гарантирует наличие файла."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = None

    async def __aenter__(self) -> aiosqlite.Connection:
        await _ensure_db_ready(self.db_path)
        self._conn = await aiosqlite.connect(self.db_path)
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        await self._conn.close()