from __future__ import annotations

import asyncio
import sqlite3
from math import ceil
from pathlib import Path

from app.classification import (
    classify_notice_audience,
    classify_notice_source_groups,
    get_clean_categories,
    normalize_filter_value,
    should_use_source_filter,
)
from app.config import get_settings
from app.db import SCHEMA_VERSION, connect, initialize_schema, read_schema_version
from app.repository import (
    NoticeRepositoryError,
    NoticeSearchQuery,
    NoticeSearchResult,
)
from app.schemas import Notice, NoticeAttachment, NoticeFacets
from app.search import (
    compact,
    compact_search_text,
    expand_search_terms,
    extract_search_terms,
    normalize_whitespace,
    rank_notices,
)


SEARCH_CANDIDATE_LIMIT = 500
_SOURCE_DELIMITER = "\x1f"


class SqliteNoticeRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        configured = db_path or get_settings().notice_db_path
        self.db_path = Path(configured).expanduser().resolve()
        self._schema_ready = False

    def schema_version(self) -> int:
        try:
            conn = connect(self.db_path)
        except sqlite3.Error:
            return 0
        try:
            return read_schema_version(conn)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = connect(self.db_path)
            if not self._schema_ready:
                initialize_schema(conn)
                self._schema_ready = True
            return conn
        except sqlite3.Error as exc:
            raise NoticeRepositoryError(
                f"공지 DB에 연결할 수 없습니다: {self.db_path}"
            ) from exc

    async def list_all(self) -> list[Notice]:
        return await asyncio.to_thread(self._list_all_sync)

    async def get_by_id(self, notice_id: str) -> Notice | None:
        return await asyncio.to_thread(self._get_by_id_sync, notice_id)

    async def search(self, query: NoticeSearchQuery) -> NoticeSearchResult:
        return await asyncio.to_thread(self._search_sync, query)

    def _list_all_sync(self) -> list[Notice]:
        conn = self._connect()
        try:
            return _fetch_all(conn)
        except sqlite3.Error as exc:
            raise NoticeRepositoryError("공지 DB 조회 중 오류가 발생했습니다.") from exc
        finally:
            conn.close()

    def _get_by_id_sync(self, notice_id: str) -> Notice | None:
        conn = self._connect()
        try:
            return _fetch_one(conn, notice_id)
        except sqlite3.Error as exc:
            raise NoticeRepositoryError("공지 DB 조회 중 오류가 발생했습니다.") from exc
        finally:
            conn.close()

    def _search_sync(self, query: NoticeSearchQuery) -> NoticeSearchResult:
        conn = self._connect()
        try:
            return _search(conn, query)
        except sqlite3.Error as exc:
            raise NoticeRepositoryError("공지 DB 조회 중 오류가 발생했습니다.") from exc
        finally:
            conn.close()


def _search(conn: sqlite3.Connection, query: NoticeSearchQuery) -> NoticeSearchResult:
    audience = normalize_filter_value(query.audience_group)
    requested_source_group = normalize_filter_value(query.source_group)
    source = normalize_filter_value(query.source)
    category = normalize_filter_value(query.category)
    department = normalize_filter_value(query.department)
    source_filter_enabled = should_use_source_filter(query.audience_group)

    source_groups_in_audience = _query_source_groups(conn, audience)
    effective_source_group = (
        requested_source_group
        if requested_source_group and requested_source_group in source_groups_in_audience
        else None
    )

    facets = NoticeFacets(
        audienceGroups=_query_audience_groups(conn),
        sourceGroups=source_groups_in_audience,
        sources=(
            _query_sources(conn, audience, effective_source_group)
            if source_filter_enabled
            else []
        ),
        categories=_query_categories(conn, audience, effective_source_group),
        departments=_query_departments(conn, audience, effective_source_group),
    )

    where_clauses, params = _build_main_where(
        audience=audience,
        source_group=effective_source_group,
        source=source if source_filter_enabled else None,
        category=category,
        department=department,
    )

    page_size = max(1, query.page_size)
    page = max(1, query.page)

    if query.q and normalize_whitespace(query.q):
        items, total = _search_with_query(
            conn,
            where_clauses=where_clauses,
            params=params,
            q=query.q,
            page=page,
            page_size=page_size,
        )
    else:
        items, total = _paginate_no_query(
            conn,
            where_clauses=where_clauses,
            params=params,
            page=page,
            page_size=page_size,
        )

    return NoticeSearchResult(
        items=items,
        total=total,
        facets=facets,
        effective_source_group=effective_source_group,
    )


