"""개인 식별자 마스킹 테스트.

가려져야 할 것보다 **가려지면 안 되는 것**이 훨씬 많은 기능이라, 오탐 방향
테스트를 더 촘촘하게 둔다. 전화번호·이메일·계좌번호는 대상이 아니다.
"""

from app.privacy import mask_notice_body, mask_personal_identifiers, mask_student_ids
from app.schemas import Notice
from app.search import build_search_text


class TestMaskStudentIds:
    def test_가운데_4자리를_가린다(self):
        assert mask_student_ids("2017999928") == "2017○○○○28"

    def test_입학년도와_뒤_2자리는_남긴다(self):
        assert mask_student_ids("| 2022999999 | 조O빈 |") == "| 2022○○○○99 | 조O빈 |"

    def test_본문_속_여러_학번을_모두_가린다(self):
        text = "1 기계 2017999928 / 2 우주 2019999951"
        assert mask_student_ids(text) == "1 기계 2017○○○○28 / 2 우주 2019○○○○51"

    def test_예시처럼_생긴_학번도_가린다(self):
        # 숫자만 보고는 예시와 실제를 구분할 수 없어 예외를 두지 않는다.
        for student_id in ("2011111111", "2026123456", "2025987654", "2018999911"):
            assert mask_student_ids(student_id) == student_id[:4] + "○○○○" + student_id[-2:]

    def test_아이디_안의_학번도_가린다(self):
        assert mask_student_ids("ex) 2026123456 ID: kh2026123456") == (
            "ex) 2026○○○○56 ID: kh2026○○○○56"
        )

    def test_10자리가_아닌_자리표시는_건드리지_않는다(self):
        text = '입금자명: 본인성명_학번(예:"20250000" 학번일 경우)'
        assert mask_student_ids(text) == text

    def test_파일명_날짜를_학번으로_오인하지_않는다(self):
        text = "2024 창의적재료설계프로젝트 발표자 명단(20240614).pdf"
        assert mask_student_ids(text) == text

    def test_날짜_표기를_건드리지_않는다(self):
        text = "접수기간 2024.11.6.(수)~2024.11.29.(금), 기준일 2023.05.21"
        assert mask_student_ids(text) == text

    def test_링크_주소_속_숫자는_가리지_않는다(self):
        # 실제 공지의 이미지 주소. 해시 속 `1928475806`이 학번 모양이라 예전에는 가려져 깨졌다.
        text = (
            "![](http://college.kau.ac.kr/web/cmm/imageSrc.do?path=9d9f8470"
            "&physical=27c5e29a2bd01f50067be7da321d4e925402ab71f3d8995d63db1928475806cbd0)"
        )
        assert mask_student_ids(text) == text

    def test_주소_파라미터의_학번_모양_숫자도_가리지_않는다(self):
        for text in (
            "https://example.com/view?id=2024123456",
            "[신청](https://kau.ac.kr/bbs?no=2024123456&page=1)",
        ):
            assert mask_student_ids(text) == text

    def test_링크_밖의_학번은_그대로_가린다(self):
        text = "[명단](https://kau.ac.kr/bbs?no=2024123456) 2017999928 홍길동"
        assert mask_student_ids(text) == (
            "[명단](https://kau.ac.kr/bbs?no=2024123456) 2017○○○○28 홍길동"
        )

    def test_학번으로_된_메일_주소는_가린다(self):
        # 연락처는 남기지만, 메일 주소 자체가 학번이면 학생을 특정하므로 가린다.
        # 전체 공지에서 2건 나왔다(문의 메일이 `학번@kau.kr`).
        assert mask_student_ids("문의: 2021999914@kau.kr") == "문의: 2021○○○○14@kau.kr"

    def test_메일_링크_안의_학번_메일_주소도_가린다(self):
        assert mask_student_ids("[문의](mailto:2021999914@kau.kr)") == (
            "[문의](mailto:2021○○○○14@kau.kr)"
        )
        assert mask_student_ids("mailto:2021999914@kau.kr") == "mailto:2021○○○○14@kau.kr"

    def test_멱등이다(self):
        once = mask_student_ids("2017999928")
        assert mask_student_ids(once) == once


class TestContactsAreNotMasked:
    """전화번호(휴대폰 포함), 이메일, 계좌번호는 문의처와 납부처라 남긴다."""

    def test_전화번호를_남긴다(self):
        text = "02-300-0272 / 031-123-4567 / 070-1234-5678 / 1588-1234 / 010-9829-4568"
        assert mask_personal_identifiers(text) == text

    def test_이메일을_남긴다(self):
        text = "cap@kau.ac.kr / abc123@naver.com"
        assert mask_personal_identifiers(text) == text

    def test_계좌번호를_남긴다(self):
        text = "입금계좌: 우리은행 1005-003-863678"
        assert mask_personal_identifiers(text) == text


