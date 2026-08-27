import random
import disnake
from disnake.ext import commands
from db.interaction import Database
from datetime import datetime

db = Database()

CLR_MONEY  = 0x2EFF7A
CLR_BANK   = 0x5865F2
CLR_FAIL   = 0xFF2E2E
CLR_GAME_W = 0xFFD700
CLR_GAME_L = 0x8B5CF6
CLR_SHOP   = 0x00D9FF
CLR_DAILY  = 0xFF69B4


def econ_embed(
    title: str,
    description: str,
    color: int,
    author: disnake.Member | disnake.User = None,
    fields: list[tuple] = None,
    thumbnail: str = None,
) -> disnake.Embed:
    embed = disnake.Embed(title=title, description=description, color=color)
    embed.timestamp = disnake.utils.utcnow()

    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)

    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    if author:
        embed.set_footer(text=str(author), icon_url=author.display_avatar.url)

    return embed


async def reply_embed(
    ctx_or_inter: commands.Context | disnake.Interaction,
    embed: disnake.Embed,
    ephemeral: bool = False,
    view: disnake.ui.View = None,
):
    if isinstance(ctx_or_inter, disnake.Interaction):
        if ctx_or_inter.response.is_done():
            await ctx_or_inter.edit_original_response(embed=embed, view=view or disnake.utils.MISSING)
        else:
            await ctx_or_inter.response.send_message(embed=embed, ephemeral=ephemeral, view=view or disnake.utils.MISSING)
    else:
        await ctx_or_inter.send(embed=embed, view=view or disnake.utils.MISSING)


def money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " 🪙"


# ──────────────────────── BALANCE VIEW (🎁 Бонус) ───────────────────

