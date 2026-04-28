# 파싱 규칙과 셀렉터

## KAU 공식 공지 (`kau_official_parser.py`)

### 목록

- 행 단위: `table.table_board tbody tr`
- 링크: `td.title a[href]`, `td.tit a[href]`
- 필터: `mode=read` + `seq=` 포함 URL
- 상시공지 판정: `tr.emp`, 공지 아이콘(`img.icon_notice` 등), 번호 셀 텍스트(숫자 아님/공지)

### 상세

- 제목: `div.view_header h4`
- 작성일: `div.view_header li.date`에서 날짜 패턴 추출
- 본문: `div.view_conts`
- 첨부: `div.view_header li.attatch a[href]`
- 카테고리: `div.location_wrap ul.location li` 마지막 유효 항목

## 취업공지 (`kau_career_parser.py`)

### 목록

- 행 단위: `ul[data-role='table'] li.tbody`
- 링크: `span.title > a[href]`
- 필터: `/view/` 포함 링크
- 상시공지 판정: `li.tbody.notice`, `span.loopnum` 텍스트(공지/notice)

### 상세

- 제목: `article[data-role='post'] .header h5`
- 작성일: `article[data-role='post'] .header li.date time`
- 본문: `#ModuleBoardunivBodyPrintBox [data-role='wysiwyg-content']` (fallback: `.content`)
- 첨부: `[data-module='attachment'] a[href]` (`data-download` 우선)
- 카테고리: `div.nbreadcrumb span` 마지막 항목 (fallback: 좌측 nav selected)

## college 계열 공지 (`kau_college_parser.py`)

### 목록

- 요청 방식: `POST /web/bbs/bbsListApi.gen` (JSON)
- 응답 필드: `resultList[*]`
- 상세 URL 구성 키: `siteFlag`, `mnuId`, `bbsId`, `nttId`, `bbsFlag=View`
- 상시공지 판정: `ntcYn`, `bnnrYn`, `ntcNo`, 공지기간 필드(`ntceBgnde/ntceEndde`)

### 상세

- 요청 방식: `POST /web/bbs/bbsViewApi.gen` (JSON)
- 제목: `result.nttSj`
- 작성일: `result.frstRegisterPnttm`
- 본문 HTML: `result.nttCn`
- 첨부: `resultFile[*]` -> `/web/bbs/FileDownApi.gen?atchFileId=...&fileSn=...&mnuId=...`
- 카테고리: 보드명 fallback 또는 `categoryCdNm`/`bbsNm`

## 카드형 학과/대학 공지 (`kau_card_notice_parser.py`)

### 목록

- 요청 방식: `notice.php?code=...&page=...`
- 대상: `aisw.kau.ac.kr`, `ai.kau.ac.kr:8100/8110/8120/8130/8140`, `sw.kau.ac.kr`, `ave.kau.ac.kr`
- 항목 단위: `ul.list_01 > li`
- 링크: `a[href*='mode=read'][href*='seq=']`
- 상시공지 판정: 항목 클래스(`notice`, `emp`, `bo_notice`) 또는 제목의 공지 표기

### 상세

- 제목: `div.view_header h4`
- 작성일: `div.view_header ul.view_info li`에서 날짜 패턴 추출
- 본문: `div.view_conts`
- 첨부: `div.attach a[href]`, `div.view_attatch a[href]`, `div.view_file a[href]`
- 카테고리: `ul.location li` 마지막 항목 또는 보드명 fallback

## 교수학습센터 (`kau_ctl_parser.py`)

### 목록

- 행 단위: `table.table_01 tr`
- 링크: `td.tit > a[href]`
- 필터: `mode=read` + `seq=`
- 상시공지 판정: 첫 번째 셀의 공지 표기

### 상세

- 제목: `div.view_header h4`
- 작성일: `div.view_header ul.info li`에서 `작성날짜/작성일` 패턴 추출
- 본문: `div.view_conts`
- 첨부: `div.attach a[href]`, `div.view_attatch a[href]`, `li.attatch a[href]`
- 카테고리: `div.location span.here` (없으면 보드명)

## 학술정보관 (`kau_library_parser.py`)

### 목록

- 행 단위: `tr[onclick*='go_view(']`
- `onclick="go_view('4955', ...)"`에서 `sb_no` 추출
- 상세 URL: `/sb/default_notice_view.mir?sb_no=...`
- 상시공지 판정: 행 클래스(`info`) 또는 행 텍스트의 공지 표기

### 상세

- 제목: `div.sc_view_header p.title`
- 작성일: `div.sc_view_header ul li`에서 날짜 패턴 추출
- 본문: `div.view_content`
- 첨부: `dl.sc_board dd a[onclick*='download_file(']`
- 다운로드 URL 변환:
  - `/sb/filedownload.mir?file_no=...&file_mno=...&sb_skin=default&sb_code=notice`
- 카테고리: 상단 타이틀 셀렉터 fallback 후 보드명

## 비행교육원 / 공통 PHP (`kau_ftc_parser.py`)

`kau_ftc`와 `kau_community_php(fsc/grad/gradbus)`는 동일 파서를 사용합니다.

### 목록

- 행 단위: `table.table_board tr`
- 링크: `a[href*='mode=read'][href*='seq=']`
- 상시공지 판정: `tr.emp`, `bo_notice`, `span.notice`, 번호 셀 공지 표기

### 상세

- 제목: `div.view_header h4`
- 작성일: `div.view_header ul.view_info li`에서 날짜 패턴 추출
- 본문: `div.view_conts`
- 첨부: `div.attach a[href]`, `div.view_attatch a[href]`, `li.attatch a[href]`
- 카테고리: `view_info` 첫 항목(관리자 계열 값이면 보드명 fallback)

