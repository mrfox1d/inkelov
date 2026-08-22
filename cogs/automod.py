import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import disnake
from disnake.ext import commands
from db.interaction import Database

db = Database()

CLR_WARN = 0xFF2E2E
CLR_INFO = 0x00D9FF

# ────────────────────────── НАСТРОЙКИ ──────────────────────────

# Роль-ограничение, выдаётся при нарушениях (id роли @× Ограничение)
RESTRICTION_ROLE_ID = 1540306233402200106  # TODO: впиши реальный ID роли "Ограничение"

# Канал, где ссылки разрешены только админам (партнёры)
PARTNERS_CHANNEL_ID = 1540400000000000000  # TODO: впиши реальный ID канала #партнёры

# Мут на уровнях эскалации (в часах), индекс = уровень-1
MUTE_HOURS_BY_LEVEL = {1: 48, 2: 48, 3: 48}  # 2 дня на каждом уровне по ТЗ; поменяй если нужно другое время

# Разрешённые ссылки (по префиксу)
ALLOWED_URL_PREFIXES = [
    "https://tenor.com/",
    "https://c.tenor.com/",
    "https://imgur.com/",
    "https://media.giphy.com/",
    "https://cdn.discordapp.com/attachments/",
    "https://cdn.discordapp.com/stickers/",
    "https://cdn.discordapp.com/emojis/",
    "https://media.discordapp.net/attachments/",
    "https://discord.com/channels/",
    "https://www.youtube.com/",
    "https://youtube.com/",
    "https://open.spotify.com/track/",
    "https://juniper.bot/playlist/",
    "https://music.yandex.ru/",
    "https://shitcode.pw/",
]

URL_REGEX = re.compile(r"https?://\S+", re.IGNORECASE)

# ── Антиспам: повторяющийся текст ──
REPEAT_THRESHOLD = 10           # больше 10 одинаковых сообщений подряд/в окне
REPEAT_WINDOW_SECONDS = 60      # за это время
REPEAT_MUTE_HOURS = 24

# ── Антиспам: пинги ──
PING_THRESHOLD = 5              # больше 5 пингов
PING_WINDOW_SECONDS = 600       # за 10 минут
PING_MUTE_HOURS = 48


