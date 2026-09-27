import logging
from pathlib import Path

import discord
from discord.ext import commands

from permissions import require_manager, require_owner, is_manager
from utils import parse_positive_int, profile_embed, send_profile_update

log = logging.getLogger("jjkbot.admin")


class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.delete_confirmations: set[tuple[int, int, int]] = set()

    @commands.command(name="give-mastery")
    @commands.guild_only()
    async def give_mastery(self, ctx, profile_id: str, amount: str, *, reason: str = "No reason provided"):
        if not await require_manager(ctx, self.bot.db):
            return
        try:
            pid = parse_positive_int(profile_id)
            value = parse_positive_int(amount)
            if len(reason) > 500:
                await ctx.send("Reason is too long.")
                return
            previous, new, profile = await self.bot.db.give_mastery(
                ctx.guild.id, pid, ctx.author.id, value, reason
            )
            fresh = await self.bot.db.get_profile(ctx.guild.id, pid)
        except LookupError:
            await ctx.send("That profile does not exist.")
            return
        except ValueError:
            await ctx.send("Invalid mastery amount or value.")
            return
        except Exception:
            log.exception("give-mastery failed")
            await ctx.send("The request could not be completed. No changes were saved.")
            return

        embed = profile_embed(fresh, "MASTERY AWARDED")
        embed.description = (
            f"{f'<@{fresh.assigned_user_id}>' if fresh.assigned_user_id else 'Unassigned'} received **{value}** mastery points.\n"
            f"Previous balance: **{previous}**\n"
            f"New balance: **{new}**\n"
            f"Reason: {discord.utils.escape_markdown(reason)}\n"
            f"Manager: <@{ctx.author.id}>"
        )
        await send_profile_update(self.bot, ctx.guild.id, embed)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

    @commands.command(name="view-account")
    @commands.guild_only()
    async def view_account(self, ctx, profile_id: str):
        if not await require_manager(ctx, self.bot.db):
            return
        try:
            pid = parse_positive_int(profile_id)
            profile = await self.bot.db.get_profile(ctx.guild.id, pid, include_archived=True)
        except ValueError:
            await ctx.send("Invalid profile ID.")
            return
        if not profile:
            await ctx.send("That profile does not exist.")
            return
        embed = profile_embed(profile, "ACCOUNT")
        if profile.archived:
            embed.add_field(name="Status", value="Archived", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="list-accounts")
    @commands.guild_only()
    async def list_accounts(self, ctx):
        if not await require_manager(ctx, self.bot.db):
            return
        profiles = await self.bot.db.list_profiles(ctx.guild.id)
        if not profiles:
            await ctx.send("No active profiles exist in this server.")
            return
        chunks = []
        current = []
        for p in profiles:
            line = f"`{p.id}` — **{discord.utils.escape_markdown(p.account_name)}** — {p.grade} — {f'<@{p.assigned_user_id}>' if p.assigned_user_id else 'Unassigned'}"
            if sum(len(x) + 1 for x in current) + len(line) > 1800:
                chunks.append("\n".join(current))
                current = []
            current.append(line)
        if current:
            chunks.append("\n".join(current))
        for chunk in chunks:
            await ctx.send(chunk)

    @commands.command(name="delete-account")
    @commands.guild_only()
    async def delete_account(self, ctx, profile_id: str):
        if not await require_manager(ctx, self.bot.db):
            return
        try:
            pid = parse_positive_int(profile_id)
        except ValueError:
            await ctx.send("Invalid profile ID.")
            return
        profile = await self.bot.db.get_profile(ctx.guild.id, pid)
        if not profile:
            await ctx.send("That profile does not exist.")
            return
        key = (ctx.guild.id, ctx.author.id, pid)
        if key not in self.delete_confirmations:
            self.delete_confirmations.add(key)
            await ctx.send(
                f"Are you sure you want to archive Account {pid}? "
                "Reply `CONFIRM` within 30 seconds. This command will only accept your own confirmation."
            )
            def check(message):
                return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id and message.content.strip().upper() == "CONFIRM"
            try:
                await self.bot.wait_for("message", timeout=30, check=check)
            except Exception:
                await ctx.send("Deletion confirmation expired.")
                self.delete_confirmations.discard(key)
                return
            self.delete_confirmations.discard(key)

        try:
            await self.bot.db.archive_profile(ctx.guild.id, pid, ctx.author.id)
            fresh = await self.bot.db.get_profile(ctx.guild.id, pid, include_archived=True)
        except Exception:
            log.exception("delete-account failed")
            await ctx.send("The request could not be completed. No changes were saved.")
            return
        embed = profile_embed(fresh, "PROFILE ARCHIVED")
        embed.add_field(name="Status", value="Archived")
        await send_profile_update(self.bot, ctx.guild.id, embed)
        await ctx.send("The profile was archived. Historical audit records were retained.")

    @commands.command(name="restore-account")
    @commands.guild_only()
    async def restore_account(self, ctx, profile_id: str):
        if not await require_manager(ctx, self.bot.db):
            return
        try:
            pid = parse_positive_int(profile_id)
            await self.bot.db.restore_profile(ctx.guild.id, pid, ctx.author.id)
        except LookupError:
            await ctx.send("That archived profile does not exist.")
            return
        except Exception:
            log.exception("restore-account failed")
            await ctx.send("The request could not be completed. No changes were saved.")
            return
        profile = await self.bot.db.get_profile(ctx.guild.id, pid)
        await send_profile_update(self.bot, ctx.guild.id, profile_embed(profile, "PROFILE RESTORED"))
        await ctx.send("Profile restored.")

    @commands.command(name="account-history")
    @commands.guild_only()
    async def account_history(self, ctx, profile_id: str):
        if not await require_manager(ctx, self.bot.db):
            return
        try:
            pid = parse_positive_int(profile_id)
            rows = await self.bot.db.history(ctx.guild.id, pid, 25)
        except ValueError:
            await ctx.send("Invalid profile ID.")
            return
        if not rows:
            await ctx.send("No audit history exists for that profile.")
            return
        lines = []
        for row in rows:
            details = discord.utils.escape_markdown(row.details[:300])
            lines.append(f"`{row.created_at:%Y-%m-%d %H:%M UTC}` **{row.action}** by <@{row.executor_user_id}>\n{details}")
        await ctx.send("\n\n".join(lines)[:1900])

    @commands.command(name="backup")
    @commands.guild_only()
    async def backup(self, ctx):
        if not await require_owner(ctx):
            return
        try:
            path = await self.bot.db.backup(__import__("config").settings.backup_dir)
        except Exception as exc:
            log.exception("backup failed")
            await ctx.send(
                "Backup could not be created automatically. "
                "If using PostgreSQL, follow the README pg_dump backup instructions."
            )
            return
        await ctx.send(f"Backup created securely on the bot host: `{path.name}`. It was not uploaded to Discord.")

    @commands.command(name="healthcheck")
    @commands.guild_only()
    async def healthcheck(self, ctx):
        if not await require_owner(ctx):
            return
        try:
            count = await self.bot.db.count_profiles(ctx.guild.id)
            await ctx.send(f"Database OK. Active profiles in this server: {count}.")
        except Exception:
            log.exception("healthcheck failed")
            await ctx.send("Database health check failed.")
