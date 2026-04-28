from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class Post:
    source_name: str
    source_type: str
    category_raw: Optional[str]
    title: str
    content: str
    published_at: Optional[str]
    original_url: str
    attachments: list[dict]
    crawled_at: str

    def to_dict(self) -> dict:
        return asdict(self)
