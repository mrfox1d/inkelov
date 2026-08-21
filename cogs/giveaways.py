import asyncio
import random
from datetime import datetime, timedelta

import disnake
from disnake.ext import commands, tasks
from db.interaction import Database

db = Database()

CLR_GW      = 0xFFD700
CLR_END     = 0x8B5CF6
CLR_FAIL    = 0xFF2E2E
CLR_OK      = 0x2EFF7A
CLR_INFO    = 0x00D9FF

GIVEAWAY_EMOJI = "🎉"


# ─────────────────────────── TIME PARSING ──────────────────────────

def parse_duration(text: str) -> timedelta | None:
    """Парсит строки вида '10m', '2h', '1d', '30s', '1d12h' в timedelta."""
    units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    total = timedelta()
    num = ""
    found = False

    for ch in text.strip().lower():
        if ch.isdigit():
            num += ch
        elif ch in units and num:
            total += timedelta(**{units[ch]: int(num)})
            num = ""
            found = True
        else:
            return None

    return total if found else None


def format_timedelta(td: timedelta) -> str:
    total = int(td.total_seconds())
    if total <= 0:
        return "уже завершается"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)

    parts = []
    if days: parts.append(f"{days}д")
    if hours: parts.append(f"{hours}ч")
    if minutes: parts.append(f"{minutes}м")
    if not parts: parts.append(f"{seconds}с")
    return " ".join(parts)


# ──────────────────────────── EMBEDS ────────────────────────────────

def giveaway_embed(gw: dict, entry_count: int, ended: bool = False) -> disnake.Embed:
    ends_at = datetime.fromisoformat(gw["ends_at"])

    embed = disnake.Embed(
        title=f"🎉 {gw['prize']}",
        color=CLR_END if ended else CLR_GW,
    )

    desc_lines = []
    if ended:
        desc_lines.append("**Розыгрыш завершён!**")
    else:
        desc_lines.append(f"Нажми на {GIVEAWAY_EMOJI}, чтобы участвовать!")

    desc_lines.append(f"⏰ Окончание: {disnake.utils.format_dt(ends_at, style='R')} ({disnake.utils.format_dt(ends_at, style='f')})")
    desc_lines.append(f"🏆 Победителей: **{gw['winners_count']}**")
    desc_lines.append(f"👑 Организатор: <@{gw['host_id']}>")
    desc_lines.append(f"👥 Участников: **{entry_count}**")

    if gw["min_role_id"]:
        desc_lines.append(f"🔒 Требуется роль: <@&{gw['min_role_id']}>")
    if gw["min_level"] and gw["min_level"] > 0:
        desc_lines.append(f"📊 Требуемый уровень: **{gw['min_level']}**")

    embed.description = "\n".join(desc_lines)
    embed.set_footer(text=f"ID розыгрыша: {gw['giveaway_id']}")
    return embed


def winners_announce_embed(gw: dict, winner_ids: list[int]) -> disnake.Embed:
    if not winner_ids:
        return disnake.Embed(
            title="🎉 Розыгрыш завершён",
            description=f"**Приз:** {gw['prize']}\n\nНикто не участвовал — победитель не выбран. 😔",
            color=CLR_END,
        )

    mentions = ", ".join(f"<@{uid}>" for uid in winner_ids)
    embed = disnake.Embed(
        title="🎉 Розыгрыш завершён!",
        description=(
            f"**Приз:** {gw['prize']}\n\n"
            f"🏆 Победител{'ь' if len(winner_ids) == 1 else 'и'}: {mentions}\n\n"
            f"Поздравляем! Свяжитесь с <@{gw['host_id']}> для получения приза."
        ),
        color=CLR_GW,
    )
    embed.set_footer(text=f"ID розыгрыша: {gw['giveaway_id']}")
    return embed


# ──────────────────────────── VIEW ──────────────────────────────────

