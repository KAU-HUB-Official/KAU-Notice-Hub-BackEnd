"""개인 식별자 마스킹 테스트.

가려져야 할 것보다 **가려지면 안 되는 것**이 훨씬 많은 기능이라, 오탐 방향
테스트를 더 촘촘하게 둔다. 전수 스캔 기준 마스킹 대상은 학번 32건과 표 성명
컬럼 322건뿐이고, 연락처·계좌 4,700여 건은 전부 대상이 아니다.
"""

from app.privacy import (
    mask_account_numbers,
    mask_contacts,
    mask_emails,
    mask_name_columns,
    mask_notice_body,
    mask_personal_identifiers,
    mask_phone_numbers,
    mask_resident_registration_numbers,
    mask_student_ids,
)
from app.schemas import Notice
from app.search import build_search_text


class TestMaskStudentIds:
    def test_실제_학번은_뒤_6자리를_가린다(self):
        assert mask_student_ids("2017121128") == "2017○○○○○○"

    def test_입학년도는_남긴다(self):
        assert mask_student_ids("| 2022126099 | 조O빈 |").startswith("| 2022○○○○○○")

    def test_본문_속_여러_학번을_모두_가린다(self):
        text = "1 기계 2017121128 / 2 우주 2019121051"
        assert mask_student_ids(text) == "1 기계 2017○○○○○○ / 2 우주 2019○○○○○○"

    def test_예시_학번은_그대로_둔다(self):
        text = '입금자명: 본인성명_학번(예:"20250000" 학번일 경우)'
        assert mask_student_ids(text) == text

    def test_반복_숫자_예시값도_그대로_둔다(self):
        for example in ("2026123456", "2011111111", "2019222222"):
            assert mask_student_ids(example) == example

    def test_파일명_날짜를_학번으로_오인하지_않는다(self):
        text = "2024 창의적재료설계프로젝트 발표자 명단(20240614).pdf"
        assert mask_student_ids(text) == text

    def test_연락처와_계좌번호는_건드리지_않는다(self):
        text = (
            "문의 : 교육성과관리센터 (02-300-0272, cap@kau.ac.kr) / "
            "입금계좌: 우리은행 1005-003-863678 / 010-9829-4568"
        )
        assert mask_student_ids(text) == text

    def test_날짜_표기를_건드리지_않는다(self):
        text = "접수기간 2024.11.6.(수)~2024.11.29.(금), 기준일 2023.05.21"
        assert mask_student_ids(text) == text

    def test_멱등이다(self):
        once = mask_student_ids("2017121128")
        assert mask_student_ids(once) == once


class TestMaskNameColumns:
    def test_성명_컬럼의_이름만_가린다(self):
        markdown = "\n".join(
            [
                "| 학번 | 성명 | 결과 |",
                "| --- | --- | --- |",
                "| 2022126099 | 김솔미 | 최우수상 |",
            ]
        )
        masked = mask_name_columns(markdown)
        assert "김○○" in masked
        assert "2022126099" in masked  # 학번은 mask_student_ids 책임
        assert "최우수상" in masked

    def test_두_행으로_쪼개진_헤더도_찾는다(self):
        markdown = "\n".join(
            [
                "| NO | 활동구분 | 팀명 | 팀장 | | | 비고 |",
                "| 학부(과) | 학번 | 성명 |",
                "| 1 | 빌드업 | KAU Vision Lab | 반도체신소재전공 | 2025 | 김진수 | |",
            ]
        )
        assert "김○○" in mask_name_columns(markdown)

    def test_이름_컬럼_라벨도_인식한다(self):
        markdown = "| 소속 | 이름 |\n| --- | --- |\n| 기계 | 심재원 |"
        assert "심○○" in mask_name_columns(markdown)

    def test_두_글자_이름은_한_글자만_남긴다(self):
        markdown = "| 성명 |\n| --- |\n| 이휘 |"
        assert "이○" in mask_name_columns(markdown)

    def test_이미_마스킹된_이름은_이중처리하지_않는다(self):
        markdown = "| 성명 |\n| --- |\n| 조O빈 |"
        assert mask_name_columns(markdown) == markdown

    def test_성명_컬럼이_없는_표는_바꾸지_않는다(self):
        markdown = "| 구분 | 기간 |\n| --- | --- |\n| 1차 접수 | 2025.3.6. |"
        assert mask_name_columns(markdown) == markdown

    def test_표가_끝나면_컬럼_위치가_새어나가지_않는다(self):
        markdown = "\n".join(
            [
                "| 성명 |",
                "| --- |",
                "| 김솔미 |",
                "",
                "| 장소 |",
                "| --- |",
                "| 기계관 |",
            ]
        )
        masked = mask_name_columns(markdown)
        assert "김○○" in masked
        assert "기계관" in masked

    def test_표가_아닌_본문의_이름_표현은_건드리지_않는다(self):
        text = "각종 비교과 활동을 완료한 학생(팀) 및 재학생 여러분의 참여 바랍니다."
        assert mask_name_columns(text) == text

    def test_멱등이다(self):
        markdown = "| 성명 |\n| --- |\n| 김솔미 |"
        once = mask_name_columns(markdown)
        assert mask_name_columns(once) == once


