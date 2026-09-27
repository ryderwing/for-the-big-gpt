import re
from datetime import datetime

import discord

GRADES = (
    "5th Grade",
    "4th Grade",
    "3rd Grade",
    "2nd Grade",
    "1st Grade",
    "Special Grade",
)

MOVE_TYPES = (
    "Normal Move",
    "Black Flash",
    "Domain Expansion",
)

CAPS = {
    "Normal Move": 50,
    "Black Flash": 20,
    "Domain Expansion": 60,
}

MAX_NAME = 100
MAX_DESCRIPTION = 2000
MAX_REASON = 500


def clean_name(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\s+", " ", value)
    if not value or len(value) > MAX_NAME:
        raise ValueError("invalid name")
    return value


def clean_description(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_DESCRIPTION:
        raise ValueError("description too long")
    return value


def parse_nonnegative_int(value: str, maximum: int = 2_000_000_000) -> int:
    value = value.strip()
    if not re.fullmatch(r"\d+", value):
        raise ValueError("invalid integer")
    result = int(value)
    if result < 0 or result > maximum:
        raise ValueError("integer out of range")
    return result


def parse_positive_int(value: str, maximum: int = 2_000_000_000) -> int:
    result = parse_nonnegative_int(value, maximum)
    if result < 1:
        raise ValueError("must be positive")
    return result


def parse_profile_id(value: str) -> int:
    return parse_positive_int(value, 2_000_000_000)


def fmt_dt(dt: datetime) -> str:
    return discord.utils.format_dt(dt, "f")


def profile_embed(profile, title: str = "RP Profile") -> discord.Embed:
    embed = discord.Embed(title=title)
    embed.add_field(name="Account", value=discord.utils.escape_markdown(profile.account_name), inline=True)
    embed.add_field(name="Assigned User", value=f"<@{profile.assigned_user_id}>" if profile.assigned_user_id else "Unassigned", inline=True)
    embed.add_field(name="Grade", value=profile.grade, inline=True)
    embed.add_field(name="Available Mastery", value=str(profile.unspent_mastery), inline=True)
    embed.add_field(name="Profile ID", value=str(profile.id), inline=True)
    moves = []
    for move in profile.moves:
        moves.append(f"{discord.utils.escape_markdown(move.move_name)} — {move.mastery}/{CAPS[move.move_type]} ({move.move_type})")
    embed.add_field(name="Moves", value="\n".join(moves) if moves else "None", inline=False)
    if profile.description:
        embed.add_field(name="Description", value=discord.utils.escape_markdown(profile.description), inline=False)
    embed.set_footer(text=f"Last updated {fmt_dt(profile.updated_at)}")
    return embed


async def send_profile_update(bot, guild_id: int, embed: discord.Embed):
    cfg = await bot.db.get_guild_config(guild_id)
    if not cfg or not cfg.profiles_channel_id:
        return
    channel = bot.get_channel(cfg.profiles_channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(cfg.profiles_channel_id)
        except discord.HTTPException:
            return
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        except discord.HTTPException:
            return
