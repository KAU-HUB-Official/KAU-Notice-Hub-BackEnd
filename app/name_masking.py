"""NER 모델로 공지 속 사람 이름을 찾아 가린다.

학생·교수·담당자를 구분하지 않고 사람 이름은 모두 첫 글자만 남기고 가린다
(`홍길동` → `홍○○`). 문의처는 전화번호와 메일이 남아 있어 이름이 없어도 찾을 수 있다.

모델은 `atonlee/koelectra-ko-pii-ner`(KoELECTRA-small, Apache-2.0, 커밋 `1e75c01e`)를
검수한 공지 478건(1차 279건 + 2차 199건)으로 파인튜닝해 오닉스 int8로 바꾼 파일이다.
토크나이저와 라벨은 원래 모델과 같다. 실명이 든 공지로 학습했으므로
공개 저장소에 올리지 않고 서버에 직접 둔다(scripts/install_name_model.py).
PyTorch 없이 `onnxruntime`과 `tokenizers`만으로 돌린다. 모델 결과에서 신뢰 점수가
MIN_SCORE 이상이고 한글이 든 구간만 가리고, 링크가 깨지지 않도록 URL과 겹치는 구간은
뺀다. 그 밖의 이름 판단 규칙(단어 목록, 길이 조건 등)은 덧붙이지 않는다.

학습에 쓰지 않은 평가 공지 50건에서 실제 이름의 96.8%를 전부 가리고, 가린 구간의
1.3%만 이름이 아니다(1차 279건 모델은 95.5%, 21.2%). 비교 방법과 결과는
docs/PRIVACY_MASKING.md에 있다.

전체 공지를 한 번 돌리는 데 CPU 한 코어로 10분 넘게 걸린다. 공지 DB는 크롤링마다
전체를 다시 적재하므로, 본문 해시별로 찾은 이름 위치를 SQLite 파일에 저장해 두고
바뀌지 않은 본문은 모델을 다시 돌리지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.privacy import MASK_CHAR, URL_RE

logger = logging.getLogger(__name__)

MODEL_FILES = ("config.json", "onnx/model_int8.onnx", "onnx/tokenizer.json")
# 평가한 파인튜닝 모델 파일. 모델을 다시 학습하면 다시 평가하고 이 값과 MODEL_VERSION을 바꾼다.
MODEL_SHA256 = {
    "config.json": "65b1c2e17c4eb6d4f5be29e4374784a03c7b886229af948757e55f3b79444a23",
    "onnx/model_int8.onnx": "56ffa2e2f5025ba89f86d6c564d40400f33670261f83a1ea4880f6ad3da869a4",
    "onnx/tokenizer.json": "9bc85a2412ae3694bffac69cb152a9aafd59fd0357e540a343fa9daa62099c38",
}
PERSON_LABEL = "NAME"
# 캐시 키에 들어간다. 모델이나 입력 처리 방식을 바꾸면 올려서 이전 결과를 버린다.
MODEL_VERSION = f"kau-finetuned@{MODEL_SHA256['onnx/model_int8.onnx'][:12]}/int8/v4"

MAX_TOKENS = 512
STRIDE = 64

# 구간 신뢰 점수가 이보다 낮으면 가리지 않는다. 파인튜닝 모델은 기준을 올려도 이름 아닌
# 구간이 줄지 않고(0.5~0.8 모두 1.3%) 놓치는 이름만 늘어서(전부 가림 96.8% → 93.6%)
# 평가 공지에서 가장 낮게 잰 0.5를 쓴다.
MIN_SCORE = 0.5
# 한글이 없는 구간(해외 대학·시험 이름 등)은 가리지 않는다. 표본에서 영문으로만 된
# 이름은 공인(외국 정상) 1명뿐이었고, 영문 오탐은 교환학생 공지의 핵심 정보를 지웠다.
_HANGUL_RE = re.compile(r"[가-힣]")

# 모델 입력에서 지울 것. URL 안을 가리면 링크가 깨지고, 마크다운 기호는 이름 판단에
# 쓸모가 없다. 같은 길이의 공백으로 바꿔 모델이 돌려준 위치를 원문에 그대로 쓴다.
# URL 패턴은 학번 마스킹과 같은 것(`app.privacy.URL_RE`)을 쓴다.
_MARKUP_RE = re.compile(r"[|*#`>\[\]]")


class NameModelMissingError(RuntimeError):
    """이름 마스킹이 켜져 있는데 모델 파일이 없다."""


@dataclass(frozen=True)
class NameSpan:
    start: int
    end: int


def prepare_model_input(text: str) -> str:
    def blank(match: re.Match[str]) -> str:
        return " " * len(match.group(0))

    return _MARKUP_RE.sub(blank, URL_RE.sub(blank, text))


def _strip_punctuation(text: str, start: int, end: int) -> tuple[int, int]:
    """모델이 잡은 구간 앞뒤의 공백·기호를 뗀다."""
    while start < end and not text[start].isalnum():
        start += 1
    while end > start and not text[end - 1].isalnum():
        end -= 1
    return start, end


def select_name_spans(text: str, scored: list[tuple[NameSpan, float]]) -> list[NameSpan]:
    """가릴 구간을 고른다. 신뢰 점수가 MIN_SCORE 이상이고 한글이 든 구간만 가린다.

    URL과 겹치는 구간도 가리지 않는다. 모델 입력에서 URL을 공백으로 지우므로
    `**[종](https://...)료**`의 `종 … 료`처럼 링크 앞뒤 글자가 한 구간으로 잡히면
    그 사이 URL까지 가려져 링크가 깨진다.
    """
    urls = [m.span() for m in URL_RE.finditer(text)]
    return [
        span
        for span, score in scored
        if score >= MIN_SCORE
        and _HANGUL_RE.search(text[span.start : span.end])
        and not any(span.start < end and start < span.end for start, end in urls)
    ]


def apply_name_spans(text: str, spans: list[NameSpan]) -> str:
    """구간마다 첫 글자를 남기고 가린다. 글자와 숫자만 가리고 공백·기호는 그대로 둔다."""
    chars = list(text)
    for span in spans:
        for i in range(span.start + 1, span.end):
            # 구간 안의 마크다운 기호(`**` 등)를 가리면 강조 표시가 깨진다.
            if chars[i].isalnum():
                chars[i] = MASK_CHAR
    return "".join(chars)


class OnnxNameFinder:
    """오닉스 int8 모델로 사람 이름 구간을 찾는다."""

    def __init__(self, model_dir: Path):
        # 이름 마스킹을 끈 환경에서는 런타임을 메모리에 올리지 않도록 여기서 불러온다.
        import onnxruntime as ort
        from tokenizers import Tokenizer

        config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        id2label = {int(k): v for k, v in config["id2label"].items()}
        self._b_ids = {i for i, label in id2label.items() if label == f"B-{PERSON_LABEL}"}
        self._i_ids = {i for i, label in id2label.items() if label == f"I-{PERSON_LABEL}"}
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1  # 서버 CPU를 API와 나눠 쓴다
        self._session = ort.InferenceSession(
            str(model_dir / "onnx" / "model_int8.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        self._tokenizer = Tokenizer.from_file(str(model_dir / "onnx" / "tokenizer.json"))
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()
        self._cls = self._tokenizer.token_to_id("[CLS]")
        self._sep = self._tokenizer.token_to_id("[SEP]")

    def _windows(self, n_tokens: int):
        body = MAX_TOKENS - 2
        start = 0
        while True:
            end = min(start + body, n_tokens)
            yield start, end
            if end >= n_tokens:
                return
            start = end - STRIDE

    def find(self, text: str) -> list[NameSpan]:
        return select_name_spans(text, self.find_scored(text))

    def find_scored(self, text: str) -> list[tuple[NameSpan, float]]:
        """찾은 이름 구간과 구간 신뢰 점수(0~1)를 돌려준다."""
        prepared =prepare_model_input(text)
        encoding = self._tokenizer.encode(prepared, add_special_tokens=False)
        ids, offsets = encoding.ids, encoding.offsets
        if not ids:
            return []
        n = len(ids)
        best_label = [0] * n
        best_prob = [0.0] * n
        for start, end in self._windows(n):
            window = np.array([[self._cls, *ids[start:end], self._sep]], dtype=np.int64)
            feed = {"input_ids": window}
            if "attention_mask" in self._input_names:
                feed["attention_mask"] = np.ones_like(window)
            if "token_type_ids" in self._input_names:
                feed["token_type_ids"] = np.zeros_like(window)
            logits = self._session.run(None, feed)[0][0][1:-1]
            probs = np.exp(logits - logits.max(-1, keepdims=True))
            probs /= probs.sum(-1, keepdims=True)
            # 창이 겹치는 토큰은 확률이 더 높은 쪽 결과를 쓴다.
            for k, p in enumerate(probs):
                label = int(p.argmax())
                if p[label] > best_prob[start + k]:
                    best_label[start + k], best_prob[start + k] = label, float(p[label])

        spans: list[tuple[NameSpan, float]] = []
        current: list[int] | None = None  # [시작 위치, 끝 위치, 첫 토큰, 끝 토큰 다음]

        def close() -> None:
            s, e = _strip_punctuation(text, current[0], current[1])
            if e > s:
                # 구간 신뢰 점수는 구간 토큰 확률의 평균이다(평가에 쓴 transformers와 같은 방식).
                spans.append((NameSpan(s, e), float(np.mean(best_prob[current[2] : current[3]]))))

        for t in range(n):
            label = best_label[t]
            s, e = offsets[t]
            if label in self._b_ids or (label in self._i_ids and current is None):
                if current:
                    close()
                current = [s, e, t, t + 1]
            elif label in self._i_ids:
                current[1], current[3] = e, t + 1
            elif current:
                close()
                current = None
        if current:
            close()
        return spans


class NameSpanCache:
    """본문 해시별로 찾은 이름 위치를 저장한다. 크롤링마다 바뀐 본문만 모델을 돌린다."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("CREATE TABLE IF NOT EXISTS name_spans (key TEXT PRIMARY KEY, spans TEXT NOT NULL)")
        self._conn.commit()
        self._lock = threading.Lock()

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha256(f"{MODEL_VERSION}\n{text}".encode("utf-8")).hexdigest()

    def get(self, text: str) -> list[NameSpan] | None:
        with self._lock:
            row = self._conn.execute("SELECT spans FROM name_spans WHERE key = ?", (self.key(text),)).fetchone()
        if row is None:
            return None
        return [NameSpan(s, e) for s, e in json.loads(row[0])]

    def put(self, text: str, spans: list[NameSpan]) -> None:
        payload = json.dumps([[s.start, s.end] for s in spans])
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO name_spans (key, spans) VALUES (?, ?)", (self.key(text), payload)
            )
            self._conn.commit()


