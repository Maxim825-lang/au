import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore

import database
from config import TIMEZONE

logger = logging.getLogger(__name__)

MOSCOW_TZ = pytz.timezone(TIMEZONE)

_scheduler: AsyncIOScheduler | None = None
_bot = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            timezone=MOSCOW_TZ,
        )
    return _scheduler


def set_bot(bot) -> None:
    global _bot
    _bot = bot


def format_dt_moscow(iso_str: str) -> str:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")


def parse_schedule_input(text: str) -> datetime | None:
    text = text.strip()
    try:
        naive = datetime.strptime(text, "%d.%m.%Y %H:%M")
    except ValueError:
        return None
    return MOSCOW_TZ.localize(naive)


async def _publish_job(post_id: int) -> None:
    from services.publisher import publish_post
    logger.info("Scheduler: publishing post %s", post_id)
    await publish_post(_bot, post_id)


def schedule_post(post_id: int, run_at: datetime) -> None:
    scheduler = get_scheduler()
    job_id = f"post_{post_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(
        _publish_job,
        trigger="date",
        run_date=run_at,
        args=[post_id],
        id=job_id,
        replace_existing=True,
    )
    logger.info("Scheduled post %s at %s", post_id, run_at)


def cancel_scheduled_post(post_id: int) -> None:
    scheduler = get_scheduler()
    job_id = f"post_{post_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Cancelled scheduled job for post %s", post_id)


async def load_scheduled_posts() -> None:
    posts = await database.get_scheduled_posts()
    now = datetime.now(MOSCOW_TZ)
    for post in posts:
        if not post.get("scheduled_at"):
            continue
        run_at = datetime.fromisoformat(post["scheduled_at"])
        if run_at.tzinfo is None:
            run_at = MOSCOW_TZ.localize(run_at)
        if run_at <= now:
            logger.warning("Post %s scheduled time passed, publishing now", post["id"])
            from services.publisher import publish_post
            await publish_post(_bot, post["id"])
        else:
            schedule_post(post["id"], run_at)
