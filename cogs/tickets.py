import disnake
from disnake.ext import commands

CLR_PANEL  = 0x5865F2
CLR_OPEN   = 0x2EFF7A
CLR_CLOSE  = 0xFF2E2E
CLR_INFO   = 0x00D9FF

TICKET_CATEGORY_ID = 1529832608199086201
SUPPORT_ROLE_ID = 1529826871271755929 # TODO: ЗАМЕНИТЬ НА ВАЛИДНОЕ ПОСЛЕ ТЕСТОВ


def panel_embed() -> disnake.Embed:
    embed = disnake.Embed(
        title="🎫 Служба поддержки",
        description=(
            "Нужна помощь или хочешь что-то сообщить администрации?\n\n"
            "Нажми на кнопку ниже, чтобы открыть приватный тикет.\n"
            "Наша команда ответит тебе как можно скорее."
        ),
        color=CLR_PANEL,
    )
    embed.set_footer(text="Нажимая кнопку, ты создаёшь приватный канал")
    return embed
 
 
def ticket_open_embed(author: disnake.Member) -> disnake.Embed:
    embed = disnake.Embed(
        title="🎫 Тикет открыт",
        description=(
            f"Привет, {author.mention}! Опиши свою проблему как можно подробнее — "
            f"команда поддержки скоро подключится.\n\n"
            f"Чтобы закрыть тикет, нажми кнопку **Закрыть тикет** ниже."
        ),
        color=CLR_OPEN,
    )
    embed.set_thumbnail(url=author.display_avatar.url)
    embed.timestamp = disnake.utils.utcnow()
    return embed
 
 
class TicketPanelView(disnake.ui.View):
    """Постоянная view с кнопкой создания тикета. Крепится к сообщению панели."""
 
    def __init__(self):
        super().__init__(timeout=None)
 
    @disnake.ui.button(
        label="Открыть тикет",
        emoji="🎫",
        style=disnake.ButtonStyle.green,
        custom_id="ticket_panel:create",
    )
    async def create_ticket(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        guild = inter.guild
        author = inter.author
 
        # проверка на уже открытый тикет
        existing = disnake.utils.get(guild.text_channels, name=f"ticket-{author.name}".lower().replace(" ", "-"))
        if existing:
            return await inter.response.send_message(
                embed=disnake.Embed(
                    title="⚠️ У тебя уже есть открытый тикет",
                    description=f"Перейди в {existing.mention}",
                    color=CLR_INFO,
                ),
                ephemeral=True,
            )
 
        await inter.response.defer(ephemeral=True)
 
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if category is None or not isinstance(category, disnake.CategoryChannel):
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
 
        channel_name = f"ticket-{author.name}".lower().replace(" ", "-")
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Тикет пользователя {author} ({author.id})",
        )
 
        await channel.send(
            content=author.mention,
            embed=ticket_open_embed(author),
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
 
 
class TicketCloseView(disnake.ui.View):
    """Постоянная view с кнопкой закрытия тикета. Крепится к первому сообщению в канале тикета."""
 
    def __init__(self):
        super().__init__(timeout=None)
 
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
        import asyncio
        await asyncio.sleep(5)
        await inter.channel.delete(reason=f"Тикет закрыт {inter.author}")
 
 
class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # регистрируем постоянные views, чтобы кнопки работали после рестарта бота
        bot.add_view(TicketPanelView())
        bot.add_view(TicketCloseView())
 
    @commands.command(name="ticketpanel")
    @commands.has_permissions(administrator=True)
    async def ticketpanel(self, ctx: commands.Context):
        """Вызвать панель создания тикетов в текущем канале"""
        await ctx.message.delete()
        await ctx.send(embed=panel_embed(), view=TicketPanelView())
 
    @ticketpanel.error
    async def ticketpanel_error(self, ctx: commands.Context, error: Exception):
        embed=disnake.Embed(
            title="⛔ Нет прав",
            description="Эта команда только для администраторов.",
            color=CLR_CLOSE,
        )
        embed.add_image(url="https://cdn.discordapp.com/attachments/1426248749830897758/1530555566093766777/Untitled16_20260725152450.jpg?ex=6a660073&is=6a64aef3&hm=f3d98cdd992518e6b8443717f87c4080687ffd3bad4ca368200e6bcc21ca15dc")
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                embed=embed
            )
        else:
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_CLOSE))
 
 
def setup(bot: commands.Bot):
    bot.add_cog(Tickets(bot))
