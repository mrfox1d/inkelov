import asyncio
import os
import disnake
from disnake.ext import commands
from dotenv import load_dotenv
from db.interaction import Database
from db.db_guard import set_bot

load_dotenv()


async def main():
    bot = commands.Bot(
        command_prefix=".",
        intents=disnake.Intents.all(),
        help_command=None,

        activity=disnake.Activity(
            type=disnake.ActivityType.streaming,
            name="💩 developed by shitcode.pw",
            url="https://twitch.tv/mrfox1d"
        )
    )
    set_bot(bot)

    db = Database()
    extensions_loaded = False

    @bot.event
    async def on_ready():
        nonlocal extensions_loaded
        print(f"Logged in as {bot.user} ({bot.user.id})")

        await db.init_db()

        if not extensions_loaded:
            bot.load_extensions("cogs")
            extensions_loaded = True

    token = os.getenv("TOKEN")
    if not token:
        raise ValueError("Токен не найден! Проверь наличие переменной TOKEN в .env")

    try:
        await bot.start(token)
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот успешно остановлен.")
    except Exception as e:
        print(f"Ошибка выполнения: {e}")