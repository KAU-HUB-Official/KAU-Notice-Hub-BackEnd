# 첨부/이미지 기반 content 보강 계획

## 범위

이 문서는 크롤링 시점에 텍스트 본문이 부재한 공지의 `content`를 보강하는 계획을 정의한다.

대상 케이스: 본문영역에 텍스트가 없는 경우 중,

1. 이미지 첨부파일이 있는 경우
2. HWP 첨부파일이 있는 경우
3. 본문 영역에 이미지만 포함하는 경우

목표는 첨부파일 또는 이미지에서 텍스트를 추출하고, LLM으로 공지 검색/RAG에 사용할 수 있는 `content`를 생성하는 것이다.
여러 케이스가 중복으로 발생할 수 있다. 그런 경우 정보를 총합하여 본문을 생성한다.

## 구현

현재 구현은 feature flag 기본값을 `false`로 두고, 크롤러 최종 JSON 저장 직전에만 보강 pipeline을 실행한다. 본문 이미지 URL은 상세 HTML에서 `content_assets`로 수집하고, 첨부파일은 이미지/HWP/HWPX만 보강 대상으로 분류한다. 본문이 동영상 iframe만 포함한 경우는 크롤링 실패로 보내지 않고 동영상 fallback content로 최소 정보를 보존하지만, 현재 LLM 보강 대상에는 포함하지 않는다.

보강 흐름은 아래 adapter로 분리되어 있다.

| 책임                               | 구현 경로                                                    |
| ---------------------------------- | ------------------------------------------------------------ |
| 후보 판단과 metadata 기록          | `app/crawler/services/content_enrichment_service.py`         |
| asset 안전성 검사와 다운로드       | `app/crawler/services/content_asset_downloader.py`           |
| HWP/HWPX 텍스트 추출               | `app/crawler/services/content_extractors/hwp_extractor.py`   |
| 이미지 텍스트 추출 및 content 생성 | `app/crawler/services/content_extractors/openai_provider.py` |

OpenAI provider는 Responses API를 사용하며, 크롤러 보강 요청에는 `store=false`를 지정해 응답 상태 저장을 사용하지 않는다. `OPENAI_API_KEY`가 없으면 보강 후보를 실패 metadata로만 기록하고 asset 다운로드나 API 호출은 수행하지 않는다.

## 비목표

- LLM이 원문에 없는 날짜, 장소, 신청 조건을 추측해서 생성하지 않는다.
- 기존 원문 텍스트가 충분한 공지를 LLM으로 다시 쓰지 않는다.
- 바이너리 첨부파일을 JSON 스냅샷에 저장하지 않는다.
- 최초 구현에서 vector DB, Redis, Celery 같은 별도 인프라를 추가하지 않는다.
- HWP 바이너리를 그대로 LLM에 던지는 방식은 사용하지 않는다.

## 현재 문제

현재 파서는 본문 텍스트가 비어 있으면 아래처럼 fallback 문자열을 저장한다.

- `[이미지 본문] 텍스트 본문 없음 (이미지 N개)`
- `[동영상 본문] 텍스트 본문 없음 (동영상 N개)`
- 첨부파일명 기반 fallback
- `본문 정보가 비어 있습니다.`

이 fallback은 API 필수 필드 누락을 막는 데는 충분하지만, 검색/RAG 품질에는 부족하다. 사용자가 질문했을 때 실제 모집 기간, 제출 서류, 신청 방법, 문의처 같은 핵심 정보가 이미지나 HWP 안에 있으면 현재 검색 대상에 들어오지 않는다.

## 기본 방향

크롤러 상세 파싱, 병합, 중복 제거, 오래된 공지 삭제가 끝난 뒤 최종 JSON 저장 전 단계에서 content 보강 pipeline을 실행한다.

```text
상세 HTML/JSON 파싱
  -> title/content/attachments/image_urls 추출
  -> 기존 데이터 병합/중복제거/1년 초과 일반공지 삭제
  -> content 보강 필요 여부 판단
  -> 이미지/HWP asset 다운로드
  -> 추출 API 또는 로컬 parser로 raw text 확보
  -> LLM으로 공지용 content 생성
  -> 검증
  -> post.content 교체 또는 fallback 유지
  -> enrichment metadata 기록
  -> atomic JSON publish
```

