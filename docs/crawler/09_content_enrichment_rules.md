# 첨부/이미지 기반 본문 보강

## 범위

이 문서는 크롤링 시점에 텍스트 본문이 부재하거나 너무 짧은 공지의 `content`를 보강하는 현재 구현을 정리한다.

대상 케이스:

1. 이미지 첨부파일이 있는 경우
2. HWP/HWPX 첨부파일이 있는 경우
3. 본문 영역에 이미지만 포함하는 경우

본문이 동영상 iframe만 포함한 경우는 크롤링 실패로 보내지 않고 `[동영상 본문]` fallback content로 최소 정보를 보존한다. 현재 LLM 보강 대상은 이미지와 HWP/HWPX이다.

## 구현 구성

현재 구현은 feature flag 기본값을 `false`로 두고, 크롤러 최종 JSON 저장 직전에만 보강 pipeline을 실행한다.

| 책임                               | 구현 경로                                                    |
| ---------------------------------- | ------------------------------------------------------------ |
| 후보 판단과 metadata 기록          | `app/crawler/services/content_enrichment_service.py`         |
| asset 안전성 검사와 다운로드       | `app/crawler/services/content_asset_downloader.py`           |
| HWP/HWPX 텍스트 추출               | `app/crawler/services/content_extractors/hwp_extractor.py`   |
| 이미지 텍스트 추출 및 content 생성 | `app/crawler/services/content_extractors/openai_provider.py` |

OpenAI provider는 Responses API를 사용하며, 크롤러 보강 요청에는 `store=false`를 지정한다. `OPENAI_API_KEY`가 없으면 보강 후보를 실패 metadata로만 기록하고 asset 다운로드나 API 호출은 수행하지 않는다.

## 비목표

- LLM이 원문에 없는 날짜, 장소, 신청 조건을 추측해서 생성하지 않는다.
- 기존 원문 텍스트가 충분한 공지를 LLM으로 다시 쓰지 않는다.
- 바이너리 첨부파일을 JSON 스냅샷에 저장하지 않는다.
- HWP 바이너리를 그대로 LLM에 전달하지 않는다.
- 동영상 iframe의 영상 내용이나 자막을 추출하지 않는다.

## 처리 흐름

