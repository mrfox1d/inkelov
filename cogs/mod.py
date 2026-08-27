from datetime import timedelta
import disnake
from disnake.ext import commands
from db.interaction import Database
from cogs.logs import log_action
import asyncio

db = Database()

CLR_BAN = 0xFF2E2E
CLR_KICK = 0xFF6B2E
CLR_MUTE = 0xFFAA00
CLR_WARN = 0xFFD700
CLR_OK = 0x2EFF7A
CLR_INFO = 0x5865F2
CLR_CLEAR = 0x8B5CF6


def mod_embed(
    title: str,
    description: str,
    color: int,
    target: disnake.Member | disnake.User = None,
    mod: disnake.Member | disnake.User = None,
    fields: list[tuple] = None,
    footer: str = None,
) -> disnake.Embed:
    embed = disnake.Embed(title=title, description=description, color=color)
    embed.timestamp = disnake.utils.utcnow()

    if target and hasattr(target, "display_avatar"):
        embed.set_thumbnail(url=target.display_avatar.url)

    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)

    footer_text = footer or (f"Модератор: {mod}" if mod else "")
    footer_icon = mod.display_avatar.url if mod and hasattr(mod, "display_avatar") else None
    embed.set_footer(text=footer_text, icon_url=footer_icon)

    return embed


def dm_embed(title: str, description: str, color: int, guild: disnake.Guild) -> disnake.Embed:
    embed = disnake.Embed(title=title, description=description, color=color)
    embed.set_footer(text=f"Сервер: {guild.name}", icon_url=guild.icon.url if guild.icon else None)
    embed.timestamp = disnake.utils.utcnow()
    return embed


