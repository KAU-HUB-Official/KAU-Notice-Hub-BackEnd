from __future__ import annotations

import json
from pathlib import Path

from ..services.url_normalizer import canonicalize_original_url
from ..utils.logger import get_logger

logger = get_logger("crawler.services.post_store")


def load_existing_posts(output_path: Path) -> list[dict]:
    if not output_path.exists():
        return []

    try:
        with output_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except Exception as exc:  # noqa: BLE001
        logger.warning("기존 결과 파일 로드 실패: %s (%s)", output_path, exc)
        return []

    if not isinstance(data, list):
        logger.warning("기존 결과 파일 형식이 list가 아님: %s", output_path)
        return []

    valid_items = [item for item in data if isinstance(item, dict) and item.get("original_url")]
    if len(valid_items) != len(data):
        logger.warning(
            "기존 결과 파일의 일부 항목이 유효하지 않아 제외됨: valid=%s total=%s",
            len(valid_items),
            len(data),
        )

    normalized_items: list[dict] = []
    for item in valid_items:
        copied = dict(item)
        copied["original_url"] = canonicalize_original_url(str(copied["original_url"]))
        normalized_items.append(copied)
    return normalized_items