def _build_main_where(
    *,
    audience: str | None,
    source_group: str | None,
    source: str | None,
    category: str | None,
    department: str | None,
) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if audience:
        clauses.append("n.audience_group = ?")
        params.append(audience)
    if source_group:
        clauses.append(
            "EXISTS(SELECT 1 FROM notice_source_groups sg "
            "WHERE sg.notice_id = n.id AND sg.source_group = ?)"
        )
        params.append(source_group)
    if source:
        clauses.append(
            "EXISTS(SELECT 1 FROM notice_sources s "
            "WHERE s.notice_id = n.id AND s.source_name = ?)"
        )
        params.append(source)
    if category:
        clauses.append("n.category = ?")
        params.append(category)
    if department:
        clauses.append("n.department = ?")
        params.append(department)
    return clauses, params


def _paginate_no_query(
    conn: sqlite3.Connection,
    *,
    where_clauses: list[str],
    params: list[object],
    page: int,
    page_size: int,
) -> tuple[list[Notice], int]:
    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    total = conn.execute(
        f"SELECT COUNT(*) FROM notices n{where_sql}",
        params,
    ).fetchone()[0]

    total_pages = max(1, ceil(total / page_size))
    current_page = min(page, total_pages)
    offset = (current_page - 1) * page_size

    rows = conn.execute(
        f"""
        SELECT id, title, content, summary, url, category, department,
               published_at, audience_group, source_group
        FROM notices n
        {where_sql}
        ORDER BY published_at DESC, title ASC, id ASC
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, offset],
    ).fetchall()
    return _rows_to_notices(conn, rows), total


def _search_with_query(
    conn: sqlite3.Connection,
    *,
    where_clauses: list[str],
    params: list[object],
    q: str,
    page: int,
    page_size: int,
) -> tuple[list[Notice], int]:
    normalized = normalize_whitespace(q).lower()
    compact_query = compact(normalized)
    terms = expand_search_terms(extract_search_terms(q))

    # phrase + 각 term을 OR로 합친다. 이전엔 AND여서 본문에 phrase가 그대로 등장하지
    # 않으면 결과가 0건이 되는 P0 버그가 있었다.
    candidate_or_parts: list[str] = [
        "n.searchable_text LIKE ?",
        "n.searchable_compact LIKE ?",
    ]
    candidate_params: list[object] = [
        f"%{normalized}%",
        f"%{compact_query}%",
    ]
    for term in terms:
        candidate_or_parts.append("n.searchable_text LIKE ?")
        candidate_or_parts.append("n.searchable_compact LIKE ?")
        candidate_params.extend([f"%{term}%", f"%{compact(term)}%"])

    candidate_clause = "(" + " OR ".join(candidate_or_parts) + ")"

    # 외부 filter(audience/source_group/...)는 AND, 키워드 매칭은 OR group.
    filter_parts = list(where_clauses)
    if candidate_clause:
        filter_parts.append(candidate_clause)
    where_sql = (" WHERE " + " AND ".join(filter_parts)) if filter_parts else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM notices n{where_sql}",
        [*params, *candidate_params],
    ).fetchone()[0]

    rows = conn.execute(
        f"""
        SELECT id, title, content, summary, url, category, department,
               published_at, audience_group, source_group,
               searchable_text, searchable_compact
        FROM notices n
        {where_sql}
        ORDER BY published_at DESC, title ASC, id ASC
        LIMIT ?
        """,
        [*params, *candidate_params, SEARCH_CANDIDATE_LIMIT],
    ).fetchall()

    candidates = _rows_to_notices(conn, rows)
    matched = _apply_text_filter(
        candidates,
        rows,
        normalized=normalized,
        compact_query=compact_query,
        terms=terms,
    )

    ranked = rank_notices(matched, q)
    total_pages = max(1, ceil(max(total, len(ranked)) / page_size))
    current_page = min(max(1, page), total_pages)
    start = (current_page - 1) * page_size
    end = start + page_size
    items = [item.notice for item in ranked[start:end]]
    return items, total


def _apply_text_filter(
    notices: list[Notice],
    rows: list[sqlite3.Row],
    *,
    normalized: str,
    compact_query: str,
    terms: list[str],
) -> list[Notice]:
    if not normalized and not terms:
        return notices

    matched: list[Notice] = []
    for notice, row in zip(notices, rows):
        searchable = row["searchable_text"] or ""
        compact_searchable = row["searchable_compact"] or ""

        if normalized and normalized in searchable:
            matched.append(notice)
            continue
        if compact_query and compact_query in compact_searchable:
            matched.append(notice)
            continue

        if not terms:
            continue

        # 한 term이라도 매치하면 후보로 인정한다. 최종 순위는 rank_notices의
        # 가중 점수 (title 7, summary 4, tags 3, ...) + recency boost가 결정.
        # 이전엔 min(2, len(terms)) 빡빡한 필터가 후보를 너무 잘라냈다.
        for term in terms:
            if term in searchable:
                matched.append(notice)
                break
            compact_term = compact(term)
            if compact_term and compact_term in compact_searchable:
                matched.append(notice)
                break
    return matched


def _query_audience_groups(conn: sqlite3.Connection) -> list[str]:
    from app.classification import AUDIENCE_GROUP_ORDER

    rows = conn.execute(
        "SELECT DISTINCT audience_group FROM notices WHERE audience_group IS NOT NULL"
    ).fetchall()
    present = {row[0] for row in rows if row[0]}
    return [group for group in AUDIENCE_GROUP_ORDER if group in present]


def _query_source_groups(conn: sqlite3.Connection, audience: str | None) -> list[str]:
    from app.classification import SOURCE_GROUP_ORDER, ordered_by_known_groups

    if audience:
        rows = conn.execute(
            """
            SELECT DISTINCT sg.source_group
            FROM notice_source_groups sg
            JOIN notices n ON n.id = sg.notice_id
            WHERE n.audience_group = ?
            """,
            (audience,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT source_group FROM notice_source_groups"
        ).fetchall()
    present = [row[0] for row in rows if row[0]]
    return ordered_by_known_groups(present, SOURCE_GROUP_ORDER)


def _query_sources(
    conn: sqlite3.Connection,
    audience: str | None,
    source_group: str | None,
) -> list[str]:
    base = (
        "SELECT n.id, n.title, n.category, "
        "GROUP_CONCAT(s.source_name, ?) AS sources "
        "FROM notices n JOIN notice_sources s ON s.notice_id = n.id"
    )
    clauses: list[str] = []
    params: list[object] = [_SOURCE_DELIMITER]
    if audience:
        clauses.append("n.audience_group = ?")
        params.append(audience)
    if source_group:
        clauses.append(
            "EXISTS(SELECT 1 FROM notice_source_groups sg "
            "WHERE sg.notice_id = n.id AND sg.source_group = ?)"
        )
        params.append(source_group)
    if clauses:
        base += " WHERE " + " AND ".join(clauses)
    base += " GROUP BY n.id"

    collected: set[str] = set()
    for row in conn.execute(base, params):
        sources = [s for s in row["sources"].split(_SOURCE_DELIMITER) if s]
        scoped: list[str] = []
        for src in sources:
            synth = Notice(
                id="",
                title=row["title"] or "",
                content="",
                category=row["category"],
                source=src,
                sources=[src],
            )
            if audience and classify_notice_audience(synth) != audience:
                continue
            if source_group and source_group not in classify_notice_source_groups(synth):
                continue
            scoped.append(src)
        collected.update(scoped if scoped else sources)
    return sorted(collected)


def _query_categories(
    conn: sqlite3.Connection,
    audience: str | None,
    source_group: str | None,
) -> list[str]:
    base = "SELECT n.category FROM notices n"
    clauses: list[str] = ["n.category IS NOT NULL"]
    params: list[object] = []
    if audience:
        clauses.append("n.audience_group = ?")
        params.append(audience)
    if source_group:
        clauses.append(
            "EXISTS(SELECT 1 FROM notice_source_groups sg "
            "WHERE sg.notice_id = n.id AND sg.source_group = ?)"
        )
        params.append(source_group)
    base += " WHERE " + " AND ".join(clauses)

    notices_with_category = [
        Notice(
            id="",
            title="",
            content="",
            category=row[0],
        )
        for row in conn.execute(base, params)
    ]
    return get_clean_categories(notices_with_category)


def _query_departments(
    conn: sqlite3.Connection,
    audience: str | None,
    source_group: str | None,
) -> list[str]:
    base = "SELECT DISTINCT n.department FROM notices n"
    clauses: list[str] = ["n.department IS NOT NULL"]
    params: list[object] = []
    if audience:
        clauses.append("n.audience_group = ?")
        params.append(audience)
    if source_group:
        clauses.append(
            "EXISTS(SELECT 1 FROM notice_source_groups sg "
            "WHERE sg.notice_id = n.id AND sg.source_group = ?)"
        )
        params.append(source_group)
    base += " WHERE " + " AND ".join(clauses)
    rows = conn.execute(base, params).fetchall()
    return sorted({row[0] for row in rows if row[0]})


def _rows_to_notices(
    conn: sqlite3.Connection, rows: list[sqlite3.Row]
) -> list[Notice]:
    if not rows:
        return []
    notice_ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in notice_ids)

    sources_map = _gather_grouped(
        conn,
        f"SELECT notice_id, source_name FROM notice_sources "
        f"WHERE notice_id IN ({placeholders}) ORDER BY notice_id, source_order",
        notice_ids,
        "source_name",
    )
    source_groups_map = _gather_grouped(
        conn,
        f"SELECT notice_id, source_group FROM notice_source_groups "
        f"WHERE notice_id IN ({placeholders}) ORDER BY notice_id, source_group_order",
        notice_ids,
        "source_group",
    )
    attachments_map: dict[str, list[NoticeAttachment]] = {}
    for row in conn.execute(
        f"SELECT notice_id, name, url FROM notice_attachments "
        f"WHERE notice_id IN ({placeholders}) ORDER BY notice_id, attachment_order",
        notice_ids,
    ):
        attachments_map.setdefault(row["notice_id"], []).append(
            NoticeAttachment(name=row["name"], url=row["url"])
        )
    tags_map = _gather_grouped(
        conn,
        f"SELECT notice_id, tag FROM notice_tags "
        f"WHERE notice_id IN ({placeholders}) ORDER BY notice_id, tag_order",
        notice_ids,
        "tag",
    )
    return [
        _row_to_notice(row, sources_map, source_groups_map, attachments_map, tags_map)
        for row in rows
    ]


def _gather_grouped(
    conn: sqlite3.Connection,
    query: str,
    params: list[str],
    value_column: str,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in conn.execute(query, params):
        result.setdefault(row["notice_id"], []).append(row[value_column])
    return result


def _fetch_all(conn: sqlite3.Connection) -> list[Notice]:
    rows = conn.execute(
        """
        SELECT id, title, content, summary, url, category, department,
               published_at, audience_group, source_group
        FROM notices
        ORDER BY published_at DESC, id ASC
        """
    ).fetchall()
    return _rows_to_notices(conn, rows)


def _fetch_one(conn: sqlite3.Connection, notice_id: str) -> Notice | None:
    row = conn.execute(
        """
        SELECT id, title, content, summary, url, category, department,
               published_at, audience_group, source_group
        FROM notices WHERE id = ?
        """,
        (notice_id,),
    ).fetchone()
    if not row:
        return None
    notices = _rows_to_notices(conn, [row])
    return notices[0] if notices else None


def _row_to_notice(
    row: sqlite3.Row,
    sources_map: dict[str, list[str]],
    source_groups_map: dict[str, list[str]],
    attachments_map: dict[str, list[NoticeAttachment]],
    tags_map: dict[str, list[str]],
) -> Notice:
    notice_id = row["id"]
    sources = sources_map.get(notice_id, [])
    source_groups = source_groups_map.get(notice_id, [])
    audience_group = _column_or_none(row, "audience_group")
    representative_source_group = _column_or_none(row, "source_group")
    return Notice(
        id=notice_id,
        title=row["title"],
        content=row["content"],
        url=row["url"],
        source=sources[0] if sources else None,
        sources=sources or None,
        audienceGroup=audience_group,
        sourceGroup=representative_source_group,
        sourceGroups=source_groups,
        category=row["category"],
        department=row["department"],
        date=row["published_at"],
        summary=row["summary"],
        tags=tags_map.get(notice_id, []),
        attachments=attachments_map.get(notice_id, []),
    )


def _column_or_none(row: sqlite3.Row, key: str) -> str | None:
    try:
        return row[key]
    except (IndexError, KeyError):
        return None
