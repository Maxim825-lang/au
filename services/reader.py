import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_telethon_client = None
_telethon_available = False

_WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ─── Init / teardown ─────────────────────────────────────────────────────────

async def init_reader() -> None:
    global _telethon_client, _telethon_available

    from config import TELETHON_API_ID, TELETHON_API_HASH, TELETHON_PHONE, TELETHON_SESSION

    if not TELETHON_API_ID or not TELETHON_API_HASH:
        logger.info("Telethon не настроен — используется web-режим (t.me/s)")
        return

    from telethon import TelegramClient
    _telethon_client = TelegramClient(TELETHON_SESSION, TELETHON_API_ID, TELETHON_API_HASH)
    await _telethon_client.start(phone=TELETHON_PHONE or None)
    _telethon_available = True
    logger.info("Telethon reader запущен")


async def stop_reader() -> None:
    global _telethon_client, _telethon_available
    if _telethon_client:
        await _telethon_client.disconnect()
        _telethon_client = None
        _telethon_available = False
        logger.info("Telethon reader остановлен")


# ─── Mode flags ───────────────────────────────────────────────────────────────

def is_available() -> bool:
    """Always True — web scraping works without any credentials."""
    return True


def is_telethon_available() -> bool:
    return _telethon_available


# ─── Channel resolution ───────────────────────────────────────────────────────

async def resolve_channel(username: str) -> Optional[dict]:
    """Return {"username": ..., "title": ...} or None if channel not found."""
    if _telethon_available and _telethon_client:
        return await _resolve_telethon(username)
    return await _resolve_web(username)


async def _resolve_telethon(username: str) -> Optional[dict]:
    try:
        entity = await _telethon_client.get_entity(username)
        return {"username": username, "title": getattr(entity, "title", None)}
    except Exception as e:
        logger.warning("Telethon: не удалось получить канал %s: %s", username, e)
        return None


async def _resolve_web(username: str) -> Optional[dict]:
    import httpx
    from bs4 import BeautifulSoup

    channel = username.lstrip("@")
    url = f"https://t.me/s/{channel}"

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=_WEB_HEADERS)
            if resp.status_code == 404:
                return None

        soup = BeautifulSoup(resp.text, "html.parser")
        title_tag = soup.select_one(".tgme_channel_info_header_title")
        title = title_tag.get_text().strip() if title_tag else None
        return {"username": username, "title": title}

    except Exception as e:
        logger.warning("Web: не удалось проверить канал %s: %s", username, e)
        # Network error — allow adding without title rather than blocking
        return {"username": username, "title": None}


# ─── Post fetching ────────────────────────────────────────────────────────────

async def fetch_posts(
    sources: list[str],
    hours: int = 24,
    max_per_source: int = 20,
    seen: Optional[set] = None,
) -> list[dict]:
    """Fetch recent posts. Telethon when configured, otherwise t.me/s web scraping."""
    if seen is None:
        seen = set()

    if _telethon_available and _telethon_client:
        return await _fetch_telethon(sources, hours, max_per_source, seen)

    return await _fetch_web(sources, hours, max_per_source, seen)


async def _fetch_telethon(
    sources: list[str],
    hours: int,
    max_per_source: int,
    seen: set,
) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    results = []

    for username in sources:
        try:
            msgs = await _telethon_client.get_messages(username, limit=min(max_per_source * 3, 100))
            count = 0
            for msg in msgs:
                if not msg.text:
                    continue
                if msg.date < cutoff:
                    continue
                key = f"{username}:{msg.id}"
                if key in seen:
                    continue
                results.append({
                    "source": username,
                    "message_id": msg.id,
                    "text": msg.text,
                    "date": msg.date.isoformat(),
                })
                count += 1
                if count >= max_per_source:
                    break
        except Exception as e:
            logger.error("Telethon: ошибка чтения канала %s: %s", username, e)

    results.sort(key=lambda x: x["date"], reverse=True)
    return results


async def _fetch_web(
    sources: list[str],
    hours: int,
    max_per_source: int,
    seen: set,
) -> list[dict]:
    """Fetch posts via public t.me/s/<channel> pages (no credentials needed)."""
    import httpx
    from bs4 import BeautifulSoup

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    results = []

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for username in sources:
            channel = username.lstrip("@")
            url = f"https://t.me/s/{channel}"

            try:
                resp = await client.get(url, headers=_WEB_HEADERS)
                resp.raise_for_status()
            except Exception as e:
                logger.error("Web: не удалось загрузить %s: %s", url, e)
                continue

            try:
                soup = BeautifulSoup(resp.text, "html.parser")
                messages = soup.select(".tgme_widget_message")
                count = 0

                for msg_div in messages:
                    data_post = msg_div.get("data-post", "")
                    try:
                        msg_id = int(data_post.split("/")[-1])
                    except (ValueError, IndexError):
                        continue

                    key = f"{username}:{msg_id}"
                    if key in seen:
                        continue

                    time_tag = msg_div.select_one("time[datetime]")
                    if not time_tag:
                        continue

                    try:
                        msg_date = datetime.fromisoformat(time_tag.get("datetime", ""))
                        if msg_date.tzinfo is None:
                            msg_date = msg_date.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        continue

                    if msg_date < cutoff:
                        continue

                    text_tag = msg_div.select_one(".tgme_widget_message_text")
                    if not text_tag:
                        continue

                    text = text_tag.get_text(separator="\n").strip()
                    if not text:
                        continue

                    results.append({
                        "source": username,
                        "message_id": msg_id,
                        "text": text,
                        "date": msg_date.isoformat(),
                    })
                    count += 1
                    if count >= max_per_source:
                        break

            except Exception as e:
                logger.error("Web: ошибка парсинга канала %s: %s", username, e)

    results.sort(key=lambda x: x["date"], reverse=True)
    return results
