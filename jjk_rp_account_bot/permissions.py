import discord
from discord.ext import commands

from database import Database


async def is_owner(ctx: commands.Context) -> bool:
    return bool(ctx.guild and ctx.guild.owner_id == ctx.author.id)


async def is_manager(ctx, db: Database) -> bool:
    if not ctx.guild:
        return False
    if ctx.guild.owner_id == ctx.author.id:
        return True
    cfg = await db.get_guild_config(ctx.guild.id)
    if not cfg or not cfg.account_manager_role_id:
        return False
    return any(role.id == cfg.account_manager_role_id for role in getattr(ctx.author, "roles", []))


async def require_manager(ctx, db: Database) -> bool:
    if await is_manager(ctx, db):
        return True
    await ctx.send("You do not have permission to use this command.")
    return False


async def require_owner(ctx) -> bool:
    if await is_owner(ctx):
        return True
    await ctx.send("Only the server owner can use this command.")
    return False