class TestMaskPersonalIdentifiers:
    def test_학번과_이름을_함께_가린다(self):
        markdown = "\n".join(
            [
                "| No. | 소속 | 학번 | 이름 | 담당교수 |",
                "| --- | --- | --- | --- | --- |",
                "| 1 | 기계 | 2017121128 | 심재원 | 김석일 |",
            ]
        )
        masked = mask_personal_identifiers(markdown)
        assert "2017○○○○○○" in masked
        assert "심○○" in masked
        assert "2017121128" not in masked
        # 담당교수 컬럼은 성명 라벨이 아니라 그대로 남는다.
        assert "김석일" in masked

    def test_빈_문자열을_받아도_안전하다(self):
        assert mask_personal_identifiers("") == ""

    def test_멱등이다(self):
        markdown = "| 학번 | 성명 |\n| --- | --- |\n| 2017121128 | 심재원 |"
        once = mask_personal_identifiers(markdown)
        assert mask_personal_identifiers(once) == once


class TestSearchIndexIsMasked:
    def _notice(self, content: str) -> Notice:
        return Notice(id="n1", title="캡스톤디자인 발표회", content=content)

    def test_학번으로는_검색_인덱스에_걸리지_않는다(self):
        notice = self._notice("| 학번 | 이름 |\n| --- | --- |\n| 2017121128 | 심재원 |")
        searchable = build_search_text(notice)
        assert "2017121128" not in searchable
        assert "심재원" not in searchable

    def test_공지_본문_자체는_바뀌지_않는다(self):
        content = "| 학번 | 이름 |\n| --- | --- |\n| 2017121128 | 심재원 |"
        notice = self._notice(content)
        build_search_text(notice)
        assert notice.content == content

    def test_일반_검색어는_그대로_동작한다(self):
        notice = self._notice("수강신청 기간은 2026.3.2.부터입니다. 문의 02-300-0272")
        searchable = build_search_text(notice)
        assert "수강신청" in searchable
        # 연락처는 기본값(PRIVACY_MASK_CONTACTS=true)에서 가려진다.
        assert "02-300-0272" not in searchable
        assert "2026.3.2." in searchable


class TestMaskNamesAdjacentToStudentIds:
    """normalize_notice()가 비정형 표를 평문으로 펼치면 파이프가 사라져 컬럼
    위치를 쓸 수 없다. 캡스톤 195명 표가 바로 그 경우여서, 가려진 학번을
    앵커로 쓰는 이 규칙이 실질적으로 최악 케이스를 담당한다.
    """

    def test_평문으로_펼쳐진_표에서_학번_뒤_이름을_가린다(self):
        text = "구조생산  1 기계 2017121128 심재원 김석일 공작기계 역설계"
        masked = mask_personal_identifiers(text)
        assert "심○○" in masked
        assert "심재원" not in masked

    def test_두_글자_이름도_가린다(self):
        assert "이○" in mask_personal_identifiers("기계 2018121173 이휘")

    def test_학번_앞의_소속명은_가리지_않는다(self):
        masked = mask_personal_identifiers("기계 2018121173 이휘")
        assert "기계 2018" in masked

    def test_학번이_딸리지_않은_담당교수는_가리지_않는다(self):
        text = "구조생산  1 기계 2017121128 심재원 김석일 공작기계 역설계"
        assert "김석일" in mask_personal_identifiers(text)

    def test_학번만_있는_행은_이름을_만들지_않는다(self):
        text = "1 항공재료공학과 2005106053"
        masked = mask_personal_identifiers(text)
        assert masked == "1 항공재료공학과 2005○○○○○○"

    def test_긴_학과명은_이름으로_오인하지_않는다(self):
        text = "반도체신소재전공 2025126140"
        assert mask_personal_identifiers(text) == "반도체신소재전공 2025○○○○○○"

    def test_예시_학번_뒤의_단어는_건드리지_않는다(self):
        text = '학번(예:"20250000" 학번일 경우)'
        assert mask_personal_identifiers(text) == text

    def test_멱등이다(self):
        text = "기계 2017121128 심재원"
        once = mask_personal_identifiers(text)
        assert mask_personal_identifiers(once) == once


