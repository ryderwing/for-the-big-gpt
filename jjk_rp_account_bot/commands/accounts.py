import asyncio
import logging
from typing import Optional

import discord
from discord.ext import commands

from permissions import require_manager
from utils import (
    CAPS, GRADES, MOVE_TYPES, clean_description, clean_name, parse_nonnegative_int,
    parse_positive_int, parse_profile_id, profile_embed, send_profile_update,
)
from models import Move


log = logging.getLogger("jjkbot.accounts")


class AccountCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="setup")
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def setup(self, ctx: commands.Context):
        if not ctx.guild or ctx.guild.owner_id != ctx.author.id:
            await ctx.send("Only the server owner can use this command.")
            return

        me = ctx.guild.me
        if me is None:
            await ctx.send("I could not verify my server permissions.")
            return
        if not me.guild_permissions.manage_roles or not me.guild_permissions.manage_channels:
            await ctx.send("I need Manage Roles and Manage Channels to complete setup.")
            return

        existing_cfg = await self.bot.db.get_guild_config(ctx.guild.id)

        role = None
        if existing_cfg and existing_cfg.account_manager_role_id:
            role = ctx.guild.get_role(existing_cfg.account_manager_role_id)

        if role is None:
            role = discord.utils.get(ctx.guild.roles, name="Account Manager")
        if role is None:
            try:
                role = await ctx.guild.create_role(
                    name="Account Manager",
                    permissions=discord.Permissions.none(),
                    reason=f"JJK RP bot setup by {ctx.author.id}",
                )
            except discord.HTTPException:
                await ctx.send("I could not create the Account Manager role. Check my role permissions and hierarchy.")
                return

        channel = None
        if existing_cfg and existing_cfg.profiles_channel_id:
            candidate = ctx.guild.get_channel(existing_cfg.profiles_channel_id)
            if isinstance(candidate, discord.TextChannel):
                channel = candidate
        if channel is None:
            channel = discord.utils.get(ctx.guild.text_channels, name="profiles")
        if channel is None:
            try:
                channel = await ctx.guild.create_text_channel(
                    "profiles",
                    reason=f"JJK RP bot setup by {ctx.author.id}",
                )
            except discord.HTTPException:
                await ctx.send("I could not create the profiles channel. Check my channel permissions.")
                return

        await self.bot.db.upsert_guild_config(ctx.guild.id, role.id, channel.id)

        embed = discord.Embed(title="Setup complete")
        embed.add_field(name="Account Manager Role", value=role.mention, inline=False)
        embed.add_field(name="Profiles Channel", value=channel.mention, inline=False)
        embed.set_footer(text="The Account Manager role has no Administrator permission.")
        await ctx.send(embed=embed)

    @commands.command(name="create-account")
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def create_account(self, ctx: commands.Context):
        if not await require_manager(ctx, self.bot.db):
            return

        def check(message: discord.Message):
            return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id

        async def ask(prompt: str) -> str | None:
            await ctx.send(prompt)
            try:
                message = await self.bot.wait_for("message", timeout=300, check=check)
            except asyncio.TimeoutError:
                await ctx.send("Account creation timed out.")
                return None
            if message.content.strip().lower() == "cancel":
                await ctx.send("Account creation cancelled.")
                return None
            return message.content.strip()

        await ctx.send("Account Creation — Step 1/5\nReply `cancel` at any stage to stop.")

        name = await ask("What is the account/character name?")
        if name is None: return
        try:
            name = clean_name(name)
        except ValueError:
            await ctx.send("Invalid account name. Use 1–100 characters.")
            return

        assigned_raw = await ask("Who should this profile be assigned to? Mention a Discord user.")
        if assigned_raw is None: return
        assigned_user = await self._resolve_member(ctx.guild, assigned_raw)
        if assigned_user is None:
            await ctx.send("I could not resolve that server member.")
            return

        grade = await ask("What grade should the character have?\n" + "\n".join(f"- {x}" for x in GRADES))
        if grade is None: return
        grade = self._match_choice(grade, GRADES)
        if grade is None:
            await ctx.send("Invalid grade.")
            return

        mastery_raw = await ask("How many starting mastery points should this account have?")
        if mastery_raw is None: return
        try:
            starting_mastery = parse_nonnegative_int(mastery_raw)
        except ValueError:
            await ctx.send("Invalid mastery amount. Enter a non-negative whole number.")
            return

        count_raw = await ask("How many moves/attacks should this account have? Enter 0 or a positive whole number.")
        if count_raw is None: return
        try:
            move_count = parse_nonnegative_int(count_raw, 50)
        except ValueError:
            await ctx.send("Invalid move count. Use a whole number from 0 to 50.")
            return

        moves = []
        used = set()
        for index in range(1, move_count + 1):
            move_name = await ask(f"Account Creation — Move {index}/{move_count}\nMove {index} name:")
            if move_name is None: return
            try:
                move_name = clean_name(move_name)
            except ValueError:
                await ctx.send("Invalid move name.")
                return
            key = move_name.casefold()
            if key in used:
                await ctx.send("Duplicate move names are not allowed within a profile.")
                return
            used.add(key)

            move_type = await ask(
                f"Move {index} type:\n" + "\n".join(f"- {x}" for x in MOVE_TYPES)
            )
            if move_type is None: return
            move_type = self._match_choice(move_type, MOVE_TYPES)
            if move_type is None:
                await ctx.send("Invalid move type.")
                return
            moves.append((move_name, move_type))

        try:
            profile = await self.bot.db.create_profile(
                ctx.guild.id, name, assigned_user.id, grade, starting_mastery, None, moves
            )
            fresh = await self.bot.db.get_profile(ctx.guild.id, profile.id)
        except Exception:
            log.exception("Profile creation failed")
            await ctx.send("The account could not be created. No changes were saved.")
            return

        embed = profile_embed(fresh, "ACCOUNT CREATED")
        await send_profile_update(self.bot, ctx.guild.id, embed)
        await ctx.send(embed=profile_embed(fresh, "Account created"))

    async def _resolve_member(self, guild: discord.Guild, raw: str) -> Optional[discord.Member]:
        if raw.startswith("<@") and raw.endswith(">"):
            raw = raw.replace("<@", "").replace("!", "").replace(">", "")
        try:
            user_id = int(raw)
        except ValueError:
            return None
        if user_id <= 0:
            return None
        return guild.get_member(user_id)

    @staticmethod
    def _match_choice(value: str, choices):
        lowered = value.strip().casefold()
        for choice in choices:
            if choice.casefold() == lowered:
                return choice
        return None

    @commands.command(name="edit-account")
    @commands.guild_only()
    async def edit_account(self, ctx, profile_id: str, field: str, *, value: str):
        if not await require_manager(ctx, self.bot.db):
            return
        try:
            pid = parse_profile_id(profile_id)
            field = field.lower().strip()
            if field == "name":
                changes = {"account_name": clean_name(value)}
            elif field == "user":
                member = await self._resolve_member(ctx.guild, value)
                if member is None:
                    await ctx.send("Invalid server member.")
                    return
                changes = {"assigned_user_id": member.id}
            elif field == "grade":
                grade = self._match_choice(value, GRADES)
                if grade is None:
                    await ctx.send("Invalid grade.")
                    return
                changes = {"grade": grade}
            elif field == "description":
                changes = {"description": clean_description(value)}
            else:
                await ctx.send("Field must be `name`, `user`, `grade`, or `description`.")
                return
            await self.bot.db.edit_profile(ctx.guild.id, pid, ctx.author.id, **changes)
            profile = await self.bot.db.get_profile(ctx.guild.id, pid)
        except LookupError:
            await ctx.send("That profile does not exist.")
            return
        except ValueError:
            await ctx.send("Invalid value.")
            return
        except Exception:
            log.exception("edit-account failed")
            await ctx.send("The request could not be completed. No changes were saved.")
            return
        await send_profile_update(self.bot, ctx.guild.id, profile_embed(profile, "PROFILE UPDATED"))
        await ctx.send(embed=profile_embed(profile, "Profile updated"))

    @commands.command(name="add-move")
    @commands.guild_only()
    async def add_move(self, ctx, profile_id: str, move_type: str, *, move_name: str):
        if not await require_manager(ctx, self.bot.db):
            return
        pid = parse_profile_id(profile_id)
        move_type = self._match_choice(move_type.replace("_", " "), MOVE_TYPES)
        if move_type is None:
            await ctx.send("Invalid move type.")
            return
        try:
            move_name = clean_name(move_name)
            await self.bot.db.add_move(ctx.guild.id, pid, ctx.author.id, move_name, move_type)
            profile = await self.bot.db.get_profile(ctx.guild.id, pid)
        except LookupError:
            await ctx.send("That profile does not exist.")
            return
        except ValueError:
            await ctx.send("That move already exists or the move name is invalid.")
            return
        except Exception:
            log.exception("add-move failed")
            await ctx.send("The request could not be completed. No changes were saved.")
            return
        await send_profile_update(self.bot, ctx.guild.id, profile_embed(profile, "MOVE UPDATED"))
        await ctx.send("Move added successfully.")

    @commands.command(name="remove-move")
    @commands.guild_only()
    async def remove_move(self, ctx, profile_id: str, *, move_name: str):
        if not await require_manager(ctx, self.bot.db):
            return
        try:
            pid = parse_profile_id(profile_id)
            await self.bot.db.remove_move(ctx.guild.id, pid, ctx.author.id, clean_name(move_name))
            profile = await self.bot.db.get_profile(ctx.guild.id, pid)
        except LookupError:
            await ctx.send("Profile or move not found.")
            return
        except ValueError:
            await ctx.send("Invalid move name.")
            return
        except Exception:
            log.exception("remove-move failed")
            await ctx.send("The request could not be completed. No changes were saved.")
            return
        await send_profile_update(self.bot, ctx.guild.id, profile_embed(profile, "MOVE UPDATED"))
        await ctx.send("Move removed successfully.")

    @commands.command(name="set-grade")
    @commands.guild_only()
    async def set_grade(self, ctx, profile_id: str, *, grade: str):
        if not await require_manager(ctx, self.bot.db):
            return
        grade = self._match_choice(grade, GRADES)
        if grade is None:
            await ctx.send("Invalid grade.")
            return
        try:
            pid = parse_profile_id(profile_id)
            await self.bot.db.set_grade(ctx.guild.id, pid, ctx.author.id, grade)
            profile = await self.bot.db.get_profile(ctx.guild.id, pid)
        except LookupError:
            await ctx.send("That profile does not exist.")
            return
        except Exception:
            log.exception("set-grade failed")
            await ctx.send("The request could not be completed. No changes were saved.")
            return
        await send_profile_update(self.bot, ctx.guild.id, profile_embed(profile, "PROFILE UPDATED"))
        await ctx.send("Grade updated.")

    @commands.command(name="assign-account")
    @commands.guild_only()
    async def assign_account(self, ctx, profile_id: str, user: discord.Member):
        if not await require_manager(ctx, self.bot.db):
            return
        try:
            pid = parse_profile_id(profile_id)
            await self.bot.db.edit_profile(ctx.guild.id, pid, ctx.author.id, assigned_user_id=user.id)
            profile = await self.bot.db.get_profile(ctx.guild.id, pid)
        except LookupError:
            await ctx.send("That profile does not exist.")
            return
        except Exception:
            log.exception("assign-account failed")
            await ctx.send("The request could not be completed. No changes were saved.")
            return
        await send_profile_update(self.bot, ctx.guild.id, profile_embed(profile, "PROFILE ASSIGNED"))
        await ctx.send(f"Profile assigned to {user.mention}.")

    @commands.command(name="unassign-account")
    @commands.guild_only()
    async def unassign_account(self, ctx, profile_id: str):
        if not await require_manager(ctx, self.bot.db):
            return
        try:
            pid = parse_profile_id(profile_id)
            await self.bot.db.edit_profile(ctx.guild.id, pid, ctx.author.id, assigned_user_id=None)
            profile = await self.bot.db.get_profile(ctx.guild.id, pid)
        except LookupError:
            await ctx.send("That profile does not exist.")
            return
        except Exception:
            log.exception("unassign-account failed")
            await ctx.send("The request could not be completed. No changes were saved.")
            return
        await send_profile_update(self.bot, ctx.guild.id, profile_embed(profile, "PROFILE UNASSIGNED"))
        await ctx.send("Profile unassigned.")
