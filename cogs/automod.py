import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import disnake
from disnake.ext import commands
from cogs.logs import log_action

CLR_WARN = 0xFF2E2E
CLR_INFO = 0x00D9FF

# ────────────────────────── НАСТРОЙКИ ──────────────────────────

LINK_MUTE_HOURS = 48  # мут за отправку инвайта

# Запрещённые паттерны инвайтов (регулярки, регистронезависимо).
# Всё остальное (ссылки на профили Steam, YouTube, картинки и т.п.) разрешено.
BANNED_INVITE_PATTERNS = [
    re.compile(r"discord\.gg/\S+", re.IGNORECASE),
    re.compile(r"discord\.com/invite/\S+", re.IGNORECASE),
    re.compile(r"t\.me/[^/\s]+", re.IGNORECASE),  # t.me/username, но не t.me/ само по себе без имени
]

# ── Антиспам: повторяющийся текст ──
REPEAT_THRESHOLD = 10           # больше 10 одинаковых сообщений подряд/в окне
REPEAT_WINDOW_SECONDS = 60      # за это время
REPEAT_MUTE_HOURS = 24

# ── Антиспам: пинги ──
PING_THRESHOLD = 5              # больше 5 пингов
PING_WINDOW_SECONDS = 600       # за 10 минут
PING_MUTE_HOURS = 48


def find_banned_invite(text: str) -> str | None:
    """Возвращает найденный запрещённый инвайт (для лога), либо None."""
    for pattern in BANNED_INVITE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # user_id -> deque[(timestamp, message_content)]
        self.recent_messages: dict[int, deque] = defaultdict(lambda: deque(maxlen=REPEAT_THRESHOLD))
        # user_id -> deque[timestamps пингов]
        self.recent_pings: dict[int, deque] = defaultdict(deque)

    # ──────────────────────── ОБЩАЯ ЛОГИКА НАКАЗАНИЯ ────────────────────────

    async def _punish(self, message: disnake.Message, reason: str, mute_hours: int):
        member = message.author

        try:
            await message.delete()
        except (disnake.NotFound, disnake.Forbidden):
            pass

        try:
            await member.timeout(duration=timedelta(hours=mute_hours), reason=reason)
        except disnake.Forbidden:
            pass

        embed = disnake.Embed(
            title="🛡️ АвтоМод: нарушение",
            description=(
                f"{member.mention} нарушил правила.\n\n"
                f"**Причина:** {reason}\n"
                f"**Мут:** {mute_hours}ч"
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
                description=f"**Причина:** {reason}\n**Мут:** {mute_hours}ч",
                color=CLR_WARN,
            ))
        except disnake.Forbidden:
            pass

        await log_action(
            self.bot, message.guild,
            category="mutes",
            actor=None,  # автоматическое действие автомода, не решение конкретного модератора
            action="Автомод: мут выдан",
            details=f"**Цель:** {member.mention} (`{member.id}`)\n**Канал:** {message.channel.mention}\n**Причина:** {reason}\n**Длительность:** {mute_hours}ч",
            color=CLR_WARN,
            target=member,
        )

    # ──────────────────────── ON MESSAGE ────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.administrator:
            return  # админы не подпадают под автомод

        if await self._check_invites(message):
            return
        if await self._check_repeated_text(message):
            return
        if await self._check_ping_spam(message):
            return

    # ──────────────────────── ПРОВЕРКА ИНВАЙТОВ ────────────────────────

    async def _check_invites(self, message: disnake.Message) -> bool:
        found = find_banned_invite(message.content)
        if not found:
            return False

        await self._punish(
            message,
            reason=f"Отправка инвайта ({found})",
            mute_hours=LINK_MUTE_HOURS,
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

        while history and now - history[0][0] > REPEAT_WINDOW_SECONDS:
            history.popleft()

        same_count = sum(1 for _, c in history if c == content)
        if same_count > REPEAT_THRESHOLD:
            history.clear()
            await self._punish(
                message,
                reason=f"Повторяющийся текст (более {REPEAT_THRESHOLD} раз)",
                mute_hours=REPEAT_MUTE_HOURS,
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
            )
            return True

        return False


def setup(bot: commands.Bot):
    bot.add_cog(AutoMod(bot))