class TestExampleIdFilterIsNarrow:
    """더미 필터를 넓게 잡으면 실제 학번을 예시로 오판해 그대로 노출된다.

    `len(set(tail)) <= 2` 규칙을 쓰던 동안 기계공학부 학번대(`2018121111`,
    `2018121121`, `2018121211`)가 예시로 분류되어 마스킹되지 않았고, 붙어
    있던 학생 이름까지 함께 남았다.
    """

    REAL_IDS = ("2018121111", "2018121121", "2018121211", "2020121233", "2017121001")

    def test_숫자_종류가_적은_실제_학번도_가린다(self):
        for student_id in self.REAL_IDS:
            masked = mask_student_ids(student_id)
            assert masked == student_id[:4] + "○○○○○○", student_id

    def test_실제_학번에_붙은_이름도_함께_가린다(self):
        masked = mask_personal_identifiers("기계 2018121111 신대수")
        assert "신○○" in masked
        assert "신대수" not in masked

    def test_한_숫자로만_채운_예시값은_그대로_둔다(self):
        for example in ("2011111111", "2019222222", "2020333333"):
            assert mask_student_ids(example) == example

    def test_연속_숫자_예시값은_그대로_둔다(self):
        for example in ("2026123456", "2020123456", "2025123456"):
            assert mask_student_ids(example) == example


class TestMaskContacts:
    """공개 연락처까지 가리는 기본 정책.

    저장된 본문은 원문 그대로이므로 사용자는 공지 상세에서 문의처를 읽을 수
    있다. 줄어드는 것은 연락처로 공지를 검색하는 경로뿐이다.
    """

    def test_학교_대표번호를_가린다(self):
        assert mask_phone_numbers("문의 02-300-0272") == "문의 02-○○○-○○○○"

    def test_휴대폰_번호를_가린다(self):
        # 국번 자리수는 보존한다. 010-9829-4568은 국번이 네 자리다.
        assert mask_phone_numbers("담당 010-9829-4568") == "담당 010-○○○○-○○○○"

    def test_네_자리_국번도_가린다(self):
        assert mask_phone_numbers("02-3420-5337") == "02-○○○○-○○○○"

    def test_이메일은_로컬_파트만_가린다(self):
        assert mask_emails("cap@kau.ac.kr") == "○○○@kau.ac.kr"

    def test_계좌번호를_가린다(self):
        masked = mask_account_numbers("입금계좌: 우리은행 1005-003-863678")
        assert "1005-003-863678" not in masked
        assert "○○○○-○○○-○○○○○○" in masked

    def test_주민등록번호를_가린다(self):
        assert mask_resident_registration_numbers("900101-1234567") == "○○○○○○-○○○○○○○"

    def test_공지_날짜는_전화번호로_오인하지_않는다(self):
        text = "접수기간 2024.11.6.(수)~2024.11.29.(금) / 기준일 2023.05.21 / 2026-09-15"
        assert mask_phone_numbers(text) == text

    def test_계좌_패턴이_전화번호를_집어가지_않는다(self):
        text = "문의 02-300-0272"
        assert mask_account_numbers(text) == text

    def test_전화번호를_먼저_가리면_계좌_패턴에_걸리지_않는다(self):
        masked = mask_contacts("입금 문의 02-300-0025")
        assert masked == "입금 문의 02-○○○-○○○○"

    def test_학번은_전화번호로_오인하지_않는다(self):
        assert mask_contacts("2017121128") == "2017121128"

    def test_멱등이다(self):
        text = "문의 02-300-0272, cap@kau.ac.kr / 입금계좌 우리은행 1005-003-863678"
        once = mask_contacts(text)
        assert mask_contacts(once) == once


