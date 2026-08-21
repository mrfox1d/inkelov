import disnake
from disnake.ext import commands
from db.interaction import Database

db = Database()

CLR_ADMIN  = 0x5865F2
CLR_OK     = 0x2EFF7A
CLR_FAIL   = 0xFF2E2E
CLR_SHOP   = 0x00D9FF
CLR_ANNOUNCE = 0xFFD700

SHOP_PANEL_KEY = "shop"


def admin_embed(title: str, description: str, color: int, fields: list[tuple] = None) -> disnake.Embed:
    embed = disnake.Embed(title=title, description=description, color=color)
    embed.timestamp = disnake.utils.utcnow()
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    return embed


def build_shop_panel_embed(items: list[dict]) -> disnake.Embed:
    embed = disnake.Embed(
        title="🛒 Магазин сервера",
        color=CLR_SHOP,
    )
    embed.timestamp = disnake.utils.utcnow()

    if not items:
        embed.description = "Магазин пока пуст. Загляните позже!"
    else:
        lines = []
        for item in items:
            stock_str = "∞" if item["stock"] == -1 else str(item["stock"])
            desc = f" — {item['description']}" if item["description"] else ""
            lines.append(
                f"**`#{item['item_id']}`  {item['name']}**{desc}\n"
                f"　　💰 {item['price']:,}".replace(",", " ") + f" 🪙　📦 Остаток: `{stock_str}`"
            )
        embed.description = "\n\n".join(lines)

    embed.set_footer(text="Выбери товар в меню ниже, чтобы купить")
    return embed


def build_shop_select_options(items: list[dict]) -> list[disnake.SelectOption]:
    options = []
    for item in items[:25]:  # лимит Discord на select menu
        stock_str = "∞" if item["stock"] == -1 else str(item["stock"])
        options.append(
            disnake.SelectOption(
                label=f"{item['name']} — {item['price']} 🪙"[:100],
                description=(item["description"] or f"Остаток: {stock_str}")[:100],
                value=str(item["item_id"]),
                emoji="🛍️",
            )
        )
    return options


