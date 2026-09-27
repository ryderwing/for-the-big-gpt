import asyncio
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from models import (
    AuditLog,
    Base,
    GuildConfig,
    MasteryTransaction,
    Move,
    Profile,
)

MAX_INT = 2_000_000_000


class Database:
    def __init__(self, url: str):
        if url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite:///"):
            url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        self.url = url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: AsyncEngine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}

    async def initialize(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if self.url.startswith("sqlite"):
                await conn.execute(text("PRAGMA foreign_keys=ON"))
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.execute(text("PRAGMA synchronous=FULL"))

    async def close(self):
        await self.engine.dispose()

    def _lock_for(self, guild_id: int, profile_id: int) -> asyncio.Lock:
        key = (guild_id, profile_id)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def get_guild_config(self, guild_id: int) -> GuildConfig | None:
        async with self.session_factory() as session:
            return await session.get(GuildConfig, guild_id)

    async def upsert_guild_config(self, guild_id: int, role_id: int | None, channel_id: int | None):
        async with self.session_factory.begin() as session:
            cfg = await session.get(GuildConfig, guild_id)
            if cfg is None:
                cfg = GuildConfig(
                    guild_id=guild_id,
                    account_manager_role_id=role_id,
                    profiles_channel_id=channel_id,
                )
                session.add(cfg)
            else:
                if role_id is not None:
                    cfg.account_manager_role_id = role_id
                if channel_id is not None:
                    cfg.profiles_channel_id = channel_id
                cfg.updated_at = datetime.now(timezone.utc)

    async def create_profile(
        self, guild_id: int, account_name: str, assigned_user_id: int | None,
        grade: str, unspent_mastery: int, description: str | None,
        moves: Sequence[tuple[str, str]]
    ) -> Profile:
        async with self.session_factory.begin() as session:
            profile = Profile(
                guild_id=guild_id,
                account_name=account_name,
                assigned_user_id=assigned_user_id,
                grade=grade,
                unspent_mastery=unspent_mastery,
                description=description,
            )
            session.add(profile)
            await session.flush()
            for name, move_type in moves:
                session.add(Move(profile_id=profile.id, move_name=name, move_type=move_type, mastery=0))
            await session.flush()
            return profile

    async def get_profile(self, guild_id: int, profile_id: int, include_archived: bool = False) -> Profile | None:
        async with self.session_factory() as session:
            stmt = (
                select(Profile)
                .options(selectinload(Profile.moves))
                .where(Profile.guild_id == guild_id, Profile.id == profile_id)
            )
            if not include_archived:
                stmt = stmt.where(Profile.archived.is_(False))
            return (await session.execute(stmt)).scalar_one_or_none()

    async def get_profiles_for_user(self, guild_id: int, user_id: int) -> list[Profile]:
        async with self.session_factory() as session:
            stmt = (
                select(Profile)
                .options(selectinload(Profile.moves))
                .where(
                    Profile.guild_id == guild_id,
                    Profile.assigned_user_id == user_id,
                    Profile.archived.is_(False),
                )
                .order_by(Profile.id)
            )
            return list((await session.execute(stmt)).scalars().unique().all())

    async def list_profiles(self, guild_id: int, include_archived: bool = False) -> list[Profile]:
        async with self.session_factory() as session:
            stmt = (
                select(Profile)
                .options(selectinload(Profile.moves))
                .where(Profile.guild_id == guild_id)
                .order_by(Profile.id)
            )
            if not include_archived:
                stmt = stmt.where(Profile.archived.is_(False))
            return list((await session.execute(stmt)).scalars().unique().all())

    async def add_audit(
        self, session: AsyncSession, guild_id: int, executor_user_id: int,
        action: str, target_profile_id: int | None, details: str
    ):
        session.add(AuditLog(
            guild_id=guild_id,
            executor_user_id=executor_user_id,
            action=action,
            target_profile_id=target_profile_id,
            details=details[:4000],
        ))

    async def give_mastery(
        self, guild_id: int, profile_id: int, executor_user_id: int,
        amount: int, reason: str | None
    ) -> tuple[int, int, Profile]:
        if not 1 <= amount <= MAX_INT:
            raise ValueError("invalid amount")
        async with self._lock_for(guild_id, profile_id):
            async with self.session_factory.begin() as session:
                profile_stmt = select(Profile).where(Profile.id == profile_id).with_for_update()
                profile = (await session.execute(profile_stmt)).scalar_one_or_none()
                if not profile or profile.guild_id != guild_id or profile.archived:
                    raise LookupError("profile not found")
                previous = profile.unspent_mastery
                if previous > MAX_INT - amount:
                    raise ValueError("mastery overflow")
                profile.unspent_mastery = previous + amount
                session.add(MasteryTransaction(
                    guild_id=guild_id, profile_id=profile_id, user_id=executor_user_id,
                    amount=amount, transaction_type="GIVE", reason=reason
                ))
                await self.add_audit(
                    session, guild_id, executor_user_id, "MASTERY_GIVEN",
                    profile_id, f"amount={amount}; previous={previous}; new={profile.unspent_mastery}; reason={reason or ''}"
                )
                await session.flush()
                return previous, profile.unspent_mastery, profile

    async def spend_mastery(
        self, guild_id: int, profile_id: int, user_id: int,
        move_name: str, amount: int
    ) -> tuple[int, int, int, int, Profile, Move]:
        if not 1 <= amount <= MAX_INT:
            raise ValueError("invalid amount")
        async with self._lock_for(guild_id, profile_id):
            async with self.session_factory.begin() as session:
                profile_stmt = select(Profile).where(Profile.id == profile_id).with_for_update()
                profile = (await session.execute(profile_stmt)).scalar_one_or_none()
                if not profile or profile.guild_id != guild_id or profile.archived:
                    raise LookupError("profile not found")
                if profile.assigned_user_id != user_id:
                    raise PermissionError("not assigned")

                move_stmt = select(Move).where(
                    Move.profile_id == profile_id,
                    func.lower(Move.move_name) == move_name.lower(),
                )
                move = (await session.execute(move_stmt)).scalar_one_or_none()
                if move is None:
                    raise LookupError("move not found")

                caps = {"Normal Move": 50, "Black Flash": 20, "Domain Expansion": 60}
                cap = caps[move.move_type]
                if move.mastery + amount > cap:
                    raise ValueError(f"cap:{cap}")

                if profile.unspent_mastery < amount:
                    raise ValueError(f"available:{profile.unspent_mastery}")

                previous_balance = profile.unspent_mastery
                previous_mastery = move.mastery
                profile.unspent_mastery -= amount
                move.mastery += amount

                session.add(MasteryTransaction(
                    guild_id=guild_id, profile_id=profile_id, user_id=user_id,
                    amount=-amount, transaction_type="SPEND",
                    reason=f"Spent on {move.move_name}"
                ))
                await self.add_audit(
                    session, guild_id, user_id, "MASTERY_SPENT", profile_id,
                    f"move={move.move_name}; amount={amount}; balance={previous_balance}->{profile.unspent_mastery}; mastery={previous_mastery}->{move.mastery}"
                )
                await session.flush()
                return (
                    previous_balance, profile.unspent_mastery,
                    previous_mastery, move.mastery, profile, move
                )

    async def edit_profile(self, guild_id: int, profile_id: int, executor: int, **changes):
        allowed = {"account_name", "assigned_user_id", "grade", "description"}
        if not set(changes).issubset(allowed):
            raise ValueError("invalid fields")
        async with self._lock_for(guild_id, profile_id):
            async with self.session_factory.begin() as session:
                profile_stmt = select(Profile).where(Profile.id == profile_id).with_for_update()
                profile = (await session.execute(profile_stmt)).scalar_one_or_none()
                if not profile or profile.guild_id != guild_id or profile.archived:
                    raise LookupError("profile not found")
                before = {k: getattr(profile, k) for k in changes}
                for key, value in changes.items():
                    setattr(profile, key, value)
                await self.add_audit(
                    session, guild_id, executor, "PROFILE_EDITED", profile_id,
                    f"before={before}; after={changes}"
                )
                await session.flush()
                return profile

    async def set_grade(self, guild_id: int, profile_id: int, executor: int, grade: str):
        return await self.edit_profile(guild_id, profile_id, executor, grade=grade)

    async def add_move(self, guild_id: int, profile_id: int, executor: int, name: str, move_type: str):
        async with self._lock_for(guild_id, profile_id):
            async with self.session_factory.begin() as session:
                profile_stmt = select(Profile).where(Profile.id == profile_id).with_for_update()
                profile = (await session.execute(profile_stmt)).scalar_one_or_none()
                if not profile or profile.guild_id != guild_id or profile.archived:
                    raise LookupError("profile not found")
                existing = (await session.execute(
                    select(Move).where(
                        Move.profile_id == profile_id,
                        func.lower(Move.move_name) == name.lower()
                    )
                )).scalar_one_or_none()
                if existing:
                    raise ValueError("duplicate move")
                move = Move(profile_id=profile_id, move_name=name, move_type=move_type, mastery=0)
                session.add(move)
                await self.add_audit(
                    session, guild_id, executor, "MOVE_ADDED", profile_id,
                    f"name={name}; type={move_type}"
                )
                await session.flush()
                return move

    async def remove_move(self, guild_id: int, profile_id: int, executor: int, name: str):
        async with self._lock_for(guild_id, profile_id):
            async with self.session_factory.begin() as session:
                profile_stmt = select(Profile).where(Profile.id == profile_id).with_for_update()
                profile = (await session.execute(profile_stmt)).scalar_one_or_none()
                if not profile or profile.guild_id != guild_id or profile.archived:
                    raise LookupError("profile not found")
                move = (await session.execute(
                    select(Move).where(
                        Move.profile_id == profile_id,
                        func.lower(Move.move_name) == name.lower()
                    )
                )).scalar_one_or_none()
                if not move:
                    raise LookupError("move not found")
                await session.delete(move)
                await self.add_audit(
                    session, guild_id, executor, "MOVE_REMOVED", profile_id,
                    f"name={name}"
                )

    async def archive_profile(self, guild_id: int, profile_id: int, executor: int):
        async with self._lock_for(guild_id, profile_id):
            async with self.session_factory.begin() as session:
                profile_stmt = select(Profile).where(Profile.id == profile_id).with_for_update()
                profile = (await session.execute(profile_stmt)).scalar_one_or_none()
                if not profile or profile.guild_id != guild_id or profile.archived:
                    raise LookupError("profile not found")
                profile.archived = True
                await self.add_audit(
                    session, guild_id, executor, "PROFILE_DELETED", profile_id,
                    "profile archived; historical audit retained"
                )

    async def restore_profile(self, guild_id: int, profile_id: int, executor: int):
        async with self._lock_for(guild_id, profile_id):
            async with self.session_factory.begin() as session:
                profile = await session.get(Profile, profile_id)
                if not profile or profile.guild_id != guild_id or not profile.archived:
                    raise LookupError("archived profile not found")
                profile.archived = False
                await self.add_audit(
                    session, guild_id, executor, "PROFILE_RESTORED", profile_id, "profile restored"
                )

    async def history(self, guild_id: int, profile_id: int, limit: int = 20) -> list[AuditLog]:
        limit = max(1, min(100, limit))
        async with self.session_factory() as session:
            stmt = (
                select(AuditLog)
                .where(AuditLog.guild_id == guild_id, AuditLog.target_profile_id == profile_id)
                .order_by(AuditLog.id.desc())
                .limit(limit)
            )
            return list((await session.execute(stmt)).scalars().all())

    async def count_profiles(self, guild_id: int) -> int:
        async with self.session_factory() as session:
            return int((await session.execute(
                select(func.count(Profile.id)).where(
                    Profile.guild_id == guild_id, Profile.archived.is_(False)
                )
            )).scalar_one())

    async def backup(self, backup_dir: Path) -> Path:
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if self.url.startswith("sqlite"):
            source = self.engine.url.database
            if not source:
                raise RuntimeError("SQLite database path unavailable")
            source_path = Path(source)
            if not source_path.is_absolute():
                source_path = Path.cwd() / source_path
            target = backup_dir / f"jjk_rp_{stamp}.db"
            async with self.engine.connect() as conn:
                await conn.run_sync(lambda c: sqlite_backup(c, target))
            return target
        raise RuntimeError(
            "PostgreSQL backup requires pg_dump. Use the documented backup command on the database host."
        )


def sqlite_backup(connection, target: Path):
    raw = connection.connection.dbapi_connection
    target_conn = sqlite3.connect(target)
    try:
        raw.backup(target_conn)
    finally:
        target_conn.close()
