import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID: str = os.getenv("CHANNEL_ID", "")

TIMEZONE = "Europe/Moscow"

DB_PATH = BASE_DIR / "database.db"
MEDIA_DIR = BASE_DIR / "data" / "media"
LOGS_DIR = BASE_DIR / "logs"
TELETHON_SESSION = str(BASE_DIR / "data" / "telethon_session")

MEDIA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Telethon — чтение каналов как пользователь
TELETHON_API_ID: int = int(os.getenv("TELETHON_API_ID", "0"))
TELETHON_API_HASH: str = os.getenv("TELETHON_API_HASH", "")
TELETHON_PHONE: str = os.getenv("TELETHON_PHONE", "")

# OpenAI / совместимый API
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Параметры выжимки
DIGEST_HOURS: int = int(os.getenv("DIGEST_HOURS", "24"))
DIGEST_MAX_POSTS: int = int(os.getenv("DIGEST_MAX_POSTS", "20"))

# Webhook (Render / production). Если пусто — запускается polling.
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")
WEB_SERVER_HOST: str = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
WEB_SERVER_PORT: int = int(os.getenv("WEB_SERVER_PORT", "10000"))


def validate_config() -> list[str]:
    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN")
    if not ADMIN_ID:
        errors.append("ADMIN_ID")
    if not CHANNEL_ID:
        errors.append("CHANNEL_ID")
    return errors