class ShopPanelView(disnake.ui.View):
    """Постоянная view с select menu для покупки товаров прямо из панели."""

    def __init__(self, items: list[dict] = None):
        super().__init__(timeout=None)
        items = items or []
        select = self.children[0]
        if items:
            select.options = build_shop_select_options(items)
            select.disabled = False
            select.placeholder = "🛒 Выбери товар для покупки..."
        else:
            select.options = [disnake.SelectOption(label="Магазин пуст", value="_empty")]
            select.disabled = True
            select.placeholder = "Магазин пуст"

    @disnake.ui.select(
        placeholder="🛒 Выбери товар для покупки...",
        min_values=1,
        max_values=1,
        custom_id="shop_panel:select",
        options=[disnake.SelectOption(label="Загрузка...", value="_loading")],
    )
    async def select_item(self, select: disnake.ui.StringSelect, inter: disnake.MessageInteraction):
        item_id = int(select.values[0])
        item = await db.get_item(item_id)

        if not item:
            return await inter.response.send_message(
                embed=admin_embed("❌ Товар не найден", "Этот товар больше не доступен.", CLR_FAIL),
                ephemeral=True,
            )

        result = await db.buy_item(inter.author.id, item_id)

        if not result["success"]:
            return await inter.response.send_message(
                embed=admin_embed("❌ Покупка не удалась", result["reason"], CLR_FAIL),
                ephemeral=True,
            )

        role_text = ""
        if item["role_id"]:
            role = inter.guild.get_role(item["role_id"])
            if role:
                await inter.author.add_roles(role, reason=f"Покупка: {item['name']}")
                role_text = f"\n🎭 Выдана роль: {role.mention}"

        await inter.response.send_message(
            embed=admin_embed(
                "✅ Покупка успешна!",
                f"Ты купил **{item['name']}** за {item['price']:,}".replace(",", " ") + f" 🪙{role_text}\n"
                f"Новый баланс: **{result['new_balance']:,}".replace(",", " ") + " 🪙**",
                CLR_OK,
            ),
            ephemeral=True,
        )


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(ShopPanelView())  # регистрируем пустую view, чтобы select работал после рестарта

    # ──────────────────────── SHOP PANEL SYNC ──────────────────────

    async def refresh_shop_panel(self, guild: disnake.Guild = None):
        """Обновить закреплённую панель магазина, если она существует.
        Вызывается автоматически после additem/removeitem/edititem."""
        panel = await db.get_panel(SHOP_PANEL_KEY)
        if not panel:
            return  # панель ещё не создавалась через /shoppanel

        target_guild = guild or self.bot.get_guild(panel["guild_id"])
        if not target_guild:
            return

        channel = target_guild.get_channel(panel["channel_id"])
        if not channel:
            return

        try:
            message = await channel.fetch_message(panel["message_id"])
        except (disnake.NotFound, disnake.Forbidden):
            return

        items = await db.get_all_items()
        await message.edit(embed=build_shop_panel_embed(items), view=ShopPanelView(items))

    # ──────────────────────── SHOP PANEL COMMAND ───────────────────

    @commands.command(name="shoppanel")
    @commands.has_permissions(administrator=True)
    async def shoppanel(self, ctx: commands.Context):
        """Создать/переставить стабильную панель магазина в текущий канал."""
        await ctx.message.delete()

        items = await db.get_all_items()
        message = await ctx.send(embed=build_shop_panel_embed(items), view=ShopPanelView(items))

        await db.set_panel(SHOP_PANEL_KEY, ctx.guild.id, ctx.channel.id, message.id)

    @shoppanel.error
    async def shoppanel_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=admin_embed("⛔ Нет прав", "Эта команда только для администраторов.", CLR_FAIL))
        else:
            await ctx.send(embed=admin_embed("❌ Ошибка", f"```{error}```", CLR_FAIL))

    # ──────────────────────── SHOP MANAGEMENT ──────────────────────

    @commands.command(name="additem")
    @commands.has_permissions(administrator=True)
    async def additem(
        self,
        ctx: commands.Context,
        name: str,
        price: int,
        role: disnake.Role = None,
        stock: int = -1,
        *,
        description: str = None,
    ):
        """Добавить товар в магазин"""
        item_id = await db.add_item(name=name, price=price, description=description, role_id=role.id if role else None, stock=stock)

        await ctx.send(embed=admin_embed(
            "➕ Товар добавлен",
            f"**{name}** добавлен в магазин под ID `{item_id}`",
            CLR_OK,
            fields=[
                ("💰 Цена", f"{price:,}".replace(",", " ") + " 🪙", True),
                ("📦 Запас", "∞" if stock == -1 else str(stock), True),
                ("🎭 Роль", role.mention if role else "—", True),
            ],
        ))

        await self.refresh_shop_panel(ctx.guild)

    @commands.command(name="removeitem")
    @commands.has_permissions(administrator=True)
    async def removeitem(self, ctx: commands.Context, item_id: int):
        """Удалить товар из магазина"""
        item = await db.get_item(item_id)
        if not item:
            return await ctx.send(embed=admin_embed("❌ Товар не найден", f"Товара с ID `{item_id}` не существует.", CLR_FAIL))

        await db.delete_item(item_id)
        await ctx.send(embed=admin_embed("➖ Товар удалён", f"**{item['name']}** удалён из магазина.", CLR_OK))

        await self.refresh_shop_panel(ctx.guild)

    @commands.command(name="edititem")
    @commands.has_permissions(administrator=True)
    async def edititem(self, ctx: commands.Context, item_id: int, field: str, *, value: str):
        """Пример: !edititem 3 price 500  /  !edititem 3 name Новое название"""
        allowed = {"name", "description", "price", "role_id", "stock", "is_active"}
        field = field.lower()

        if field not in allowed:
            return await ctx.send(embed=admin_embed(
                "❌ Неверное поле",
                f"Доступные поля: `{'`, `'.join(allowed)}`",
                CLR_FAIL,
            ))

        item = await db.get_item(item_id)
        if not item:
            return await ctx.send(embed=admin_embed("❌ Товар не найден", f"Товара с ID `{item_id}` не существует.", CLR_FAIL))

        # приведение типов
        cast_value = value
        if field in ("price", "stock"):
            try:
                cast_value = int(value)
            except ValueError:
                return await ctx.send(embed=admin_embed("❌ Ошибка", f"Значение поля `{field}` должно быть числом.", CLR_FAIL))
        elif field == "role_id":
            cast_value = int(value.strip("<@&>")) if value.strip("<@&>").isdigit() else None
        elif field == "is_active":
            cast_value = 1 if value.lower() in ("1", "true", "yes", "да") else 0

        await db.edit_item(item_id, **{field: cast_value})

        await ctx.send(embed=admin_embed(
            "✏️ Товар обновлён",
            f"**{item['name']}** (`#{item_id}`): `{field}` → `{cast_value}`",
            CLR_OK,
        ))

        await self.refresh_shop_panel(ctx.guild)

    @additem.error
    @removeitem.error
    @edititem.error
    async def shop_manage_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=admin_embed("⛔ Нет прав", "Эта команда только для администраторов.", CLR_FAIL))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=admin_embed("❌ Ошибка аргументов", f"Не указан обязательный аргумент: `{error.param.name}`", CLR_FAIL))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=admin_embed("❌ Ошибка аргумента", str(error), CLR_FAIL))
        else:
            await ctx.send(embed=admin_embed("❌ Ошибка", f"```{error}```", CLR_FAIL))

    # ──────────────────────── USER MANAGEMENT ──────────────────────

    @commands.command(name="setbalance")
    @commands.has_permissions(administrator=True)
    async def setbalance(self, ctx: commands.Context, member: disnake.Member, amount: int):
        """Установить точный баланс пользователю"""
        await db.set_balance(member.id, amount)
        await ctx.send(embed=admin_embed(
            "⚙️ Баланс изменён",
            f"Баланс {member.mention} установлен на **{amount:,}".replace(",", " ") + " 🪙**",
            CLR_ADMIN,
        ))

    @commands.command(name="addmoney")
    @commands.has_permissions(administrator=True)
    async def addmoney(self, ctx: commands.Context, member: disnake.Member, amount: int):
        """Начислить/списать деньги пользователю"""
        new_balance = await db.add_balance(member.id, amount, reason=f"Админ-выдача: {ctx.author}")
        await ctx.send(embed=admin_embed(
            "💸 Баланс изменён",
            f"{member.mention}: {'+' if amount >= 0 else ''}{amount:,}".replace(",", " ") + f" 🪙\nНовый баланс: **{new_balance:,}".replace(",", " ") + " 🪙**",
            CLR_ADMIN,
        ))

    @commands.command(name="resetwarns")
    @commands.has_permissions(administrator=True)
    async def resetwarns(self, ctx: commands.Context, member: disnake.Member):
        """Сбросить все предупреждения пользователя"""
        await db.clear_warnings(member.id)
        await ctx.send(embed=admin_embed("🗑️ Предупреждения сброшены", f"Все предупреждения {member.mention} удалены.", CLR_OK))

    # ──────────────────────── SERVER UTILITIES ─────────────────────

    @commands.command(name="announce")
    @commands.has_permissions(administrator=True)
    async def announce(self, ctx: commands.Context, channel: disnake.TextChannel, *, message: str):
        """Отправить объявление от лица бота в указанный канал."""
        await ctx.message.delete()
        await channel.send(embed=admin_embed("📢 Объявление", message, CLR_ANNOUNCE))

    @commands.command(name="say")
    @commands.has_permissions(administrator=True)
    async def say(self, ctx: commands.Context, *, message: str):
        """Бот пишет текст от своего лица в текущем канале."""
        await ctx.message.delete()
        await ctx.send(message)

    @commands.command(name="slowmode")
    @commands.has_permissions(administrator=True)
    async def slowmode(self, ctx: commands.Context, seconds: int):
        """Установить slowmode в текущем канале"""
        await ctx.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await ctx.send(embed=admin_embed("⏱️ Slowmode выключен", "Ограничение частоты сообщений снято.", CLR_OK))
        else:
            await ctx.send(embed=admin_embed("⏱️ Slowmode включён", f"Задержка между сообщениями: **{seconds}с**", CLR_ADMIN))

    @commands.command(name="lock")
    @commands.has_permissions(administrator=True)
    async def lock(self, ctx: commands.Context, channel: disnake.TextChannel = None):
        """Заблокировать отправку сообщений в канале"""
        channel = channel or ctx.channel
        await channel.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send(embed=admin_embed("🔒 Канал заблокирован", f"{channel.mention} закрыт для отправки сообщений.", CLR_FAIL))

    @commands.command(name="unlock")
    @commands.has_permissions(administrator=True)
    async def unlock(self, ctx: commands.Context, channel: disnake.TextChannel = None):
        """Разблокировать отправку сообщений в канале"""
        channel = channel or ctx.channel
        await channel.set_permissions(ctx.guild.default_role, send_messages=None)
        await ctx.send(embed=admin_embed("🔓 Канал разблокирован", f"{channel.mention} снова открыт для сообщений.", CLR_OK))

    @setbalance.error
    @addmoney.error
    @resetwarns.error
    @announce.error
    @say.error
    @slowmode.error
    @lock.error
    @unlock.error
    async def admin_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=admin_embed("⛔ Нет прав", "Эта команда только для администраторов.", CLR_FAIL))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=admin_embed("❌ Ошибка аргументов", f"Не указан обязательный аргумент: `{error.param.name}`", CLR_FAIL))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=admin_embed("❌ Ошибка аргумента", str(error), CLR_FAIL))
        else:
            await ctx.send(embed=admin_embed("❌ Ошибка", f"```{error}```", CLR_FAIL))


def setup(bot: commands.Bot):
    bot.add_cog(Admin(bot))