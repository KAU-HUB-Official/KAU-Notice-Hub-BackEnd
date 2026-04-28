import json
from pathlib import Path

import pytest

from app.config import Settings
from app import crawler_scheduler
from app.crawler_scheduler import publish_crawler_snapshot


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_publish_crawler_snapshot_replaces_file_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_path = tmp_path / "notices.json"
    write_json(final_path, [{"id": "old"}])

    def fake_crawl_all_notices(*, max_pages: int, output_path: Path):
        assert max_pages == 7
        write_json(output_path, [{"id": "new"}, {"id": "new-2"}])
        return [{"id": "new"}, {"id": "new-2"}], []

    monkeypatch.setattr(crawler_scheduler, "_crawl_all_notices", fake_crawl_all_notices)

    result = publish_crawler_snapshot(
        Settings(
            notice_json_path=final_path,
            crawler_max_pages=7,
            crawler_min_records=1,
            crawler_min_retain_ratio=0.5,
        )
    )

    assert result is not None
    assert result.output_path == final_path.resolve()
    assert result.total_records == 2
    assert json.loads(final_path.read_text(encoding="utf-8")) == [
        {"id": "new"},
        {"id": "new-2"},
    ]


def test_publish_crawler_snapshot_keeps_file_on_large_record_drop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_path = tmp_path / "notices.json"
    write_json(final_path, [{"id": str(index)} for index in range(10)])

    def fake_crawl_all_notices(*, max_pages: int, output_path: Path):
        write_json(output_path, [{"id": "only-one"}])
        return [{"id": "only-one"}], []

    monkeypatch.setattr(crawler_scheduler, "_crawl_all_notices", fake_crawl_all_notices)

    with pytest.raises(ValueError, match="record count dropped"):
        publish_crawler_snapshot(
            Settings(
                notice_json_path=final_path,
                crawler_min_records=1,
                crawler_min_retain_ratio=0.5,
            )
        )

    assert len(json.loads(final_path.read_text(encoding="utf-8"))) == 10