중요한 기준:

- 원문 텍스트가 충분하면 보강하지 않는다.
- 보강 실패는 크롤링 실패로 취급하지 않고 기존 fallback content를 유지한다.
- 보강 결과는 출처와 처리 상태를 metadata로 남긴다.
- LLM 생성 content는 추출된 텍스트와 기존 공지 메타데이터 안에서만 작성한다.

## 보강 필요 여부 판단

아래 조건 중 하나면 보강 후보로 본다.

| 조건                                       | 예시                                              |
| ------------------------------------------ | ------------------------------------------------- |
| content가 비어 있음                        | `""`, `None`                                      |
| content가 시스템 fallback임                | `[이미지 본문] ...`, `[동영상 본문] ...`, `본문 정보가 비어 있습니다.` |
| content가 첨부파일명만 담고 있음           | `첨부파일: 모집요강.hwp`                          |
| 본문 텍스트 길이가 너무 짧고 이미지가 있음 | 텍스트 30자 미만 + `img` 존재                     |
| 본문 텍스트가 없고 첨부파일이 있음         | 이미지, HWP 첨부                                  |

초기 기준값:

```text
CONTENT_ENRICHMENT_MIN_TEXT_LENGTH=30
CONTENT_ENRICHMENT_MAX_ASSETS_PER_NOTICE=3
CONTENT_ENRICHMENT_MAX_FILE_BYTES=10485760
```

## 케이스별 처리 계획

### 1. 이미지 첨부파일만 있는 경우

처리 순서:

1. 첨부파일 URL과 파일명을 수집한다.
2. 확장자와 `Content-Type`으로 이미지 여부를 확인한다.
3. 허용된 도메인에서만 다운로드한다.
4. 이미지 OCR/Vision API로 텍스트와 시각적 구조를 추출한다.
5. 추출 결과를 LLM에 전달해 공지 본문 형태로 정리한다.

생성 content 기준:

- 제목, 날짜, source, 원문 URL을 함께 사용한다.
- 이미지 안의 표, 일정, 문의처, 제출 서류를 bullet 또는 문단으로 풀어쓴다.
- 판독 불가 영역은 추측하지 않고 `[판독 불가]` 또는 `확인 필요`로 표시한다.

### 2. HWP 첨부파일만 있는 경우

HWP는 이미지보다 실패 가능성이 높으므로 별도 단계로 처리한다.

권장 순서:

1. HWP 파일을 다운로드한다.
2. 확장자, `Content-Type`, 파일 시그니처를 확인한다.
3. `.hwp`와 `.hwpx`를 구분한다.
4. 먼저 로컬 HWP text extractor로 텍스트 추출을 시도한다.
5. 로컬 추출이 실패하면 문서 추출 API 또는 변환 API를 사용한다.
6. 변환 API도 실패하면 기존 fallback content를 유지한다.
7. 텍스트를 얻은 뒤 LLM으로 공지용 content를 생성한다.

주의:

- HWP 지원 여부는 API마다 다르므로 구현 전에 사용할 provider를 확정해야 한다.
- HWP를 PDF 또는 이미지로 변환한 뒤 OCR하는 경로는 가능하지만, 변환 도구 설치와 서버 리소스 사용량을 검토해야 한다.
- LLM은 HWP 바이너리 자체를 해석하는 도구로 쓰지 않는다. 먼저 텍스트 또는 이미지 페이지로 변환한 뒤 사용한다.

초기 구현 판단:

| 방식                          | 장점                      | 단점                              | 초기 추천 |
| ----------------------------- | ------------------------- | --------------------------------- | --------- |
| 로컬 HWP text extractor       | 비용 낮음, API 의존 낮음  | HWP 버전/형식별 실패 가능         | 1순위     |
| 문서 추출 API                 | 구현 단순, 운영 관찰 쉬움 | 비용/개인정보/지원 형식 확인 필요 | 2순위     |
| HWP -> 이미지/PDF 변환 후 OCR | Vision API 재사용 가능    | 서버 패키지와 변환 안정성 부담    | fallback  |

