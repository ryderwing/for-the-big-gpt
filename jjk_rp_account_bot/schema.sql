-- Reference schema. The bot creates this schema automatically with SQLAlchemy.
-- For PostgreSQL deployments, run the bot once to create the tables.
-- Production migrations should be managed with Alembic once the schema is established.

CREATE TABLE guilds (
    guild_id BIGINT PRIMARY KEY,
    profiles_channel_id BIGINT,
    account_manager_role_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE profiles (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    account_name VARCHAR(100) NOT NULL,
    assigned_user_id BIGINT,
    grade VARCHAR(30) NOT NULL,
    unspent_mastery INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE moves (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    move_name VARCHAR(100) NOT NULL,
    move_type VARCHAR(30) NOT NULL,
    mastery INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_move_profile_name UNIQUE(profile_id, move_name)
);

CREATE TABLE mastery_transactions (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    amount INTEGER NOT NULL,
    transaction_type VARCHAR(30) NOT NULL,
    reason VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    executor_user_id BIGINT NOT NULL,
    action VARCHAR(50) NOT NULL,
    target_profile_id INTEGER,
    details TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_profiles_guild_active ON profiles(guild_id, archived);
CREATE INDEX ix_profiles_assigned_user ON profiles(assigned_user_id);
CREATE INDEX ix_moves_profile ON moves(profile_id);
CREATE INDEX ix_mastery_profile ON mastery_transactions(profile_id);
CREATE INDEX ix_audit_profile ON audit_logs(target_profile_id);
