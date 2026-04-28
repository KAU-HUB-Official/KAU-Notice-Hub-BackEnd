# 실행 가이드

## 요구사항

- Python 3.11+
- 외부 사이트 접근 가능한 네트워크 환경

## 설치

```bash
python3 -m pip install -e .
```

## 기본 실행

```bash
python3 -m app.crawler.main
```

## 주요 옵션

```bash
python3 -m app.crawler.main --max-pages 3
python3 -m app.crawler.main --output data/custom_posts.json
```

- `--max-pages`: 보드별 목록 탐색 페이지 상한. `0`이면 상한 없이 최근성 정책으로 자동 중단(기본값: `0`)
- `--output`: 결과 JSON 저장 경로(기본값: `data/kau_official_posts.json`)

참고: `--output` 파일은 다음 실행에서 증분 수집 기준 파일(기존 데이터 로드)로도 사용됩니다.

## 기본 산출물

- 게시글 결과: `data/kau_official_posts.json`
- 실패 내역: `data/kau_official_failed.json`
- 실행 로그: `data/crawler.log`

## 증분 수집 동작

- 크롤러는 실행 시작 시 결과 파일의 `original_url`과 `source_meta[].original_url`을 읽어 캐시를 구성합니다.
- 이미 수집된 URL은 상세 요청을 건너뛰되, 기존 `published_at`으로 일반공지 중단 여부를 판단합니다.
- 기본 실행은 신규 URL 0건만으로 페이지 순회를 멈추지 않고, 오래된 일반공지/빈 목록/반복 목록을 만날 때 종료합니다.

## 빠른 점검

```bash
python3 - <<'PY'
import json
from pathlib import Path

p = Path('data/kau_official_posts.json')
if not p.exists():
    print('output file not found')
else:
    posts = json.loads(p.read_text(encoding='utf-8'))
    print('count =', len(posts))
    print('first_title =', posts[0]['title'] if posts else None)
PY
```
