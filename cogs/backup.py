import os
import shutil
from datetime import datetime, time

import disnake
from disnake.ext import commands, tasks
from db.db_guard import BACKUP_CHANNEL_ID

CLR_BACKUP = 0x00D9FF
CLR_FAIL   = 0xFF2E2E
CLR_OK     = 0x2EFF7A

DB_PATH = "db/database.db"   # держи синхронно с db/interaction.py -> DB_PATH
BACKUP_HOUR_UTC = 3          # в какой час (UTC) запускать ежедневный бэкап


class Backup(commands.Cog):
    """
    Ежедневный бэкап БД в канал BACKUP_CHANNEL_ID.
    Восстановление файла БД в реальном времени при его отсутствии
    выполняется прозрачно через db/db_guard.py при любом обращении к БД —
    отдельно вызывать здесь ничего не нужно.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.daily_backup.start()

    def cog_unload(self):
        self.daily_backup.cancel()

    # ──────────────────────── ЕЖЕДНЕВНЫЙ БЭКАП ────────────────────────

    @tasks.loop(time=time(hour=BACKUP_HOUR_UTC, minute=0))
    async def daily_backup(self):
        await self._do_backup(reason="Плановый ежедневный бэкап")

    @daily_backup.before_loop
    async def before_daily_backup(self):
        await self.bot.wait_until_ready()

    async def _do_backup(self, reason: str = "Бэкап") -> bool:
        if not os.path.exists(DB_PATH):
            print(f"[backup] Нечего бэкапить — {DB_PATH} не существует.")
            return False

        channel = self.bot.get_channel(BACKUP_CHANNEL_ID)
        if channel is None:
            print("[backup] Канал бэкапов не найден.")
            return False

        # копируем во временный файл, чтобы не держать блокировку основной БД дольше нужного
        timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        tmp_path = f"backup_{timestamp}.db"
        shutil.copy2(DB_PATH, tmp_path)

        try:
            await channel.send(
                embed=disnake.Embed(
                    title="💾 Бэкап базы данных",
                    description=f"{reason}\n\n**Дата:** {disnake.utils.format_dt(datetime.utcnow(), style='F')}",
                    color=CLR_BACKUP,
                ),
                file=disnake.File(tmp_path, filename=f"database_{timestamp}.db"),
            )
            return True
        finally:
            os.remove(tmp_path)

    # ──────────────────────── АДМИН-КОМАНДЫ ────────────────────────

    @commands.command(name="backupnow")
    @commands.has_permissions(administrator=True)
    async def txt_backupnow(self, ctx: commands.Context):
        """Сделать бэкап БД прямо сейчас"""
        msg = await ctx.send(embed=disnake.Embed(title="💾 Создаю бэкап...", color=CLR_BACKUP))
        success = await self._do_backup(reason=f"Ручной бэкап от {ctx.author}")
        if success:
            await msg.edit(embed=disnake.Embed(title="✅ Бэкап создан", description=f"Файл отправлен в <#{BACKUP_CHANNEL_ID}>", color=CLR_OK))
        else:
            await msg.edit(embed=disnake.Embed(title="❌ Ошибка", description="Не удалось создать бэкап. Проверь логи.", color=CLR_FAIL))

    @commands.slash_command(name="backupnow", description="💾 [Admin] Сделать бэкап БД прямо сейчас")
    @commands.has_permissions(administrator=True)
    async def slash_backupnow(self, inter: disnake.AppCmdInter):
        await inter.response.defer()
        success = await self._do_backup(reason=f"Ручной бэкап от {inter.author}")
        if success:
            await inter.edit_original_response(embed=disnake.Embed(title="✅ Бэкап создан", description=f"Файл отправлен в <#{BACKUP_CHANNEL_ID}>", color=CLR_OK))
        else:
            await inter.edit_original_response(embed=disnake.Embed(title="❌ Ошибка", description="Не удалось создать бэкап. Проверь логи.", color=CLR_FAIL))

    @txt_backupnow.error
    async def backup_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=disnake.Embed(title="⛔ Нет прав", description="Эта команда только для администраторов.", color=CLR_FAIL))
        else:
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_FAIL))

    @slash_backupnow.error
    async def slash_backup_error(self, inter: disnake.AppCmdInter, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await inter.response.send_message(embed=disnake.Embed(title="⛔ Нет прав", description="Эта команда только для администраторов.", color=CLR_FAIL), ephemeral=True)
        else:
            await inter.response.send_message(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_FAIL), ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(Backup(bot))