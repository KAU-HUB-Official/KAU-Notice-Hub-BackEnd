from functools import lru_cache

from app.repository import JsonNoticeRepository
from app.service import NoticeService


@lru_cache
def get_notice_service() -> NoticeService:
    return NoticeService(JsonNoticeRepository())