class TestSearchIndexIsMasked:
    def _notice(self, content: str) -> Notice:
        return Notice(id="n1", title="캡스톤디자인 발표회", content=content)

    def test_학번으로는_검색_인덱스에_걸리지_않는다(self):
        notice = self._notice("| 학번 | 이름 |\n| --- | --- |\n| 2017999928 | 홍길동 |")
        assert "2017999928" not in build_search_text(notice)

    def test_공지_본문_자체는_바뀌지_않는다(self):
        content = "| 학번 | 이름 |\n| --- | --- |\n| 2017999928 | 홍길동 |"
        notice = self._notice(content)
        build_search_text(notice)
        assert notice.content == content

    def test_일반_검색어는_그대로_동작한다(self):
        notice = self._notice("수강신청 기간은 2026.3.2.부터입니다. 문의 02-300-0272")
        searchable = build_search_text(notice)
        assert "수강신청" in searchable
        assert "02-300-0272" in searchable
        assert "2026.3.2." in searchable


class TestMaskNoticeBody:
    """사용자에게 렌더되는 본문 마스킹. `PRIVACY_MASK_BODY`로 끌 수 있다."""

    BODY = "\n".join(
        [
            "| 학번 | 이름 |",
            "| --- | --- |",
            "| 2017999928 | 홍길동 |",
            "",
            "문의 : 교육성과관리센터 02-300-0272",
        ]
    )

    def test_켜면_본문의_학번을_가린다(self):
        masked = mask_notice_body(self.BODY, enabled=True)
        assert "2017999928" not in masked
        assert "02-300-0272" in masked

    def test_끄면_본문을_그대로_둔다(self):
        assert mask_notice_body(self.BODY, enabled=False) == self.BODY

    def test_기본값은_본문을_가린다(self):
        from app.config import get_settings

        assert get_settings().privacy_mask_body is True
        assert "2017999928" not in mask_notice_body(self.BODY)

    def test_메일_mailto_링크는_그대로_둔다(self):
        body = "[jchae@kau.ac.kr](mailto:jchae@kau.ac.kr)"
        assert mask_notice_body(body, enabled=True) == body

    def test_이미지와_링크_URL은_훼손하지_않는다(self):
        body = (
            "![포스터](https://kau.ac.kr/upfile/2026/09/10/20260910143813-8701.jpg)\n"
            "[신청서](https://kau.ac.kr/bbs/down.php?code=notice&idx=58&no=1)"
        )
        assert mask_notice_body(body, enabled=True) == body

    def test_공지_날짜는_훼손하지_않는다(self):
        body = "접수기간 2024.11.6.(수)~2024.11.29.(금) / 2026학년도 2학기 / 2026-09-15"
        assert mask_notice_body(body, enabled=True) == body

    def test_멱등이다(self):
        once = mask_notice_body(self.BODY, enabled=True)
        assert mask_notice_body(once, enabled=True) == once


class TestNoticeIdIsStable:
    """본문을 가려도 공지 ID는 변하지 않아야 한다.

    `build_notice_id()`는 원문 URL로, URL이 없으면 제목·날짜·출처로 ID를 만든다.
    제목을 가리면 URL 없는 공지의 ID가 바뀌어 북마크가 끊기므로 제목은 건드리지
    않는다.
    """

    RAW = {
        "title": "2023 캡스톤디자인 발표회 포스터 위치 안내",
        "content": "| 학번 | 이름 |\n| --- | --- |\n| 2017999928 | 홍길동 |",
        "url": "https://www.kau.ac.kr/web/pages/notice.do?idx=1234",
        "source_name": "한국항공대학교 공식 홈페이지",
        "published_at": "2023-12-19",
    }

    def test_본문_마스킹_여부와_무관하게_ID가_같다(self, monkeypatch):
        from app.normalize import normalize_notice

        masked = normalize_notice(dict(self.RAW), 0)
        monkeypatch.setattr("app.privacy._body_masking_enabled", lambda: False)
        plain = normalize_notice(dict(self.RAW), 0)

        assert masked.id == plain.id
        assert masked.title == plain.title
        assert "2017999928" not in masked.content
        assert "2017999928" in plain.content

    def test_제목은_가리지_않는다(self):
        from app.normalize import normalize_notice

        notice = normalize_notice(dict(self.RAW), 0)
        assert notice.title == self.RAW["title"]