#### HWP 텍스트 추출 구현 세부 계획

HWP 처리의 기본 원칙은 “바이너리 문서를 먼저 텍스트로 바꾸고, 그 텍스트만 LLM에 넘긴다”이다.

```text
.hwp/.hwpx 다운로드
  -> 크기/확장자/Content-Type/파일 시그니처 검증
  -> 암호화 여부 확인
  -> 로컬 text extractor 실행
  -> 텍스트 길이와 품질 검증
  -> LLM content generator 호출
  -> 실패 시 fallback 유지
```

초기 구현 후보:

| 포맷    | 1차 처리                              | 2차 처리                                  | 비고                                                         |
| ------- | ------------------------------------- | ----------------------------------------- | ------------------------------------------------------------ |
| `.hwpx` | ZIP/XML 직접 파싱 또는 HWP 라이브러리 | 문서 추출 API                             | HWPX는 ZIP 안의 XML text node를 읽을 수 있어 상대적으로 단순 |
| `.hwp`  | HWP 5.0 지원 Python 라이브러리        | 문서 추출 API 또는 PDF/이미지 변환 후 OCR | OLE 바이너리 구조라 직접 파싱하지 않음                       |

초기 라이브러리 후보와 결정:

- `unhwp`: HWP/HWPX 텍스트와 Markdown 추출을 지원하며 실제 smoke test에서 KAU HWP 텍스트 추출 확인
- `extract-hwp`: HWP 5.0과 HWPX 텍스트 추출을 지원하는 Python 라이브러리 후보였으나, 0.1.0 wheel에 import 가능한 모듈이 없어 기본 의존성에서는 제외
- `hwp-hwpx-parser`: HWP/HWPX reader와 text/table 추출 기능 후보
- `pyhwp`: HWP v5 분석/추출 도구지만 오래된 Python 지원 범위를 확인해야 함

초기 구현에서는 `unhwp`를 1차 extractor로 사용하되, 하나의 라이브러리에 강하게 결합하지 않도록 adapter로 감싼다.

```text
app/crawler/services/content_extractors/hwp_extractor.py
```

예상 interface:

```python
class HwpTextExtractor:
    def extract(self, file_path: Path) -> ExtractedText:
        ...
```

`ExtractedText`에는 최소 아래 정보를 담는다.

```text
text
format: hwp|hwpx
method: unhwp|extract-hwp|hwpx-xml|document-api|ocr-fallback
confidence: high|medium|low
warnings
```

추출 성공 기준:

- 추출 텍스트가 비어 있지 않다.
- 공백 제거 후 최소 길이 이상이다. 초기값은 `CONTENT_ENRICHMENT_MIN_TEXT_LENGTH=30`.
- 암호화 파일이 아니다.
- 오류 문구만 추출된 결과가 아니다.

실패 처리:

- 암호화 파일: `content_enrichment.error_code=password_protected_hwp`
- 미지원 HWP 버전: `unsupported_hwp_format`
- 텍스트 추출 실패: `hwp_text_extract_failed`
- 추출 텍스트 부족: `hwp_text_too_short`
- 파일 크기 초과: `asset_too_large`

이 실패들은 크롤링 전체 실패로 보지 않는다. 해당 공지는 기존 fallback content를 유지하고 `content_enrichment.status=failed`만 기록한다.

### 3. 본문에 이미지만 있는 경우

처리 순서:

1. 본문 HTML에서 `img[src]`, `alt`, 주변 caption 텍스트를 수집한다.
2. 이미지 URL을 절대 URL로 변환한다.
3. 이미지가 여러 개면 최대 N개까지만 처리한다.
4. `alt` 텍스트가 충분하면 API 호출 전에 보조 context로 사용한다.
5. 이미지 OCR/Vision API로 텍스트를 추출한다.
6. LLM으로 공지용 content를 생성한다.

