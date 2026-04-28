from __future__ import annotations

from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse


def canonicalize_original_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return url

    scheme = parsed.scheme or "https"
    netloc = parsed.netloc
    path = parsed.path
    host = netloc.lower()

    # KAU 공식 공지 상세 URL:
    #   /kaulife/{board}.php?...&code=sXXXX&page=..&mode=read&seq=NNNN
    # 여기서 중복에 영향 없는 page/searchkey/searchvalue는 제거한다.
    if host.endswith("kau.ac.kr") and path.startswith("/kaulife/") and path.endswith(".php"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if "mode" in query and "seq" in query:
            compact_query: dict[str, str] = {}
            if query.get("code"):
                compact_query["code"] = query["code"][-1]
            compact_query["mode"] = query["mode"][-1]
            compact_query["seq"] = query["seq"][-1]
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # 대학일자리센터 상세 URL:
    #   /ko/community/notice/view/{id}?p=1
    #   /ko/dataroom/data/view/{id}?p=1 (기존 경로)
    # p 파라미터 제거.
    if host.endswith("career.kau.ac.kr") and "/view/" in path and (
        path.startswith("/ko/community/notice/")
        or path.startswith("/ko/dataroom/data/")
    ):
        return urlunparse((scheme, netloc, path.rstrip("/"), "", "", ""))

    # college.kau.ac.kr 공지 상세 URL:
    #   /web/pages/gc63585b.do?...&bbsId=0123&nttId=NNNN
    # 중복에 영향 없는 쿼리 파라미터는 제거한다.
    if host.endswith("college.kau.ac.kr") and path.startswith("/web/pages/") and path.endswith(".do"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query.get("bbsId") and query.get("nttId"):
            compact_query: dict[str, str] = {
                "bbsId": query["bbsId"][-1],
                "nttId": query["nttId"][-1],
            }
            if query.get("mnuId"):
                compact_query["mnuId"] = query["mnuId"][-1]
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # research.kau.ac.kr 공지 상세 URL:
    #   /info/info_011.php?...&code=s2101&page=..&mode=read&seq=NNNN
    # 중복에 영향 없는 page/search 파라미터를 제거한다.
    if host.endswith("research.kau.ac.kr") and path.startswith("/info/") and path.endswith(".php"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if "mode" in query and "seq" in query:
            compact_query: dict[str, str] = {}
            if query.get("code"):
                compact_query["code"] = query["code"][-1]
            compact_query["mode"] = query["mode"][-1]
            compact_query["seq"] = query["seq"][-1]
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # ctl.kau.ac.kr 공지 상세 URL:
    #   /notice/list.php?...&code=s1101&page=..&mode=read&seq=NNNN
    # 중복에 영향 없는 page/search 파라미터를 제거한다.
    if host.endswith("ctl.kau.ac.kr") and path.endswith("/notice/list.php"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if "mode" in query and "seq" in query:
            compact_query: dict[str, str] = {}
            if query.get("code"):
                compact_query["code"] = query["code"][-1]
            compact_query["mode"] = query["mode"][-1]
            compact_query["seq"] = query["seq"][-1]
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # lib.kau.ac.kr 공지 상세 URL:
    #   /sb/default_notice_view.mir?sb_no=NNNN[&...]
    # sb_no만 유지해 중복 URL을 제거한다.
    if host.endswith("lib.kau.ac.kr") and path.endswith("/sb/default_notice_view.mir"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query.get("sb_no"):
            compact_query = {"sb_no": query["sb_no"][-1]}
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # ftc.kau.ac.kr 공지 상세 URL:
    #   /info/notice_02.php?...&code=s1102&page=..&mode=read&seq=NNNN
    # 중복에 영향 없는 page/search 파라미터를 제거한다.
    if host.endswith("ftc.kau.ac.kr") and path.startswith("/info/") and path.endswith(".php"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if "mode" in query and "seq" in query:
            compact_query: dict[str, str] = {}
            if query.get("code"):
                compact_query["code"] = query["code"][-1]
            compact_query["mode"] = query["mode"][-1]
            compact_query["seq"] = query["seq"][-1]
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # fsc/grad/gradbus/카드형 학과 계열 공지 상세 URL:
    #   /info/info_01.php?...&code=s1101&page=..&mode=read&seq=NNNN
    #   /community/notice_02.php?...&code=s1201&page=..&mode=read&seq=NNNN
    #   /community/notice_01.php?...&code=s1101&page=..&mode=read&seq=NNNN
    #   /pages/notice.php?...&code=s1201&page=..&mode=read&seq=NNNN
    #   /pages/notice.php?...&code=s1401&page=..&mode=read&seq=NNNN
    if host in {
        "fsc.kau.ac.kr",
        "grad.kau.ac.kr",
        "gradbus.kau.ac.kr",
        "aisw.kau.ac.kr",
        "ai.kau.ac.kr:8100",
        "ai.kau.ac.kr:8110",
        "ai.kau.ac.kr:8120",
        "ai.kau.ac.kr:8130",
        "ai.kau.ac.kr:8140",
        "sw.kau.ac.kr",
        "ave.kau.ac.kr",
    } and path.endswith(".php"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if "mode" in query and "seq" in query:
            compact_query: dict[str, str] = {}
            if query.get("code"):
                compact_query["code"] = query["code"][-1]
            compact_query["mode"] = query["mode"][-1]
            compact_query["seq"] = query["seq"][-1]
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # lms.kau.ac.kr ubboard 상세 URL:
    #   /mod/ubboard/article.php?id=55398&bwid=NNNN
    if host.endswith("lms.kau.ac.kr") and path.endswith("/mod/ubboard/article.php"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query.get("id") and query.get("bwid"):
            compact_query = {
                "id": query["id"][-1],
                "bwid": query["bwid"][-1],
            }
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # asbt.kau.ac.kr 공지 상세 URL:
    #   /customer/notice.php?ptype=view&idx=NNN&page=..&code=notice
    if host.endswith("asbt.kau.ac.kr") and path.endswith("/customer/notice.php"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query.get("ptype", [""])[-1] == "view" and query.get("idx"):
            compact_query = {
                "ptype": "view",
                "idx": query["idx"][-1],
            }
            if query.get("code"):
                compact_query["code"] = query["code"][-1]
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # eslscat 공지 상세 URL:
    #   /class/student/help/notice_view.asp?id=NNN
    if host.endswith("eslscat.com") and path.endswith("/class/student/help/notice_view.asp"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query.get("id"):
            compact_query = {"id": query["id"][-1]}
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # amtc.kau.ac.kr 공지 상세 URL:
    #   /bbs/board.php?bo_table=notice&wr_id=NNN[&...]
    # bo_table, wr_id만 유지한다.
    if host.endswith("amtc.kau.ac.kr") and path.endswith("/bbs/board.php"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query.get("bo_table") and query.get("wr_id"):
            compact_query = {
                "bo_table": query["bo_table"][-1],
                "wr_id": query["wr_id"][-1],
            }
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # ibhak.kau.ac.kr 입학처 공지 상세 URL:
    #   /admission/html/guide/noticeView.asp?p_board_id=BBS0004&p_board_idx=NNNN&page=..
    # 중복에 영향 없는 page/search 파라미터를 제거한다.
    if host.endswith("ibhak.kau.ac.kr") and path.endswith("/noticeView.asp"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query.get("p_board_id") and query.get("p_board_idx"):
            compact_query = {
                "p_board_id": query["p_board_id"][-1],
                "p_board_idx": query["p_board_idx"][-1],
            }
            normalized_query = urlencode(compact_query)
            return urlunparse((scheme, netloc, path, "", normalized_query, ""))

    # generic fallback: fragment 제거 + 쿼리 키 정렬
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    normalized_query = urlencode(sorted(query_items)) if query_items else ""
    return urlunparse((scheme, netloc, path, "", normalized_query, ""))
