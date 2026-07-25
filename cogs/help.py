import disnake
from disnake.ext import commands

CLR_HELP = 0x5865F2

# Категории и эмодзи для когов — подстрой под свои имена cog'ов
COG_META = {
    "Economy":    {"emoji": "💰", "title": "Экономика"},
    "Moderation": {"emoji": "🔨", "title": "Модерация"},
    "Tickets":    {"emoji": "🎫", "title": "Тикеты"},
}


def is_admin_only(command: commands.Command) -> bool:
    """Проверяет, навешен ли на команду чек has_permissions(administrator=True)."""
    for check in command.checks:
        qualname = getattr(check, "__qualname__", "")
        if "has_permissions" in qualname:
            return True
    return False


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _do_help(self, target_ctx, is_slash: bool):
        bot = self.bot
        author = target_ctx.author

        is_author_admin = False
        if isinstance(author, disnake.Member):
            is_author_admin = author.guild_permissions.administrator

        embed = disnake.Embed(
            title="📖 Список команд",
            description=f"Префикс текстовых команд: `{bot.command_prefix}`\nВсе команды также доступны как `/слэш`.",
            color=CLR_HELP,
        )
        embed.set_thumbnail(url=bot.user.display_avatar.url)

        # ── Обычные текстовые команды (commands.Cog), сгруппированные по когам ──
        for cog_name, cog in bot.cogs.items():
            if cog_name == "Help":
                continue

            visible_cmds = []
            for cmd in cog.get_commands():
                if cmd.hidden:
                    continue
                if is_admin_only(cmd) and not is_author_admin:
                    continue
                visible_cmds.append(cmd)

            if not visible_cmds:
                continue

            meta = COG_META.get(cog_name, {"emoji": "📂", "title": cog_name})
            lines = []
            for cmd in sorted(visible_cmds, key=lambda c: c.name):
                desc = cmd.help or "Без описания"
                lines.append(f"`{bot.command_prefix}{cmd.name}` — {desc}")

            embed.add_field(
                name=f"{meta['emoji']} {meta['title']}",
                value="\n".join(lines),
                inline=False,
            )

        embed.set_footer(text=f"Запросил: {author}", icon_url=author.display_avatar.url)

        if is_slash:
            await target_ctx.response.send_message(embed=embed)
        else:
            await target_ctx.send(embed=embed)

    @commands.command(name="help", aliases=["помощь", "команды"])
    async def txt_help(self, ctx: commands.Context):
        await self._do_help(ctx, is_slash=False)

    @commands.slash_command(name="help", description="📖 Показать список доступных команд")
    async def slash_help(self, inter: disnake.AppCmdInter):
        await self._do_help(inter, is_slash=True)


def setup(bot: commands.Bot):
    bot.add_cog(Help(bot))