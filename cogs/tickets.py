import asyncio
import disnake
from disnake.ext import commands

CLR_PANEL = 0x5865F2
CLR_OPEN  = 0x2EFF7A
CLR_CLOSE = 0xFF2E2E
CLR_INFO  = 0x00D9FF

TICKET_CATEGORY_ID = 1529832608199086201
SUPPORT_ROLE_ID = 1540306233402200106
TICKET_CATEGORIES = [
    {
        "value": "complaint",
        "label": "Жалоба на пользователя",
        "description": "Нарушение правил, токсичность",
        "emoji": "🚫",
        "question": "Опиши, кто нарушил правила и что именно произошло. Приложи скриншоты/видео, если есть.",
    },
    {
        "value": "tech",
        "label": "Техническая проблема",
        "description": "Баги, лаги, проблемы с подключением",
        "emoji": "🛠️",
        "question": "Опиши техническую проблему как можно подробнее: что произошло, когда, какие шаги воспроизводят баг.",
    },
    {
        "value": "appeal",
        "label": "Обжалование наказания",
        "description": "Бан, мут или варн, с которым ты не согласен",
        "emoji": "⚖️",
        "question": "Укажи, какое наказание обжалуешь, когда оно было выдано и почему считаешь его несправедливым.",
    },
    {
        "value": "donate",
        "label": "Вопрос по донату/покупкам",
        "description": "Проблемы с оплатой, не пришла покупка",
        "emoji": "💎",
        "question": "Опиши проблему с покупкой: что покупал, когда, приложи чек/скриншот оплаты.",
    },
    {
        "value": "other",
        "label": "Другое",
        "description": "Вопрос не подходит ни под одну категорию",
        "emoji": "❓",
        "question": "Опиши свой вопрос как можно подробнее — команда поддержки скоро подключится.",
    },
]

CATEGORY_BY_VALUE = {c["value"]: c for c in TICKET_CATEGORIES}


def panel_embed() -> disnake.Embed:
    embed = disnake.Embed(
        title="🎫 Служба поддержки",
        description=(
            "**Создать тикет, в котором можно задать вопрос персоналу или отправить жалобу.**\n\n"
            "Каждое действие отображаются в наших логах и видно кто создал / удалил какой-либо тикет. Мы отслеживаем и наказываем участников, которые используют эту систему не по назначению (наказания варьируются от предупреждений до блокировки на сервере.)\n\n"
            "Полезные ссылки:\n"
            "· ПРАВИЛА ПРОЕКТА - https://discord.com/channels/1511109878272360648/1514956848745418942"
        ),
        color=CLR_PANEL,
    )
    embed.set_footer(text="Выбирая категорию, ты создаёшь приватный канал")
    embed.set_image(url="https://cdn.discordapp.com/attachments/1426248749830897758/1530555566093766777/Untitled16_20260725152450.jpg?ex=6a66a933&is=6a6557b3&hm=445f871cf9c17430b8b74c12fe7af6f6511a0184b5a3e05d368b3ad07dfa5cec")
    return embed


def ticket_open_embed(author: disnake.Member, category: dict) -> disnake.Embed:
    embed = disnake.Embed(
        title=f"{category['emoji']} {category['label']}",
        description=(
            f"Привет, {author.mention}!\n\n"
            f"**{category['question']}**\n\n"
            f"Чтобы закрыть тикет, нажми кнопку **Закрыть тикет** ниже."
        ),
        color=CLR_OPEN,
    )
    embed.set_thumbnail(url=author.display_avatar.url)
    embed.set_footer(text=f"Категория: {category['label']}")
    embed.timestamp = disnake.utils.utcnow()
    return embed


class TicketCategorySelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label=cat["label"],
                description=cat["description"],
                emoji=cat["emoji"],
                value=cat["value"],
            )
            for cat in TICKET_CATEGORIES
        ]
        super().__init__(
            placeholder="Выберите категорию вашего вопроса...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_panel:select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        guild = inter.guild
        author = inter.author
        category = CATEGORY_BY_VALUE[self.values[0]]

        channel_name = f"{category['value']}-{author.name}".lower().replace(" ", "-")

        existing = disnake.utils.get(guild.text_channels, name=channel_name)
        if existing:
            return await inter.response.send_message(
                embed=disnake.Embed(
                    title="⚠️ У тебя уже есть открытый тикет этой категории",
                    description=f"Перейди в {existing.mention}",
                    color=CLR_INFO,
                ),
                ephemeral=True,
            )

        await inter.response.defer(ephemeral=True)

        parent_category = guild.get_channel(TICKET_CATEGORY_ID)
        if parent_category is None or not isinstance(parent_category, disnake.CategoryChannel):
            return await inter.followup.send(
                embed=disnake.Embed(
                    title="❌ Ошибка настройки",
                    description="Категория для тикетов не найдена. Сообщи администрации.",
                    color=CLR_CLOSE,
                ),
                ephemeral=True,
            )

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            author: disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: disnake.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }

        if SUPPORT_ROLE_ID:
            support_role = guild.get_role(SUPPORT_ROLE_ID)
            if support_role:
                overwrites[support_role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True)

        if len(parent_category.channels) >= 50:
            return await inter.followup.send(
                embed=disnake.Embed(
                    title="❌ Слишком много открытых тикетов",
                    description="Категория переполнена. Сообщи администрации.",
                    color=CLR_CLOSE,
                ),
                ephemeral=True,
            )

        channel = await guild.create_text_channel(
            name=channel_name,
            category=parent_category,
            overwrites=overwrites,
            topic=f"Тикет [{category['label']}] пользователя {author} ({author.id})",
        )

        await channel.send(
            content=author.mention,
            embed=ticket_open_embed(author, category),
            view=TicketCloseView(),
        )

        await inter.followup.send(
            embed=disnake.Embed(
                title="✅ Тикет создан",
                description=f"Твой тикет: {channel.mention}",
                color=CLR_OPEN,
            ),
            ephemeral=True,
        )


class TicketPanelView(disnake.ui.View):
    """Постоянная view с select menu выбора категории. Крепится к сообщению панели."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())


class TicketCloseView(disnake.ui.View):
    """Постоянная view с кнопками закрытия и добавления участника. Крепится к первому сообщению в канале тикета."""

    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="Добавить участника",
        emoji="➕",
        style=disnake.ButtonStyle.blurple,
        custom_id="ticket_panel:adduser",
    )
    async def add_user(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_message(
            embed=disnake.Embed(
                title="➕ Добавить участника в тикет",
                description="Выбери пользователя ниже — он получит доступ к этому каналу.",
                color=CLR_INFO,
            ),
            view=AddUserSelectView(),
            ephemeral=True,
        )

    @disnake.ui.button(
        label="Закрыть тикет",
        emoji="🔒",
        style=disnake.ButtonStyle.red,
        custom_id="ticket_panel:close",
    )
    async def close_ticket(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_message(
            embed=disnake.Embed(
                title="🔒 Тикет будет закрыт",
                description="Канал удалится через 5 секунд...",
                color=CLR_CLOSE,
            )
        )
        await inter.channel.send(
            embed=disnake.Embed(
                description=f"Тикет закрыт пользователем {inter.author.mention}",
                color=CLR_CLOSE,
            )
        )
        await asyncio.sleep(5)
        await inter.channel.delete(reason=f"Тикет закрыт {inter.author}")


class AddUserSelectView(disnake.ui.View):
    """Временная view (не persistent) с UserSelect — выдаётся эфемерно при нажатии 'Добавить участника'."""

    def __init__(self):
        super().__init__(timeout=60)

    @disnake.ui.user_select(placeholder="Выберите пользователя...", min_values=1, max_values=1)
    async def select_user(self, select: disnake.ui.UserSelect, inter: disnake.MessageInteraction):
        member = select.values[0]

        if isinstance(member, disnake.User):
            member = inter.guild.get_member(member.id)
            if member is None:
                return await inter.response.edit_message(
                    embed=disnake.Embed(title="❌ Ошибка", description="Этот пользователь не найден на сервере.", color=CLR_CLOSE),
                    view=None,
                )

        await inter.channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )

        await inter.channel.send(embed=disnake.Embed(
            description=f"➕ {inter.author.mention} добавил в тикет {member.mention}",
            color=CLR_OPEN,
        ))

        await inter.response.edit_message(
            embed=disnake.Embed(
                title="✅ Участник добавлен",
                description=f"{member.mention} теперь имеет доступ к этому тикету.",
                color=CLR_OPEN,
            ),
            view=None,
        )


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(TicketPanelView())
        bot.add_view(TicketCloseView())

    @commands.command(name="ticketpanel")
    @commands.has_permissions(administrator=True)
    async def ticketpanel(self, ctx: commands.Context):
        """Вызвать панель создания тикетов с выбором категории"""
        await ctx.message.delete()
        await ctx.send(embed=panel_embed(), view=TicketPanelView())

    @ticketpanel.error
    async def ticketpanel_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                embed=disnake.Embed(
                    title="⛔ Нет прав",
                    description="Эта команда только для администраторов.",
                    color=CLR_CLOSE,
                )
            )
        else:
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_CLOSE))


def setup(bot: commands.Bot):
    bot.add_cog(Tickets(bot))