이 케이스는 첨부 이미지와 달리 본문 이미지가 원문 안내 전체일 가능성이 높다. 따라서 `alt`, caption, 이미지 표시 순서를 보존해 LLM에 전달한다.

## API provider 설계

초기 구현은 provider 교체가 가능하도록 interface를 분리한다.

```text
ContentAssetDownloader
  -> URL 안전성 검사
  -> 다운로드
  -> 확장자/content-type/크기 검증

ContentExtractor
  -> extract_image(asset) -> ExtractedText
  -> extract_hwp(asset) -> ExtractedText

NoticeContentGenerator
  -> generate_content(notice_meta, extracted_texts) -> GeneratedContent

ContentEnrichmentService
  -> should_enrich(post)
  -> enrich(post) -> post
```

OpenAI를 1차 provider로 사용할 경우:

- 이미지 OCR/해석: vision 가능한 LLM API
- content 생성: 텍스트 LLM API
- RAG 답변 단계: 추후 Responses API 또는 자체 검색/embedding pipeline 검토

OpenAI 공식 예제는 Vision과 Responses API를 조합해 이미지와 텍스트를 함께 다루는 RAG 구성을 설명하고, Responses API의 file search는 vector store 기반 검색과 답변 생성을 단순화할 수 있다고 설명한다. 단, 이 프로젝트의 초기 목표는 먼저 공지 JSON의 `content` 품질을 높이는 것이므로, hosted file search 도입은 후속 단계로 분리한다.

## LLM 출력 계약

LLM은 반드시 JSON 형태로 응답하게 한다.

```json
{
  "content": "검색과 답변에 사용할 Markdown 공지 본문",
  "summary": "짧은 요약",
  "confidence": "high|medium|low",
  "warnings": ["판독 불가 영역이 있음"],
  "source_asset_names": ["모집안내.hwp"]
}
```

프롬프트 원칙:

- 공지 제목, 게시일, source, 원문 URL, 첨부파일명, 추출 텍스트만 근거로 사용한다.
- 날짜, 금액, 장소, 신청 링크, 제출 서류는 원문에 있을 때만 작성한다.
- 판독이 불확실한 정보는 확정 문장으로 쓰지 않는다.
- 학생이 검색할 만한 키워드는 자연스럽게 포함하되 과장하지 않는다.
- 한국어로 작성한다.
- `content`는 Markdown 문법으로 작성한다.
- 제목은 `##`, 하위 항목은 `###`, 목록은 `-` 또는 `1.`을 사용한다.
- 원문에 표가 있으면 가능한 한 Markdown table로 변환한다.

## 데이터 모델 계획

공개 API의 `Notice.content`는 최종 검색 가능한 본문으로 유지한다. 대신 크롤러 원본 JSON에는 보강 metadata를 추가한다.

예시:

```json
{
  "title": "장학금 신청 안내",
  "content": "LLM으로 정리된 최종 본문",
  "content_original": "[이미지 본문] 텍스트 본문 없음 (이미지 1개)",
  "content_enrichment": {
    "enabled": true,
    "status": "success",
    "trigger": "image_only_body",
    "provider": "openai",
    "model": "gpt-4.1-mini",
    "assets": [
      {
        "type": "inline_image",
        "name": "notice-image-1.png",
        "url": "https://...",
        "sha256": "..."
      }
    ],
    "confidence": "medium",
    "warnings": [],
    "generated_at": "2026-05-03T00:00:00+09:00"
  }
}
```

실패 예시:

```json
{
  "content": "[이미지 본문] 텍스트 본문 없음 (이미지 1개)",
  "content_enrichment": {
    "enabled": true,
    "status": "failed",
    "trigger": "image_only_body",
    "error_code": "asset_download_failed"
  }
}
```

`normalize_notice()`는 기존처럼 `content`를 읽으면 된다. 필요하면 API 응답에 metadata를 노출하지 않고 내부 운영용으로만 보관한다.

### trigger 분류

`content_enrichment.trigger`는 보강을 시작한 원인을 기록한다. 여러 자산이 섞인 공지는 단일 원인보다 혼합 원인을 먼저 기록한다.