```text
상세 HTML/JSON 파싱
  -> title/content/attachments/content_assets 추출
  -> 기존 데이터 병합/중복제거/1년 초과 일반공지 삭제
  -> 본문 보강 필요 여부 판단
  -> 이미지/HWP/HWPX asset 다운로드
  -> 이미지: OpenAI vision으로 텍스트 추출
  -> HWP/HWPX: 로컬 extractor로 텍스트 추출
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
- `content_enrichment.status=success`인 공지는 다음 수집에서 다시 보강하지 않는다.
- 공지 1건에 여러 asset이 있으면 실패한 asset을 건너뛰고 남은 asset을 계속 처리한다.
- 호출 예산이 소진된 후보는 실패가 아니라 `content_enrichment.status=skipped`로 남겨 다음 실행에서 다시 시도한다.

## 보강 후보 판단

아래 조건 중 하나면 보강 후보로 본다.

| 조건                                                 | 예시                                                                                          |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 보강 가능한 asset이 있고 content가 시스템 fallback임 | `[이미지 본문] ...`, `[동영상 본문] ...`, `[첨부파일 공지] ...`, `본문 정보가 비어 있습니다.` |
| 본문 텍스트가 너무 짧고 본문 이미지가 있음           | 텍스트 30자 미만 + `content_assets` 존재                                                      |
| 본문 텍스트가 없고 보강 가능한 첨부파일이 있음       | 이미지, HWP, HWPX 첨부                                                                        |

기본 기준값:

```env
CONTENT_ENRICHMENT_MIN_TEXT_LENGTH=30
CONTENT_ENRICHMENT_MAX_ASSETS_PER_NOTICE=3
CONTENT_ENRICHMENT_MAX_FILE_BYTES=10485760
CONTENT_ENRICHMENT_MAX_CALLS_PER_RUN=50
```

## 케이스별 처리

### 1. 이미지 첨부파일

처리 순서:

1. 첨부파일 URL과 파일명을 수집한다.
2. 확장자와 `Content-Type`으로 이미지 여부를 확인한다.
3. 허용된 도메인에서만 다운로드한다.
4. OpenAI vision으로 이미지 텍스트와 시각적 구조를 추출한다.
5. 추출 결과를 LLM에 전달해 공지 본문 형태로 정리한다.

생성 content 기준:

- 제목, 날짜, source, 원문 URL을 함께 사용한다.
- 이미지 안의 표, 일정, 문의처, 제출 서류를 bullet 또는 문단으로 풀어쓴다.
- 판독 불가 영역은 추측하지 않고 `[판독 불가]` 또는 `확인 필요`로 표시한다.

### 2. HWP/HWPX 첨부파일

HWP/HWPX는 로컬 extractor만 사용한다.

처리 순서:

1. HWP/HWPX 파일을 다운로드한다.
2. 확장자와 `Content-Type`으로 HWP/HWPX 여부를 확인한다.
3. `.hwpx`는 ZIP/XML 직접 파싱을 먼저 시도한다.
4. 로컬 `unhwp` extractor로 텍스트 추출을 시도한다.
5. `unhwp`를 import할 수 없는 환경에서는 `extract-hwp` 패키지가 import 가능한 경우 선택적 fallback으로 사용한다.
6. 텍스트 추출에 성공하면 LLM으로 공지용 content를 생성한다.
7. 실패하면 기존 fallback content를 유지하고 `content_enrichment.status=failed`를 기록한다.

HWP 처리 구현:

```text
app/crawler/services/content_extractors/hwp_extractor.py
```

지원 method:

| method        | 의미                                                                                  |
| ------------- | ------------------------------------------------------------------------------------- |
| `hwpx-xml`    | HWPX ZIP 내부 XML text node 직접 파싱                                                 |
| `unhwp`       | `unhwp` 로컬 라이브러리 기반 추출                                                     |
| `extract-hwp` | `unhwp`를 import할 수 없고, 해당 패키지는 import 가능한 경우 사용하는 선택적 fallback |

추출 성공 기준:

- 추출 텍스트가 비어 있지 않다.
- 공백 제거 후 최소 길이 이상이다.
- 암호화 파일이 아니다.
- 오류 문구만 추출된 결과가 아니다.

실패 코드:

- `password_protected_hwp`: 암호화된 HWP/HWPX
- `unsupported_hwp_format`: 미지원 또는 손상된 HWP/HWPX
- `hwp_text_extract_failed`: 텍스트 추출 실패
- `hwp_text_too_short`: 추출 텍스트가 최소 길이 미만
- `hwp_text_extractor_unavailable`: 사용할 수 있는 로컬 extractor가 없음

### 3. 본문 이미지만 있는 경우

처리 순서:

1. 본문 HTML에서 `img[src]`, `alt`, 주변 caption 텍스트를 수집한다.
2. 이미지 URL을 절대 URL로 변환한다.
3. `data:image/...;base64,...` 형태의 inline 이미지는 네트워크 요청 없이 decode한다.
4. 이미지가 여러 개면 `CONTENT_ENRICHMENT_MAX_ASSETS_PER_NOTICE` 개까지만 처리한다.
5. OpenAI vision으로 이미지 텍스트를 추출한다.
6. LLM으로 공지용 content를 생성한다.

본문 이미지 URL은 `content_assets`에 저장한다.

### 4. 본문 동영상 iframe만 있는 경우

처리 순서:

1. 본문 HTML에서 `iframe[src]`를 수집한다.
2. `content`가 비어 있으면 `[동영상 본문]` fallback content를 생성한다.
3. 크롤링 실패 파일에는 기록하지 않는다.

동영상 iframe은 현재 LLM 보강 대상이 아니다.

## LLM 출력 계약

LLM은 반드시 JSON 형태로 응답해야 한다.

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

## 데이터 모델

공개 API의 `Notice.content`는 최종 검색 가능한 본문으로 유지한다. 크롤러 원본 JSON에는 보강 metadata를 추가한다.

성공 예시:

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

성공 로그:

```text
본문 보강 성공 | 제목=장학금 신청 안내 | trigger=image_only_body | asset수=1 | model=gpt-4.1-mini | confidence=high
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

## 실패와 건너뜀 기준

본문 보강 실패는 원본 공지 수집 실패가 아니다. 실패 시 기존 fallback `content`를 유지하고, 실패 원인은 `content_enrichment.error_code`와 `asset_errors`로 남긴다.

| 상황 | 기록 | 처리 |
| --- | --- | --- |
| data URL 인라인 이미지가 정상 이미지임 | 보강 가능 | data URL을 decode하고 MIME/크기 검증 후 image extractor로 전달 |
| data URL payload가 깨져 있음 | `asset_download_failed` | 해당 asset을 건너뛰고 다른 asset이 있으면 계속 처리 |
| asset 다운로드가 timeout 또는 네트워크 오류로 실패함 | `asset_download_failed` | 해당 asset을 건너뛰고 다른 asset이 있으면 계속 처리 |
| 이미지 MIME이 아님 | `unsupported_asset_type` | 해당 asset을 보강 대상에서 제외 |
| 이미지/첨부파일이 너무 큼 | `asset_too_large` | 비용과 메모리 보호를 위해 해당 asset 제외 |
| HWP extractor가 없음 | `hwp_text_extractor_unavailable` | 다른 asset이 있으면 계속 처리 |
| HWP/HWPX가 암호화됨 | `password_protected_hwp` | 기존 fallback content 유지 |
| HWP/HWPX가 손상 또는 미지원 형식임 | `unsupported_hwp_format`, `hwp_text_extract_failed` | 기존 fallback content 유지 |
| 추출 텍스트가 너무 짧음 | `hwp_text_too_short`, `image_text_too_short` | content 생성 근거로 사용하지 않음 |
| LLM 응답이 비정상임 | `openai_invalid_response`, `openai_empty_response`, `llm_json_parse_failed` | 기존 fallback content 유지 |
| 생성된 content가 너무 짧음 | `generated_content_too_short` | 기존 fallback content 유지 |
| 모든 asset에서 텍스트 확보 실패 | `no_extracted_text` | 공지 단위 보강 실패로 기록 |
| 호출 예산 소진 | `status=skipped`, `reason=enrichment_call_budget_exceeded` | 실패로 보지 않고 다음 실행에서 재시도 가능 |

