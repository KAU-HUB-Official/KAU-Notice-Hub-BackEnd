"""사람 이름 마스킹 테스트. 예시 이름은 모두 지어낸 것이다."""

from pathlib import Path

import pytest

from app import name_masking
from app.config import get_settings
from app.name_masking import (
    MIN_SCORE,
    NameMasker,
    NameModelMissingError,
    NameSpan,
    NameSpanCache,
    apply_name_spans,
    prepare_model_input,
    select_name_spans,
)
from app.privacy import mask_personal_identifiers
from tests.fakes import FakeFinder


class TestApplyNameSpans:
    def test_첫_글자만_남기고_가린다(self):
        assert apply_name_spans("수상자 홍길동", [NameSpan(4, 7)]) == "수상자 홍○○"

    def test_두_글자_이름(self):
        assert apply_name_spans("이휘 학생", [NameSpan(0, 2)]) == "이○ 학생"

    def test_공백은_남긴다(self):
        assert apply_name_spans("홍길동 김항공", [NameSpan(0, 7)]) == "홍○○ ○○○"

    def test_마크다운_기호는_남긴다(self):
        assert apply_name_spans("대 상**  가.", [NameSpan(0, 8)]) == "대 ○**  ○."


class TestSelectNameSpans:
    def test_기준_점수보다_낮으면_가리지_않는다(self):
        text = "수상자 홍길동, 천원의 아침밥"
        scored = [(NameSpan(4, 7), 0.99), (NameSpan(9, 11), MIN_SCORE - 0.01)]
        assert select_name_spans(text, scored) == [NameSpan(4, 7)]

    def test_기준_점수와_같으면_가린다(self):
        assert select_name_spans("홍길동", [(NameSpan(0, 3), MIN_SCORE)]) == [NameSpan(0, 3)]

    def test_한글이_없는_구간은_가리지_않는다(self):
        text = "California State University, San Bernardino 홍길동"
        scored = [(NameSpan(30, 44), 0.98), (NameSpan(45, 48), 0.98)]
        assert select_name_spans(text, scored) == [NameSpan(45, 48)]


    def test_URL과_겹치는_구간은_가리지_않는다(self):
        # 전수 점검에서 찾은 경우. 링크 앞뒤 `종`과 `료`가 한 구간으로 잡혔다.
        text = "참여하기 URL : **[종](https://forms.gle/AbCdEf123)료**"
        start, end = text.index("종"), text.index("료") + 1
        assert select_name_spans(text, [(NameSpan(start, end), 0.99)]) == []


class TestPrepareModelInput:
    def test_길이를_유지한다(self):
        text = "| 성명 | **홍길동** | [신청](https://kau.ac.kr/a?b=1) |"
        assert len(prepare_model_input(text)) == len(text)

    def test_URL과_마크다운_기호를_지운다(self):
        prepared = prepare_model_input("[신청](https://kau.ac.kr/a) **홍길동**")
        assert "kau.ac.kr" not in prepared
        assert "*" not in prepared
        assert "홍길동" in prepared


class TestNameMasker:
    def test_모델이_찾은_이름을_가린다(self):
        masker = NameMasker(FakeFinder("홍길동", "김교수"), cache=None)
        assert masker.mask("지도교수 김교수, 수상자 홍길동") == "지도교수 김○○, 수상자 홍○○"

    def test_빈_문자열은_모델을_돌리지_않는다(self):
        finder = FakeFinder("홍길동")
        masker = NameMasker(finder, cache=None)
        assert masker.mask("") == ""
        assert masker.mask("   ") == "   "
        assert finder.calls == 0

    def test_같은_본문은_캐시에서_꺼낸다(self, tmp_path):
        finder = FakeFinder("홍길동")
        masker = NameMasker(finder, NameSpanCache(tmp_path / "cache.db"))
        first = masker.mask("수상자 홍길동")
        second = masker.mask("수상자 홍길동")
        assert first == second == "수상자 홍○○"
        assert finder.calls == 1

    def test_캐시는_파일에_남아_다음_적재에서도_쓴다(self, tmp_path):
        path = tmp_path / "cache.db"
        NameMasker(FakeFinder("홍길동"), NameSpanCache(path)).mask("수상자 홍길동")
        finder = FakeFinder("홍길동")
        assert NameMasker(finder, NameSpanCache(path)).mask("수상자 홍길동") == "수상자 홍○○"
        assert finder.calls == 0

    def test_가린_본문을_다시_넘겨도_모델을_돌리지_않는다(self, tmp_path):
        finder = FakeFinder("홍길동")
        masker = NameMasker(finder, NameSpanCache(tmp_path / "cache.db"))
        masked = masker.mask("수상자 홍길동")
        assert masker.mask(masked) == masked
        assert finder.calls == 1


