from functools import wraps

from aiogram.types import Message, CallbackQuery

from config import ADMIN_ID


def admin_only(func):
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