def is_url_allowed(url: str) -> bool:
    return any(url.lower().startswith(prefix) for prefix in ALLOWED_URL_PREFIXES)


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # user_id -> deque[(timestamp, message_content)]
        self.recent_messages: dict[int, deque] = defaultdict(lambda: deque(maxlen=REPEAT_THRESHOLD))
        # user_id -> deque[timestamps пингов]
        self.recent_pings: dict[int, deque] = defaultdict(deque)

    # ──────────────────────── ОБЩАЯ ЛОГИКА НАКАЗАНИЯ ────────────────────────

    async def _punish(self, message: disnake.Message, reason: str, mute_hours: int, bump_level: bool = True):
        member = message.author
        guild = message.guild

        try:
            await message.delete()
        except (disnake.NotFound, disnake.Forbidden):
            pass

        # мут через timeout
        try:
            await member.timeout(duration=timedelta(hours=mute_hours), reason=reason)
        except disnake.Forbidden:
            pass

        level_text = ""
        if bump_level:
            new_level = await db.bump_restriction_level(member.id)
            level_text = f"\n📊 Уровень ограничения: **{new_level}/3**"

            role = guild.get_role(RESTRICTION_ROLE_ID)
            if role:
                try:
                    await member.add_roles(role, reason=reason)
                except disnake.Forbidden:
                    pass

        embed = disnake.Embed(
            title="🛡️ АвтоМод: нарушение",
            description=(
                f"{member.mention} нарушил правила.\n\n"
                f"**Причина:** {reason}\n"
                f"**Мут:** {mute_hours}ч{level_text}"
            ),
            color=CLR_WARN,
        )
        embed.timestamp = disnake.utils.utcnow()

        try:
            await message.channel.send(embed=embed, delete_after=15)
        except disnake.Forbidden:
            pass

        try:
            await member.send(embed=disnake.Embed(
                title="⚠️ Ты нарушил правила сервера",
                description=f"**Причина:** {reason}\n**Мут:** {mute_hours}ч{level_text}",
                color=CLR_WARN,
            ))
        except disnake.Forbidden:
            pass

    # ──────────────────────── ON MESSAGE ────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.administrator:
            return  # админы не подпадают под автомод

        if await self._check_links(message):
            return
        if await self._check_repeated_text(message):
            return
        if await self._check_ping_spam(message):
            return

    # ──────────────────────── ПРОВЕРКА ССЫЛОК ────────────────────────

    async def _check_links(self, message: disnake.Message) -> bool:
        urls = URL_REGEX.findall(message.content)
        if not urls:
            return False

        # в канале партнёров ссылки разрешены (постить могут только админы —
        # но админы уже отфильтрованы выше, поэтому все ссылки в этом канале от
        # обычных юзеров всё равно запрещены)
        disallowed = [u for u in urls if not is_url_allowed(u)]
        if not disallowed:
            return False

        await self._punish(
            message,
            reason="Отправка запрещённой ссылки",
            mute_hours=48,
            bump_level=True,
        )
        return True

    # ──────────────────────── ПОВТОРЯЮЩИЙСЯ ТЕКСТ ────────────────────────

    async def _check_repeated_text(self, message: disnake.Message) -> bool:
        content = message.content.strip().lower()
        if not content:
            return False

        now = time.time()
        history = self.recent_messages[message.author.id]
        history.append((now, content))

        # оставляем только сообщения в пределах окна
        while history and now - history[0][0] > REPEAT_WINDOW_SECONDS:
            history.popleft()

        same_count = sum(1 for _, c in history if c == content)
        if same_count > REPEAT_THRESHOLD:
            history.clear()
            await self._punish(
                message,
                reason=f"Повторяющийся текст (более {REPEAT_THRESHOLD} раз)",
                mute_hours=REPEAT_MUTE_HOURS,
                bump_level=False,  # по ТЗ у этого нарушения нет привязки к роли ограничения
            )
            return True

        return False

    # ──────────────────────── СПАМ ПИНГАМИ ────────────────────────

    async def _check_ping_spam(self, message: disnake.Message) -> bool:
        ping_count = len(message.mentions) + len(message.role_mentions)
        if ping_count == 0:
            return False

        now = time.time()
        pings = self.recent_pings[message.author.id]
        for _ in range(ping_count):
            pings.append(now)

        while pings and now - pings[0] > PING_WINDOW_SECONDS:
            pings.popleft()

        if len(pings) > PING_THRESHOLD:
            pings.clear()
            await self._punish(
                message,
                reason=f"Спам пингами (более {PING_THRESHOLD} за {PING_WINDOW_SECONDS // 60} мин)",
                mute_hours=PING_MUTE_HOURS,
                bump_level=True,
            )
            return True

        return False

    # ──────────────────────── АДМИН-КОМАНДЫ ────────────────────────

    @commands.command(name="resetrestriction")
    @commands.has_permissions(administrator=True)
    async def resetrestriction(self, ctx: commands.Context, member: disnake.Member):
        """Сбросить уровень ограничения и снять роль"""
        await db.reset_restriction_level(member.id)
        role = ctx.guild.get_role(RESTRICTION_ROLE_ID)
        if role and role in member.roles:
            await member.remove_roles(role, reason=f"Сброшено {ctx.author}")
        await ctx.send(embed=disnake.Embed(
            title="✅ Уровень ограничения сброшен",
            description=f"{member.mention} снова чист.",
            color=CLR_INFO,
        ))

    @resetrestriction.error
    async def resetrestriction_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=disnake.Embed(title="⛔ Нет прав", description="Только для администраторов.", color=CLR_WARN))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description="Укажи пользователя: `!resetrestriction @юзер`", color=CLR_WARN))
        else:
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_WARN))


def setup(bot: commands.Bot):
    bot.add_cog(AutoMod(bot))