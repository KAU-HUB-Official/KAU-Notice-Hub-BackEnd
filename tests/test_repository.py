import asyncio
import json

from app.repository import JsonNoticeRepository


def write_json(path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_repository_normalizes_duplicate_ids_and_reloads(tmp_path) -> None:
    json_path = tmp_path / "notices.json"
    write_json(
        json_path,
        [
            {"id": "same", "title": "첫 공지", "content": "본문"},
            {"id": "same", "title": "둘째 공지", "content": "본문"},
        ],
    )
    repository = JsonNoticeRepository(json_path)

    first = asyncio.run(repository.list_all())
    assert [notice.id for notice in first] == ["same", "same-2"]

    write_json(json_path, [{"id": "next", "title": "새 공지", "content": "본문"}])
    second = asyncio.run(repository.list_all())

    assert [notice.id for notice in second] == ["next"]


def test_repository_keeps_previous_cache_on_invalid_reload(tmp_path) -> None:
    json_path = tmp_path / "notices.json"
    write_json(json_path, [{"id": "ok", "title": "정상 공지", "content": "본문"}])
    repository = JsonNoticeRepository(json_path)

    first = asyncio.run(repository.list_all())
    json_path.write_text("{ invalid json", encoding="utf-8")
    second = asyncio.run(repository.list_all())

    assert [notice.id for notice in first] == ["ok"]
    assert [notice.id for notice in second] == ["ok"]

