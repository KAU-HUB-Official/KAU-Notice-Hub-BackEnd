"""여러 테스트가 함께 쓰는 가짜 객체와 헬퍼."""

import time
from pathlib import Path

from app import chat_log
from app.name_masking import NameSpan


def wait_for_chat_rows(db: Path, session_id: str, count: int, timeout: float = 3.0) -> list:
    """스트림 경로의 저장은 백그라운드 태스크라 행이 count개 쌓일 때까지 잠시 기다렸다 읽는다."""
    deadline = time.monotonic() + timeout
    rows = chat_log.read_session_messages(db, session_id)
    while len(rows) < count and time.monotonic() < deadline:
        time.sleep(0.02)
        rows = chat_log.read_session_messages(db, session_id)
    return rows


class FakeFinder:
    """주어진 이름이 나오는 위치를 돌려주는 가짜 모델."""

    def __init__(self, *names: str):
        self.names = names
        self.calls = 0

    def find(self, text: str) -> list[NameSpan]:
        self.calls += 1
        spans = []
        for name in self.names:
            start = text.find(name)
            while start != -1:
                spans.append(NameSpan(start, start + len(name)))
                start = text.find(name, start + 1)
        return spans
