import time
from collections import defaultdict, deque

import disnake
from disnake.ext import commands
from db.interaction import Database

db = Database()

CLR_ALERT = 0xFF2E2E
CLR_INFO  = 0x00D9FF
CLR_OK    = 0x2EFF7A

LOG_CHANNEL_ID = 1540400000000000000  # TODO: впиши ID канала для логов antiraid (можно тот же, что в security.py)

# ────────────────────────── ПОРОГИ СРАБАТЫВАНИЯ ──────────────────────────
# формат: action_type -> (макс. действий, окно в секундах, наказание)
# punishment: "strip_roles" (снять все опасные роли) | "kick" | "ban"

THRESHOLDS = {
    "ban":               {"limit": 3,  "window": 30,  "punishment": "ban"},
    "kick":               {"limit": 5,  "window": 30,  "punishment": "ban"},
    "channel_delete":     {"limit": 3,  "window": 30,  "punishment": "ban"},
    "channel_create":     {"limit": 5,  "window": 30,  "punishment": "strip_roles"},
    "role_delete":        {"limit": 2,  "window": 30,  "punishment": "ban"},
    "role_create":        {"limit": 5,  "window": 30,  "punishment": "strip_roles"},
    "webhook_create":     {"limit": 3,  "window": 30,  "punishment": "strip_roles"},
    "member_prune":       {"limit": 1,  "window": 30,  "punishment": "ban"},
    "dangerous_perm_grant": {"limit": 1, "window": 10, "punishment": "ban"},  # выдача роли с administrator/ban_members и т.п.
}

# Права, выдача которых кому-либо мгновенно триггерит "dangerous_perm_grant"
DANGEROUS_PERMS = {
    "administrator", "ban_members", "kick_members", "manage_guild",
    "manage_roles", "manage_channels", "manage_webhooks", "mention_everyone",
}

ACTION_TYPE_MAP = {
    disnake.AuditLogAction.ban: "ban",
    disnake.AuditLogAction.kick: "kick",
    disnake.AuditLogAction.channel_delete: "channel_delete",
    disnake.AuditLogAction.channel_create: "channel_create",
    disnake.AuditLogAction.role_delete: "role_delete",
    disnake.AuditLogAction.role_create: "role_create",
    disnake.AuditLogAction.webhook_create: "webhook_create",
    disnake.AuditLogAction.member_prune: "member_prune",
}


class AntiRaid(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # (guild_id, actor_id, action_type) -> deque[timestamps]
        self.action_log: dict[tuple, deque] = defaultdict(deque)
        self._punished_recently: set[int] = set()  # чтобы не наказывать одного actor'а дважды подряд за один всплеск

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

    def _record_action(self, guild_id: int, actor_id: int, action_type: str, window: int) -> int:
        """Записывает действие и возвращает кол-во действий этого типа в окне."""
        key = (guild_id, actor_id, action_type)
        now = time.time()
        log = self.action_log[key]
        log.append(now)

        while log and now - log[0] > window:
            log.popleft()

        return len(log)

    async def _punish(self, guild: disnake.Guild, actor_id: int, action_type: str, count: int, punishment: str):
        if actor_id in self._punished_recently:
            return  # уже наказали за этот всплеск — не спамим повторными наказаниями
        self._punished_recently.add(actor_id)

        member = guild.get_member(actor_id)
        executed = "не найден на сервере"

        try:
            if punishment == "ban" and member:
                await guild.ban(member, reason=f"AntiRaid: {action_type} x{count}", delete_message_days=0)
                executed = "🔨 Забанен"
            elif punishment == "strip_roles" and member:
                roles_to_remove = [r for r in member.roles if r != guild.default_role]
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason=f"AntiRaid: {action_type} x{count}")
                executed = "🎭 Все роли сняты"
            elif punishment == "kick" and member:
                await member.kick(reason=f"AntiRaid: {action_type} x{count}")
                executed = "👢 Кикнут"
        except disnake.Forbidden:
            executed = "❌ Не удалось (недостаточно прав бота)"

        await db.log_antiraid_incident(guild.id, actor_id, action_type, count, executed)

        await self._log(guild, disnake.Embed(
            title="🚨 AntiRaid: обнаружена подозрительная активность!",
            description=(
                f"**Пользователь:** {member.mention if member else f'`{actor_id}`'}\n"
                f"**Действие:** `{action_type}` x**{count}** за короткое время\n"
                f"**Реакция:** {executed}"
            ),
            color=CLR_ALERT,
        ))

        # снятие флага через минуту, чтобы можно было снова реагировать при повторном инциденте
        async def _clear_flag():
            import asyncio
            await asyncio.sleep(60)
            self._punished_recently.discard(actor_id)

        self.bot.loop.create_task(_clear_flag())

    # ──────────────────────── ГЛАВНЫЙ СЛУШАТЕЛЬ ────────────────────────

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: disnake.AuditLogEntry):
        guild = entry.guild
        executor = entry.user

        if executor is None:
            return
        if await self._is_whitelisted(guild, executor.id):
            return

        # ── выдача опасных прав кому-либо (роль с administrator и т.п.) ──
        if entry.action in (disnake.AuditLogAction.role_update, disnake.AuditLogAction.role_create):
            for change in entry.changes:
                if change.key != "permissions":
                    continue
                new_perms = disnake.Permissions(int(change.new_value)) if change.new_value else disnake.Permissions.none()
                granted_dangerous = [p for p in DANGEROUS_PERMS if getattr(new_perms, p, False)]
                if granted_dangerous:
                    cfg = THRESHOLDS["dangerous_perm_grant"]
                    count = self._record_action(guild.id, executor.id, "dangerous_perm_grant", cfg["window"])
                    if count >= cfg["limit"]:
                        await self._punish(guild, executor.id, "dangerous_perm_grant", count, cfg["punishment"])
                    return

        # ── обычные пороговые действия ──
        action_type = ACTION_TYPE_MAP.get(entry.action)
        if action_type is None:
            return

        cfg = THRESHOLDS.get(action_type)
        if cfg is None:
            return

        count = self._record_action(guild.id, executor.id, action_type, cfg["window"])
        if count >= cfg["limit"]:
            await self._punish(guild, executor.id, action_type, count, cfg["punishment"])

    # ──────────────────────── АДМИН-КОМАНДЫ ────────────────────────

    @commands.command(name="raidlog")
    @commands.has_permissions(administrator=True)
    async def raidlog(self, ctx: commands.Context, limit: int = 10):
        """Показать последние инциденты antiraid-системы"""
        incidents = await db.get_recent_antiraid_incidents(ctx.guild.id, limit=limit)

        if not incidents:
            return await ctx.send(embed=disnake.Embed(title="📋 Инциденты AntiRaid", description="Инцидентов не зафиксировано.", color=CLR_INFO))

        lines = []
        for inc in incidents:
            member = ctx.guild.get_member(inc["actor_id"])
            who = member.mention if member else f"`{inc['actor_id']}`"
            lines.append(
                f"`{inc['created_at'][:16]}` — {who} → **{inc['action_type']}** x{inc['action_count']} → {inc['punishment']}"
            )

        await ctx.send(embed=disnake.Embed(
            title="📋 Последние инциденты AntiRaid",
            description="\n".join(lines),
            color=CLR_INFO,
        ))

    @raidlog.error
    async def raidlog_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=disnake.Embed(title="⛔ Нет прав", description="Только для администраторов.", color=CLR_ALERT))
        else:
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_ALERT))


def setup(bot: commands.Bot):
    bot.add_cog(AntiRaid(bot))