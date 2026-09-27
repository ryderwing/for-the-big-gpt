import asyncio
import logging

import discord
from discord.ext import commands

from config import settings
from database import Database
from commands.accounts import AccountCommands
from commands.player import PlayerCommands
from commands.admin import AdminCommands
from logging_config import configure_logging


class JJKBot(commands.Bot):
    def __init__(self, db: Database):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(
            command_prefix=settings.prefix,
            intents=intents,
            case_insensitive=True,
            help_command=commands.DefaultHelpCommand(
                no_category="Commands"
            ),
        )
        self.db = db
        self.logger = logging.getLogger("jjkbot")

    async def setup_hook(self):
        await self.db.initialize()
        await self.add_cog(AccountCommands(self))
        await self.add_cog(PlayerCommands(self))
        await self.add_cog(AdminCommands(self))

    async def on_ready(self):
        self.logger.info("Logged in as %s (%s)", self.user, self.user.id)
        self.logger.info("Connected to %d guild(s)", len(self.guilds))

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing required argument: `{error.param.name}`.")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send("Invalid argument. Please check the command format.")
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Please wait {error.retry_after:.1f}s before trying again.")
            return
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send("This command can only be used inside a server.")
            return
        self.logger.exception("Unhandled command error", exc_info=error)
        try:
            await ctx.send("The request could not be completed. No changes were saved.")
        except discord.HTTPException:
            pass


async def main():
    configure_logging()
    if not settings.discord_token:
        raise RuntimeError("DISCORD_TOKEN is not configured.")
    db = Database(settings.database_url)
    bot = JJKBot(db)
    try:
        await bot.start(settings.discord_token)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
