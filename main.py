import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, validate_config, LOGS_DIR, TELETHON_API_ID, TELETHON_API_HASH
from database import init_db
from bot.handlers import router
from bot.digest_handlers import digest_router
from services.scheduler import get_scheduler, set_bot, load_scheduled_posts


def setup_logging():
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(LOGS_DIR / "bot.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


async def on_startup(bot: Bot):
    set_bot(bot)
    scheduler = get_scheduler()
    scheduler.start()
    await load_scheduled_posts()

    from services.reader import init_reader
    try:
        await init_reader()
    except Exception as e:
        logging.getLogger(__name__).warning("Telethon init failed: %s — используется web-режим", e)

    if not (TELETHON_API_ID and TELETHON_API_HASH):
        logging.getLogger(__name__).info(
            "Telethon не настроен — выжимка работает через t.me/s (только публичные каналы)"
        )

    logging.getLogger(__name__).info("Бот запущен")


async def on_shutdown(bot: Bot):
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)

    from services.reader import stop_reader
    await stop_reader()

    logging.getLogger(__name__).info("Бот остановлен")


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    missing = validate_config()
    if missing:
        print(f"Заполни {', '.join(missing)} в .env")
        sys.exit(1)

    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(digest_router)
    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Starting polling...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
