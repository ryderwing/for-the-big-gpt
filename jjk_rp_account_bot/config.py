import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    discord_token: str
    database_url: str
    prefix: str
    log_level: str
    backup_dir: Path
    wizard_timeout: int
    command_cooldown: float


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


settings = Settings(
    discord_token=os.getenv("DISCORD_TOKEN", "").strip(),
    database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./jjk_rp.db").strip(),
    prefix=os.getenv("PREFIX", "!").strip() or "!",
    log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    backup_dir=Path(os.getenv("BACKUP_DIR", "./backups")),
    wizard_timeout=_int_env("WIZARD_TIMEOUT_SECONDS", 300, 30, 1800),
    command_cooldown=_float_env("COMMAND_COOLDOWN_SECONDS", 1.0, 0.0, 30.0),
)
