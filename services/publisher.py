import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import database
from config import CHANNEL_ID

logger = logging.getLogger(__name__)


async def publish_post(bot: Bot, post_id: int) -> bool:
    post = await database.get_post(post_id)
    if not post:
        logger.error("publish_post: post %s not found", post_id)
        return False

    try:
        msg = await _send(bot, post)
        now = datetime.now(timezone.utc).isoformat()
        await database.update_post(
            post_id,
            status="published",
            published_at=now,
            telegram_message_id=msg.message_id,
        )
        logger.info("Post %s published, message_id=%s", post_id, msg.message_id)
        return True
    except TelegramAPIError as e:
        logger.error("Failed to publish post %s: %s", post_id, e)
        await database.update_post(post_id, status="failed")
        return False


async def _send(bot: Bot, post: dict):
    text = post.get("text") or ""
    post_type = post["post_type"]

    if post_type == "text":
        return await bot.send_message(CHANNEL_ID, text)

    if post_type == "photo":
        return await bot.send_photo(CHANNEL_ID, post["media_file_id"], caption=text)

    if post_type == "video":
        return await bot.send_video(CHANNEL_ID, post["media_file_id"], caption=text)

    raise ValueError(f"Unknown post_type: {post_type}")