data URL의 base64 payload는 로그에 남기지 않고 `<omitted>`로 축약한다. 개별 원인은 `content_enrichment.asset_errors`를 우선 확인한다.

호출 예산 소진 skip 예시:

```json
{
  "content": "[이미지 본문] 텍스트 본문 없음 (이미지 1개)",
  "content_enrichment": {
    "enabled": true,
    "status": "skipped",
    "trigger": "image_only_body",
    "reason": "enrichment_call_budget_exceeded"
  }
}
```

`normalize_notice()`는 기존처럼 `content`를 읽으면 된다. API 응답에는 enrichment metadata를 노출하지 않는다.

## trigger 분류

`content_enrichment.trigger`는 보강을 시작한 원인을 기록한다. 여러 자산이 섞인 공지는 단일 원인보다 혼합 원인을 먼저 기록한다.

| trigger                              | 기록 조건                                           |
| ------------------------------------ | --------------------------------------------------- |
| `inline_image_and_mixed_attachments` | 본문 이미지, 이미지 첨부, HWP/HWPX 첨부가 모두 있음 |
| `inline_image_and_hwp_attachment`    | 본문 이미지와 HWP/HWPX 첨부가 같이 있음             |
| `inline_image_and_image_attachment`  | 본문 이미지와 이미지 첨부가 같이 있음               |
| `mixed_attachments`                  | 이미지 첨부와 HWP/HWPX 첨부가 같이 있음             |
| `image_only_body`                    | 본문 이미지 중심이며 별도 보강 첨부가 없음          |
| `hwp_attachment_only`                | HWP/HWPX 첨부만 보강 자산으로 있음                  |
| `image_attachment_only`              | 이미지 첨부만 보강 자산으로 있음                    |
| `inline_image`                       | 일반 텍스트가 짧고 본문 이미지가 있음               |
| `unknown`                            | 보강 후보지만 위 조건에 맞지 않음                   |

## 보안 및 운영 기준

다운로드 안전성:

- `http`, `https` URL은 allowlist 도메인과 공개 IP 조건을 통과해야 한다.
- `data:image/...;base64,...` inline 이미지는 네트워크 요청 없이 decode하고 MIME/크기 검증을 통과한 경우에만 처리한다.
- private IP, localhost, link-local 주소로 향하는 URL은 차단한다.
- 크롤링 대상 도메인 또는 첨부파일 도메인 allowlist를 둔다.
- 파일 크기 상한을 둔다.
- 요청 timeout과 redirect 결과 URL을 확인한다.
- 응답 `Content-Type`과 파일 확장자를 함께 확인한다.

비용 방어:

- 기본값은 `CONTENT_ENRICHMENT_ENABLED=false`다.
- 공지 1건당 처리 asset 수를 제한한다.
- crawl 1회당 enrichment API 호출 상한을 둔다.
- 호출 예산이 소진되면 남은 후보는 `status=skipped`, `reason=enrichment_call_budget_exceeded`로 기록하고 다음 실행에서 다시 시도한다.
- 이미 `content_enrichment.status=success`인 공지는 다시 보강하지 않는다.
- `OPENAI_API_KEY`가 없으면 API 호출 없이 실패 metadata만 기록한다.

개인정보/민감정보:

- secret과 API key는 로그에 남기지 않는다.
- 다운로드한 파일 원문은 영구 저장하지 않는다.

## 테스트 기준

- fallback content 판별
- 이미지 URL 추출
- iframe fallback 생성
- 첨부파일 확장자/content-type 판별
- asset size 초과 차단
- private IP/localhost URL 차단
- HWPX XML 텍스트 추출
- provider 성공 시 content 교체
- provider 실패 시 기존 fallback 유지
- LLM JSON 응답 파싱 실패 처리
- 기존 정상 본문 공지는 enrichment 미실행
- 이미 성공한 enrichment 결과는 재실행하지 않음