async def reply_embed(
    ctx_or_inter: commands.Context | disnake.Interaction,
    embed: disnake.Embed,
    ephemeral: bool = False,
):
    if isinstance(ctx_or_inter, disnake.Interaction):
        if ctx_or_inter.response.is_done():
            await ctx_or_inter.edit_original_response(embed=embed)
        else:
            await ctx_or_inter.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await ctx_or_inter.send(embed=embed)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _do_ban(
        self,
        target_ctx: commands.Context | disnake.Interaction,
        member: disnake.Member,
        reason: str,
        delete_days: int = 0,
    ):
        author = target_ctx.author
        guild = target_ctx.guild

        if member.top_role >= author.top_role and author.id != guild.owner_id:
            return await reply_embed(
                target_ctx,
                mod_embed("⛔ Отказано", "Ты не можешь забанить пользователя с равной или высшей ролью.", CLR_BAN),
                ephemeral=True,
            )

        if member.top_role >= guild.me.top_role:
            return await reply_embed(
                target_ctx,
                mod_embed("⛔ Ошибка", "У бота нет прав забанить этого пользователя (его роль выше роли бота).", CLR_BAN),
                ephemeral=True,
            )

        try:
            await member.send(embed=dm_embed("🔨 Вы забанены", f"Вас забанили на сервере **{guild.name}**.\n**Причина:** {reason}", CLR_BAN, guild))
        except disnake.Forbidden:
            pass

        await member.ban(reason=reason, delete_message_days=delete_days)

        await log_action(
            self.bot, guild,
            category="bans",
            actor=author,
            action="Пользователь забанен",
            details=f"**Цель:** {member.mention} (`{member.id}`)\n**Причина:** {reason}",
            color=CLR_BAN,
            target=member,
        )

        await reply_embed(
            target_ctx,
            mod_embed(
                "🔨 Пользователь забанен",
                f"{member.mention} получил бессрочный бан.",
                CLR_BAN,
                target=member,
                mod=author,
                fields=[
                    ("👤 Пользователь", f"{member} (`{member.id}`)", True),
                    ("🛡️ Модератор", f"{author.mention}", True),
                    ("📋 Причина", reason, False),
                ],
            ),
        )

    async def _do_unban(
        self,
        target_ctx: commands.Context | disnake.Interaction,
        user_id: str,
        reason: str,
    ):
        author = target_ctx.author
        guild = target_ctx.guild

        try:
            user = await self.bot.fetch_user(int(user_id))
            await guild.unban(user, reason=reason)
        except (ValueError, disnake.NotFound):
            return await reply_embed(
                target_ctx,
                mod_embed("❌ Ошибка", "Пользователь не найден или не в бане.", CLR_BAN),
                ephemeral=True,
            )

        await log_action(
            self.bot, guild,
            category="bans",
            actor=author,
            action="Пользователь разбанен",
            details=f"**Цель:** {user} (`{user.id}`)\n**Причина:** {reason}",
            color=CLR_OK,
            target=user,
        )

        await reply_embed(
            target_ctx,
            mod_embed(
                "✅ Пользователь разбанен",
                f"**{user}** (`{user.id}`) был разбанен.",
                CLR_OK,
                mod=author,
                fields=[("📋 Причина", reason, False)],
            ),
        )

    async def _do_kick(
        self,
        target_ctx: commands.Context | disnake.Interaction,
        member: disnake.Member,
        reason: str,
    ):
        author = target_ctx.author
        guild = target_ctx.guild

        if member.top_role >= author.top_role and author.id != guild.owner_id:
            return await reply_embed(
                target_ctx,
                mod_embed("⛔ Отказано", "Нельзя кикнуть пользователя с равной или высшей ролью.", CLR_KICK),
                ephemeral=True,
            )

        if member.top_role >= guild.me.top_role:
            return await reply_embed(
                target_ctx,
                mod_embed("⛔ Ошибка", "У бота нет прав кикнуть этого пользователя (его роль выше роли бота).", CLR_KICK),
                ephemeral=True,
            )

        try:
            await member.send(embed=dm_embed("👢 Вас кикнули", f"Вас выгнали с сервера **{guild.name}**.\n**Причина:** {reason}", CLR_KICK, guild))
        except disnake.Forbidden:
            pass

        await member.kick(reason=reason)

        await log_action(
            self.bot, guild,
            category="kicks",
            actor=author,
            action="Пользователь кикнут",
            details=f"**Цель:** {member.mention} (`{member.id}`)\n**Причина:** {reason}",
            color=CLR_KICK,
            target=member,
        )

        await reply_embed(
            target_ctx,
            mod_embed(
                "👢 Пользователь кикнут",
                f"{member.mention} был выгнан с сервера.",
                CLR_KICK,
                target=member,
                mod=author,
                fields=[
                    ("👤 Пользователь", f"{member} (`{member.id}`)", True),
                    ("🛡️ Модератор", f"{author.mention}", True),
                    ("📋 Причина", reason, False),
                ],
            ),
        )

    async def _do_mute(
        self,
        target_ctx: commands.Context | disnake.Interaction,
        member: disnake.Member,
        duration: int,
        reason: str,
    ):
        author = target_ctx.author
        guild = target_ctx.guild

        if member.top_role >= author.top_role and author.id != guild.owner_id:
            return await reply_embed(
                target_ctx,
                mod_embed("⛔ Отказано", "Нельзя замутить пользователя с равной или высшей ролью.", CLR_MUTE),
                ephemeral=True,
            )

        if member.top_role >= guild.me.top_role:
            return await reply_embed(
                target_ctx,
                mod_embed("⛔ Ошибка", "У бота нет прав замутить этого пользователя.", CLR_MUTE),
                ephemeral=True,
            )

        until = disnake.utils.utcnow() + timedelta(minutes=duration)
        await member.timeout(duration=timedelta(minutes=duration), reason=reason)

        hours, mins = divmod(duration, 60)
        duration_str = f"{hours}ч {mins}м" if hours else f"{mins}м"

        try:
            await member.send(embed=dm_embed("🔇 Вы замучены", f"Вас замутили на сервере **{guild.name}**.\n**Длительность:** {duration_str}\n**Причина:** {reason}", CLR_MUTE, guild))
        except disnake.Forbidden:
            pass

        await log_action(
            self.bot, guild,
            category="mutes",
            actor=author,
            action="Пользователь замучен",
            details=f"**Цель:** {member.mention} (`{member.id}`)\n**Длительность:** {duration_str}\n**Причина:** {reason}",
            color=CLR_MUTE,
            target=member,
        )

        await reply_embed(
            target_ctx,
            mod_embed(
                "🔇 Пользователь замучен",
                f"{member.mention} получил таймаут.",
                CLR_MUTE,
                target=member,
                mod=author,
                fields=[
                    ("👤 Пользователь", f"{member} (`{member.id}`)", True),
                    ("🛡️ Модератор", f"{author.mention}", True),
                    ("⏱️ Длительность", duration_str, True),
                    ("🕐 До", disnake.utils.format_dt(until, style="R"), True),
                    ("📋 Причина", reason, False),
                ],
            ),
        )

    async def _do_unmute(
        self,
        target_ctx: commands.Context | disnake.Interaction,
        member: disnake.Member,
    ):
        author = target_ctx.author

        if not member.current_timeout:
            return await reply_embed(
                target_ctx,
                mod_embed("❌ Ошибка", f"{member.mention} не замучен.", CLR_MUTE),
                ephemeral=True,
            )

        await member.timeout(duration=None)

        await log_action(
            self.bot, target_ctx.guild,
            category="mutes",
            actor=author,
            action="Мут снят",
            details=f"**Цель:** {member.mention} (`{member.id}`)",
            color=CLR_OK,
            target=member,
        )

        await reply_embed(
            target_ctx,
            mod_embed(
                "🔊 Мут снят",
                f"{member.mention} может снова писать.",
                CLR_OK,
                target=member,
                mod=author,
            ),
        )

    async def _do_warn(
        self,
        target_ctx: commands.Context | disnake.Interaction,
        member: disnake.Member,
        reason: str,
    ):
        author = target_ctx.author
        guild = target_ctx.guild

        total = await db.add_warning(member.id, author.id, reason)

        action_text = ""
        if total >= 5:
            await member.ban(reason=f"Авто-бан: {total} предупреждений")
            action_text = "\n\n⚙️ **Авто-бан:** достигнут лимит в 5 предупреждений."
            await log_action(
                self.bot, guild,
                category="bans",
                actor=None,  # автоматическое действие системы варнов, не прямой вызов модератора
                action="Авто-бан за предупреждения",
                details=f"**Цель:** {member.mention} (`{member.id}`)\n**Причина:** достигнут лимит в 5 предупреждений",
                color=CLR_BAN,
                target=member,
            )
        elif total >= 3:
            await member.timeout(
                duration=timedelta(hours=1), reason="Авто-мут: 3 предупреждения"
            )
            action_text = "\n\n⚙️ **Авто-мут:** выдан таймаут на 1 час."
            await log_action(
                self.bot, guild,
                category="mutes",
                actor=None,
                action="Авто-мут за предупреждения",
                details=f"**Цель:** {member.mention} (`{member.id}`)\n**Причина:** достигнуто 3 предупреждения\n**Длительность:** 1ч",
                color=CLR_MUTE,
                target=member,
            )

        await log_action(
            self.bot, guild,
            category="warns",
            actor=author,
            action="Выдано предупреждение",
            details=f"**Цель:** {member.mention} (`{member.id}`)\n**Причина:** {reason}\n**Всего предупреждений:** {total}/5",
            color=CLR_WARN,
            target=member,
        )

        try:
            await member.send(
                embed=dm_embed(
                    "⚠️ Вы получили предупреждение",
                    f"**Сервер:** {guild.name}\n**Причина:** {reason}\n**Предупреждений всего:** `{total}`{action_text}",
                    CLR_WARN,
                    guild,
                )
            )
        except disnake.Forbidden:
            pass

        warn_bar = "🟥" * total + "⬜" * max(0, 5 - total)

        await reply_embed(
            target_ctx,
            mod_embed(
                "⚠️ Предупреждение выдано",
                f"{member.mention} получил предупреждение.{action_text}",
                CLR_WARN,
                target=member,
                mod=author,
                fields=[
                    ("👤 Пользователь", f"{member} (`{member.id}`)", True),
                    ("🛡️ Модератор", f"{author.mention}", True),
                    ("📋 Причина", reason, False),
                    ("📊 Предупреждения", f"{warn_bar} `{total}/5`", False),
                ],
            ),
        )

        if total == 3:
            admin_alert = mod_embed(
                "🔔 Внимание администрации: 3/5 варнов",
                f"Пользователь {member.mention} достиг порога в **3/5** предупреждений.\n"
                f"⚙️ **Автоматическое действие:** Выдан таймаут на 1 час.",
                CLR_MUTE,
                target=member,
                mod=author,
            )
            await target_ctx.channel.send(embed=admin_alert)

        elif total >= 5:
            admin_alert = mod_embed(
                "🚨 Внимание администрации: 5/5 варнов",
                f"Пользователь {member.mention} достиг критического лимита **5/5** предупреждений.\n"
                f"⚙️ **Автоматическое действие:** Пользователь забанен на сервере.",
                CLR_BAN,
                target=member,
                mod=author,
            )
            await target_ctx.channel.send(embed=admin_alert)

    async def _do_warnings(
        self,
        target_ctx: commands.Context | disnake.Interaction,
        member: disnake.Member,
    ):
        guild = target_ctx.guild
        warns = await db.get_warnings(member.id)

        if not warns:
            return await reply_embed(
                target_ctx,
                mod_embed("📋 Предупреждения", f"У {member.mention} нет предупреждений. Чистый! ✅", CLR_OK, target=member),
            )

        warn_bar = "🟥" * len(warns) + "⬜" * max(0, 5 - len(warns))
        lines = []
        for i, w in enumerate(warns, 1):
            mod_obj = guild.get_member(w["mod_id"])
            mod_str = mod_obj.mention if mod_obj else f"`{w['mod_id']}`"
            date = w["created_at"][:10]
            lines.append(f"`{i}.` {w['reason'] or 'Причина не указана'} — {mod_str} • {date}")

        await reply_embed(
            target_ctx,
            mod_embed(
                f"📋 Предупреждения — {member}",
                "\n".join(lines),
                CLR_WARN,
                target=member,
                fields=[("📊 Прогресс", f"{warn_bar} `{len(warns)}/5`", False)],
            ),
        )

    async def _do_unwarn(
        self,
        target_ctx: commands.Context | disnake.Interaction,
        member: disnake.Member,
    ):
        author = target_ctx.author
        total = await db.remove_warning(member.id)

        await log_action(
            self.bot, target_ctx.guild,
            category="warns",
            actor=author,
            action="Предупреждение снято",
            details=f"**Цель:** {member.mention} (`{member.id}`)\n**Осталось:** {total}/5",
            color=CLR_OK,
            target=member,
        )

        await reply_embed(
            target_ctx,
            mod_embed(
                "✏️ Предупреждение снято",
                f"У {member.mention} снято последнее предупреждение.\nОсталось: `{total}`",
                CLR_OK,
                target=member,
                mod=author,
            ),
        )

    async def _do_clearwarns(
        self,
        target_ctx: commands.Context | disnake.Interaction,
        member: disnake.Member,
    ):
        author = target_ctx.author
        await db.clear_warnings(member.id)

        await log_action(
            self.bot, target_ctx.guild,
            category="warns",
            actor=author,
            action="Все предупреждения сброшены",
            details=f"**Цель:** {member.mention} (`{member.id}`)",
            color=CLR_OK,
            target=member,
        )

        await reply_embed(
            target_ctx,
            mod_embed(
                "🗑️ Предупреждения сброшены",
                f"Все предупреждения {member.mention} были удалены.",
                CLR_OK,
                target=member,
                mod=author,
            ),
        )

    async def _do_clear(
        self,
        target_ctx: commands.Context | disnake.Interaction,
        amount: int,
        member: disnake.Member = None,
    ):
        author = target_ctx.author

        if isinstance(target_ctx, disnake.Interaction):
            await target_ctx.response.defer(ephemeral=True)

        def check(msg: disnake.Message):
            return member is None or msg.author == member

        if isinstance(target_ctx, commands.Context):
            await target_ctx.message.delete()

        deleted = await target_ctx.channel.purge(limit=amount, check=check)

        msg = await reply_embed(
            target_ctx,
            mod_embed(
                "🧹 Очистка выполнена",
                f"Удалено **{len(deleted)}** сообщений" + (f" от {member.mention}" if member else "") + ".",
                CLR_CLEAR,
                mod=author,
            ),
        )

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def txt_ban(self, ctx: commands.Context, member: disnake.Member, delete_days: int = 0, *, reason: str = "Причина не указана"):
        await self._do_ban(ctx, member, reason, delete_days)

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def txt_unban(self, ctx: commands.Context, user_id: str, *, reason: str = "Причина не указана"):
        await self._do_unban(ctx, user_id, reason)

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def txt_kick(self, ctx: commands.Context, member: disnake.Member, *, reason: str = "Причина не указана"):
        await self._do_kick(ctx, member, reason)

    @commands.command(name="mute")
    @commands.has_permissions(moderate_members=True)
    async def txt_mute(self, ctx: commands.Context, member: disnake.Member, duration: int, *, reason: str = "Причина не указана"):
        await self._do_mute(ctx, member, duration, reason)

    @commands.command(name="unmute")
    @commands.has_permissions(moderate_members=True)
    async def txt_unmute(self, ctx: commands.Context, member: disnake.Member):
        await self._do_unmute(ctx, member)

    @commands.command(name="warn")
    @commands.has_permissions(moderate_members=True)
    async def txt_warn(self, ctx: commands.Context, member: disnake.Member, *, reason: str = "Причина не указана"):
        await self._do_warn(ctx, member, reason)

    @commands.command(name="warnings")
    @commands.has_permissions(moderate_members=True)
    async def txt_warnings(self, ctx: commands.Context, member: disnake.Member):
        await self._do_warnings(ctx, member)

    @commands.command(name="unwarn")
    @commands.has_permissions(moderate_members=True)
    async def txt_unwarn(self, ctx: commands.Context, member: disnake.Member):
        await self._do_unwarn(ctx, member)

    @commands.command(name="clearwarns")
    @commands.has_permissions(administrator=True)
    async def txt_clearwarns(self, ctx: commands.Context, member: disnake.Member):
        await self._do_clearwarns(ctx, member)

    @commands.command(name="clear")
    @commands.has_permissions(manage_messages=True)
    async def txt_clear(self, ctx: commands.Context, amount: int = 10, member: disnake.Member = None):
        await self._do_clear(ctx, amount, member)

    @commands.slash_command(name="ban", description="🔨 Забанить пользователя")
    @commands.has_permissions(ban_members=True)
    async def slash_ban(
        self,
        inter: disnake.AppCmdInter,
        member: disnake.Member = commands.Param(description="Кого банить"),
        reason: str = commands.Param(default="Причина не указана", description="Причина"),
        delete_days: int = commands.Param(default=0, ge=0, le=7, description="Удалить сообщения за N дней"),
    ):
        await self._do_ban(inter, member, reason, delete_days)

    @commands.slash_command(name="unban", description="✅ Разбанить пользователя")
    @commands.has_permissions(ban_members=True)
    async def slash_unban(
        self,
        inter: disnake.AppCmdInter,
        user_id: str = commands.Param(description="ID пользователя"),
        reason: str = commands.Param(default="Причина не указана", description="Причина"),
    ):
        await self._do_unban(inter, user_id, reason)

    @commands.slash_command(name="kick", description="👢 Кикнуть пользователя")
    @commands.has_permissions(kick_members=True)
    async def slash_kick(
        self,
        inter: disnake.AppCmdInter,
        member: disnake.Member = commands.Param(description="Кого кикнуть"),
        reason: str = commands.Param(default="Причина не указана", description="Причина"),
    ):
        await self._do_kick(inter, member, reason)

    @commands.slash_command(name="mute", description="🔇 Замутить пользователя (таймаут)")
    @commands.has_permissions(moderate_members=True)
    async def slash_mute(
        self,
        inter: disnake.AppCmdInter,
        member: disnake.Member = commands.Param(description="Кого мутить"),
        duration: int = commands.Param(description="Длительность в минутах", ge=1, le=40320),
        reason: str = commands.Param(default="Причина не указана", description="Причина"),
    ):
        await self._do_mute(inter, member, duration, reason)

    @commands.slash_command(name="unmute", description="🔊 Снять мут с пользователя")
    @commands.has_permissions(moderate_members=True)
    async def slash_unmute(
        self,
        inter: disnake.AppCmdInter,
        member: disnake.Member = commands.Param(description="Кому снять мут"),
    ):
        await self._do_unmute(inter, member)

    @commands.slash_command(name="warn", description="⚠️ Выдать предупреждение")
    @commands.has_permissions(moderate_members=True)
    async def slash_warn(
        self,
        inter: disnake.AppCmdInter,
        member: disnake.Member = commands.Param(description="Кому выдать"),
        reason: str = commands.Param(default="Причина не указана", description="Причина"),
    ):
        await self._do_warn(inter, member, reason)

    @commands.slash_command(name="warnings", description="📋 Список предупреждений пользователя")
    @commands.has_permissions(moderate_members=True)
    async def slash_warnings(
        self,
        inter: disnake.AppCmdInter,
        member: disnake.Member = commands.Param(description="Чьи предупреждения"),
    ):
        await self._do_warnings(inter, member)

    @commands.slash_command(name="unwarn", description="✏️ Снять последнее предупреждение")
    @commands.has_permissions(moderate_members=True)
    async def slash_unwarn(
        self,
        inter: disnake.AppCmdInter,
        member: disnake.Member = commands.Param(description="У кого снять"),
    ):
        await self._do_unwarn(inter, member)

    @commands.slash_command(name="clearwarns", description="🗑️ Сбросить все предупреждения")
    @commands.has_permissions(administrator=True)
    async def slash_clearwarns(
        self,
        inter: disnake.AppCmdInter,
        member: disnake.Member = commands.Param(description="У кого сбросить"),
    ):
        await self._do_clearwarns(inter, member)

    @commands.slash_command(name="clear", description="🧹 Очистить сообщения в канале")
    @commands.has_permissions(manage_messages=True)
    async def slash_clear(
        self,
        inter: disnake.AppCmdInter,
        amount: int = commands.Param(description="Сколько сообщений удалить", ge=1, le=100),
        member: disnake.Member = commands.Param(default=None, description="Только от этого пользователя"),
    ):
        await self._do_clear(inter, amount, member)

    async def cog_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await reply_embed(ctx, mod_embed("⛔ Нет прав", "У тебя недостаточно прав для этой команды.", CLR_BAN))
        elif isinstance(error, commands.MissingRequiredArgument):
            await reply_embed(ctx, mod_embed("❌ Ошибка аргументов", f"Не указан обязательный аргумент: `{error.param.name}`", CLR_BAN))
        else:
            await reply_embed(ctx, mod_embed("❌ Ошибка", f"```{error}```", CLR_BAN))

    @slash_ban.error
    @slash_unban.error
    @slash_kick.error
    @slash_mute.error
    @slash_unmute.error
    @slash_warn.error
    @slash_warnings.error
    @slash_unwarn.error
    @slash_clearwarns.error
    @slash_clear.error
    async def slash_error(self, inter: disnake.AppCmdInter, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await reply_embed(inter, mod_embed("⛔ Нет прав", "У тебя недостаточно прав для этой команды.", CLR_BAN), ephemeral=True)
        else:
            await reply_embed(inter, mod_embed("❌ Ошибка", f"```{error}```", CLR_BAN), ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(Moderation(bot))