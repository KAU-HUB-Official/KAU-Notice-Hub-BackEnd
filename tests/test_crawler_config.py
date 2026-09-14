"""크롤러 수집 기간·요청 간격 환경변수 검증.

기본값은 운영 수집 정책(365일, 0.5~1.2초)이다. 이 값은 모듈 import 시점에 한 번 읽혀
정책 함수의 기본 인자로 굳으므로, 환경변수가 실제 정리 판정까지 전달되는지는 새
프로세스에서 확인한다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.crawler import config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_positive_int_uses_default_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("X_DAYS", raising=False)
    assert config._positive_int_from_env("X_DAYS", 365) == 365


def test_positive_int_reads_override(monkeypatch) -> None:
    monkeypatch.setenv("X_DAYS", " 1110 ")
    assert config._positive_int_from_env("X_DAYS", 365) == 1110


@pytest.mark.parametrize("raw", ["0", "-5", "abc"])
def test_positive_int_rejects_invalid(monkeypatch, raw) -> None:
    monkeypatch.setenv("X_DAYS", raw)
    with pytest.raises(ValueError):
        config._positive_int_from_env("X_DAYS", 365)


def test_delay_range_reads_override(monkeypatch) -> None:
    monkeypatch.setenv("X_DELAY", "0.1, 0.3")
    assert config._delay_range_from_env("X_DELAY", (0.5, 1.2)) == (0.1, 0.3)


@pytest.mark.parametrize("raw", ["0.3", "0.3,0.1", "-0.1,0.2", "a,b"])
def test_delay_range_rejects_invalid(monkeypatch, raw) -> None:
    monkeypatch.setenv("X_DELAY", raw)
    with pytest.raises(ValueError):
        config._delay_range_from_env("X_DELAY", (0.5, 1.2))


def _prune_two_year_old_notice(extra_env: dict[str, str]) -> str:
    env = {k: v for k, v in os.environ.items() if k != "CRAWLER_RECENT_NOTICE_DAYS"}
    env.update(extra_env)
    code = (
        "from datetime import date\n"
        "from app.crawler.policies.notice_policy import should_prune_stale_notice\n"
        "print(should_prune_stale_notice(\n"
        "    {'published_at': '2024-09-14', 'is_permanent_notice': False},\n"
        "    current_date=date(2026, 9, 14),\n"
        "))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_recent_notice_days_env_reaches_prune_policy() -> None:
    # 기본 365일이면 2년 전 일반공지는 정리 대상이고, 1110일로 넓히면 보존한다.
    assert _prune_two_year_old_notice({}) == "True"
    assert _prune_two_year_old_notice({"CRAWLER_RECENT_NOTICE_DAYS": "1110"}) == "False"
