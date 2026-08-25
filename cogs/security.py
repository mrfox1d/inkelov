import disnake
from disnake.ext import commands
from db.interaction import Database

db = Database()

CLR_ALERT = 0xFF2E2E
CLR_INFO  = 0x00D9FF
CLR_OK    = 0x2EFF7A

LOG_CHANNEL_ID = 1541724061384708127

# Твой ID добавляется в вайтлист автоматически при первом старте (см. cog_load)
HARDCODED_WHITELIST_IDS = {
    1172512889731555351,
}


class Security(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # гарантируем, что хардкодный вайтлист всегда есть в БД (на случай чистой установки)
        for uid in HARDCODED_WHITELIST_IDS:
            await db.add_to_security_whitelist(uid, added_by=self.bot.user.id if self.bot.user else 0)

    async def _is_whitelisted(self, guild: disnake.Guild, user_id: int) -> bool:
        if user_id == guild.owner_id:
            return True
        if self.bot.user and user_id == self.bot.user.id:
            return True
        return await db.is_security_whitelisted(user_id)

    async def _log(self, guild: disnake.Guild, embed: disnake.Embed):
        channel = guild.get_channel(LOG_CHANNEL_ID)
        if channel:
            try:
                await channel.send(embed=embed)
            except disnake.Forbidden:
                pass

    # ──────────────────────── ОТКАТ ВЫДАЧИ РОЛЕЙ ────────────────────────

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: disnake.AuditLogEntry):
        if entry.action != disnake.AuditLogActionType.member_role_update:
            return

        guild = entry.guild
        executor = entry.user
        target = entry.target

        if executor is None or target is None:
            return

        if await self._is_whitelisted(guild, executor.id):
            return

        added_roles = []
        for change in entry.changes:
            if change.key == "$add":
                added_roles = change.new_value or []

        if not added_roles:
            return  # это было снятие ролей, а не выдача — не откатываем

        member = guild.get_member(target.id) if isinstance(target, (disnake.User, disnake.Member)) else None
        if member is None:
            try:
                member = await guild.fetch_member(target.id)
            except disnake.NotFound:
                return

        roles_to_remove = []
        for role_data in added_roles:
            role = guild.get_role(role_data.id)
            if role and role in member.roles:
                roles_to_remove.append(role)

        if not roles_to_remove:
            return

        try:
            await member.remove_roles(*roles_to_remove, reason=f"Security: откат несанкционированной выдачи роли ({executor})")
        except disnake.Forbidden:
            await self._log(guild, disnake.Embed(
                title="❌ Не удалось откатить роль",
                description=(
                    f"**Кто выдал:** {executor.mention} (`{executor.id}`)\n"
                    f"**Кому:** {member.mention} (`{member.id}`)\n"
                    f"**Роли:** {', '.join(r.mention for r in roles_to_remove)}\n\n"
                    f"У бота недостаточно прав/позиции роли, чтобы откатить."
                ),
                color=CLR_ALERT,
            ))
            return

        await self._log(guild, disnake.Embed(
            title="🛡️ Security: откат роли",
            description=(
                f"**Кто выдал (не в вайтлисте):** {executor.mention} (`{executor.id}`)\n"
                f"**Кому:** {member.mention} (`{member.id}`)\n"
                f"**Откачено:** {', '.join(r.mention for r in roles_to_remove)}"
            ),
            color=CLR_ALERT,
        ))

    # ──────────────────────── АДМИН-КОМАНДЫ ────────────────────────

    @commands.command(name="secwhitelist", aliases=["secwl"])
    @commands.has_permissions(administrator=True)
    async def secwhitelist(self, ctx: commands.Context):
        """Показать список пользователей в вайтлисте security-системы"""
        entries = await db.get_security_whitelist()

        lines = []
        owner = ctx.guild.owner
        if owner:
            lines.append(f"👑 {owner.mention} (владелец сервера, всегда в ВЛ)")

        for e in entries:
            member = ctx.guild.get_member(e["user_id"])
            mention_or_id = member.mention if member else f"`{e['user_id']}`"
            lines.append(f"✅ {mention_or_id} — добавлен `{e['added_at'][:10]}`")

        await ctx.send(embed=disnake.Embed(
            title="🛡️ Вайтлист Security",
            description="\n".join(lines) if lines else "Пусто",
            color=CLR_INFO,
        ))

    @commands.command(name="secwladd")
    @commands.has_permissions(administrator=True)
    async def secwladd(self, ctx: commands.Context, member: disnake.Member):
        """Добавить пользователя в вайтлист security-системы"""
        added = await db.add_to_security_whitelist(member.id, added_by=ctx.author.id)
        if added:
            await ctx.send(embed=disnake.Embed(
                title="✅ Добавлен в вайтлист",
                description=f"{member.mention} теперь может свободно выдавать роли.",
                color=CLR_OK,
            ))
        else:
            await ctx.send(embed=disnake.Embed(
                title="⚠️ Уже в вайтлисте",
                description=f"{member.mention} уже в вайтлисте security-системы.",
                color=CLR_INFO,
            ))

    @commands.command(name="secwlremove", aliases=["secwlrm"])
    @commands.has_permissions(administrator=True)
    async def secwlremove(self, ctx: commands.Context, member: disnake.Member):
        """Убрать пользователя из вайтлиста security-системы"""
        if member.id == ctx.guild.owner_id:
            return await ctx.send(embed=disnake.Embed(
                title="❌ Ошибка",
                description="Владелец сервера не может быть удалён из вайтлиста.",
                color=CLR_ALERT,
            ))

        removed = await db.remove_from_security_whitelist(member.id)
        if removed:
            await ctx.send(embed=disnake.Embed(
                title="✅ Удалён из вайтлиста",
                description=f"{member.mention} больше не в вайтлисте — его выдачи ролей теперь будут откатываться.",
                color=CLR_OK,
            ))
        else:
            await ctx.send(embed=disnake.Embed(
                title="⚠️ Не найден",
                description=f"{member.mention} не был в вайтлисте.",
                color=CLR_INFO,
            ))

    @secwhitelist.error
    @secwladd.error
    @secwlremove.error
    async def security_cmd_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=disnake.Embed(title="⛔ Нет прав", description="Только для администраторов.", color=CLR_ALERT))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description="Укажи пользователя.", color=CLR_ALERT))
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description="Пользователь не найден.", color=CLR_ALERT))
        else:
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_ALERT))


def setup(bot: commands.Bot):
    bot.add_cog(Security(bot))