## 산학협력단 (`kau_research_parser.py`)

### 목록

- 행 단위: `table.table_01 tr`
- 링크: `td.tit > a[href]`
- 필터: `mode=read` + `seq=`
- 상시공지 판정: 번호 셀 공지 표기

### 상세

- 제목: `div.view_header h4`
- 작성일: `div.view_header .view_info .date`
- 본문: `div.view_conts`
- 첨부: `div.view_attatch a[href]`
- 카테고리: `div.article_tit h3` (없으면 보드명)

## 입학처 (`kau_admission_parser.py`)

### 목록

- 행 단위: `section.board_list .bl table tbody tr`
- 링크: `td.tit a[onclick]`
- `viewBoardProcess('idx')`에서 `p_board_idx` 추출
- 상세 URL: `noticeView.asp?p_board_id=...&p_board_idx=...&page=...`
- 상시공지 판정: `td.no._important`, `span._important_txt`, 번호 셀 표기

### 상세

- 제목: `section.board_read h2.br_tit`
- 작성일: `section.board_read ul.br_info li`의 `작성일` 라벨 항목
- 본문: `section.board_read div.br_con .editor` (fallback: `.br_con`)
- 첨부: `section.board_read div.br_file a[href]`
- 카테고리: `section.board_read h3.br_cart`

## 항공기술교육원 (`kau_amtc_parser.py`)

### 목록

- 행 단위: `li.board-list-body`
- 링크: `a[href*='bo_table='][href*='wr_id=']`
- 필터: `bo_table` 일치 + `wr_id` 존재
- 상시공지 판정: `bo_notice` 클래스, `.notice_item`

### 상세

- 제목: `#bo_v_title`, `.bo_v_tit` (fallback)
- 작성일: `strong.if_date`, `span.if_date`, `.if_date`
- 본문: `#bo_v_con` (fallback: `#bo_v_atc`, `article#bo_v`)
- 첨부: `#bo_v_file a[href]`, `a[href*='download.php']`
- 카테고리: `<title>` 앞부분(없으면 보드명)

## LMS (`kau_lms_parser.py`)

### 목록

- 행 단위: `div.ubboard_list table.ubboard_table tbody tr`
- 링크: `a[href*='article.php'][href*='bwid=']`
- 상시공지 판정: 공지 아이콘, 번호 셀 공백/`-`/공지 텍스트

### 상세

- 제목: `div.ubboard_view .subject`
- 작성일: `div.ubboard_view .date`, `.writer`에서 날짜 패턴 추출
- 본문: `div.ubboard_view .content .text_to_html` (fallback: `.content`)
- 첨부: `.attach/.file` 링크 + `pluginfile.php`/`download.php`
- 카테고리: breadcrumb 마지막 항목 fallback

## 부트캠프사업단 (`kau_asbt_parser.py`)

### 목록

- 행 단위: `table tbody tr`
- 링크: `a[href*='ptype=view'][href*='idx=']`
- 상시공지 판정: `tr.point`, `.notice/.m_notice`, 번호 셀 공지 텍스트

### 상세

- 제목: `div.bbs_view h3.subject`
- 작성일: `div.bbs_view ul li` 중 `작성일` 항목
- 본문: `div.bbs_view div.view_content`
- 첨부: `div.bbs_view div.view_file a[href]`
- 카테고리: `#subtitle h3` (없으면 보드명)

## eSLS CAT (`kau_eslscat_parser.py`, 현재 비활성)

- 목록 링크: `a[href*='javascript:goview(']`
- 상세 URL 변환: `notice_view.asp?id={id}`
- 상세 파싱: `table.tt_list` 기반 제목/본문/작성일/첨부 추출

## 공통 규칙

- 모든 상대 링크는 `urljoin()`으로 절대 URL 변환
- 본문 텍스트가 비어 있으면 이미지 수/alt 기반 fallback 문자열 생성
- 상세 파싱 후 본문이 비어 있고 첨부파일이 있으면 첨부파일명 기반 fallback 문자열 생성
- 첨부 URL은 URL 기준으로 중복 제거

## URL 정규화(`services/url_normalizer.py`)

- `kau.ac.kr`: `code`, `mode`, `seq`만 유지
- `career.kau.ac.kr`: `/ko/community/notice/view/{id}` 및 `/ko/dataroom/data/view/{id}` 경로에서 query 제거
- `college.kau.ac.kr`: `bbsId`, `nttId`, `mnuId`만 유지
- `research.kau.ac.kr`: `code`, `mode`, `seq`만 유지
- `ctl.kau.ac.kr`: `code`, `mode`, `seq`만 유지
- `lib.kau.ac.kr`: `sb_no`만 유지
- `ftc.kau.ac.kr`: `code`, `mode`, `seq`만 유지
- `fsc/grad/gradbus.kau.ac.kr`: `code`, `mode`, `seq`만 유지
- 카드형 학과/대학 계열(`aisw`, `ai`, `sw`, `ave`): `code`, `mode`, `seq`만 유지
- `ibhak.kau.ac.kr`: `p_board_id`, `p_board_idx`만 유지
- `amtc.kau.ac.kr`: `bo_table`, `wr_id`만 유지
- `lms.kau.ac.kr`: `id`, `bwid`만 유지
- `asbt.kau.ac.kr`: `ptype=view`, `idx`, `code`만 유지
- `eslscat.com`: `id`만 유지
- 그 외: fragment 제거 + query key 정렬
