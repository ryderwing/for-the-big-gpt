# JJK RP Account Manager Discord Bot

Production-oriented Discord bot for Jujutsu Kaisen roleplay account/profile management.

The implementation follows the supplied specification: persistent profiles, Account Manager authorization, mastery accounting, move caps, audit logs, soft deletion, backups, cross-guild isolation, validation, and transaction-based changes.

## Current dependency

`discord.py==2.7.1` is pinned because it is the current stable release used by this project.

## Requirements

- Python 3.10+ recommended
- A Discord bot application
- Message Content Intent enabled in the Discord Developer Portal
- Server Members Intent enabled if you want reliable member resolution
- PostgreSQL for production, or SQLite for a smaller server

## Install

Windows:

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt
copy .env.example .env
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `DISCORD_TOKEN`.

For SQLite, the default is:

```env
DATABASE_URL=sqlite+aiosqlite:///./jjk_rp.db
```

For PostgreSQL:

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DATABASE
```

Never commit `.env`.

## Discord permissions

The bot needs only what it actually uses:

- View Channels
- Send Messages
- Embed Links
- Read Message History
- Manage Roles
- Manage Channels

`Manage Roles` and `Manage Channels` are required for `!setup`.

Do not give the bot Administrator unless your server policy specifically requires it.

The automatically created `Account Manager` role receives no Administrator permission.

The bot's role must be high enough in the role hierarchy to create/manage the Account Manager role.

Enable these privileged intents in the Developer Portal:

- Message Content Intent
- Server Members Intent

## Start

```bash
python main.py
```

The database schema is created automatically at startup.

## First setup

Run this as the server owner:

```text
!setup
```

The bot will reuse an existing configured role/channel when possible, making setup idempotent.

## Account commands

Managers/server owner:

```text
!create-account
!give-mastery <profile_id> <amount> [reason]
!edit-account <profile_id> name <new name>
!edit-account <profile_id> user <@user>
!edit-account <profile_id> grade <grade>
!edit-account <profile_id> description <text>
!add-move <profile_id> <move_type> <move name>
!remove-move <profile_id> <move name>
!set-grade <profile_id> <grade>
!assign-account <profile_id> <@user>
!unassign-account <profile_id>
!view-account <profile_id>
!list-accounts
!delete-account <profile_id>
!restore-account <profile_id>
!account-history <profile_id>
!backup
!healthcheck
```

Player commands:

```text
!profile
!profile <profile_id>
!mastery
!my-mastery
!spend-mastery <move> <amount>
```

## Grades

- 5th Grade
- 4th Grade
- 3rd Grade
- 2nd Grade
- 1st Grade
- Special Grade

## Move types and caps

- Normal Move: 50
- Black Flash: 20
- Domain Expansion: 60

Caps are enforced in the database transaction path.

## Security model

The database is the source of truth. The bot does not use JSON files or in-memory dictionaries for account state.

Important protections include:

- Environment-only secrets
- Parameterized SQL through SQLAlchemy
- Guild ID scoping on profile queries
- User ID ownership checks for player commands
- Server-side manager checks
- Input validation and bounded integers
- No stack traces or connection strings in Discord responses
- Audit logging for privileged/account changes
- Immediate transaction commits
- Per-profile async locking plus database transactions
- Atomic mastery state changes within a transaction
- Soft deletion instead of destructive hard deletion
- Confirmation tied to the manager/channel and short-lived
- Mention allowlists for intentional player pings
- No Administrator permission on the Account Manager role

No software can honestly be described as mathematically 100% secure. This project is designed to fail safely and reduce common security/data-integrity risks.

## Concurrency

Mastery spending is performed inside a transaction while the bot serializes operations for the same `(guild_id, profile_id)` in-process. The transaction validates the current balance and move cap before commit.

For multi-process deployments, use PostgreSQL and run a single bot process or add a distributed lock strategy. Do not run multiple independent bot workers against SQLite.

## Backups

### SQLite

`!backup` creates a timestamped SQLite backup in `BACKUP_DIR` without uploading it to Discord.

Do not keep only one backup. Copy backups to a separate storage location and retain multiple historical copies.

### PostgreSQL

For production PostgreSQL, use `pg_dump` from a trusted machine/backup host:

```bash
pg_dump --format=custom --file=backups/jjk_rp_$(date -u +%Y%m%dT%H%M%SZ).dump "$DATABASE_URL"
```

Restore with:

```bash
pg_restore --clean --if-exists --dbname="$DATABASE_URL" backups/FILE.dump
```

Do not post database dumps in Discord.

## Database schema

`schema.sql` documents the core schema and `migrations/001_initial.sql` is the initial SQL migration/reference. The application currently creates tables automatically at startup. For long-lived production deployments with evolving schemas, adopt Alembic migrations before making schema changes.

## Data isolation

Every profile lookup includes the current Discord guild ID. A profile ID from another server cannot be used to retrieve or modify that profile.

## Public profile channel

`!setup` creates/reuses `#profiles`. Important profile events are posted there as embeds. Private database fields and connection information are never included.

## Failure behavior

If a database transaction fails, SQLAlchemy rolls the transaction back. The bot then returns a generic failure message instead of exposing implementation details.

## Operational recommendations

- Use PostgreSQL for a busy production server.
- Run the bot under a dedicated OS account.
- Restrict filesystem access to the bot directory.
- Keep `.env` outside source control.
- Back up the database to a different machine/storage provider.
- Test restoration periodically.
- Keep Discord bot permissions minimal.
- Review `!account-history` when investigating unexpected changes.
