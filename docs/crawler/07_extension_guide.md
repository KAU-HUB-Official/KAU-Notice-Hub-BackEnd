# 확장 가이드

## 1) 기존 board_type 재사용 추가 (권장)

동일한 구조의 게시판이면 기존 client/parser를 재사용하는 방식이 가장 안전합니다.

작업 순서:

1. `app/crawler/config.py`의 `NOTICE_BOARDS`에 신규 항목 추가
2. `key`, `name`, `board_type`, `list_url`, `source_name`, `source_type` 설정
3. board_type별 필수 필드(`code`, `bbs_id`, `bo_table` 등) 설정
4. 구조 점검은 `python3 -m app.crawler.main --max-pages 1`, 실제 수집은 `python3 -m app.crawler.main`로 결과/실패 로그 확인

## 2) 신규 사이트(신규 board_type) 추가

작업 순서:

1. `app/crawler/clients/`에 `XXXClient` 추가
2. `app/crawler/parsers/`에 `XXXParser` 추가
3. `app/crawler/services/board_registry.py`에 board_type 매핑(`BoardAdapter`) 추가
4. `app/crawler/config.py`의 `NOTICE_BOARDS`에 신규 보드 설정 추가
5. `docs/crawler/03`, `docs/crawler/05`, `docs/crawler/08` 문서 동시 업데이트

## 3) 현재 재사용 가능한 board_type

- `kau_official`: 공식홈 `mode=read&seq` 계열
- `kau_career`: 대학일자리센터 목록/상세
- `kau_college`: college JSON API(`bbsListApi`, `bbsViewApi`)
- `kau_card_notice`: AI융합대학/학과 `notice.php` 카드형 목록/상세
- `kau_research`: research `mode=read&seq` 계열
- `kau_admission`: 입학처 `viewBoardProcess` 계열
- `kau_ctl`: ctl `mode=read&seq` 계열
- `kau_library`: `sb_no` 기반 목록/상세
- `kau_ftc`: ftc `mode=read&seq` 계열
- `kau_community_php`: fsc/grad/gradbus 공통 PHP 게시판
- `kau_amtc`: GNU board(`bo_table`, `wr_id`) 계열
- `kau_lms_ubboard`: LMS `view.php/article.php` 계열
- `kau_asbt`: `ptype=list/view&idx` 계열
- `kau_eslscat`: eSLS CAT 계열(현재 기본 목록 비활성)

## 4) BoardAdapter 구현 체크포인트

- `build_list_page_url(board, page)`
- `fetch_list_html(board, page)`
- `fetch_detail(board, detail_url)` -> `DetailFetchResult` 반환
- `parser_factory(board)`
- 필요 시
  - `can_fetch` + `check_robots_on_list/detail`
  - `min_pages_field` (최소 페이지 보장)

## 5) Parser 구현 체크리스트

- 목록 링크 selector가 최신 DOM 구조를 반영하는가
- `is_permanent_notice` 판정이 안정적인가
- 상세에서 `title`, `content`, `published_at`를 일관되게 추출하는가
- 첨부 링크를 절대경로로 변환하는가
- 이미지 본문 fallback이 필요한가
- 실패 reason이 운영 관점에서 분리 가능한가

## 6) 권장 검증 명령

```bash
python3 -m app.crawler.main --max-pages 1
python3 - <<'PY'
import json
from pathlib import Path

posts_path = Path('data/kau_official_posts.json')
failed_path = Path('data/kau_official_failed.json')

posts = json.loads(posts_path.read_text(encoding='utf-8')) if posts_path.exists() else []
failed = json.loads(failed_path.read_text(encoding='utf-8')) if failed_path.exists() else []

print('posts =', len(posts))
print('failed =', len(failed))
print('sample title =', posts[0]['title'] if posts else None)
PY
```
