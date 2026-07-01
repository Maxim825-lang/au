import logging
from pathlib import Path
from config import MEDIA_DIR

logger = logging.getLogger(__name__)

MAX_VIDEO_SIZE_MB = 50


def get_media_path(filename: str) -> Path:
    return MEDIA_DIR / filename


def check_file_size_ok(file_size: int | None) -> bool:
    if file_size is None:
        return True
    return file_size <= MAX_VIDEO_SIZE_MB * 1024 * 1024
