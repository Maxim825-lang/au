from aiogram.fsm.state import State, StatesGroup


class NewPost(StatesGroup):
    choosing_type = State()
    waiting_text = State()
    waiting_photo = State()
    waiting_photo_caption = State()
    waiting_video = State()
    waiting_video_caption = State()
    editing_text = State()
    waiting_schedule_time = State()
    waiting_reschedule_time = State()


class DigestStates(StatesGroup):
    waiting_source = State()
    editing_text = State()