class TestSwitch:
    def test_끄면_그대로_둔다(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "privacy_mask_names", False)
        assert name_masking.mask_names("수상자 홍길동") == "수상자 홍길동"

    def test_켰는데_모델이_없으면_오류를_낸다(self, monkeypatch, tmp_path):
        monkeypatch.setattr(get_settings(), "privacy_mask_names", True)
        monkeypatch.setattr(get_settings(), "name_model_dir", tmp_path / "없음")
        monkeypatch.setattr(name_masking, "_masker", None)
        with pytest.raises(NameModelMissingError):
            name_masking.mask_names("수상자 홍길동")


class TestMaskPersonalIdentifiers:
    def test_학번과_이름을_함께_가린다(self, masking_on):
        masking_on(FakeFinder("홍길동"))
        masked = mask_personal_identifiers("| 2017999928 | 홍길동 | 02-300-0272 |")
        assert masked == "| 2017○○○○28 | 홍○○ | 02-300-0272 |"

    def test_모델에는_학번을_가린_본문이_들어간다(self, masking_on):
        seen = []

        class Recorder(FakeFinder):
            def find(self, text):
                seen.append(text)
                return []

        masking_on(Recorder())
        mask_personal_identifiers("학번 2017999928")
        assert seen == ["학번 2017○○○○28"]


MODEL_DIR = Path(get_settings().name_model_dir)


@pytest.fixture(scope="module")
def masker():
    return NameMasker(name_masking.OnnxNameFinder(MODEL_DIR), cache=None)


@pytest.mark.skipif(not (MODEL_DIR / "onnx" / "model_int8.onnx").exists(), reason="이름 마스킹 모델 파일 없음")
class TestRealModel:
    """실제 오닉스 모델로 돌린다. 모델 파일이 있을 때만 실행한다."""

    def test_문장_속_학생_이름을_가린다(self, masker):
        masked = masker.mask("항공교통 경진대회 수상자: 최우수상 서지안(항공교통물류학부), 우수상 남궁현")
        assert "서지안" not in masked
        assert "남궁현" not in masked

    def test_교수와_담당자_이름도_가린다(self, masker):
        masked = masker.mask("지도교수 윤재혁 교수님께 제출하고, 문의는 학사팀 오미란 주무관(02-300-0123)")
        assert "윤재혁" not in masked
        assert "오미란" not in masked
        assert "02-300-0123" in masked

    def test_학번_뒤_이름을_가린다(self, masker):
        masked = masker.mask("구조생산 1 기계 2017○○○○28 한도윤 공작기계 역설계")
        assert "한도윤" not in masked
        assert "2017○○○○28" in masked

    # 아래 두 테스트는 이전 이름 규칙의 오탐(학번 뒤 `선발`·`예비` 11곳, 여러 행으로 나뉜
    # 표 머리글 18곳)이 모델로 바꾼 뒤에도 다시 생기지 않는지 본다. 표는 실제 공지의
    # 형태를 따르고 이름은 지어냈다.
    @pytest.mark.parametrize(
        "text",
        [
            "학번 선발여부 2021○○○○40 선발 2022○○○○56 선발 2020○○○○30 예비",
            "| 학번 | 결과 |\n| --- | --- |\n| 2021○○○○40 | 선발 |\n| 2022○○○○56 | 예비 |",
        ],
    )
    def test_학번_뒤_선발_여부는_가리지_않는다(self, masker, text):
        assert masker.mask(text) == text

    @pytest.mark.parametrize(
        "table, name",
        [
            (
                "| 분과 | 동아리명 | 동아리대표 | | 장학금 |\n| --- | --- | --- | --- | --- |\n"
                "| | | 학번 | 성명 | |\n| 항공분과 | 비행연구회 | 2021○○○○30 | 김민준 | 3,000,000 |",
                "김민준",
            ),
            (
                "| 단과대학 | 우수활동 재학생멘토 | | | 장학금 |\n| --- | --- | --- | --- | --- |\n"
                "| | 팀명 | 학번 | 성명 | |\n| 공과대학 | 날개팀 | 2022○○○○49 | 박서연 | 200,000원 |",
                "박서연",
            ),
            (
                "| 구분 | 신청자 | | | |\n| --- | --- | --- | --- | --- |\n"
                "| 순번 | 학부(과) | 학번 | 생년월일 | 연락처 |\n| 1 | 항공우주공학과 | 2023○○○○15 | 2004.03.02 | 010-1234-5678 |",
                None,
            ),
        ],
    )
    def test_여러_행으로_나뉜_표_머리글은_가리지_않는다(self, masker, table, name):
        masked = masker.mask(table)
        for header in ("학번", "성명", "학부(과)", "생년월일", "연락처", "팀명", "순번"):
            assert masked.count(header) == table.count(header)
        if name:
            assert name not in masked

    def test_링크와_이미지_주소를_건드리지_않는다(self, masker):
        text = "![포스터](https://kau.ac.kr/upfile/2026/a.jpg)\n[신청서](https://kau.ac.kr/bbs/down.php?no=1)"
        assert masker.mask(text) == text
