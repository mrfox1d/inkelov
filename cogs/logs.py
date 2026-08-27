"""
logs.py — единая система логирования действий бота, с маршрутизацией
по категориям в разные каналы (#чат, #мьюты, #кики, #баны, #никнеймы,
#варны, #антирейд).

Использование из любого другого кога:

    from cogs.logs import log_action

    await log_action(
        bot=self.bot,
        guild=ctx.guild,
        category="bans",           # см. CATEGORIES ниже
        actor=ctx.author,          # кто реально инициировал действие (не бот!)
        action="Выдан бан",
        details=f"Цель: {member.mention}\nПричина: {reason}",
        color=0xFF2E2E,
        target=member,
    )

Если категория на сервере не настроена (нет записи в БД) — лог просто
не отправляется, без ошибок.
"""

import disnake
from disnake.ext import commands
from db.interaction import Database

db = Database()

CLR_LOG  = 0x5865F2
CLR_FAIL = 0xFF2E2E
CLR_OK   = 0x2EFF7A

# Категории логов: ключ -> (эмодзи, читаемое имя)
CATEGORIES = {
    "chat":      ("💬", "Чат"),
    "mutes":     ("🔇", "Мьюты"),
    "kicks":     ("👢", "Кики"),
    "bans":      ("🚫", "Баны"),
    "nicknames": ("👤", "Никнеймы"),
    "warns":     ("⚠️", "Варны"),
    "antiraid":  ("🛡️", "Антирейд"),
}


async def log_action(
    bot: commands.Bot,
    guild: disnake.Guild,
    category: str,
    actor: disnake.Member | disnake.User | None,
    action: str,
    details: str = None,
    color: int = CLR_LOG,
    target: disnake.Member | disnake.User | None = None,
):
    """
    Отправляет embed в канал логов конкретной категории.

    actor    — реальный человек, инициировавший действие. None, если действие
               полностью автоматическое (автомод/антирейд/таймер).
    category — один из ключей CATEGORIES.
    """
    channel_id = await db.get_log_channel(guild.id, category)
    if channel_id is None:
        return  # эта категория не настроена на сервере — молча пропускаем

    channel = guild.get_channel(channel_id)
    if channel is None:
        return

    emoji, _ = CATEGORIES.get(category, ("📋", category))
    embed = disnake.Embed(title=f"{emoji} {action}", description=details or "", color=color)
    embed.timestamp = disnake.utils.utcnow()

    if actor is not None:
        embed.set_author(name=f"{actor} (инициатор)", icon_url=actor.display_avatar.url)
    else:
        embed.set_author(name="Система (автоматическое действие)", icon_url=bot.user.display_avatar.url if bot.user else None)

    if target is not None:
        embed.set_thumbnail(url=target.display_avatar.url)

    try:
        await channel.send(embed=embed)
    except disnake.Forbidden:
        pass


def _truncate(text: str, limit: int = 1000) -> str:
    if text is None:
        return "*(пусто)*"
    text = text.strip()
    if not text:
        return "*(пусто)*"
    return text if len(text) <= limit else text[:limit] + "…"