| trigger | 기록 조건 |
| --- | --- |
| `inline_image_and_mixed_attachments` | 본문 이미지, 이미지 첨부, HWP/HWPX 첨부가 모두 있음 |
| `inline_image_and_hwp_attachment` | 본문 이미지와 HWP/HWPX 첨부가 같이 있음 |
| `inline_image_and_image_attachment` | 본문 이미지와 이미지 첨부가 같이 있음 |
| `mixed_attachments` | 이미지 첨부와 HWP/HWPX 첨부가 같이 있음 |
| `image_only_body` | 본문 이미지 중심이며 별도 보강 첨부가 없음 |
| `hwp_attachment_only` | HWP/HWPX 첨부만 보강 자산으로 있음 |
| `image_attachment_only` | 이미지 첨부만 보강 자산으로 있음 |
| `inline_image` | 일반 텍스트가 짧고 본문 이미지가 있음 |
| `unknown` | 보강 후보지만 위 조건에 맞지 않음 |

## 보안 및 운영 기준

다운로드 안전성:

- `http`, `https`만 허용한다.
- private IP, localhost, link-local 주소로 향하는 URL은 차단한다.
- 크롤링 대상 도메인 또는 첨부파일 도메인 allowlist를 둔다.
- 파일 크기 상한을 둔다.
- 요청 timeout과 redirect 횟수 제한을 둔다.
- 응답 `Content-Type`과 파일 확장자를 함께 확인한다.

비용 방어:

- 공지 1건당 처리 asset 수를 제한한다.
- crawl 1회당 enrichment API 호출 상한을 둔다.
- asset URL 또는 sha256 기준 캐시를 둔다.
- 이미 성공한 enrichment 결과는 같은 공지/같은 asset이면 재사용한다.

개인정보/민감정보:

- secret과 API key는 로그에 남기지 않는다.
- 다운로드한 파일 원문은 영구 저장하지 않는 것을 기본값으로 한다.
- 장애 분석용으로 저장이 필요하면 별도 flag와 보관 기간을 둔다.

## 환경변수 계획

구현 시 `.env.example`, `docs/DEPLOYMENT.md`, Docker Compose에 아래 값을 추가한다.

```env
CONTENT_ENRICHMENT_ENABLED=false
CONTENT_ENRICHMENT_PROVIDER=openai
CONTENT_ENRICHMENT_MODEL=gpt-4.1-mini
CONTENT_ENRICHMENT_FALLBACK_MODEL=gpt-5.5
CONTENT_ENRICHMENT_IMAGE_DETAIL=high
CONTENT_ENRICHMENT_MIN_TEXT_LENGTH=30
CONTENT_ENRICHMENT_MAX_ASSETS_PER_NOTICE=3
CONTENT_ENRICHMENT_MAX_FILE_BYTES=10485760
CONTENT_ENRICHMENT_MAX_CALLS_PER_RUN=50
CONTENT_ENRICHMENT_ALLOWED_DOMAINS=kau.ac.kr,career.kau.ac.kr,college.kau.ac.kr,research.kau.ac.kr,ibhak.kau.ac.kr,ctl.kau.ac.kr,lib.kau.ac.kr,ftc.kau.ac.kr,amtc.kau.ac.kr,fsc.kau.ac.kr,grad.kau.ac.kr,gradbus.kau.ac.kr,aisw.kau.ac.kr,lms.kau.ac.kr,asbt.kau.ac.kr
OPENAI_API_KEY=
```

초기값은 반드시 `CONTENT_ENRICHMENT_ENABLED=false`로 둔다. 운영에서 비용과 정확도를 확인한 뒤 켠다.

## 구현 단계

### 1단계: 탐지와 metadata 기반만 추가

- fallback content 판별 함수 추가
- 본문 이미지 URL 추출 기능 추가
- 첨부파일 유형 판별 함수 추가
- 실제 API 호출 없이 enrichment 후보를 로그/metadata로 기록
- 테스트: image-only, attachment-only, hwp-only 후보 판별

