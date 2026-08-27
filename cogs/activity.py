import disnake
from disnake.ext import commands
from db.interaction import Database

db = Database()

CLR_LEVEL = 0xFFD700
CLR_INFO  = 0x00D9FF
CLR_FAIL  = 0xFF2E2E

# ────────────────────────── НАСТРОЙКИ ──────────────────────────

XP_PER_MESSAGE = 15          # XP за одно засчитанное сообщение
XP_MESSAGE_COOLDOWN = 10     # антиспам: не чаще раза в 10 сек

XP_PER_VOICE_MINUTE = 1      # XP за каждую полную минуту в войсе

# Каналы, где сообщения НЕ дают XP (например бот-спам, счётчики, тикеты)
XP_IGNORED_CHANNEL_IDS: set[int] = {
    1532336745453191238,  # канал считалки — иначе абуз через считалку
}

LEVEL_UP_ANNOUNCE_CHANNEL_ID = None  # None = левелап пишется в тот же канал, где было сообщение


def format_voice_time(seconds: int) -> str:
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    if hours:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"


def level_up_embed(member: disnake.Member, new_level: int) -> disnake.Embed:
    embed = disnake.Embed(
        title="🎉 Новый уровень!",
        description=f"{member.mention} достиг **{new_level}** уровня!",
        color=CLR_LEVEL,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    return embed


class Activity(commands.Cog):
    """
    Отслеживает активность пользователей (сообщения и время в войсе),
    начисляет XP/уровни и ведёт статистику для /profile и /leaderboard.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ──────────────────────── СООБЩЕНИЯ → XP ────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        if message.author.bot or not message.guild:
            return
        if message.channel.id in XP_IGNORED_CHANNEL_IDS:
            return
        if not message.content.strip() and not message.attachments:
            return  # пустые системные сообщения не считаем

        result = await db.register_message(
            message.author.id, XP_PER_MESSAGE, XP_MESSAGE_COOLDOWN
        )

        if result["leveled_up"]:
            target_channel = message.channel
            if LEVEL_UP_ANNOUNCE_CHANNEL_ID:
                announce_channel = message.guild.get_channel(LEVEL_UP_ANNOUNCE_CHANNEL_ID)
                if announce_channel:
                    target_channel = announce_channel

            try:
                await target_channel.send(embed=level_up_embed(message.author, result["level"]))
            except disnake.Forbidden:
                pass

    # ──────────────────────── ВОЙС → XP ────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: disnake.Member, before: disnake.VoiceState, after: disnake.VoiceState
    ):
        if member.bot:
            return

        was_in_voice = before.channel is not None
        is_in_voice = after.channel is not None

        # зашёл в войс (был не в войсе -> стал в войсе)
        if not was_in_voice and is_in_voice:
            await db.start_voice_session(member.id)
            return

        # вышел из войса (был в войсе -> стал не в войсе)
        if was_in_voice and not is_in_voice:
            result = await db.end_voice_session(member.id, XP_PER_VOICE_MINUTE)
            if result and result["leveled_up"]:
                channel = None
                if LEVEL_UP_ANNOUNCE_CHANNEL_ID:
                    channel = member.guild.get_channel(LEVEL_UP_ANNOUNCE_CHANNEL_ID)
                if channel:
                    try:
                        await channel.send(embed=level_up_embed(member, result["level"]))
                    except disnake.Forbidden:
                        pass
            return

        # переход между войс-каналами (был в войсе -> остался в войсе, но канал сменился)
        # сессию не рвём — время продолжает копиться от исходного voice_join_at

    # ──────────────────────── /profile ────────────────────────

    async def _do_profile(self, target_ctx, member: disnake.Member = None):
        author = target_ctx.author
        target = member or author

        user = await db.get_user(target.id)
        if not user:
            user = await db.ensure_user(target.id)

        next_level_xp = db.xp_for_level(user["level"])
        progress_pct = int((user["xp"] / next_level_xp) * 100) if next_level_xp else 0
        bar_filled = progress_pct // 10
        progress_bar = "🟩" * bar_filled + "⬜" * (10 - bar_filled)

        msg_rank = await db.get_rank(target.id, "message_count")
        voice_rank = await db.get_rank(target.id, "voice_seconds")
        bal_rank = await db.get_rank(target.id, "balance")
        total_users = await db.get_user_count()

        embed = disnake.Embed(
            title=f"👤 Профиль — {target.display_name}",
            color=CLR_INFO,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(
            name=f"📊 Уровень {user['level']}",
            value=f"{progress_bar} `{user['xp']}/{next_level_xp} XP`",
            inline=False,
        )
        embed.add_field(name="💬 Сообщений", value=f"{user['message_count']}\n`#{msg_rank}` из {total_users}", inline=True)
        embed.add_field(name="🎙️ Время в войсе", value=f"{format_voice_time(user['voice_seconds'])}\n`#{voice_rank}` из {total_users}", inline=True)
        embed.add_field(name="💰 Баланс", value=f"{user['balance'] + user['bank']:,}".replace(",", " ") + f" 🪙\n`#{bal_rank}` из {total_users}", inline=True)

        embed.set_footer(text=f"Запросил: {author}", icon_url=author.display_avatar.url)

        await self._reply(target_ctx, embed)

    async def _reply(self, ctx_or_inter, embed: disnake.Embed):
        if isinstance(ctx_or_inter, disnake.Interaction):
            await ctx_or_inter.response.send_message(embed=embed)
        else:
            await ctx_or_inter.send(embed=embed)

    @commands.command(name="profile", aliases=["rank", "balance", "bal"])
    async def txt_profile(self, ctx: commands.Context, member: disnake.Member = None):
        """Показать профиль активности (уровень, сообщения, войс, баланс)"""
        await self._do_profile(ctx, member)

    @commands.slash_command(name="profile", description="👤 Показать профиль активности")
    async def slash_profile(
        self, inter: disnake.AppCmdInter,
        member: disnake.Member = commands.Param(default=None, description="Чей профиль показать"),
    ):
        await self._do_profile(inter, member)

    # ──────────────────────── /activitytop ────────────────────────

    METRIC_LABELS = {
        "message_count": ("💬 Топ по сообщениям", lambda u: f"{u['message_count']} сообщ."),
        "voice_seconds": ("🎙️ Топ по времени в войсе", lambda u: format_voice_time(u["voice_seconds"])),
        "balance": ("💰 Топ по балансу", lambda u: f"{u['balance'] + u['bank']:,}".replace(",", " ") + " 🪙"),
    }

    async def _do_activitytop(self, target_ctx, metric: str):
        if metric not in self.METRIC_LABELS:
            return await self._reply(target_ctx, disnake.Embed(
                title="❌ Ошибка",
                description="Метрика должна быть одной из: `messages`, `voice`, `balance`.",
                color=CLR_FAIL,
            ))

        title, value_fn = self.METRIC_LABELS[metric]
        top = await db.get_leaderboard(metric, limit=10)

        if not top:
            return await self._reply(target_ctx, disnake.Embed(title=title, description="Пока нет данных.", color=CLR_INFO))

        guild = target_ctx.guild
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, row in enumerate(top):
            place = medals[i] if i < 3 else f"`#{i + 1}`"
            user = guild.get_member(row["user_id"])
            name = user.mention if user else f"`{row['user_id']}`"
            lines.append(f"{place} {name} — **{value_fn(row)}**")

        await self._reply(target_ctx, disnake.Embed(title=title, description="\n".join(lines), color=CLR_LEVEL))

    @commands.command(name="activitytop", aliases=["atop"])
    async def txt_activitytop(self, ctx: commands.Context, metric: str = "messages"):
        """Топ активности: !activitytop messages|voice|balance"""
        metric_map = {"messages": "message_count", "voice": "voice_seconds", "balance": "balance"}
        await self._do_activitytop(ctx, metric_map.get(metric, metric))

    @commands.slash_command(name="activitytop", description="🏆 Топ активности сервера")
    async def slash_activitytop(
        self, inter: disnake.AppCmdInter,
        metric: str = commands.Param(choices=["messages", "voice", "balance"], description="По какой метрике"),
    ):
        metric_map = {"messages": "message_count", "voice": "voice_seconds", "balance": "balance"}
        await self._do_activitytop(inter, metric_map.get(metric, metric))


def setup(bot: commands.Bot):
    bot.add_cog(Activity(bot))