import logging
import asyncio

from discord.ext import commands

from utils import CAPS, parse_positive_int, profile_embed, send_profile_update

log = logging.getLogger("jjkbot.player")


class PlayerCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="profile")
    @commands.guild_only()
    async def profile(self, ctx, profile_id: str | None = None):
        if profile_id is not None:
            try:
                pid = int(profile_id)
                if pid <= 0:
                    raise ValueError
            except ValueError:
                await ctx.send("Invalid profile ID.")
                return
            profile = await self.bot.db.get_profile(ctx.guild.id, pid)
            if profile is None:
                await ctx.send("That profile does not exist.")
                return
            if profile.assigned_user_id != ctx.author.id:
                from permissions import is_manager
                if not await is_manager(ctx, self.bot.db):
                    await ctx.send("You are not assigned to this profile.")
                    return
            await ctx.send(embed=profile_embed(profile))
            return

        profiles = await self.bot.db.get_profiles_for_user(ctx.guild.id, ctx.author.id)
        if not profiles:
            await ctx.send("You do not have any assigned profiles.")
            return
        for profile in profiles[:10]:
            await ctx.send(embed=profile_embed(profile))

    @commands.command(name="mastery", aliases=["my-mastery"])
    @commands.guild_only()
    async def mastery(self, ctx):
        profiles = await self.bot.db.get_profiles_for_user(ctx.guild.id, ctx.author.id)
        if not profiles:
            await ctx.send("You do not have any assigned profiles.")
            return
        for profile in profiles[:10]:
            lines = [
                f"Account: **{profile.account_name}**",
                f"Available Mastery: **{profile.unspent_mastery}**",
                "",
                "Move Mastery:",
            ]
            for move in profile.moves:
                lines.append(f"{move.move_name} — {move.mastery}/{CAPS[move.move_type]}")
            await ctx.send("\n".join(lines))

    @commands.command(name="spend-mastery")
    @commands.guild_only()
    @commands.cooldown(3, 10, commands.BucketType.user)
    async def spend_mastery(self, ctx, move: str, amount: str):
        try:
            value = parse_positive_int(amount)
        except ValueError:
            await ctx.send("Invalid mastery amount. Please enter a positive whole number.")
            return

        profiles = await self.bot.db.get_profiles_for_user(ctx.guild.id, ctx.author.id)
        if not profiles:
            await ctx.send("You do not have an assigned profile.")
            return
        if len(profiles) > 1:
            lines = ["You have multiple assigned profiles. Reply with the profile ID you want to use:"]
            for item in profiles:
                lines.append(f"`{item.id}` — {item.account_name} — {item.grade}")
            await ctx.send("\n".join(lines))

            def check(message):
                return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id

            try:
                selection = await self.bot.wait_for("message", timeout=60, check=check)
                selected_id = int(selection.content.strip())
            except (ValueError, asyncio.TimeoutError):
                await ctx.send("Profile selection timed out or was invalid.")
                return

            profile = next((item for item in profiles if item.id == selected_id), None)
            if profile is None:
                await ctx.send("That profile is not assigned to you.")
                return
        else:
            profile = profiles[0]
        try:
            before_balance, after_balance, before_mastery, after_mastery, _, updated_move = await self.bot.db.spend_mastery(
                ctx.guild.id, profile.id, ctx.author.id, move, value
            )
        except LookupError as exc:
            if str(exc) == "move not found":
                await ctx.send("That move does not exist on your profile.")
            else:
                await ctx.send("That profile does not exist.")
            return
        except PermissionError:
            await ctx.send("You are not assigned to this profile.")
            return
        except ValueError as exc:
            message = str(exc)
            if message.startswith("cap:"):
                await ctx.send(f"This move can only reach {message.split(':', 1)[1]} mastery.")
            elif message.startswith("available:"):
                await ctx.send(f"You only have {message.split(':', 1)[1]} unspent mastery points.")
            else:
                await ctx.send("Invalid mastery amount.")
            return
        except Exception:
            log.exception("spend-mastery failed")
            await ctx.send("The request could not be completed. No changes were saved.")
            return

        fresh = await self.bot.db.get_profile(ctx.guild.id, profile.id)
        embed = profile_embed(fresh, "MASTERY SPENT")
        embed.description = (
            f"**{updated_move.move_name}**: {before_mastery}/{CAPS[updated_move.move_type]} "
            f"→ {after_mastery}/{CAPS[updated_move.move_type]}\n"
            f"Remaining mastery: **{after_balance}**"
        )
        await send_profile_update(self.bot, ctx.guild.id, embed)
        await ctx.send(embed=embed)