class GiveawayView(disnake.ui.View):
    """Постоянная view с кнопкой участия. custom_id хранит giveaway_id, поэтому работает после рестарта."""

    def __init__(self, giveaway_id: int = 0):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        # переопределяем custom_id кнопки под конкретный розыгрыш
        self.children[0].custom_id = f"giveaway:join:{giveaway_id}"

    @disnake.ui.button(label="Участвовать", emoji="🎉", style=disnake.ButtonStyle.green, custom_id="giveaway:join:0")
    async def join(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        giveaway_id = int(button.custom_id.split(":")[-1])
        gw = await db.get_giveaway(giveaway_id)

        if not gw or gw["status"] != "active":
            return await inter.response.send_message(
                embed=disnake.Embed(title="❌ Розыгрыш завершён", description="Этот розыгрыш больше не активен.", color=CLR_FAIL),
                ephemeral=True,
            )

        # проверка требований
        if gw["min_role_id"]:
            role = inter.guild.get_role(gw["min_role_id"])
            if role and role not in inter.author.roles:
                return await inter.response.send_message(
                    embed=disnake.Embed(
                        title="🔒 Недостаточно прав",
                        description=f"Для участия нужна роль {role.mention}.",
                        color=CLR_FAIL,
                    ),
                    ephemeral=True,
                )

        if gw["min_level"] and gw["min_level"] > 0:
            user = await db.ensure_user(inter.author.id)
            if user["level"] < gw["min_level"]:
                return await inter.response.send_message(
                    embed=disnake.Embed(
                        title="🔒 Недостаточный уровень",
                        description=f"Требуется уровень **{gw['min_level']}**, у тебя **{user['level']}**.",
                        color=CLR_FAIL,
                    ),
                    ephemeral=True,
                )

        # тоггл участия: повторный клик снимает участие
        already_in = await db.is_entered(giveaway_id, inter.author.id)

        if already_in:
            await db.remove_giveaway_entry(giveaway_id, inter.author.id)
            response_embed = disnake.Embed(
                title="👋 Участие отменено",
                description="Ты больше не участвуешь в этом розыгрыше.",
                color=CLR_INFO,
            )
        else:
            await db.add_giveaway_entry(giveaway_id, inter.author.id)
            response_embed = disnake.Embed(
                title="🎉 Ты участвуешь!",
                description="Удачи в розыгрыше!",
                color=CLR_OK,
            )

        await inter.response.send_message(embed=response_embed, ephemeral=True)

        # обновляем счётчик участников в основном сообщении
        entry_count = await db.get_giveaway_entry_count(giveaway_id)
        await inter.message.edit(embed=giveaway_embed(gw, entry_count))


# ──────────────────────────── COG ────────────────────────────────────

class Giveaways(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pending_tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self):
        # регистрируем "пустую" persistent view — фактические клики будут распознаны
        # по custom_id, но View должна быть добавлена хотя бы раз с той же схемой custom_id.
        self.bot.add_view(GiveawayView(0))
        await self._restore_giveaways()

    async def _restore_giveaways(self):
        """После рестарта бота — досчитать оставшееся время для активных розыгрышей."""
        active = await db.get_active_giveaways()
        for gw in active:
            ends_at = datetime.fromisoformat(gw["ends_at"])
            delay = (ends_at - datetime.utcnow()).total_seconds()
            self._schedule_end(gw["giveaway_id"], max(delay, 0))

    def _schedule_end(self, giveaway_id: int, delay_seconds: float):
        async def runner():
            await asyncio.sleep(delay_seconds)
            await self._finish_giveaway(giveaway_id)
            self.pending_tasks.pop(giveaway_id, None)

        task = asyncio.create_task(runner())
        self.pending_tasks[giveaway_id] = task

    async def _finish_giveaway(self, giveaway_id: int, is_reroll: bool = False):
        gw = await db.get_giveaway(giveaway_id)
        if not gw:
            return
        if gw["status"] != "active" and not is_reroll:
            return

        guild = self.bot.get_guild(gw["guild_id"])
        if not guild:
            return
        channel = guild.get_channel(gw["channel_id"])
        if not channel:
            return

        entries = await db.get_giveaway_entries(giveaway_id)
        # фильтруем на случай если юзер вышел с сервера
        valid_entries = [uid for uid in entries if guild.get_member(uid)]

        winners_count = min(gw["winners_count"], len(valid_entries))
        winners = random.sample(valid_entries, winners_count) if winners_count > 0 else []

        if not is_reroll:
            await db.set_giveaway_status(giveaway_id, "ended")
            try:
                message = await channel.fetch_message(gw["message_id"])
                entry_count = await db.get_giveaway_entry_count(giveaway_id)
                view = GiveawayView(giveaway_id)
                for child in view.children:
                    child.disabled = True
                await message.edit(embed=giveaway_embed(gw, entry_count, ended=True), view=view)
            except (disnake.NotFound, disnake.Forbidden):
                pass

        await channel.send(
            content=" ".join(f"<@{uid}>" for uid in winners) if winners else None,
            embed=winners_announce_embed(gw, winners),
        )

    # ──────────────────── SHARED LOGIC ────────────────────

    async def _do_gstart(
        self, ctx_or_inter, duration_str: str, winners_count: int, prize: str,
        min_role: disnake.Role = None, min_level: int = 0,
    ):
        guild = ctx_or_inter.guild
        channel = ctx_or_inter.channel
        author = ctx_or_inter.author

        duration = parse_duration(duration_str)
        if not duration:
            embed = disnake.Embed(
                title="❌ Неверный формат времени",
                description="Используй формат вроде `10m`, `2h`, `1d`, `1d12h`.",
                color=CLR_FAIL,
            )
            if isinstance(ctx_or_inter, disnake.Interaction):
                return await ctx_or_inter.response.send_message(embed=embed, ephemeral=True)
            return await ctx_or_inter.send(embed=embed)

        if winners_count < 1:
            embed = disnake.Embed(title="❌ Ошибка", description="Количество победителей должно быть не меньше 1.", color=CLR_FAIL)
            if isinstance(ctx_or_inter, disnake.Interaction):
                return await ctx_or_inter.response.send_message(embed=embed, ephemeral=True)
            return await ctx_or_inter.send(embed=embed)

        ends_at = datetime.utcnow() + duration

        # временный embed, реальный ID розыгрыша впишем после вставки в БД
        placeholder = disnake.Embed(title=f"🎉 {prize}", description="Создание розыгрыша...", color=CLR_GW)

        if isinstance(ctx_or_inter, disnake.Interaction):
            await ctx_or_inter.response.send_message(embed=placeholder)
            message = await ctx_or_inter.original_message()
        else:
            message = await ctx_or_inter.send(embed=placeholder)

        giveaway_id = await db.create_giveaway(
            guild_id=guild.id,
            channel_id=channel.id,
            message_id=message.id,
            host_id=author.id,
            prize=prize,
            winners_count=winners_count,
            ends_at=ends_at.isoformat(),
            min_role_id=min_role.id if min_role else None,
            min_level=min_level,
        )

        gw = await db.get_giveaway(giveaway_id)
        view = GiveawayView(giveaway_id)
        await message.edit(embed=giveaway_embed(gw, 0), view=view)

        self._schedule_end(giveaway_id, duration.total_seconds())

    async def _do_gend(self, ctx_or_inter, giveaway_id: int):
        gw = await db.get_giveaway(giveaway_id)
        if not gw or gw["status"] != "active":
            embed = disnake.Embed(title="❌ Розыгрыш не найден", description="Активный розыгрыш с таким ID не найден.", color=CLR_FAIL)
        else:
            task = self.pending_tasks.pop(giveaway_id, None)
            if task:
                task.cancel()
            await self._finish_giveaway(giveaway_id)
            embed = disnake.Embed(title="✅ Розыгрыш завершён досрочно", description=f"ID: `{giveaway_id}`", color=CLR_OK)

        if isinstance(ctx_or_inter, disnake.Interaction):
            await ctx_or_inter.response.send_message(embed=embed, ephemeral=True)
        else:
            await ctx_or_inter.send(embed=embed)

    async def _do_greroll(self, ctx_or_inter, giveaway_id: int):
        gw = await db.get_giveaway(giveaway_id)
        if not gw or gw["status"] != "ended":
            embed = disnake.Embed(
                title="❌ Ошибка",
                description="Реролл возможен только для уже завершённого розыгрыша.",
                color=CLR_FAIL,
            )
        else:
            await self._finish_giveaway(giveaway_id, is_reroll=True)
            embed = disnake.Embed(title="🔄 Победители перевыбраны", description=f"ID: `{giveaway_id}`", color=CLR_OK)

        if isinstance(ctx_or_inter, disnake.Interaction):
            await ctx_or_inter.response.send_message(embed=embed, ephemeral=True)
        else:
            await ctx_or_inter.send(embed=embed)

    async def _do_gcancel(self, ctx_or_inter, giveaway_id: int):
        gw = await db.get_giveaway(giveaway_id)
        if not gw or gw["status"] != "active":
            embed = disnake.Embed(title="❌ Розыгрыш не найден", description="Активный розыгрыш с таким ID не найден.", color=CLR_FAIL)
        else:
            task = self.pending_tasks.pop(giveaway_id, None)
            if task:
                task.cancel()
            await db.set_giveaway_status(giveaway_id, "cancelled")

            guild = self.bot.get_guild(gw["guild_id"])
            channel = guild.get_channel(gw["channel_id"]) if guild else None
            if channel:
                try:
                    message = await channel.fetch_message(gw["message_id"])
                    cancelled_embed = disnake.Embed(
                        title=f"🚫 Розыгрыш отменён",
                        description=f"**{gw['prize']}**\n\nЭтот розыгрыш был отменён организатором.",
                        color=CLR_FAIL,
                    )
                    view = GiveawayView(giveaway_id)
                    for child in view.children:
                        child.disabled = True
                    await message.edit(embed=cancelled_embed, view=view)
                except (disnake.NotFound, disnake.Forbidden):
                    pass

            embed = disnake.Embed(title="🚫 Розыгрыш отменён", description=f"ID: `{giveaway_id}`", color=CLR_OK)

        if isinstance(ctx_or_inter, disnake.Interaction):
            await ctx_or_inter.response.send_message(embed=embed, ephemeral=True)
        else:
            await ctx_or_inter.send(embed=embed)

    async def _do_glist(self, ctx_or_inter):
        active = await db.get_active_giveaways()
        guild_active = [g for g in active if g["guild_id"] == ctx_or_inter.guild.id]

        if not guild_active:
            embed = disnake.Embed(title="📋 Активные розыгрыши", description="Сейчас нет активных розыгрышей.", color=CLR_INFO)
        else:
            lines = []
            for gw in guild_active:
                ends_at = datetime.fromisoformat(gw["ends_at"])
                count = await db.get_giveaway_entry_count(gw["giveaway_id"])
                lines.append(
                    f"`#{gw['giveaway_id']}` **{gw['prize']}** — {disnake.utils.format_dt(ends_at, style='R')} • 👥 {count}"
                )
            embed = disnake.Embed(title="📋 Активные розыгрыши", description="\n".join(lines), color=CLR_INFO)

        if isinstance(ctx_or_inter, disnake.Interaction):
            await ctx_or_inter.response.send_message(embed=embed)
        else:
            await ctx_or_inter.send(embed=embed)

    # ──────────────────── TEXT COMMANDS ────────────────────

    @commands.command(name="gstart")
    @commands.has_permissions(administrator=True)
    async def txt_gstart(self, ctx: commands.Context, duration: str, winners_count: int, *, prize: str):
        """Запустить розыгрыш: !gstart 1h 1 Nitro Boost"""
        await self._do_gstart(ctx, duration, winners_count, prize)

    @commands.command(name="gend")
    @commands.has_permissions(administrator=True)
    async def txt_gend(self, ctx: commands.Context, giveaway_id: int):
        """Завершить розыгрыш досрочно"""
        await self._do_gend(ctx, giveaway_id)

    @commands.command(name="greroll")
    @commands.has_permissions(administrator=True)
    async def txt_greroll(self, ctx: commands.Context, giveaway_id: int):
        """Перевыбрать победителей завершённого розыгрыша"""
        await self._do_greroll(ctx, giveaway_id)

    @commands.command(name="gcancel")
    @commands.has_permissions(administrator=True)
    async def txt_gcancel(self, ctx: commands.Context, giveaway_id: int):
        """Отменить активный розыгрыш без выбора победителей"""
        await self._do_gcancel(ctx, giveaway_id)

    @commands.command(name="glist")
    async def txt_glist(self, ctx: commands.Context):
        """Список активных розыгрышей на сервере"""
        await self._do_glist(ctx)

    # ──────────────────── SLASH COMMANDS ────────────────────

    @commands.slash_command(name="gstart", description="🎉 [Admin] Запустить розыгрыш")
    @commands.has_permissions(administrator=True)
    async def slash_gstart(
        self, inter: disnake.AppCmdInter,
        duration: str = commands.Param(description="Длительность: 10m, 2h, 1d, 1d12h"),
        winners_count: int = commands.Param(description="Количество победителей", ge=1),
        prize: str = commands.Param(description="Приз"),
        min_role: disnake.Role = commands.Param(default=None, description="Обязательная роль для участия"),
        min_level: int = commands.Param(default=0, description="Минимальный уровень для участия", ge=0),
    ):
        await self._do_gstart(inter, duration, winners_count, prize, min_role, min_level)

    @commands.slash_command(name="gend", description="🎉 [Admin] Завершить розыгрыш досрочно")
    @commands.has_permissions(administrator=True)
    async def slash_gend(self, inter: disnake.AppCmdInter, giveaway_id: int = commands.Param(description="ID розыгрыша")):
        await self._do_gend(inter, giveaway_id)

    @commands.slash_command(name="greroll", description="🔄 [Admin] Перевыбрать победителей")
    @commands.has_permissions(administrator=True)
    async def slash_greroll(self, inter: disnake.AppCmdInter, giveaway_id: int = commands.Param(description="ID розыгрыша")):
        await self._do_greroll(inter, giveaway_id)

    @commands.slash_command(name="gcancel", description="🚫 [Admin] Отменить розыгрыш")
    @commands.has_permissions(administrator=True)
    async def slash_gcancel(self, inter: disnake.AppCmdInter, giveaway_id: int = commands.Param(description="ID розыгрыша")):
        await self._do_gcancel(inter, giveaway_id)

    @commands.slash_command(name="glist", description="📋 Список активных розыгрышей")
    async def slash_glist(self, inter: disnake.AppCmdInter):
        await self._do_glist(inter)

    # ──────────────────── ERRORS ────────────────────

    async def cog_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=disnake.Embed(title="⛔ Нет прав", description="Эта команда только для администраторов.", color=CLR_FAIL))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка аргументов", description=f"Не указан обязательный аргумент: `{error.param.name}`", color=CLR_FAIL))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка аргумента", description=str(error), color=CLR_FAIL))
        else:
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_FAIL))

    @slash_gstart.error
    @slash_gend.error
    @slash_greroll.error
    @slash_gcancel.error
    async def slash_admin_error(self, inter: disnake.AppCmdInter, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await inter.response.send_message(embed=disnake.Embed(title="⛔ Нет прав", description="Эта команда только для администраторов.", color=CLR_FAIL), ephemeral=True)
        else:
            await inter.response.send_message(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_FAIL), ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(Giveaways(bot))