class NameMasker:
    """캐시를 먼저 보고, 없을 때만 모델로 이름을 찾아 가린다."""

    def __init__(self, finder, cache: NameSpanCache | None):
        self._finder = finder
        self._cache = cache

    def find_spans(self, text: str) -> list[NameSpan]:
        """가릴 이름 구간. 전수 점검(scripts/audit_privacy_masking.py)도 이 결과를 쓴다."""
        if not text or not text.strip():
            return []
        spans = self._cache.get(text) if self._cache else None
        if spans is None:
            spans = self._finder.find(text)
            if self._cache:
                self._cache.put(text, spans)
        return spans

    def mask(self, text: str) -> str:
        if not text or not text.strip():
            return text
        masked = apply_name_spans(text, self.find_spans(text))
        # 가린 결과도 "더 가릴 것 없음"으로 저장한다. 검색 인덱스와 챗봇이 이미 가린
        # 본문을 다시 넘겨도 모델을 또 돌리지 않는다.
        if self._cache and masked != text and self._cache.get(masked) is None:
            self._cache.put(masked, [])
        return masked


_masker: NameMasker | None = None
_masker_lock = threading.Lock()


def get_name_masker() -> NameMasker:
    global _masker
    if _masker is None:
        with _masker_lock:
            if _masker is None:
                from app.config import get_settings

                settings = get_settings()
                model_dir = Path(settings.name_model_dir)
                missing = [f for f in MODEL_FILES if not (model_dir / f).exists()]
                if missing:
                    raise NameModelMissingError(
                        f"이름 마스킹 모델 파일이 없습니다: {model_dir} ({', '.join(missing)}). "
                        "scripts/install_name_model.py로 넣거나 PRIVACY_MASK_NAMES=false로 끄세요."
                    )
                logger.info("name masking model loading: %s", model_dir)
                _masker = NameMasker(OnnxNameFinder(model_dir), NameSpanCache(Path(settings.name_mask_cache_path)))
    return _masker


def mask_names(text: str) -> str:
    """사람 이름을 가린다. `PRIVACY_MASK_NAMES=false`면 그대로 돌려준다."""
    from app.config import get_settings

    if not text or not get_settings().privacy_mask_names:
        return text
    return get_name_masker().mask(text)
