import disnake
from disnake.ext import commands

CLR_PENDING  = 0xFFAA00
CLR_APPROVED = 0x2EFF7A
CLR_REJECTED = 0xFF2E2E

IDEAS_CHANNEL_ID = 1529950209818362096   # канал "идеи участников"
REVIEW_CHANNEL_ID = 1514957148193296498

VOTE_UP_EMOJI = "👍"
VOTE_DOWN_EMOJI = "👎"


def pending_embed(author: disnake.Member, content: str, attachment_url: str = None) -> disnake.Embed:
    embed = disnake.Embed(
        title="💡 Новая идея на рассмотрении",
        description=content or "*(без текста)*",
        color=CLR_PENDING,
    )
    embed.set_author(name=str(author), icon_url=author.display_avatar.url)
    embed.add_field(name="👤 Автор", value=f"{author.mention} (`{author.id}`)", inline=True)
    if attachment_url:
        embed.set_image(url=attachment_url)
    embed.set_footer(text="Ожидает решения администрации")
    embed.timestamp = disnake.utils.utcnow()
    return embed


def published_embed(author: disnake.Member, content: str, attachment_url: str = None) -> disnake.Embed:
    embed = disnake.Embed(
        title="💡 Идея участника",
        description=content or "*(без текста)*",
        color=CLR_APPROVED,
    )
    embed.set_author(name=str(author), icon_url=author.display_avatar.url)
    if attachment_url:
        embed.set_image(url=attachment_url)
    embed.set_footer(text="Голосуйте реакциями ниже!")
    embed.timestamp = disnake.utils.utcnow()
    return embed


class IdeaReviewView(disnake.ui.View):
    """Постоянная view с кнопками Одобрить/Отклонить. Крепится к сообщению в канале модерации."""

    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="Одобрить", emoji="✅", style=disnake.ButtonStyle.green, custom_id="idea_review:approve")
    async def approve(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self._resolve(inter, approved=True)

    @disnake.ui.button(label="Отклонить", emoji="❌", style=disnake.ButtonStyle.red, custom_id="idea_review:reject")
    async def reject(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self._resolve(inter, approved=False)

    async def _resolve(self, inter: disnake.MessageInteraction, approved: bool):
        if not inter.author.guild_permissions.administrator:
            return await inter.response.send_message(
                embed=disnake.Embed(title="⛔ Нет прав", description="Только администраторы могут модерировать идеи.", color=CLR_REJECTED),
                ephemeral=True,
            )

        embed = inter.message.embeds[0]
        author_field = next((f for f in embed.fields if f.name == "👤 Автор"), None)
        author_id = int(author_field.value.split("`")[1]) if author_field else None
        author = inter.guild.get_member(author_id) if author_id else None

        content = embed.description if embed.description != "*(без текста)*" else ""
        attachment_url = embed.image.url if embed.image else None

        if approved and author:
            ideas_channel = inter.guild.get_channel(IDEAS_CHANNEL_ID)
            if ideas_channel:
                new_msg = await ideas_channel.send(embed=published_embed(author, content, attachment_url))
                await new_msg.add_reaction(VOTE_UP_EMOJI)
                await new_msg.add_reaction(VOTE_DOWN_EMOJI)

            try:
                await author.send(embed=disnake.Embed(
                    title="✅ Твоя идея одобрена!",
                    description=f"Идея опубликована в {ideas_channel.mention if ideas_channel else 'канале идей'} — теперь участники могут голосовать за неё.",
                    color=CLR_APPROVED,
                ))
            except disnake.Forbidden:
                pass

            result_text = f"✅ Одобрено пользователем {inter.author.mention}"
            result_color = CLR_APPROVED

        elif not approved and author:
            try:
                await author.send(embed=disnake.Embed(
                    title="❌ Твоя идея отклонена",
                    description="К сожалению, администрация решила не публиковать эту идею.",
                    color=CLR_REJECTED,
                ))
            except disnake.Forbidden:
                pass

            result_text = f"❌ Отклонено пользователем {inter.author.mention}"
            result_color = CLR_REJECTED

        else:
            result_text = "⚠️ Автор идеи покинул сервер — действие выполнено без уведомления."
            result_color = CLR_PENDING

        embed.color = result_color
        embed.set_footer(text=result_text)
        for child in self.children:
            child.disabled = True

        await inter.response.edit_message(embed=embed, view=self)


class Ideas(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(IdeaReviewView())

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        if message.author.bot:
            return
        if message.channel.id != IDEAS_CHANNEL_ID:
            return

        # удаляем исходное сообщение — оно появится в канале только после одобрения
        try:
            await message.delete()
        except disnake.Forbidden:
            return

        attachment_url = message.attachments[0].url if message.attachments else None

        review_channel = message.guild.get_channel(REVIEW_CHANNEL_ID)
        if not review_channel:
            return

        await review_channel.send(
            embed=pending_embed(message.author, message.content, attachment_url),
            view=IdeaReviewView(),
        )

        try:
            await message.author.send(embed=disnake.Embed(
                title="💡 Идея отправлена на рассмотрение",
                description="Администрация рассмотрит её в ближайшее время. Ты получишь уведомление о решении.",
                color=CLR_PENDING,
            ))
        except disnake.Forbidden:
            pass


def setup(bot: commands.Bot):
    bot.add_cog(Ideas(bot))