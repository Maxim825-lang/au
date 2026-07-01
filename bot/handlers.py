import logging
from datetime import datetime, timezone

from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import database
from bot.keyboards import (
    main_menu_kb,
    post_type_kb,
    post_actions_kb,
    drafts_list_kb,
    scheduled_list_kb,
    history_list_kb,
    confirm_delete_kb,
)
from bot.states import NewPost
from config import ADMIN_ID, CHANNEL_ID
from services.publisher import publish_post
from services.scheduler import (
    schedule_post,
    cancel_scheduled_post,
    parse_schedule_input,
    format_dt_moscow,
    MOSCOW_TZ,
)

logger = logging.getLogger(__name__)
router = Router()

HELP_TEXT = """
<b>Команды бота:</b>

/start — главное меню
/newpost — создать новый пост
/drafts — черновики
/scheduled — запланированные посты
/history — история публикаций
/cancel — отменить текущее действие
/help — эта справка

<b>Типы постов:</b>
📝 Текст — только текстовое сообщение
🖼 Фото + текст — изображение с подписью
🎬 Видео + текст — видео с подписью

<b>Планирование:</b>
Укажи дату и время в формате: <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>
Например: <code>15.06.2026 19:30</code>
Часовой пояс: Europe/Moscow
"""


def admin_only(func):
    from functools import wraps

    @wraps(func)
    async def wrapper(event, *args, **kwargs):
        user_id = event.from_user.id if hasattr(event, "from_user") else None
        if user_id != ADMIN_ID:
            if isinstance(event, Message):
                await event.answer("Нет доступа.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Нет доступа.", show_alert=True)
            return
        return await func(event, *args, **kwargs)

    return wrapper


# ── /start ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
@admin_only
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привет! Я бот для ведения Telegram-канала.\nВыбери действие:",
        reply_markup=main_menu_kb(),
    )


# ── /help ───────────────────────────────────────────────────────────────────

@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
@admin_only
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")


# ── /cancel ─────────────────────────────────────────────────────────────────

@router.message(Command("cancel"))
@admin_only
async def cmd_cancel(message: Message, state: FSMContext):
    data = await state.get_data()
    post_id = data.get("post_id")
    if post_id:
        post = await database.get_post(post_id)
        if post and post["status"] == "draft":
            await database.delete_post(post_id)
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_menu_kb())


# ── /newpost ─────────────────────────────────────────────────────────────────