class BalanceView(disnake.ui.View):
    """Постоянная view с кнопкой быстрого забора daily-бонуса под /balance."""

    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="Бонус",
        emoji="🎁",
        style=disnake.ButtonStyle.primary,
        custom_id="balance_panel:daily",
    )
    async def claim_daily(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        author = inter.author
        can_claim = await db.can_claim_daily(author.id)

        if not can_claim:
            return await inter.response.send_message(
                embed=econ_embed(
                    "⏳ Рано!",
                    "Ты уже забирал ежедневную награду. Возвращайся через некоторое время.",
                    CLR_FAIL,
                ),
                ephemeral=True,
            )

        reward = random.randint(200, 500)
        new_balance = await db.add_balance(author.id, reward, reason="Ежедневная награда (кнопка)")
        await db.set_daily_claimed(author.id)

        await inter.response.send_message(
            embed=econ_embed(
                "🎁 Награда получена!",
                f"Ты получил **{money(reward)}**",
                CLR_DAILY,
                author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            ),
            ephemeral=True,
        )


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(BalanceView())

    async def _do_balance(self, target_ctx, member: disnake.Member = None):
        author = target_ctx.author
        target = member or author
        bal, bank = await db.get_balance(target.id)
        total = bal + bank

        await reply_embed(
            target_ctx,
            econ_embed(
                f"💰 Баланс — {target.display_name}",
                f"### {money(total)}",
                CLR_MONEY,
                author=author,
                thumbnail=target.display_avatar.url,
                fields=[
                    ("👛 Кошелёк", money(bal), True),
                    ("🏦 Банк", money(bank), True),
                ],
            ),
            view=BalanceView() if target.id == author.id else None,
        )

    async def _do_daily(self, target_ctx):
        author = target_ctx.author
        can_claim = await db.can_claim_daily(author.id)

        if not can_claim:
            return await reply_embed(
                target_ctx,
                econ_embed("⏳ Рано!", "Ты уже забирал ежедневную награду. Возвращайся через некоторое время.", CLR_FAIL),
                ephemeral=True,
            )

        reward = random.randint(200, 500)
        new_balance = await db.add_balance(author.id, reward, reason="Ежедневная награда")
        await db.set_daily_claimed(author.id)

        await reply_embed(
            target_ctx,
            econ_embed(
                "🎁 Награда получена!",
                f"Ты получил **{money(reward)}**",
                CLR_DAILY,
                author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            ),
        )

    JOBS = [
        ("почистил конюшни", 50, 150),
        ("разнёс пиццу по адресам", 80, 200),
        ("написал код за фрилансера", 150, 350),
        ("выгулял чужих собак", 40, 120),
        ("продал старые вещи на барахолке", 60, 180),
    ]

    async def _do_work(self, target_ctx):
        author = target_ctx.author
        can_work = await db.can_work(author.id, cooldown_seconds=3600)

        if not can_work:
            return await reply_embed(
                target_ctx,
                econ_embed("⏳ Ты устал", "Нужно отдохнуть перед следующей работой. Попробуй через час.", CLR_FAIL),
                ephemeral=True,
            )

        job, low, high = random.choice(self.JOBS)
        earned = random.randint(low, high)
        new_balance = await db.add_balance(author.id, earned, reason="Работа")
        await db.set_work_done(author.id)

        await reply_embed(
            target_ctx,
            econ_embed(
                "💼 Работа выполнена",
                f"Ты **{job}** и заработал **{money(earned)}**",
                CLR_MONEY,
                author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            ),
        )

    async def _do_deposit(self, target_ctx, amount: int):
        author = target_ctx.author
        bal, _ = await db.get_balance(author.id)

        if amount > bal:
            return await reply_embed(
                target_ctx,
                econ_embed("❌ Недостаточно средств", f"В кошельке всего {money(bal)}.", CLR_FAIL),
                ephemeral=True,
            )

        new_bal, new_bank = await db.deposit(author.id, amount)

        await reply_embed(
            target_ctx,
            econ_embed(
                "🏦 Депозит выполнен",
                f"Положено **{money(amount)}** в банк.",
                CLR_BANK,
                author=author,
                fields=[
                    ("👛 Кошелёк", money(new_bal), True),
                    ("🏦 Банк", money(new_bank), True),
                ],
            ),
        )

    async def _do_withdraw(self, target_ctx, amount: int):
        author = target_ctx.author
        _, bank = await db.get_balance(author.id)

        if amount > bank:
            return await reply_embed(
                target_ctx,
                econ_embed("❌ Недостаточно средств", f"В банке всего {money(bank)}.", CLR_FAIL),
                ephemeral=True,
            )

        new_bal, new_bank = await db.withdraw(author.id, amount)

        await reply_embed(
            target_ctx,
            econ_embed(
                "🏧 Снятие выполнено",
                f"Снято **{money(amount)}** с банка.",
                CLR_BANK,
                author=author,
                fields=[
                    ("👛 Кошелёк", money(new_bal), True),
                    ("🏦 Банк", money(new_bank), True),
                ],
            ),
        )

    async def _do_pay(self, target_ctx, member: disnake.Member, amount: int):
        author = target_ctx.author

        if member.id == author.id:
            return await reply_embed(
                target_ctx, econ_embed("❌ Ошибка", "Нельзя перевести деньги самому себе.", CLR_FAIL), ephemeral=True,
            )
        if member.bot:
            return await reply_embed(
                target_ctx, econ_embed("❌ Ошибка", "Нельзя перевести деньги боту.", CLR_FAIL), ephemeral=True,
            )

        bal, _ = await db.get_balance(author.id)
        if amount > bal:
            return await reply_embed(
                target_ctx, econ_embed("❌ Недостаточно средств", f"В кошельке всего {money(bal)}.", CLR_FAIL), ephemeral=True,
            )

        await db.add_balance(author.id, -amount, reason=f"Перевод → {member}")
        await db.add_balance(member.id, amount, reason=f"Перевод ← {author}")

        await reply_embed(
            target_ctx,
            econ_embed(
                "💸 Перевод выполнен",
                f"{author.mention} перевёл {member.mention} **{money(amount)}**",
                CLR_MONEY,
            ),
        )

    async def _do_leaderboard(self, target_ctx):
        guild = target_ctx.guild
        top = await db.get_leaderboard(limit=10)

        if not top:
            return await reply_embed(target_ctx, econ_embed("🏆 Топ пуст", "Пока никто не заработал денег.", CLR_MONEY))

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, row in enumerate(top):
            place = medals[i] if i < 3 else f"`#{i + 1}`"
            user = guild.get_member(row["user_id"])
            name = user.mention if user else f"`{row['user_id']}`"
            lines.append(f"{place} {name} — **{money(row['total'])}**")

        await reply_embed(target_ctx, econ_embed("🏆 Топ богачей сервера", "\n".join(lines), CLR_GAME_W))

    async def _do_coinflip(self, target_ctx, bet: int, side: str):
        author = target_ctx.author
        side = side.capitalize()
        if side not in ("Орёл", "Решка"):
            return await reply_embed(
                target_ctx, econ_embed("❌ Ошибка", "Сторона должна быть `Орёл` или `Решка`.", CLR_FAIL), ephemeral=True,
            )

        bal, _ = await db.get_balance(author.id)
        if bet > bal:
            return await reply_embed(
                target_ctx, econ_embed("❌ Недостаточно средств", f"В кошельке всего {money(bal)}.", CLR_FAIL), ephemeral=True,
            )

        result = random.choice(["Орёл", "Решка"])
        won = result == side

        if won:
            new_balance = await db.add_balance(author.id, bet, reason="Coinflip: выигрыш")
            embed = econ_embed(
                f"🪙 Выпал {result}! Ты выиграл!",
                f"Ставка **{money(bet)}** удвоена.\nВыигрыш: **{money(bet * 2)}**",
                CLR_GAME_W,
                author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            )
        else:
            new_balance = await db.add_balance(author.id, -bet, reason="Coinflip: проигрыш")
            embed = econ_embed(
                f"🪙 Выпал {result}! Ты проиграл.",
                f"Потеряно: **{money(bet)}**",
                CLR_GAME_L,
                author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            )

        await reply_embed(target_ctx, embed)

    SLOT_EMOJIS = ["🍒", "🍋", "🍇", "🍉", "⭐", "💎"]
    SLOT_WEIGHTS = [35, 28, 20, 12, 4, 1]  # чем реже символ, тем больше платит — но джекпот крайне редкий
    SLOT_MULTIPLIERS = {"🍒": 1.4, "🍋": 1.8, "🍇": 2.2, "🍉": 3, "⭐": 6, "💎": 12}

    async def _do_slots(self, target_ctx, bet: int):
        author = target_ctx.author
        bal, _ = await db.get_balance(author.id)
        if bet > bal:
            return await reply_embed(
                target_ctx, econ_embed("❌ Недостаточно средств", f"В кошельке всего {money(bal)}.", CLR_FAIL), ephemeral=True,
            )

        roll = random.choices(self.SLOT_EMOJIS, weights=self.SLOT_WEIGHTS, k=3)
        slot_display = f"### 🎰 [ {' | '.join(roll)} ]"

        if roll[0] == roll[1] == roll[2]:
            multiplier = self.SLOT_MULTIPLIERS[roll[0]]
            winnings = int(bet * multiplier)
            new_balance = await db.add_balance(author.id, winnings - bet, reason="Slots: выигрыш")
            embed = econ_embed(
                "🎰 Три в ряд!",
                f"{slot_display}\n\nВыигрыш x{multiplier}: **{money(winnings)}**",
                CLR_GAME_W,
                author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            )
        else:
            # две одинаковые больше не спасают ставку — только полный джекпот платит
            new_balance = await db.add_balance(author.id, -bet, reason="Slots: проигрыш")
            embed = econ_embed(
                "🎰 Не повезло",
                f"{slot_display}\n\nПотеряно: **{money(bet)}**",
                CLR_GAME_L,
                author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            )

        await reply_embed(target_ctx, embed)

    # ──────────────────────── ROULETTE (числа/цвета) ────────────────────────

    ROULETTE_RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

    async def _do_roulette(self, target_ctx, bet: int, choice: str):
        author = target_ctx.author
        choice = choice.lower().strip()

        bal, _ = await db.get_balance(author.id)
        if bet > bal:
            return await reply_embed(
                target_ctx, econ_embed("❌ Недостаточно средств", f"В кошельке всего {money(bal)}.", CLR_FAIL), ephemeral=True,
            )

        number = random.randint(0, 36)
        color = "green" if number == 0 else ("red" if number in self.ROULETTE_RED else "black")
        color_emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}[color]

        won = False
        multiplier = 0

        if choice in ("red", "black", "красное", "чёрное", "черное"):
            bet_color = "red" if choice in ("red", "красное") else "black"
            won = bet_color == color
            multiplier = 2
        elif choice.isdigit():
            won = int(choice) == number
            multiplier = 14  # ниже классических 35x — под честный минус-RTP
        else:
            return await reply_embed(
                target_ctx, econ_embed(
                    "❌ Ошибка", "Ставь на `red`/`black` или на конкретное число 0-36.", CLR_FAIL,
                ), ephemeral=True,
            )

        result_line = f"### 🎡 Выпало: {color_emoji} **{number}**"

        if won:
            winnings = bet * multiplier
            new_balance = await db.add_balance(author.id, winnings - bet, reason="Roulette: выигрыш")
            embed = econ_embed(
                "🎡 Выигрыш!",
                f"{result_line}\n\nВыигрыш x{multiplier}: **{money(winnings)}**",
                CLR_GAME_W, author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            )
        else:
            new_balance = await db.add_balance(author.id, -bet, reason="Roulette: проигрыш")
            embed = econ_embed(
                "🎡 Не в этот раз",
                f"{result_line}\n\nПотеряно: **{money(bet)}**",
                CLR_GAME_L, author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            )

        await reply_embed(target_ctx, embed)

    # ──────────────────────── GUESS (угадай число) ────────────────────────

    async def _do_guess(self, target_ctx, bet: int, number: int):
        author = target_ctx.author

        if not (1 <= number <= 10):
            return await reply_embed(
                target_ctx, econ_embed("❌ Ошибка", "Число должно быть от 1 до 10.", CLR_FAIL), ephemeral=True,
            )

        bal, _ = await db.get_balance(author.id)
        if bet > bal:
            return await reply_embed(
                target_ctx, econ_embed("❌ Недостаточно средств", f"В кошельке всего {money(bal)}.", CLR_FAIL), ephemeral=True,
            )

        actual = random.randint(1, 10)

        if number == actual:
            multiplier = 7  # 1/10 шанс, честный множитель был бы x10 — тут x7, минус-RTP
            winnings = bet * multiplier
            new_balance = await db.add_balance(author.id, winnings - bet, reason="Guess: угадал")
            embed = econ_embed(
                "🎯 Угадал!",
                f"Загаданное число: **{actual}**\n\nВыигрыш x{multiplier}: **{money(winnings)}**",
                CLR_GAME_W, author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            )
        else:
            new_balance = await db.add_balance(author.id, -bet, reason="Guess: не угадал")
            embed = econ_embed(
                "🎯 Мимо",
                f"Ты назвал **{number}**, а выпало **{actual}**.\n\nПотеряно: **{money(bet)}**",
                CLR_GAME_L, author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            )

        await reply_embed(target_ctx, embed)

    # ──────────────────────── ROB (ограбление) ────────────────────────

    ROB_SUCCESS_CHANCE = 0.35
    ROB_STEAL_MIN_PCT = 0.10
    ROB_STEAL_MAX_PCT = 0.30
    ROB_FAIL_FINE_PCT = 0.15
    ROB_COOLDOWN_SECONDS = 3600

    async def _do_rob(self, target_ctx, member: disnake.Member):
        author = target_ctx.author

        if member.id == author.id:
            return await reply_embed(
                target_ctx, econ_embed("❌ Ошибка", "Нельзя ограбить самого себя.", CLR_FAIL), ephemeral=True,
            )
        if member.bot:
            return await reply_embed(
                target_ctx, econ_embed("❌ Ошибка", "Ботов грабить бессмысленно.", CLR_FAIL), ephemeral=True,
            )

        can_rob = await db.can_do_action(author.id, "rob_last", self.ROB_COOLDOWN_SECONDS)
        if not can_rob:
            return await reply_embed(
                target_ctx, econ_embed("⏳ Рано грабить", "Дай себе отдохнуть перед следующим ограблением. Попробуй позже.", CLR_FAIL), ephemeral=True,
            )

        victim_bal, _ = await db.get_balance(member.id)
        if victim_bal < 50:
            return await reply_embed(
                target_ctx, econ_embed(
                    "❌ Нечего красть",
                    f"У {member.mention} слишком мало денег в кошельке для ограбления.",
                    CLR_FAIL,
                ), ephemeral=True,
            )

        author_bal, _ = await db.get_balance(author.id)
        await db.set_action_done(author.id, "rob_last")

        success = random.random() < self.ROB_SUCCESS_CHANCE

        if success:
            steal_pct = random.uniform(self.ROB_STEAL_MIN_PCT, self.ROB_STEAL_MAX_PCT)
            stolen = max(1, int(victim_bal * steal_pct))

            await db.add_balance(member.id, -stolen, reason=f"Ограблен пользователем {author}")
            new_author_balance = await db.add_balance(author.id, stolen, reason=f"Ограбление {member}")

            embed = econ_embed(
                "🦹 Ограбление удалось!",
                f"Ты стащил **{money(stolen)}** из кошелька {member.mention}!",
                CLR_GAME_W, author=author,
                fields=[("👛 Новый баланс", money(new_author_balance), False)],
            )
        else:
            fine = max(1, int(author_bal * self.ROB_FAIL_FINE_PCT))
            new_author_balance = await db.add_balance(author.id, -fine, reason="Ограбление: пойман, штраф")

            embed = econ_embed(
                "🚨 Тебя поймали!",
                f"Попытка ограбить {member.mention} провалилась. Штраф: **{money(fine)}**",
                CLR_GAME_L, author=author,
                fields=[("👛 Новый баланс", money(new_author_balance), False)],
            )

        await reply_embed(target_ctx, embed)

    # ──────────────────────── FISH / MINE (доп. заработок) ────────────────────────

    FISH_LOOT = [
        ("поймал старый ботинок", 5, 20, 0.15),
        ("поймал мелкую рыбёшку", 20, 60, 0.35),
        ("поймал хорошего окуня", 60, 150, 0.30),
        ("поймал редкого лосося", 150, 300, 0.15),
        ("выловил сундук с сокровищами", 400, 800, 0.05),
    ]

    MINE_LOOT = [
        ("накопал только камней", 5, 20, 0.15),
        ("нашёл немного угля", 20, 60, 0.35),
        ("добыл железную руду", 60, 150, 0.30),
        ("нашёл золотую жилу", 150, 300, 0.15),
        ("наткнулся на алмазную жилу", 400, 800, 0.05),
    ]

    def _weighted_loot(self, loot_table):
        names = [l[0] for l in loot_table]
        weights = [l[3] for l in loot_table]
        chosen = random.choices(loot_table, weights=weights, k=1)[0]
        text, low, high, _ = chosen
        return text, random.randint(low, high)

    async def _do_fish(self, target_ctx):
        author = target_ctx.author
        can_action = await db.can_do_action(author.id, "fish_last", 1800)
        if not can_action:
            return await reply_embed(
                target_ctx, econ_embed("⏳ Отдохни", "Слишком рано для новой рыбалки. Попробуй позже.", CLR_FAIL), ephemeral=True,
            )

        text, earned = self._weighted_loot(self.FISH_LOOT)
        new_balance = await db.add_balance(author.id, earned, reason="Рыбалка")
        await db.set_action_done(author.id, "fish_last")

        await reply_embed(
            target_ctx,
            econ_embed(
                "🎣 Рыбалка",
                f"Ты {text} и заработал **{money(earned)}**",
                CLR_MONEY, author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            ),
        )

    async def _do_mine(self, target_ctx):
        author = target_ctx.author
        can_action = await db.can_do_action(author.id, "mine_last", 1800)
        if not can_action:
            return await reply_embed(
                target_ctx, econ_embed("⏳ Отдохни", "Слишком рано для новой добычи. Попробуй позже.", CLR_FAIL), ephemeral=True,
            )

        text, earned = self._weighted_loot(self.MINE_LOOT)
        new_balance = await db.add_balance(author.id, earned, reason="Шахта")
        await db.set_action_done(author.id, "mine_last")

        await reply_embed(
            target_ctx,
            econ_embed(
                "⛏️ Шахта",
                f"Ты {text} и заработал **{money(earned)}**",
                CLR_MONEY, author=author,
                fields=[("👛 Новый баланс", money(new_balance), False)],
            ),
        )

    async def _do_inventory(self, target_ctx):
        author = target_ctx.author
        items = await db.get_inventory(author.id)

        if not items:
            return await reply_embed(
                target_ctx,
                econ_embed("🎒 Инвентарь пуст", "У тебя пока нет купленных товаров. Загляни в магазин!", CLR_SHOP),
                ephemeral=True,
            )

        lines = [f"**{i['name']}** — {i['bought_at'][:10]}" for i in items]

        await reply_embed(
            target_ctx,
            econ_embed(
                f"🎒 Инвентарь — {author.display_name}",
                "\n".join(lines),
                CLR_SHOP,
                author=author,
                thumbnail=author.display_avatar.url,
            ),
            ephemeral=True,
        )

    async def _do_setbalance(self, target_ctx, member: disnake.Member, amount: int):
        await db.set_balance(member.id, amount)

        await reply_embed(
            target_ctx,
            econ_embed("⚙️ Баланс изменён", f"Баланс {member.mention} установлен на **{money(amount)}**", CLR_BANK),
        )

    # ─────────────────────── TEXT COMMANDS ─────────────────────────

    @commands.command(name="daily")
    async def txt_daily(self, ctx: commands.Context):
        """Забрать ежедневную награду"""
        await self._do_daily(ctx)

    @commands.command(name="work")
    async def txt_work(self, ctx: commands.Context):
        """Поработать и заработать деньги"""
        await self._do_work(ctx)

    @commands.command(name="deposit")
    async def txt_deposit(self, ctx: commands.Context, amount: int):
        """Положить деньги в банк"""
        await self._do_deposit(ctx, amount)

    @commands.command(name="withdraw")
    async def txt_withdraw(self, ctx: commands.Context, amount: int):
        """Снять деньги с банка"""
        await self._do_withdraw(ctx, amount)

    @commands.command(name="pay")
    async def txt_pay(self, ctx: commands.Context, member: disnake.Member, amount: int):
        """Перевести деньги другому пользователю"""
        await self._do_pay(ctx, member, amount)

    @commands.command(name="leaderboard", aliases=["top"])
    async def txt_leaderboard(self, ctx: commands.Context):
        """Топ богатых пользователей сервера"""
        await self._do_leaderboard(ctx)

    @commands.command(name="coinflip", aliases=["cf"])
    async def txt_coinflip(self, ctx: commands.Context, bet: int, side: str):
        """Орёл и решка — удвой ставку"""
        await self._do_coinflip(ctx, bet, side)

    @commands.command(name="slots")
    async def txt_slots(self, ctx: commands.Context, bet: int):
        """Крутить слоты"""
        await self._do_slots(ctx, bet)

    @commands.command(name="roulette", aliases=["rl"])
    async def txt_roulette(self, ctx: commands.Context, bet: int, choice: str):
        """Рулетка: ставь на red/black или число 0-36"""
        await self._do_roulette(ctx, bet, choice)

    @commands.command(name="guess")
    async def txt_guess(self, ctx: commands.Context, bet: int, number: int):
        """Угадай число от 1 до 10"""
        await self._do_guess(ctx, bet, number)

    @commands.command(name="rob")
    async def txt_rob(self, ctx: commands.Context, member: disnake.Member):
        """Попытаться ограбить кошелёк другого пользователя (35% шанс успеха, банк не трогается)"""
        await self._do_rob(ctx, member)

    @commands.command(name="fish")
    async def txt_fish(self, ctx: commands.Context):
        """Порыбачить и заработать деньги"""
        await self._do_fish(ctx)

    @commands.command(name="mine")
    async def txt_mine(self, ctx: commands.Context):
        """Покопать в шахте и заработать деньги"""
        await self._do_mine(ctx)

    @commands.command(name="inventory", aliases=["inv"])
    async def txt_inventory(self, ctx: commands.Context):
        """Посмотреть свой инвентарь"""
        await self._do_inventory(ctx)

    # ─────────────────────── SLASH COMMANDS ────────────────────────

    @commands.slash_command(name="daily", description="🎁 Забрать ежедневную награду")
    async def slash_daily(self, inter: disnake.AppCmdInter):
        await self._do_daily(inter)

    @commands.slash_command(name="work", description="💼 Поработать и заработать деньги")
    async def slash_work(self, inter: disnake.AppCmdInter):
        await self._do_work(inter)

    @commands.slash_command(name="deposit", description="🏦 Положить деньги в банк")
    async def slash_deposit(self, inter: disnake.AppCmdInter, amount: int = commands.Param(description="Сколько положить", ge=1)):
        await self._do_deposit(inter, amount)

    @commands.slash_command(name="withdraw", description="🏧 Снять деньги с банка")
    async def slash_withdraw(self, inter: disnake.AppCmdInter, amount: int = commands.Param(description="Сколько снять", ge=1)):
        await self._do_withdraw(inter, amount)

    @commands.slash_command(name="pay", description="💸 Перевести деньги другому пользователю")
    async def slash_pay(
        self, inter: disnake.AppCmdInter,
        member: disnake.Member = commands.Param(description="Кому перевести"),
        amount: int = commands.Param(description="Сумма", ge=1),
    ):
        await self._do_pay(inter, member, amount)

    @commands.slash_command(name="leaderboard", description="🏆 Топ богатых пользователей")
    async def slash_leaderboard(self, inter: disnake.AppCmdInter):
        await self._do_leaderboard(inter)

    @commands.slash_command(name="coinflip", description="🪙 Орёл и решка — удвой ставку")
    async def slash_coinflip(
        self, inter: disnake.AppCmdInter,
        bet: int = commands.Param(description="Ставка", ge=1),
        side: str = commands.Param(choices=["Орёл", "Решка"], description="Твоя сторона"),
    ):
        await self._do_coinflip(inter, bet, side)

    @commands.slash_command(name="slots", description="🎰 Крутить слоты")
    async def slash_slots(self, inter: disnake.AppCmdInter, bet: int = commands.Param(description="Ставка", ge=1)):
        await self._do_slots(inter, bet)

    @commands.slash_command(name="roulette", description="🎡 Рулетка: ставь на red/black или число 0-36")
    async def slash_roulette(
        self, inter: disnake.AppCmdInter,
        bet: int = commands.Param(description="Ставка", ge=1),
        choice: str = commands.Param(description="red / black / число 0-36"),
    ):
        await self._do_roulette(inter, bet, choice)

    @commands.slash_command(name="guess", description="🎯 Угадай число от 1 до 10")
    async def slash_guess(
        self, inter: disnake.AppCmdInter,
        bet: int = commands.Param(description="Ставка", ge=1),
        number: int = commands.Param(description="Число от 1 до 10", ge=1, le=10),
    ):
        await self._do_guess(inter, bet, number)

    @commands.slash_command(name="rob", description="🦹 Попытаться ограбить кошелёк другого пользователя")
    async def slash_rob(self, inter: disnake.AppCmdInter, member: disnake.Member = commands.Param(description="Кого ограбить")):
        await self._do_rob(inter, member)

    @commands.slash_command(name="fish", description="🎣 Порыбачить и заработать деньги")
    async def slash_fish(self, inter: disnake.AppCmdInter):
        await self._do_fish(inter)

    @commands.slash_command(name="mine", description="⛏️ Покопать в шахте и заработать деньги")
    async def slash_mine(self, inter: disnake.AppCmdInter):
        await self._do_mine(inter)

    @commands.slash_command(name="inventory", description="🎒 Посмотреть свой инвентарь")
    async def slash_inventory(self, inter: disnake.AppCmdInter):
        await self._do_inventory(inter)

    @commands.slash_command(name="setbalance", description="⚙️ [Admin] Установить баланс пользователю")
    @commands.has_permissions(administrator=True)
    async def slash_setbalance(
        self, inter: disnake.AppCmdInter,
        member: disnake.Member = commands.Param(description="Кому установить"),
        amount: int = commands.Param(description="Новый баланс", ge=0),
    ):
        await self._do_setbalance(inter, member, amount)

    async def cog_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await reply_embed(ctx, econ_embed("⛔ Нет прав", "Эта команда только для администраторов.", CLR_FAIL))
        elif isinstance(error, commands.MissingRequiredArgument):
            await reply_embed(ctx, econ_embed("❌ Ошибка аргументов", f"Не указан обязательный аргумент: `{error.param.name}`", CLR_FAIL))
        else:
            await reply_embed(ctx, econ_embed("❌ Ошибка", f"```{error}```", CLR_FAIL))

    @slash_setbalance.error
    async def slash_admin_error(self, inter: disnake.AppCmdInter, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await reply_embed(inter, econ_embed("⛔ Нет прав", "Эта команда только для администраторов.", CLR_FAIL), ephemeral=True)
        else:
            await reply_embed(inter, econ_embed("❌ Ошибка", f"```{error}```", CLR_FAIL), ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(Economy(bot))