### 2단계: 이미지 OCR/Vision 보강

- 안전한 asset downloader 추가
- 이미지 extractor provider 추가
- LLM content generator 추가
- inline image body와 image attachment 처리
- 테스트: fake provider로 content 교체, 실패 시 fallback 유지

### 3단계: HWP 추출

- HWP 파일 판별
- 로컬 text extractor 또는 문서 추출 API adapter 추가
- HWP 추출 결과를 LLM content generator에 연결
- 테스트: fixture HWP 또는 fake extractor 기반 성공/실패 케이스

### 4단계: 운영 안정화

- API 호출 상한, retry, timeout, cache 적용
- logs에 `content_enrichment.status`, `trigger`, `provider`, `cost guard` 출력
- 실패 유형별 카운트 기록
- 수동 crawl script와 scheduler 양쪽에서 같은 정책 사용

### 5단계: RAG 답변 품질 개선

- 생성된 `content`가 기존 local search에 반영되는지 확인
- `/api/chat`에서 OpenAI API를 실제 호출하도록 구현
- 검색 결과 references를 답변 근거로 강제
- 필요 시 embedding/vector store 또는 hosted file search 검토

## 코드 변경 후보

| 영역           | 변경 후보                                                               |
| -------------- | ----------------------------------------------------------------------- |
| 설정           | `app/config.py`, `.env.example`, `docker-compose.yml`                   |
| 크롤러 모델    | `app/crawler/models/post.py`                                            |
| 파서 공통 처리 | 각 parser의 image URL 수집 또는 공통 helper                             |
| 신규 서비스    | `app/crawler/services/content_enrichment_service.py`                    |
| 다운로드       | `app/crawler/services/content_asset_downloader.py`                      |
| provider       | `app/crawler/services/content_extractors/`                              |
| 병합           | `app/crawler/services/dedup_service.py` metadata 보존                   |
| 문서           | `docs/CRAWLING_UPDATE.md`, `docs/crawler/08_crawling_rules.md`, 본 문서 |
| 테스트         | `tests/test_content_enrichment*.py`                                     |

## 테스트 계획

단위 테스트:

- fallback content 판별
- 이미지 URL 추출
- 첨부파일 확장자/content-type 판별
- asset size 초과 차단
- private IP/localhost URL 차단
- provider 성공 시 content 교체
- provider 실패 시 기존 fallback 유지
- LLM JSON 응답 파싱 실패 처리

통합 테스트:

- 본문 image-only fixture
- image attachment-only fixture
- hwp attachment-only fixture
- 기존 정상 본문 공지는 enrichment 미실행
- 증분 병합 후 `content_enrichment` metadata 보존
- atomic publish 검증 실패 시 기존 JSON 유지

운영 확인:

```bash
pytest
NOTICE_JSON_PATH=./data/kau_official_posts.json \
CONTENT_ENRICHMENT_ENABLED=true \
bash scripts/run_incremental_crawl_publish.sh
```

운영 적용 전에는 `CONTENT_ENRICHMENT_MAX_CALLS_PER_RUN`을 낮게 두고 일부 게시판만 대상으로 검증한다.

## 결정 필요 사항

구현 전에 아래 항목은 확정해야 한다.

1. 이미지 OCR/Vision provider
2. HWP 추출 방식
3. API 호출 비용 상한
4. enrichment 결과 metadata를 API 응답에 노출할지 여부
5. 다운로드 파일 임시 저장 위치와 보관 정책

초기 권장 결정:

- 이미지: OpenAI-compatible vision provider adapter
- HWP: 로컬 text extractor 우선, 실패 시 문서 추출 API adapter
- API 응답: `content`만 보강하고 enrichment metadata는 비공개
- 운영 시작: feature flag off, 수동 crawl에서 먼저 검증

## 참고 문서

- OpenAI Cookbook: [Image Understanding with RAG](https://developers.openai.com/cookbook/examples/multimodal/image_understanding_with_rag)
- OpenAI Cookbook: [Doing RAG on PDFs using File Search in the Responses API](https://developers.openai.com/cookbook/examples/file_search_responses)
