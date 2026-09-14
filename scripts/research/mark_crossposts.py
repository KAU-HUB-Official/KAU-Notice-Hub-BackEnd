"""연구 수집 원본에 교차 게시 표시를 붙인다. 공지는 지우거나 합치지 않는다.

같은 공지가 여러 게시판(예: 학사공지와 학과 게시판)에 올라온 경우를 같은 crosspost_group_id로 묶는다.
어느 게시판에 올라왔는지가 대상 정보일 수 있어 원본 행은 모두 남긴다.

규칙: 정규화 제목(크롤러 제목 중복 판정과 같은 공백·대소문자 정리)이 같고, 게시일 차이가
MAX_DAYS_APART일 이내이며, board_key가 다른 두 공지는 같은 그룹이다. 묶음은 전이적으로 닫는다
(A-B, B-C가 규칙을 만족하면 A·B·C가 한 그룹). 게시일이나 board_key가 없는 공지와 어느 그룹에도
들지 않은 공지는 crosspost_group_id가 None이다.

원본 파일은 덮어쓰지 않고 표시를 붙인 가공본을 따로 쓴다:
    .venv/bin/python -m scripts.research.mark_crossposts \\
        --input data/research/kau_notices_raw_<수집일>.json \\
        --output data/research/kau_notices_marked_<수집일>.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from app.crawler.policies.notice_policy import parse_published_date
from app.crawler.services.dedup_service import normalize_title_for_dedup

MAX_DAYS_APART = 7
GROUP_FIELD = "crosspost_group_id"


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, index: int) -> int:
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def mark_crossposts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """posts 순서를 유지한 사본에 crosspost_group_id를 붙여 돌려준다."""
    marked = [dict(post) for post in posts]
    buckets: dict[str, list[tuple[int, date, str]]] = defaultdict(list)
    for index, post in enumerate(marked):
        post[GROUP_FIELD] = None
        title_key = normalize_title_for_dedup(post.get("title"))
        published = parse_published_date(post.get("published_at"))
        board_key = str(post.get("board_key") or "")
        if title_key and published and board_key:
            buckets[title_key].append((index, published, board_key))

    groups = _UnionFind(len(marked))
    for entries in buckets.values():
        entries.sort(key=lambda entry: entry[1])
        for position, (index, published, board_key) in enumerate(entries):
            for other_index, other_published, other_board in entries[position + 1 :]:
                if (other_published - published).days > MAX_DAYS_APART:
                    break
                if other_board != board_key:
                    groups.union(index, other_index)

    members: dict[int, list[int]] = defaultdict(list)
    for entries in buckets.values():
        for index, _published, _board in entries:
            members[groups.find(index)].append(index)

    multi = [sorted(indexes) for indexes in members.values() if len(indexes) > 1]
    # 그룹 번호는 입력 순서와 무관하게 (가장 이른 게시일, 제목, URL) 순으로 매겨 재실행해도 같게 한다.
    multi.sort(
        key=lambda indexes: min(
            (
                parse_published_date(marked[i].get("published_at")),
                normalize_title_for_dedup(marked[i].get("title")),
                str(marked[i].get("original_url") or ""),
            )
            for i in indexes
        )
    )
    for number, indexes in enumerate(multi, start=1):
        for index in indexes:
            marked[index][GROUP_FIELD] = f"xp-{number:05d}"
    return marked


def summarize(marked: list[dict[str, Any]]) -> dict[str, Any]:
    sizes = Counter(post[GROUP_FIELD] for post in marked if post.get(GROUP_FIELD))
    return {
        "posts": len(marked),
        "groups": len(sizes),
        "posts_in_groups": sum(sizes.values()),
        "group_size_counts": dict(sorted(Counter(sizes.values()).items())),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="연구 수집 원본에 교차 게시 표시를 붙인다.")
    parser.add_argument("--input", type=Path, required=True, help="연구 수집 원본 JSON")
    parser.add_argument("--output", type=Path, required=True, help="표시를 붙인 가공본 JSON")
    args = parser.parse_args(argv)

    if args.output.resolve() == args.input.resolve():
        parser.error("원본을 덮어쓰지 않습니다. --output 을 다른 경로로 주세요.")

    posts = json.loads(args.input.read_text(encoding="utf-8"))
    marked = mark_crossposts(posts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(marked, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summarize(marked), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
