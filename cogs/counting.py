import re
import random
import disnake
from disnake.ext import commands
from db.interaction import Database

db = Database()

COUNTING_CHANNEL_ID = 1532336745453191238

CLR_FAIL = 0xFF2E2E

# Фразы для "ты всё испортил" — рандомная, чтобы не приедалось
FAIL_PHRASES = [
    "{mention} ошибся с числом — подсчёт сбит на **{count}**.",
    "Ой! {mention} написал не то число, считалка сорвалась на **{count}**.",
    "{mention} перепутал порядок — подсчёт был на **{count}**, начинаем заново.",
    "{mention} отправил не **{expected}**, а что-то другое — подсчёт обнулён с **{count}**.",
]

NUMBER_REGEX = re.compile(r"^\s*(\d+)\s*$")


class Counting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await self._ensure_initialized()

    async def _ensure_initialized(self):
        """При самом первом запуске восстанавливает текущий счёт из истории канала."""
        state = await db.get_counting_state(COUNTING_CHANNEL_ID)
        if state and state["initialized"]:
            return  # уже инициализировано — больше историю не парсим

        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(COUNTING_CHANNEL_ID)
        if channel is None:
            print("[counting] Канал считалки не найден — инициализация отложена до следующего запуска.")
            return

        found_count = 0
        async for message in channel.history(limit=500):
            if message.author.bot:
                continue
            match = NUMBER_REGEX.match(message.content)
            if match:
                found_count = int(match.group(1))
                break  # history() идёт от новых к старым — первое найденное число самое свежее

        await db.init_counting_state(COUNTING_CHANNEL_ID, found_count)
        print(f"[counting] Инициализирован счёт из истории канала: {found_count}")

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        if message.channel.id != COUNTING_CHANNEL_ID:
            return
        if message.author.bot:
            return

        state = await db.get_counting_state(COUNTING_CHANNEL_ID)
        if state is None or not state["initialized"]:
            return  # ещё не инициализировано — пропускаем, чтобы не сбить восстановление

        current_count = state["current_count"]
        last_user_id = state["last_user_id"]
        expected = current_count + 1

        match = NUMBER_REGEX.match(message.content)

        # не число — просто игнорируем сообщение (не считается нарушением)
        if not match:
            return

        sent_number = int(match.group(1))

        # проверка: тот же юзер написал два раза подряд
        if last_user_id is not None and message.author.id == last_user_id:
            await self._fail(message, current_count, expected, own_turn_violation=True)
            return

        # проверка: правильное ли число
        if sent_number != expected:
            await self._fail(message, current_count, expected, own_turn_violation=False)
            return

        # всё верно — засчитываем
        try:
            await message.add_reaction("✅")
        except disnake.Forbidden:
            pass

        await db.set_counting_state(COUNTING_CHANNEL_ID, sent_number, message.author.id)

    async def _fail(self, message: disnake.Message, current_count: int, expected: int, own_turn_violation: bool):
        try:
            await message.add_reaction("❌")
        except disnake.Forbidden:
            pass

        if own_turn_violation:
            text = f"{message.author.mention}, стоп — нельзя писать два числа подряд! Дождись, пока кто-то другой продолжит. Счёт остаётся **{current_count}**, следующее число: **{expected}**."
        else:
            phrase = random.choice(FAIL_PHRASES).format(
                mention=message.author.mention,
                count=current_count,
                expected=expected,
            )
            text = f"{phrase}\n\n🔢 Подсчёт начинается заново с **1**."
            await db.reset_counting_state(COUNTING_CHANNEL_ID)

        await message.channel.send(text)

    # ──────────────────────── АДМИН-КОМАНДЫ ────────────────────────

    @commands.command(name="countreset")
    @commands.has_permissions(administrator=True)
    async def countreset(self, ctx: commands.Context, value: int = 0):
        """Принудительно установить счёт считалки на конкретное значение (по умолчанию 0)"""
        if ctx.channel.id != COUNTING_CHANNEL_ID:
            return await ctx.send(embed=disnake.Embed(
                title="❌ Неверный канал",
                description=f"Эта команда работает только в <#{COUNTING_CHANNEL_ID}>.",
                color=CLR_FAIL,
            ))

        await db.init_counting_state(COUNTING_CHANNEL_ID, value)
        await ctx.send(embed=disnake.Embed(
            title="🔢 Счёт установлен",
            description=f"Текущий счёт: **{value}**. Следующее число: **{value + 1}**.",
            color=0x2EFF7A,
        ))

    @countreset.error
    async def countreset_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=disnake.Embed(title="⛔ Нет прав", description="Только для администраторов.", color=CLR_FAIL))
        else:
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_FAIL))


def setup(bot: commands.Bot):
    bot.add_cog(Counting(bot))