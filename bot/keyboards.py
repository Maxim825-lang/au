from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✏️ Новый пост"), KeyboardButton(text="📋 Черновики")],
            [KeyboardButton(text="🕐 Запланированные"), KeyboardButton(text="📜 История")],
            [KeyboardButton(text="📰 Выжимка"), KeyboardButton(text="📡 Источники")],
            [KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
    )


def post_type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📝 Текст", callback_data="type:text"))
    builder.row(InlineKeyboardButton(text="🖼 Фото + текст", callback_data="type:photo"))
    builder.row(InlineKeyboardButton(text="🎬 Видео + текст", callback_data="type:video"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


def post_actions_kb(post_id: int, status: str = "draft") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if status in ("draft", "scheduled"):
        builder.row(InlineKeyboardButton(text="🚀 Опубликовать сейчас", callback_data=f"post:publish:{post_id}"))
    if status == "draft":
        builder.row(InlineKeyboardButton(text="⏰ Запланировать", callback_data=f"post:schedule:{post_id}"))
        builder.row(InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"post:edit_text:{post_id}"))
        builder.row(InlineKeyboardButton(text="💾 Сохранить черновик", callback_data=f"post:save_draft:{post_id}"))
    if status == "scheduled":
        builder.row(InlineKeyboardButton(text="🕐 Изменить время", callback_data=f"post:reschedule:{post_id}"))
        builder.row(InlineKeyboardButton(text="🚫 Отменить публикацию", callback_data=f"post:cancel_schedule:{post_id}"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"post:delete:{post_id}"))
    return builder.as_markup()


def drafts_list_kb(drafts: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in drafts:
        label = _post_label(d)
        builder.row(InlineKeyboardButton(text=label, callback_data=f"draft:open:{d['id']}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main"))
    return builder.as_markup()


def scheduled_list_kb(posts: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in posts:
        label = _post_label(p, show_time=True)
        builder.row(InlineKeyboardButton(text=label, callback_data=f"scheduled:open:{p['id']}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main"))
    return builder.as_markup()


def history_list_kb(posts: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in posts:
        label = _post_label(p, show_published=True)
        builder.row(InlineKeyboardButton(text=label, callback_data=f"history:open:{p['id']}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main"))
    return builder.as_markup()


def confirm_delete_kb(post_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"post:delete_confirm:{post_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"post:delete_cancel:{post_id}"),
    )
    return builder.as_markup()


def digest_draft_kb(digest_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"digest:publish:{digest_id}"))
    builder.row(InlineKeyboardButton(text="🔁 Переделать", callback_data=f"digest:redo:{digest_id}"))
    builder.row(InlineKeyboardButton(text="📝 Изменить текст", callback_data=f"digest:edit:{digest_id}"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"digest:cancel:{digest_id}"))
    return builder.as_markup()


def sources_remove_kb(sources: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in sources:
        label = s["username"]
        if s.get("title"):
            label += f" — {s['title']}"
        builder.row(InlineKeyboardButton(
            text=f"❌ {label}",
            callback_data=f"source:remove:{s['id']}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main"))
    return builder.as_markup()


def _post_label(post: dict, show_time: bool = False, show_published: bool = False) -> str:
    icons = {"text": "📝", "photo": "🖼", "video": "🎬"}
    icon = icons.get(post["post_type"], "📄")
    text = (post.get("text") or "")[:30]
    label = f"{icon} #{post['id']} {text}"
    if show_time and post.get("scheduled_at"):
        from services.scheduler import format_dt_moscow
        label += f" | {format_dt_moscow(post['scheduled_at'])}"
    if show_published and post.get("published_at"):
        label += f" | {post['published_at'][:16]}"
    return label
