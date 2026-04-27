# KAU Notice Hub BackEnd

FastAPI 기반 공지 API 서버다. MVP 저장소는 JSON 파일이며, 크롤러는 외부 프로세스가 전체 스냅샷 JSON을 atomic 교체한다.

## 로컬 실행

```bash
python3 -m pip install -e '.[dev]'
NOTICE_JSON_PATH=../MVP/kau_official_posts.json uvicorn app.main:app --reload --port 8000
```

확인:

```bash
curl http://localhost:8000/health
curl 'http://localhost:8000/api/notices?page=1&pageSize=5'
```

## 테스트

```bash
pytest -q
```

## 크롤러 게시

`CRAWLER_COMMAND`는 `$CRAWLER_OUTPUT_PATH`에 병합된 전체 JSON 스냅샷을 써야 한다.

```bash
NOTICE_JSON_PATH=./data/kau_official_posts.json \
CRAWLER_COMMAND='cd ../Crawler && python crawler/main.py --output "$CRAWLER_OUTPUT_PATH"' \
bash scripts/run_incremental_crawl_publish.sh
```

## Docker

```bash
docker compose up -d --build api
docker compose --profile proxy up -d --build
```

# KAU-Notice-Hub-BackEnd
