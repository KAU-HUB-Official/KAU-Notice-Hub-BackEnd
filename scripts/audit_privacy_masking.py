"""공지 전체를 마스킹해 보고 결과를 점검한다.

    python scripts/audit_privacy_masking.py [공지 JSON] [--top N] [--all]

공지 JSON을 생략하면 설정의 NOTICE_JSON_PATH를 읽는다. 앱과 같은 경로로 본문을
정리하고(`normalize_notice`) 가린 뒤(`mask_personal_identifiers`) 세 가지를 출력한다.

1. 남은 학번: 가린 본문에 10자리 학번이 남아 있는 곳. 0이어야 한다.
2. 바뀐 URL: 링크·이미지·메일 주소가 마스킹 전후로 달라진 곳. 0이어야 한다.
3. 이름으로 가린 단어: 모델이 이름으로 보고 가린 구간(두 글자 이상)과 횟수.
   이름이 아닌 단어(오탐)가 섞였는지 사람이 훑어본다.

이름은 PRIVACY_MASK_NAMES가 켜져 있고 모델 파일이 있을 때만 점검한다. 이름 위치
캐시(NAME_MASK_CACHE_PATH)를 쓰므로 처음에는 전체 공지에 10분 넘게 걸리고, 그
다음부터는 바뀐 본문만 모델을 돌린다.

3번 출력에는 실명이 들어 있다. 결과를 저장소에 올리거나 공유하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.normalize import normalize_notice  # noqa: E402
from app.privacy import STUDENT_ID_RE, mask_personal_identifiers, mask_student_ids  # noqa: E402

URL_RE = re.compile(r"(?:https?://|mailto:)[^\s)\]>\"']+")
CONTEXT_CHARS = 20


def snippet(text: str, start: int, end: int) -> str:
    left = max(0, start - CONTEXT_CHARS)
    return " ".join(text[left : end + CONTEXT_CHARS].split())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("json_path", nargs="?", type=Path)
    parser.add_argument("--top", type=int, default=50, help="이름으로 가린 단어를 몇 개까지 출력할지")
    parser.add_argument("--all", action="store_true", help="이름으로 가린 단어를 전부 출력")
    args = parser.parse_args()

    settings = get_settings()
    json_path = args.json_path or settings.notice_json_path
    items = [item for item in json.loads(Path(json_path).read_text(encoding="utf-8")) if isinstance(item, dict)]

    # 정리만 하고 가리지 않은 본문을 얻은 뒤, 가리는 것은 아래에서 직접 한다.
    settings.privacy_mask_body = False
    check_names = settings.privacy_mask_names
    masker = None
    if check_names:
        from app.name_masking import get_name_masker

        masker = get_name_masker()

    left_ids: list[str] = []
    changed_urls: list[str] = []
    url_total = 0
    words: Counter[str] = Counter()
    notices_with_names = 0

    for index, item in enumerate(items):
        notice = normalize_notice(item, index)
        plain = notice.content
        masked = mask_personal_identifiers(plain)

        for match in STUDENT_ID_RE.finditer(masked):
            left_ids.append(f"[{notice.id}] {snippet(masked, match.start(), match.end())}")

        before, after = Counter(URL_RE.findall(plain)), Counter(URL_RE.findall(masked))
        url_total += sum(before.values())
        for url in (before - after).elements():
            changed_urls.append(f"[{notice.id}] {url}")

        if masker:
            text = mask_student_ids(plain)
            found = [text[s.start : s.end] for s in masker.find_spans(text) if s.end - s.start >= 2]
            if found:
                notices_with_names += 1
                words.update(" ".join(word.split()) for word in found)

        if (index + 1) % 500 == 0:
            print(f"... {index + 1}/{len(items)}", file=sys.stderr, flush=True)

    print(f"공지 {len(items)}건 ({json_path})")
    print(f"\n1. 남은 학번: {len(left_ids)}곳")
    for line in left_ids[:20]:
        print(f"   {line}")

    print(f"\n2. 바뀐 URL: {len(changed_urls)}개 (전체 URL {url_total}개)")
    for line in changed_urls[:20]:
        print(f"   {line}")

    if not check_names:
        print("\n3. 이름으로 가린 단어: PRIVACY_MASK_NAMES=false라 점검하지 않음")
        return
    shown = words.most_common() if args.all else words.most_common(args.top)
    print(
        f"\n3. 이름으로 가린 단어: 구간 {sum(words.values())}개, 서로 다른 단어 {len(words)}개, "
        f"공지 {notices_with_names}건"
    )
    print("   (실명이 들어 있다. 이 출력을 공유하지 않는다.)")
    for word, count in shown:
        print(f"   {count:5d}  {word}")


if __name__ == "__main__":
    main()