@router.message(Command("newpost"))
@router.message(F.text == "✏️ Новый пост")
@admin_only
async def cmd_newpost(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(NewPost.choosing_type)
    await message.answer("Что создаём?", reply_markup=post_type_kb())


@router.callback_query(F.data == "cancel")
@admin_only
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    post_id = data.get("post_id")
    if post_id:
        post = await database.get_post(post_id)
        if post and post["status"] == "draft":
            await database.delete_post(post_id)
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


# ── Выбор типа поста ─────────────────────────────────────────────────────────

@router.callback_query(NewPost.choosing_type, F.data.startswith("type:"))
@admin_only
async def cb_choose_type(callback: CallbackQuery, state: FSMContext):
    post_type = callback.data.split(":")[1]
    await state.update_data(post_type=post_type)

    if post_type == "text":
        await state.set_state(NewPost.waiting_text)
        await callback.message.edit_text("✏️ Напиши текст поста:")
    elif post_type == "photo":
        await state.set_state(NewPost.waiting_photo)
        await callback.message.edit_text("🖼 Отправь фото:")
    elif post_type == "video":
        await state.set_state(NewPost.waiting_video)
        await callback.message.edit_text("🎬 Отправь видео:")
    await callback.answer()


# ── TEXT post ─────────────────────────────────────────────────────────────────

@router.message(NewPost.waiting_text)
@admin_only
async def handle_text_input(message: Message, state: FSMContext):
    text = message.text or message.caption or ""
    if not text.strip():
        await message.answer("Пожалуйста, отправь текстовое сообщение.")
        return

    post_id = await database.create_post(post_type="text", text=text, media_type="none")
    await state.update_data(post_id=post_id)
    await state.set_state(None)
    logger.info("Created text draft post %s", post_id)

    await _send_preview(message, post_id)


# ── PHOTO post ────────────────────────────────────────────────────────────────

@router.message(NewPost.waiting_photo, F.photo)
@admin_only
async def handle_photo_input(message: Message, state: FSMContext):
    photo = message.photo[-1]
    file_id = photo.file_id
    await state.update_data(media_file_id=file_id, media_type="photo")
    await state.set_state(NewPost.waiting_photo_caption)
    await message.answer("📝 Напиши подпись к фото (или отправь /skip чтобы без подписи):")


@router.message(NewPost.waiting_photo, ~F.photo)
@admin_only
async def handle_photo_wrong(message: Message):
    await message.answer("Пожалуйста, отправь именно фото (не файл).")


@router.message(NewPost.waiting_photo_caption)
@admin_only
async def handle_photo_caption(message: Message, state: FSMContext):
    caption = "" if message.text == "/skip" else (message.text or "")
    data = await state.get_data()
    file_id = data["media_file_id"]

    post_id = await database.create_post(
        post_type="photo",
        text=caption,
        media_type="photo",
        media_file_id=file_id,
    )
    await state.update_data(post_id=post_id)
    await state.set_state(None)
    logger.info("Created photo draft post %s", post_id)

    await _send_preview(message, post_id)


# ── VIDEO post ────────────────────────────────────────────────────────────────

@router.message(NewPost.waiting_video, F.video)
@admin_only
async def handle_video_input(message: Message, state: FSMContext):
    from services.media_storage import check_file_size_ok

    video = message.video
    if not check_file_size_ok(video.file_size):
        await message.answer(
            "⚠️ Файл слишком большой для Telegram Bot API (лимит 50 МБ).\n"
            "Пожалуйста, отправь видео меньшего размера."
        )
        return

    await state.update_data(media_file_id=video.file_id, media_type="video")
    await state.set_state(NewPost.waiting_video_caption)
    await message.answer("📝 Напиши подпись к видео (или отправь /skip чтобы без подписи):")


@router.message(NewPost.waiting_video, ~F.video)
@admin_only
async def handle_video_wrong(message: Message):
    await message.answer("Пожалуйста, отправь именно видео-файл (не ссылку).")


@router.message(NewPost.waiting_video_caption)
@admin_only
async def handle_video_caption(message: Message, state: FSMContext):
    caption = "" if message.text == "/skip" else (message.text or "")
    data = await state.get_data()
    file_id = data["media_file_id"]

    post_id = await database.create_post(
        post_type="video",
        text=caption,
        media_type="video",
        media_file_id=file_id,
    )
    await state.update_data(post_id=post_id)
    await state.set_state(None)
    logger.info("Created video draft post %s", post_id)

    await _send_preview(message, post_id)


# ── Preview ───────────────────────────────────────────────────────────────────

async def _send_preview(message: Message, post_id: int):
    post = await database.get_post(post_id)
    if not post:
        await message.answer("Ошибка: пост не найден.")
        return

    caption = f"👁 <b>Предпросмотр поста #{post_id}</b>\n\n"

    if post["post_type"] == "text":
        await message.answer(
            caption + (post["text"] or ""),
            reply_markup=post_actions_kb(post_id, "draft"),
            parse_mode="HTML",
        )
    elif post["post_type"] == "photo":
        await message.answer_photo(
            post["media_file_id"],
            caption=(post["text"] or ""),
            reply_markup=post_actions_kb(post_id, "draft"),
        )
        await message.answer(
            caption + "⬆️ Фото с подписью выше",
            reply_markup=post_actions_kb(post_id, "draft"),
            parse_mode="HTML",
        )
    elif post["post_type"] == "video":
        await message.answer_video(
            post["media_file_id"],
            caption=(post["text"] or ""),
            reply_markup=post_actions_kb(post_id, "draft"),
        )
        await message.answer(
            caption + "⬆️ Видео с подписью выше",
            reply_markup=post_actions_kb(post_id, "draft"),
            parse_mode="HTML",
        )


async def _send_post_view(message: Message, post_id: int, edit: bool = False):
    post = await database.get_post(post_id)
    if not post:
        await message.answer("Пост не найден.")
        return

    status = post["status"]
    icons = {"draft": "📋", "scheduled": "🕐", "published": "✅", "failed": "❌"}
    icon = icons.get(status, "📄")

    info = f"{icon} Пост #{post_id} | {status}"
    if status == "scheduled" and post.get("scheduled_at"):
        info += f"\n⏰ Запланирован на: {format_dt_moscow(post['scheduled_at'])}"
    if status == "published" and post.get("published_at"):
        info += f"\n📅 Опубликован: {post['published_at'][:16]}"

    kb = post_actions_kb(post_id, status) if status in ("draft", "scheduled") else None

    text_body = post.get("text") or ""
    if post["post_type"] == "text":
        await message.answer(f"{info}\n\n{text_body}", reply_markup=kb, parse_mode="HTML")
    elif post["post_type"] == "photo":
        await message.answer_photo(post["media_file_id"], caption=text_body)
        await message.answer(info, reply_markup=kb, parse_mode="HTML")
    elif post["post_type"] == "video":
        await message.answer_video(post["media_file_id"], caption=text_body)
        await message.answer(info, reply_markup=kb, parse_mode="HTML")


# ── Post action callbacks ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("post:publish:"))
@admin_only
async def cb_publish_now(callback: CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[2])
    await callback.answer("Публикую...")
    success = await publish_post(callback.bot, post_id)
    if success:
        await callback.message.edit_text(f"✅ Пост #{post_id} опубликован в канал!")
    else:
        await callback.message.edit_text(
            f"❌ Не удалось опубликовать пост #{post_id}.\n"
            "Проверь, что бот является администратором канала."
        )
    await state.clear()


@router.callback_query(F.data.startswith("post:schedule:"))
@admin_only
async def cb_schedule(callback: CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[2])
    await state.update_data(post_id=post_id)
    await state.set_state(NewPost.waiting_schedule_time)
    await callback.message.answer(
        "⏰ Введи дату и время публикации (МСК):\n\n"
        "Формат: <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n"
        "Пример: <code>15.06.2026 19:30</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(NewPost.waiting_schedule_time)
@admin_only
async def handle_schedule_time(message: Message, state: FSMContext):
    data = await state.get_data()
    post_id = data.get("post_id")
    if not post_id:
        await message.answer("Ошибка: пост не найден.")
        await state.clear()
        return

    run_at = parse_schedule_input(message.text or "")
    if not run_at:
        await message.answer(
            "❌ Неверный формат. Попробуй ещё раз:\n<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>",
            parse_mode="HTML",
        )
        return

    from datetime import datetime
    now = datetime.now(MOSCOW_TZ)
    if run_at <= now:
        await message.answer("❌ Дата должна быть в будущем. Введи другое время:")
        return

    await database.update_post(post_id, status="scheduled", scheduled_at=run_at.isoformat())
    schedule_post(post_id, run_at)
    await state.clear()
    logger.info("Scheduled post %s at %s", post_id, run_at)

    formatted = run_at.strftime("%d.%m.%Y %H:%M")
    await message.answer(
        f"✅ Пост #{post_id} запланирован на <b>{formatted}</b> (МСК)",
        parse_mode="HTML",
        reply_markup=post_actions_kb(post_id, "scheduled"),
    )


@router.callback_query(F.data.startswith("post:reschedule:"))
@admin_only
async def cb_reschedule(callback: CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[2])
    await state.update_data(post_id=post_id)
    await state.set_state(NewPost.waiting_reschedule_time)
    await callback.message.answer(
        "⏰ Введи новую дату и время (МСК):\n\n"
        "Формат: <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(NewPost.waiting_reschedule_time)
@admin_only
async def handle_reschedule_time(message: Message, state: FSMContext):
    data = await state.get_data()
    post_id = data.get("post_id")

    run_at = parse_schedule_input(message.text or "")
    if not run_at:
        await message.answer(
            "❌ Неверный формат:\n<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>",
            parse_mode="HTML",
        )
        return

    from datetime import datetime
    if run_at <= datetime.now(MOSCOW_TZ):
        await message.answer("❌ Дата должна быть в будущем.")
        return

    cancel_scheduled_post(post_id)
    await database.update_post(post_id, scheduled_at=run_at.isoformat())
    schedule_post(post_id, run_at)
    await state.clear()

    formatted = run_at.strftime("%d.%m.%Y %H:%M")
    await message.answer(
        f"✅ Время публикации поста #{post_id} изменено на <b>{formatted}</b> (МСК)",
        parse_mode="HTML",
        reply_markup=post_actions_kb(post_id, "scheduled"),
    )


@router.callback_query(F.data.startswith("post:cancel_schedule:"))
@admin_only
async def cb_cancel_schedule(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[2])
    cancel_scheduled_post(post_id)
    await database.update_post(post_id, status="draft", scheduled_at=None)
    await callback.message.edit_text(
        f"🚫 Публикация поста #{post_id} отменена. Пост сохранён как черновик.",
        reply_markup=post_actions_kb(post_id, "draft"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("post:edit_text:"))
@admin_only
async def cb_edit_text(callback: CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[2])
    await state.update_data(post_id=post_id)
    await state.set_state(NewPost.editing_text)
    await callback.message.answer("✏️ Введи новый текст поста:")
    await callback.answer()


@router.message(NewPost.editing_text)
@admin_only
async def handle_edit_text(message: Message, state: FSMContext):
    data = await state.get_data()
    post_id = data.get("post_id")
    new_text = message.text or ""
    await database.update_post(post_id, text=new_text)
    await state.set_state(None)
    await message.answer("✅ Текст обновлён.")
    await _send_post_view(message, post_id)


@router.callback_query(F.data.startswith("post:save_draft:"))
@admin_only
async def cb_save_draft(callback: CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[2])
    await state.clear()
    await callback.message.edit_text(f"💾 Пост #{post_id} сохранён как черновик.")
    await callback.answer()


@router.callback_query(F.data.startswith("post:delete:"))
@admin_only
async def cb_delete_confirm(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        f"Удалить пост #{post_id}? Это действие нельзя отменить.",
        reply_markup=confirm_delete_kb(post_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("post:delete_confirm:"))
@admin_only
async def cb_delete_do(callback: CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[2])
    post = await database.get_post(post_id)
    if post and post["status"] == "scheduled":
        cancel_scheduled_post(post_id)
    await database.delete_post(post_id)
    await state.clear()
    await callback.message.edit_text(f"🗑 Пост #{post_id} удалён.")
    await callback.answer()


@router.callback_query(F.data.startswith("post:delete_cancel:"))
@admin_only
async def cb_delete_cancel(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[2])
    post = await database.get_post(post_id)
    status = post["status"] if post else "draft"
    await callback.message.edit_text(
        f"Отменено. Пост #{post_id} не удалён.",
        reply_markup=post_actions_kb(post_id, status),
    )
    await callback.answer()


# ── /drafts ───────────────────────────────────────────────────────────────────

@router.message(Command("drafts"))
@router.message(F.text == "📋 Черновики")
@admin_only
async def cmd_drafts(message: Message):
    drafts = await database.get_draft_posts()
    if not drafts:
        await message.answer("Черновиков нет.")
        return
    await message.answer(
        f"📋 <b>Черновики ({len(drafts)}):</b>",
        reply_markup=drafts_list_kb(drafts),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("draft:open:"))
@admin_only
async def cb_open_draft(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[2])
    await callback.answer()
    await _send_post_view(callback.message, post_id)


# ── /scheduled ────────────────────────────────────────────────────────────────

@router.message(Command("scheduled"))
@router.message(F.text == "🕐 Запланированные")
@admin_only
async def cmd_scheduled(message: Message):
    posts = await database.get_scheduled_posts()
    if not posts:
        await message.answer("Запланированных постов нет.")
        return
    await message.answer(
        f"🕐 <b>Запланированные ({len(posts)}):</b>",
        reply_markup=scheduled_list_kb(posts),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("scheduled:open:"))
@admin_only
async def cb_open_scheduled(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[2])
    await callback.answer()
    await _send_post_view(callback.message, post_id)


# ── /history ──────────────────────────────────────────────────────────────────

@router.message(Command("history"))
@router.message(F.text == "📜 История")
@admin_only
async def cmd_history(message: Message):
    posts = await database.get_published_posts(limit=20)
    if not posts:
        await message.answer("История публикаций пуста.")
        return
    await message.answer(
        f"📜 <b>Последние публикации ({len(posts)}):</b>",
        reply_markup=history_list_kb(posts),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("history:open:"))
@admin_only
async def cb_open_history(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[2])
    await callback.answer()
    await _send_post_view(callback.message, post_id)


# ── Menu back ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:main")
@admin_only
async def cb_menu_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Главное меню:")
    await callback.message.answer("Выбери действие:", reply_markup=main_menu_kb())
    await callback.answer()


# ── Fallback ──────────────────────────────────────────────────────────────────

@router.message()
async def fallback(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Нет доступа.")
        return
    await message.answer(
        "Не понял команду. Используй /help или кнопки меню.",
        reply_markup=main_menu_kb(),
    )