class TestContactMaskingIsToggleable:
    """`나중에 수정`을 코드 변경 없이 하기 위한 플래그."""

    TEXT = "문의 02-300-0272 / 기계 2017121128 심재원"

    def test_연락처_마스킹을_끄면_학번과_이름만_가린다(self):
        masked = mask_personal_identifiers(self.TEXT, include_contacts=False)
        assert "02-300-0272" in masked
        assert "2017○○○○○○" in masked
        assert "심○○" in masked

    def test_연락처_마스킹을_켜면_연락처도_가린다(self):
        masked = mask_personal_identifiers(self.TEXT, include_contacts=True)
        assert "02-○○○-○○○○" in masked
        assert "2017○○○○○○" in masked
        assert "심○○" in masked

    def test_기본값은_연락처까지_가린다(self):
        from app.config import get_settings

        assert get_settings().privacy_mask_contacts is True
        assert "02-300-0272" not in mask_personal_identifiers(self.TEXT)


class TestBoldWrappedContacts:
    """공지는 마크다운 굵게를 많이 쓴다. `*`가 번호에 붙어도 가려져야 한다.

    lookaround에서 `*`를 배제했던 동안 `**... 02-300-0027**` 형태의 번호 13건과
    휴대폰 1건이 인덱스에 그대로 남았다.
    """

    def test_굵게_닫힘_뒤의_번호를_가린다(self):
        masked = mask_phone_numbers("**대학일자리플러스센터 02-300-0027**")
        assert "02-300-0027" not in masked
        assert "02-○○○-○○○○" in masked

    def test_굵게_열림_뒤의_번호를_가린다(self):
        masked = mask_phone_numbers("**3.문의사항 :**02-300-0120 / 02-300-0121")
        assert "02-300-0120" not in masked
        assert "02-300-0121" not in masked

    def test_굵게_안의_휴대폰도_가린다(self):
        masked = mask_phone_numbers("**운영사무국 010-2276-3432**")
        assert "010-2276-3432" not in masked

    def test_멱등이다(self):
        once = mask_phone_numbers("**문의 02-300-0027**")
        assert mask_phone_numbers(once) == once


class TestMaskNoticeBody:
    """사용자에게 렌더되는 본문 마스킹. `PRIVACY_MASK_BODY`로 끌 수 있다."""

    BODY = "\n".join(
        [
            "| 학번 | 이름 |",
            "| --- | --- |",
            "| 2017121128 | 심재원 |",
            "",
            "문의 : 교육성과관리센터 02-300-0272",
        ]
    )

    def test_켜면_본문의_학번_이름_연락처를_가린다(self):
        masked = mask_notice_body(self.BODY, enabled=True)
        assert "2017121128" not in masked
        assert "심재원" not in masked
        assert "02-300-0272" not in masked

    def test_끄면_본문을_그대로_둔다(self):
        assert mask_notice_body(self.BODY, enabled=False) == self.BODY

    def test_기본값은_본문을_가린다(self):
        from app.config import get_settings

        assert get_settings().privacy_mask_body is True
        assert "2017121128" not in mask_notice_body(self.BODY)

    def test_가려진_주소의_mailto_링크를_평문으로_펼친다(self):
        masked = mask_notice_body("[jchae@kau.ac.kr](mailto:jchae@kau.ac.kr)", enabled=True)
        assert masked == "○○○@kau.ac.kr"
        assert "mailto:" not in masked

    def test_마스킹을_끄면_mailto_링크가_유지된다(self):
        body = "[jchae@kau.ac.kr](mailto:jchae@kau.ac.kr)"
        assert mask_notice_body(body, enabled=False) == body

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

    `build_notice_id()`는 url·title·date·source로 ID를 만든다. 제목을 가리면 ID가
    바뀌어 사용자가 저장한 북마크가 끊기므로 제목은 건드리지 않는다.
    """

    RAW = {
        "title": "2023 캡스톤디자인 발표회 포스터 위치 안내",
        "content": "| 학번 | 이름 |\n| --- | --- |\n| 2017121128 | 심재원 |",
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
        assert "2017121128" not in masked.content
        assert "2017121128" in plain.content

    def test_제목은_가리지_않는다(self):
        from app.normalize import normalize_notice

        notice = normalize_notice(dict(self.RAW), 0)
        assert notice.title == self.RAW["title"]
