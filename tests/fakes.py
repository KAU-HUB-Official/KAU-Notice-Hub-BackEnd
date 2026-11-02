"""여러 테스트가 함께 쓰는 가짜 객체."""

from app.name_masking import NameSpan


class FakeFinder:
    """주어진 이름이 나오는 위치를 돌려주는 가짜 모델."""

    def __init__(self, *names: str):
        self.names = names
        self.calls = 0

    def find(self, text: str) -> list[NameSpan]:
        self.calls += 1
        spans = []
        for name in self.names:
            start = text.find(name)
            while start != -1:
                spans.append(NameSpan(start, start + len(name)))
                start = text.find(name, start + 1)
        return spans
