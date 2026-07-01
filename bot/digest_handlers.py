import json
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import database
from bot.keyboards import digest_draft_kb, sources_remove_kb
from bot.states import DigestStates
from bot.utils import admin_only
from config import CHANNEL_ID, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, DIGEST_HOURS, DIGEST_MAX_POSTS

logger = logging.getLogger(__name__)
digest_router = Router()


# ─── /digest ─────────────────────────────────────────────────────────────────

@digest_router.message(Command("digest"))
@digest_router.message(F.text == "📰 Выжимка")
@admin_only
async def cmd_digest(message: Message, state: FSMContext):
    sources = await database.get_active_sources()
    if not sources:
        await message.answer(
            "Источников нет. Добавь каналы командой:\n/addsource @channelname"
        )
        return

    if not OPENAI_API_KEY:
        await message.answer(
            "❌ OpenAI не настроен.\n"
            "Укажи OPENAI_API_KEY в .env и перезапусти бота."
        )
        return

    from services.reader import is_telethon_available
    mode = "Telethon" if is_telethon_available() else "web (t.me/s)"
    status_msg = await message.answer(f"⏳ Собираю новости из источников [{mode}]...")

    try:
        source_usernames = [s["username"] for s in sources]
        seen = await database.get_seen_keys(source_usernames)

        from services.reader import fetch_posts
        posts = await fetch_posts(
            sources=source_usernames,
            hours=DIGEST_HOURS,
            max_per_source=DIGEST_MAX_POSTS,
            seen=seen,
        )

        if not posts:
            await status_msg.edit_text(
                f"📭 Новых постов за последние {DIGEST_HOURS} ч. не найдено.\n"
                "Все посты уже были обработаны или источники молчат."
            )
            return

        await status_msg.edit_text(
            f"🤖 Нашёл {len(posts)} постов. Генерирую выжимку..."
        )

        from services.ai import generate_digest
        digest_text = await generate_digest(posts)

        digest_id = await database.create_digest(
            text=digest_text,
            sources_used=",".join(source_usernames),
            raw_posts_json=json.dumps(posts, ensure_ascii=False),
        )

        await status_msg.edit_text(
            f"📋 <b>Черновик выжимки:</b>\n\n{digest_text}",
            reply_markup=digest_draft_kb(digest_id),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error("Ошибка при создании выжимки: %s", e)
        await status_msg.edit_text(f"❌ Ошибка: {e}")


# ─── Callbacks: ✅ Опубликовать ───────────────────────────────────────────────

@digest_router.callback_query(F.data.startswith("digest:publish:"))
@admin_only
async def cb_digest_publish(callback: CallbackQuery, state: FSMContext):
    digest_id = int(callback.data.split(":")[2])
    digest = await database.get_digest(digest_id)
    if not digest:
        await callback.answer("Выжимка не найдена.", show_alert=True)
        return

    await callback.answer("Публикую...")

    try:
        msg = await callback.bot.send_message(
            CHANNEL_ID,
            digest["text"],
            parse_mode="HTML",
        )
        await database.update_digest(
            digest_id,
            status="published",
            published_at=msg.date.isoformat(),
            telegram_message_id=msg.message_id,
        )

        posts = json.loads(digest.get("raw_posts") or "[]")
        for p in posts:
            await database.mark_seen(p["source"], p["message_id"])

        await state.clear()
        await callback.message.edit_text("✅ Выжимка опубликована в канал!")

    except Exception as e:
        logger.error("Ошибка публикации выжимки %s: %s", digest_id, e)
        await callback.message.edit_text(f"❌ Ошибка публикации: {e}")


# ─── Callbacks: 🔁 Переделать ────────────────────────────────────────────────

@digest_router.callback_query(F.data.startswith("digest:redo:"))
@admin_only
async def cb_digest_redo(callback: CallbackQuery, state: FSMContext):
    digest_id = int(callback.data.split(":")[2])
    digest = await database.get_digest(digest_id)
    if not digest:
        await callback.answer("Выжимка не найдена.", show_alert=True)
        return

    posts = json.loads(digest.get("raw_posts") or "[]")
    if not posts:
        await callback.message.edit_text(
            "❌ Данные постов утрачены. Запусти /digest заново."
        )
        await callback.answer()
        return

    await callback.answer("Генерирую заново...")
    await callback.message.edit_text("🤖 Генерирую новую версию выжимки...")

    try:
        from services.ai import generate_digest
        new_text = await generate_digest(posts)
        await database.update_digest(digest_id, text=new_text)

        await callback.message.edit_text(
            f"📋 <b>Черновик выжимки (новая версия):</b>\n\n{new_text}",
            reply_markup=digest_draft_kb(digest_id),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error("Ошибка при переделке выжимки %s: %s", digest_id, e)
        await callback.message.edit_text(f"❌ Ошибка: {e}")


# ─── Callbacks: 📝 Изменить текст ────────────────────────────────────────────

@digest_router.callback_query(F.data.startswith("digest:edit:"))
@admin_only
async def cb_digest_edit(callback: CallbackQuery, state: FSMContext):
    digest_id = int(callback.data.split(":")[2])
    await state.update_data(digest_id=digest_id)
    await state.set_state(DigestStates.editing_text)
    await callback.message.answer("✏️ Введи новый текст выжимки:")
    await callback.answer()


@digest_router.message(DigestStates.editing_text)
@admin_only
async def handle_digest_edit_text(message: Message, state: FSMContext):
    data = await state.get_data()
    digest_id = data.get("digest_id")
    new_text = message.text or ""

    await database.update_digest(digest_id, text=new_text)
    await state.set_state(None)

    await message.answer(
        f"📋 <b>Обновлённый черновик:</b>\n\n{new_text}",
        reply_markup=digest_draft_kb(digest_id),
        parse_mode="HTML",
    )


# ─── Callbacks: ❌ Отмена ────────────────────────────────────────────────────

@digest_router.callback_query(F.data.startswith("digest:cancel:"))
@admin_only
async def cb_digest_cancel(callback: CallbackQuery, state: FSMContext):
    digest_id = int(callback.data.split(":")[2])
    await database.delete_digest(digest_id)
    await state.clear()
    await callback.message.edit_text("❌ Выжимка отменена.")
    await callback.answer()


# ─── /sources ────────────────────────────────────────────────────────────────

@digest_router.message(Command("sources"))
@digest_router.message(F.text == "📡 Источники")
@admin_only
async def cmd_sources(message: Message):
    sources = await database.get_active_sources()
    if not sources:
        await message.answer(
            "Источников нет.\n\nДобавь канал командой:\n/addsource @channelname"
        )
        return

    lines = ["<b>Источники новостей:</b>\n"]
    for s in sources:
        line = f"• {s['username']}"
        if s.get("title"):
            line += f" — {s['title']}"
        lines.append(line)

    lines.append("\nДля удаления используй /removesource")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── /addsource ──────────────────────────────────────────────────────────────

@digest_router.message(Command("addsource"))
@admin_only
async def cmd_addsource(message: Message, state: FSMContext):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        await _do_add_source(message, parts[1].strip())
    else:
        await state.set_state(DigestStates.waiting_source)
        await message.answer("Введи юзернейм канала (например: @durov или durov):")


@digest_router.message(DigestStates.waiting_source)
@admin_only
async def handle_add_source_input(message: Message, state: FSMContext):
    await state.clear()
    await _do_add_source(message, (message.text or "").strip())


async def _do_add_source(message: Message, raw: str):
    if not raw:
        await message.answer("Укажи юзернейм канала.")
        return

    username = raw.lstrip("@").lower()
    username = "@" + username

    existing = await database.get_source_by_username(username)
    if existing:
        await message.answer(f"Канал {username} уже в списке источников.")
        return

    from services.reader import resolve_channel, is_telethon_available

    info = await resolve_channel(username)
    if info is None:
        if is_telethon_available():
            await message.answer(
                f"❌ Канал {username} не найден или нет доступа.\n"
                "Убедись, что аккаунт Telethon подписан на этот канал."
            )
        else:
            await message.answer(
                f"❌ Канал {username} не найден.\n"
                "Убедись, что канал публичный и доступен по ссылке t.me/s/<channel>."
            )
        return

    title = info.get("title")
    await database.add_source(username=username, title=title)
    title_str = f" ({title})" if title else ""
    await message.answer(f"✅ Источник добавлен: {username}{title_str}")


# ─── /removesource ───────────────────────────────────────────────────────────

@digest_router.message(Command("removesource"))
@admin_only
async def cmd_removesource(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        raw = parts[1].strip()
        username = "@" + raw.lstrip("@").lower()
        await _do_remove_by_username(message, username)
        return

    sources = await database.get_active_sources()
    if not sources:
        await message.answer("Источников нет.")
        return

    await message.answer(
        "Выбери источник для удаления:",
        reply_markup=sources_remove_kb(sources),
    )


@digest_router.callback_query(F.data.startswith("source:remove:"))
@admin_only
async def cb_remove_source(callback: CallbackQuery):
    source_id = int(callback.data.split(":")[2])
    source = await database.get_source(source_id)
    if source:
        await database.remove_source(source_id)
        await callback.message.edit_text(f"✅ Источник {source['username']} удалён.")
    else:
        await callback.message.edit_text("Источник не найден.")
    await callback.answer()


async def _do_remove_by_username(message: Message, username: str):
    source = await database.get_source_by_username(username)
    if not source:
        await message.answer(f"Источник {username} не найден.")
        return
    await database.remove_source(source["id"])
    await message.answer(f"✅ Источник {username} удалён.")


# ─── /settings ───────────────────────────────────────────────────────────────

@digest_router.message(Command("settings"))
@admin_only
async def cmd_settings(message: Message):
    from services.reader import is_telethon_available

    if is_telethon_available():
        reader_status = "✅ Telethon (полный доступ)"
    else:
        reader_status = "✅ Web-режим (t.me/s, только публичные каналы)"

    ai_status = "✅ Настроен" if OPENAI_API_KEY else "❌ Не настроен"

    sources = await database.get_active_sources()

    text = (
        "<b>⚙️ Настройки бота</b>\n\n"
        f"<b>Режим чтения каналов:</b> {reader_status}\n"
        f"<b>OpenAI</b> (генерация): {ai_status}\n"
        f"Модель: <code>{OPENAI_MODEL}</code>\n"
        f"API Base: <code>{OPENAI_BASE_URL}</code>\n\n"
        f"Период выжимки: <b>{DIGEST_HOURS} ч.</b>\n"
        f"Макс. постов с канала: <b>{DIGEST_MAX_POSTS}</b>\n"
        f"Источников: <b>{len(sources)}</b>\n\n"
        "Для изменения параметров отредактируй .env и перезапусти бота."
    )
    await message.answer(text, parse_mode="HTML")
