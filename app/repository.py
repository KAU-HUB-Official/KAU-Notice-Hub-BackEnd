from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import get_settings
from app.normalize import normalize_notice
from app.schemas import Notice


class NoticeRepositoryError(RuntimeError):
    pass


class NoticeRepository(Protocol):
    async def list_all(self) -> list[Notice]:
        ...

    async def get_by_id(self, notice_id: str) -> Notice | None:
        ...


@dataclass
class CacheEntry:
    file_path: Path
    mtime_ns: int
    notices: list[Notice]


class JsonNoticeRepository:
    def __init__(self, file_path: str | Path | None = None) -> None:
        configured_path = file_path or get_settings().notice_json_path
        self.file_path = Path(configured_path).expanduser().resolve()
        self._cache: CacheEntry | None = None

    async def list_all(self) -> list[Notice]:
        cache = self._read_and_normalize()
        return cache.notices

    async def get_by_id(self, notice_id: str) -> Notice | None:
        notices = await self.list_all()
        return next((notice for notice in notices if notice.id == notice_id), None)

    def _read_and_normalize(self) -> CacheEntry:
        try:
            file_stat = self.file_path.stat()
        except OSError as exc:
            if self._cache:
                return self._cache
            raise NoticeRepositoryError(f"공지 JSON 파일을 읽을 수 없습니다: {self.file_path}") from exc

        if self._cache and self._cache.mtime_ns == file_stat.st_mtime_ns:
            return self._cache

        try:
            parsed = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(parsed, list):
                raise ValueError("공지 JSON 파일은 배열(Array) 형식이어야 합니다.")

            used_ids: dict[str, int] = {}
            notices: list[Notice] = []
            for index, item in enumerate(parsed):
                if not isinstance(item, dict):
                    continue

                notice = normalize_notice(item, index)
                current = used_ids.get(notice.id, 0)
                used_ids[notice.id] = current + 1
                if current > 0:
                    notice = notice.model_copy(update={"id": f"{notice.id}-{current + 1}"})
                notices.append(notice)
        except Exception as exc:
            if self._cache:
                return self._cache
            raise NoticeRepositoryError(f"공지 JSON 파일을 정규화할 수 없습니다: {self.file_path}") from exc

        self._cache = CacheEntry(
            file_path=self.file_path,
            mtime_ns=file_stat.st_mtime_ns,
            notices=notices,
        )
        return self._cache

