"""학술정보관 목록 파서의 상시공지 판정 검증.

목록 표는 상단 고정 행(tr.info, 번호 칸 "공지")과 번호 행으로 이뤄지고, 고정 공지는 번호 행에도
한 번 더 나온다. 카테고리 칸의 "공지사항"·"학술DB공지" 글자로 일반 공지가 상시공지로 잡히면 안 된다.
"""

from __future__ import annotations

from app.crawler.parsers.kau_library_parser import KAULibraryParser

LIST_URL = "https://lib.kau.ac.kr/sb/default_notice_list.mir"
LIST_HTML = """
<table class="table table-striped table-hover table-condensed">
  <thead>
    <tr><th>번호</th><th>카테고리</th><th>제목</th><th>작성일</th><th>조회</th></tr>
  </thead>
  <tbody>
    <tr class="info" onclick="go_view('5410','default_notice_view');">
      <th><span class="label notice_type type01">공지</span></th>
      <td><font color="#CC0000">공지사항</font></td>
      <td class="text-left"><a href="#link">2026 학술정보관 전자정보 박람회</a></td>
      <td>2026-09-11</td><td>128</td>
    </tr>
    <tr onclick="go_view('5410','default_notice_view');">
      <th>3</th>
      <td><font color="#CC0000">공지사항</font></td>
      <td class="text-left"><a href="#link">2026 학술정보관 전자정보 박람회</a></td>
      <td>2026-09-11</td><td>128</td>
    </tr>
    <tr onclick="go_view('5408','default_notice_view');">
      <th>2</th>
      <td><font color="#CC0000">학술DB공지</font></td>
      <td class="text-left"><a href="#link">O'Reilly for Higher education 온라인 이용교육</a></td>
      <td>2026-09-03</td><td>29</td>
    </tr>
    <tr onclick="go_view('3872','default_notice_view');">
      <th>1</th>
      <td><font color="#CC0000">공지사항</font></td>
      <td class="text-left"><a href="#link">학술정보관 회원제 서비스 이용 안내</a></td>
      <td>2026-06-04</td><td>3663</td>
    </tr>
  </tbody>
</table>
"""


def test_only_pinned_rows_are_permanent_notices() -> None:
    items = KAULibraryParser().parse_post_items(LIST_HTML, LIST_URL)

    assert [(item["url"].rsplit("=", 1)[-1], item["is_permanent_notice"]) for item in items] == [
        ("5410", True),  # 고정 행과 번호 행에 모두 나와도 상시공지로 남는다
        ("5408", False),
        ("3872", False),
    ]