class Logs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ──────────────────────── НАСТРОЙКА ────────────────────────

    @commands.command(name="setlog")
    @commands.has_permissions(administrator=True)
    async def setlog(self, ctx: commands.Context, category: str, channel: disnake.TextChannel = None):
        """Привязать категорию логов к каналу: !setlog chat #чат"""
        category = category.lower().strip()
        if category not in CATEGORIES:
            valid = ", ".join(f"`{c}`" for c in CATEGORIES)
            return await ctx.send(embed=disnake.Embed(
                title="❌ Неверная категория",
                description=f"Доступные категории: {valid}",
                color=CLR_FAIL,
            ))

        target_channel = channel or ctx.channel
        await db.set_log_channel(ctx.guild.id, category, target_channel.id)

        emoji, label = CATEGORIES[category]
        await ctx.send(embed=disnake.Embed(
            title="✅ Категория логов настроена",
            description=f"{emoji} **{label}** → {target_channel.mention}",
            color=CLR_OK,
        ))

    @commands.command(name="logchannels")
    @commands.has_permissions(administrator=True)
    async def logchannels(self, ctx: commands.Context):
        """Показать текущую настройку всех категорий логов"""
        configured = await db.get_all_log_channels(ctx.guild.id)

        lines = []
        for key, (emoji, label) in CATEGORIES.items():
            channel_id = configured.get(key)
            status = f"<#{channel_id}>" if channel_id else "*не настроено*"
            lines.append(f"{emoji} **{label}** — {status}")

        await ctx.send(embed=disnake.Embed(
            title="📋 Настройка логов",
            description="\n".join(lines),
            color=CLR_LOG,
        ))

    @setlog.error
    @logchannels.error
    async def logs_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=disnake.Embed(title="⛔ Нет прав", description="Только для администраторов.", color=CLR_FAIL))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description="Укажи категорию: `!setlog <категория> [#канал]`", color=CLR_FAIL))
        else:
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_FAIL))

    # ──────────────────────── ЛОГИ ЧАТА ────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: disnake.Message):
        if message.author.bot or not message.guild:
            return

        actor = None
        try:
            async for entry in message.guild.audit_logs(limit=5, action=disnake.AuditLogAction.message_delete):
                if entry.target.id == message.author.id and entry.extra.channel.id == message.channel.id:
                    actor = entry.user
                    break
        except disnake.Forbidden:
            pass

        await log_action(
            self.bot, message.guild,
            category="chat",
            actor=actor,  # None если сам автор удалил своё сообщение (или бот не смог узнать)
            action="Сообщение удалено",
            details=(
                f"**Автор:** {message.author.mention} (`{message.author.id}`)\n"
                f"**Канал:** {message.channel.mention}\n"
                f"**Содержимое:**\n{_truncate(message.content)}"
            ),
            color=0xFF6B2E,
            target=message.author,
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: disnake.Message, after: disnake.Message):
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return  # редактирование embed/pin и т.п. без изменения текста — не логируем

        await log_action(
            self.bot, before.guild,
            category="chat",
            actor=before.author,  # сообщения редактирует только сам автор — это Discord-ограничение
            action="Сообщение отредактировано",
            details=(
                f"**Автор:** {before.author.mention} (`{before.author.id}`)\n"
                f"**Канал:** {before.channel.mention}\n"
                f"**Было:**\n{_truncate(before.content)}\n\n"
                f"**Стало:**\n{_truncate(after.content)}\n\n"
                f"[Перейти к сообщению]({after.jump_url})"
            ),
            color=0xFFAA00,
            target=before.author,
        )

    # ──────────────────────── ЛОГИ НИКНЕЙМОВ ────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: disnake.Member, after: disnake.Member):
        if before.nick == after.nick:
            return

        actor = None
        try:
            async for entry in after.guild.audit_logs(limit=5, action=disnake.AuditLogAction.member_update):
                if entry.target.id == after.id:
                    actor = entry.user
                    break
        except disnake.Forbidden:
            pass

        # если инициатор — сам юзер, показываем именно его, а не "Систему"
        if actor is None:
            actor = after

        await log_action(
            self.bot, after.guild,
            category="nicknames",
            actor=actor,
            action="Никнейм изменён",
            details=(
                f"**Пользователь:** {after.mention} (`{after.id}`)\n"
                f"**Было:** {before.nick or before.name}\n"
                f"**Стало:** {after.nick or after.name}"
            ),
            color=0x8B5CF6,
            target=after,
        )

    @commands.Cog.listener()
    async def on_user_update(self, before: disnake.User, after: disnake.User):
        """Смена глобального имени пользователя Discord (не серверного никнейма)."""
        if before.name == after.name and before.global_name == after.global_name:
            return

        # проходим по всем серверам, где бот видит этого юзера, и логируем в каждый
        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if member is None:
                continue

            await log_action(
                self.bot, guild,
                category="nicknames",
                actor=after,  # смену глобального имени/юзернейма инициирует только сам юзер
                action="Имя пользователя Discord изменено",
                details=(
                    f"**Пользователь:** {after.mention} (`{after.id}`)\n"
                    f"**Было:** {before.name}\n"
                    f"**Стало:** {after.name}"
                ),
                color=0x8B5CF6,
                target=after,
            )


def setup(bot: commands.Bot):
    bot.add_cog(Logs(bot))