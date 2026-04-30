# 크롤링 대상

## 대상 게시판 목록 (`NOTICE_BOARDS`)

현재 기본 설정 기준 총 69개 게시판을 수집 대상으로 등록합니다.

| key | 게시판명 | 홈페이지 분류 | board_type | 목록 URL | 식별값 |
| --- | --- | --- | --- | --- | --- |
| general_notice | 일반공지 | 공식홈 | kau_official | https://kau.ac.kr/kaulife/notice.php | `code=s1101` |
| academic_notice | 학사공지 | 공식홈 | kau_official | https://kau.ac.kr/kaulife/acdnoti.php | `code=s1201` |
| scholarship_notice | 장학/대출공지 | 공식홈 | kau_official | https://kau.ac.kr/kaulife/scholnoti.php | `code=s1301` |
| event_notice | 행사공지 | 공식홈 | kau_official | https://kau.ac.kr/kaulife/event.php | `code=s1401` |
| bid_notice | 입찰공지 | 공식홈 | kau_official | https://kau.ac.kr/kaulife/bid.php | `code=s1601` |
| covid_notice | 감염병 관리 공지사항 | 공식홈 | kau_official | https://kau.ac.kr/kaulife/covidnoti.php | `code=s1701` |
| it_notice | IT공지사항 | 공식홈 | kau_official | https://kau.ac.kr/kaulife/itnoti.php | `code=s1801` |
| job_notice | 대학일자리센터 공지사항 | 대학일자리센터 | kau_career | https://career.kau.ac.kr/ko/community/notice | `min_pages=2` |
| college_gc63585_notice | 국제교류처 공지(gc63585b) | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc63585b.do | `site_flag=inter_www`, `bbs_id=0123`, `mnu_id=gc63585b` |
| engineering_college_notice | 공과대학 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc17891b.do | `site_flag=engineer_col`, `bbs_id=0369`, `mnu_id=gc17891b` |
| aisw_college_notice | AI융합대학 공지사항 | 카드형 학과/대학 | kau_card_notice | http://aisw.kau.ac.kr/pages/notice.php | `base_url=aisw.kau.ac.kr`, `code=s1201` |
| aviation_management_college_notice | 항공·경영대학 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc306b.do | `site_flag=avimanagement_col`, `bbs_id=0372`, `mnu_id=gc306b` |
| free_major_notice | 자유전공학부 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc46051b.do | `site_flag=free_www`, `bbs_id=0072`, `mnu_id=gc46051b` |
| humanities_natural_notice | 인문자연학부 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc87634b.do | `site_flag=ct_www`, `bbs_id=0088`, `mnu_id=gc87634b` |
| aeronautics_major_notice | 항공공학전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc99647b.do | `site_flag=new_major_aeronautics`, `bbs_id=0395`, `mnu_id=gc99647b` |
| mechanical_engineering_major_notice | 기계공학전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc5953b.do | `site_flag=new_major_mech`, `bbs_id=0392`, `mnu_id=gc5953b` |
| aviation_mro_major_notice | 항공MRO전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc46188b.do | `site_flag=new_major_amem`, `bbs_id=0389`, `mnu_id=gc46188b` |
| space_engineering_major_notice | 우주공학전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc41675b.do | `site_flag=spc_www`, `bbs_id=0421`, `mnu_id=gc41675b` |
| aerospace_engineering_department_notice | 항공우주공학과 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc64016b.do | `site_flag=ade_www`, `bbs_id=0323`, `mnu_id=gc64016b` |
| mechanical_aerospace_engineering_department_notice | 기계항공공학과 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc30562b.do | `site_flag=mae_www`, `bbs_id=0283`, `mnu_id=gc30562b` |
| materials_undergrad_notice | 신소재공학과 학부 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc46806b.do | `site_flag=materials_www`, `bbs_id=0096`, `mnu_id=gc46806b` |
| aerospace_mechanical_engineering_division_notice | 항공우주및기계공학부 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc1986b.do | `site_flag=am_www`, `bbs_id=0024`, `mnu_id=gc1986b` |
| space_aerospace_materials_major_notice | 우주항공신소재전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc49194b.do | `site_flag=new_major_aam`, `bbs_id=0402`, `mnu_id=gc49194b` |
| semiconductor_materials_major_notice | 반도체신소재전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc55157b.do | `site_flag=mic_www`, `bbs_id=0423`, `mnu_id=gc55157b` |
| smart_drone_engineering_department_notice | 스마트드론공학과 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc13106b.do | `site_flag=smartdrone_www`, `bbs_id=0101`, `mnu_id=gc13106b` |
| ai_major_notice | 인공지능전공 공지사항 | 카드형 학과/대학 | kau_card_notice | http://ai.kau.ac.kr:8100/pages/notice.php | `base_url=ai.kau.ac.kr:8100`, `code=s1401` |
| engineering_convergence_major_notice | 공과대학 융합전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc33372b.do | `site_flag=sme_www`, `bbs_id=0127`, `mnu_id=gc33372b` |
| semiconductor_system_major_notice | 반도체시스템전공 공지사항 | 카드형 학과/대학 | kau_card_notice | http://ai.kau.ac.kr:8130/pages/notice.php | `base_url=ai.kau.ac.kr:8130`, `code=s1401` |
| computer_engineering_major_notice | 컴퓨터공학전공 공지사항 | 카드형 학과/대학 | kau_card_notice | http://ai.kau.ac.kr:8110/pages/notice.php | `base_url=ai.kau.ac.kr:8110`, `code=s1401` |
| electronics_aerospace_electronics_major_notice | 전자및항공전자전공 공지사항 | 카드형 학과/대학 | kau_card_notice | http://ai.kau.ac.kr:8120/pages/notice.php | `base_url=ai.kau.ac.kr:8120`, `code=s1401` |
| ai_convergence_ict_major_notice | AI융합ICT전공 공지사항 | 카드형 학과/대학 | kau_card_notice | http://ai.kau.ac.kr:8140/pages/notice.php | `base_url=ai.kau.ac.kr:8140`, `code=s1401` |
| electrical_electronics_engineering_department_notice | 전기전자공학과 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc84580b.do | `site_flag=eee_www`, `bbs_id=0324`, `mnu_id=gc84580b` |
| software_department_notice | 소프트웨어학과 공지사항 | 카드형 학과/대학 | kau_card_notice | http://sw.kau.ac.kr/pages/notice.php | `base_url=sw.kau.ac.kr`, `code=s1401` |
| eie_notice | 항공전자정보공학부 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc23761b.do | `site_flag=eie_www`, `bbs_id=0015`, `mnu_id=gc23761b` |
| ai_autonomous_vehicle_system_department_notice | AI자율주행시스템공학과 공지사항 | 카드형 학과/대학 | kau_card_notice | http://ave.kau.ac.kr/pages/notice.php | `base_url=ave.kau.ac.kr`, `code=s1401` |
| computer_engineering_department_notice | 컴퓨터공학과 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc34907b.do | `site_flag=dcs_www`, `bbs_id=0319`, `mnu_id=gc34907b` |
| aisw_convergence_major_notice | AI융합대학 융합전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc29417b.do | `site_flag=ai_www`, `bbs_id=0117`, `mnu_id=gc29417b` |
| logistics_major_notice | 물류전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc10416b.do | `site_flag=new_major_logist`, `bbs_id=0386`, `mnu_id=gc10416b` |
| air_traffic_major_notice | 항공교통전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc51246b.do | `site_flag=new_major_atm`, `bbs_id=0383`, `mnu_id=gc51246b` |
| aviation_management_major_notice | 항공경영전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc34408b.do | `site_flag=new_major_avm`, `bbs_id=0399`, `mnu_id=gc34408b` |
| business_administration_major_notice | 경영전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc19393b.do | `site_flag=new_major_bam`, `bbs_id=0378`, `mnu_id=gc19393b` |
| flight_operation_department_notice | 항공운항학과 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc61682b.do | `site_flag=hw_www`, `bbs_id=0003`, `mnu_id=gc61682b` |
| international_exchange_division_notice | 국제교류학부 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc14416b.do | `site_flag=diekor_www`, `bbs_id=0356`, `mnu_id=gc14416b` |
| air_transport_logistics_division_notice | 항공교통물류학부 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc93464b.do | `site_flag=attll_www`, `bbs_id=0048`, `mnu_id=gc93464b` |
| business_administration_department_notice | 경영학과 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc99805b.do | `site_flag=dba_www`, `bbs_id=0320`, `mnu_id=gc99805b` |
| business_administration_division_notice | 경영학부 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc25685b.do | `site_flag=biz_www`, `bbs_id=0056`, `mnu_id=gc25685b` |
| aviation_management_college_convergence_major_notice | 항공경영대학융합전공 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc60453b.do | `site_flag=samc_www`, `bbs_id=0124`, `mnu_id=gc60453b` |
| aviation_business_department_notice | 항공경영학과 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc84986b.do | `site_flag=dam_www`, `bbs_id=0322`, `mnu_id=gc84986b` |
| college_gc24251_notice | 드림칼리지디자인 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc24251b.do | `site_flag=mat_WWW`, `bbs_id=0414`, `mnu_id=gc24251b` |
| research_notice | 산학협력단 공지사항 | 산학협력단 | kau_research | https://research.kau.ac.kr/info/info_011.php | `code=s2101` |
| admission_notice | 입학처 공지사항 | 입학처 | kau_admission | https://ibhak.kau.ac.kr/admission/html/guide/notice.asp | `board_id=BBS0004`, `site_type=MAM0001` |
| ctl_notice | 교수학습센터 공지사항 | 교수학습센터 | kau_ctl | https://ctl.kau.ac.kr/notice/list.php | `code=s1101` |
| library_notice | 학술정보관 일반공지 | 학술정보관 | kau_library | https://lib.kau.ac.kr/sb/default_notice_list.mir | `sb_no` 기반 |
| human_rights_notice | 인권센터 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc22052b.do | `site_flag=rights_www`, `bbs_id=0142`, `mnu_id=gc22052b` |
| dorm_notice | 생활관 일반공지 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc65332b.do | `site_flag=dorm_www`, `bbs_id=0230`, `mnu_id=gc65332b` |
| museum_notice | 항공우주박물관 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc73673b.do | `site_flag=museum`, `bbs_id=0276`, `mnu_id=gc73673b` |
| ftc_notice | 비행교육원 공지사항 | 비행교육원 | kau_ftc | https://ftc.kau.ac.kr/info/notice_02.php | `code=s1102` |
| fsc_notice | 새내기성공센터 공지사항 | 공통 PHP | kau_community_php | http://fsc.kau.ac.kr/info/info_01.php | `base_url=fsc.kau.ac.kr`, `code=s1101` |
| grad_notice | 대학원 공지사항 | 공통 PHP | kau_community_php | https://grad.kau.ac.kr/community/notice_02.php | `base_url=grad.kau.ac.kr`, `code=s1201` |
| gradbus_notice | 경영대학원 공지사항 | 공통 PHP | kau_community_php | http://gradbus.kau.ac.kr/community/notice_01.php | `base_url=gradbus.kau.ac.kr`, `code=s1101` |
| atci_notice | 항공교통관제교육원 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc80226b.do | `site_flag=atci`, `bbs_id=0226`, `mnu_id=gc80226b` |
| college_gc91652_notice | 항공우주정책대학원 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc91652b.do | `site_flag=lawpolicy_www`, `bbs_id=0349`, `mnu_id=gc91652b` |
| materials_grad_notice | 신소재공학과 대학원 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc74927b.do | `site_flag=materials_www`, `bbs_id=0097`, `mnu_id=gc74927b` |
| materials_job_notice | 신소재공학과 취업공지 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc34619b.do | `site_flag=materials_www`, `bbs_id=0098`, `mnu_id=gc34619b` |
| amtc_notice | 항공기술교육원 공지사항 | 항공기술교육원 | kau_amtc | http://amtc.kau.ac.kr/bbs/board.php | `bo_table=notice` |
| kasi_notice | 항공안전교육원 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc63977b.do | `site_flag=kasi_www`, `bbs_id=0136`, `mnu_id=gc63977b` |
| life_notice | 평생교육원 공지사항 | college 계열 | kau_college | http://college.kau.ac.kr/web/pages/gc11101b.do | `site_flag=life_www`, `bbs_id=0120`, `mnu_id=gc11101b` |
| lms_notice | LMS 공지사항 | LMS | kau_lms_ubboard | https://lms.kau.ac.kr/mod/ubboard/view.php?id=55398 | `id=55398` |
| asbt_notice | 첨단분야 부트캠프사업단 공지사항 | 부트캠프 사업단 | kau_asbt | https://asbt.kau.ac.kr/customer/notice.php | `code=notice` |

## 도메인 그룹

- 공식홈: `kau.ac.kr`
- 대학일자리센터: `career.kau.ac.kr`
- college 계열: `college.kau.ac.kr` 42종
- 카드형 학과/대학 계열: `aisw.kau.ac.kr`, `ai.kau.ac.kr:8100/8110/8120/8130/8140`, `sw.kau.ac.kr`, `ave.kau.ac.kr` 8종
- 산학협력단: `research.kau.ac.kr`
- 입학처: `ibhak.kau.ac.kr`
- 교수학습센터: `ctl.kau.ac.kr`
- 학술정보관: `lib.kau.ac.kr`
- 비행교육원: `ftc.kau.ac.kr`
- 항공기술교육원: `amtc.kau.ac.kr`
- 공통 PHP 계열: `fsc.kau.ac.kr`, `grad.kau.ac.kr`, `gradbus.kau.ac.kr`
- LMS: `lms.kau.ac.kr`
- 부트캠프사업단: `asbt.kau.ac.kr`

참고: 박물관/항공안전교육원/평생교육원은 원 사이트에서 `college.kau.ac.kr` 공지 페이지를 연결해 사용하므로, 크롤러도 `college` 페이지 URL을 직접 수집 대상으로 사용합니다.

## robots 정책 처리

- 기본 정책: 사이트별 `robots.txt` 준수
- 예외 정책: `kau_career`는 사용자 요청으로 robots 검사 비활성화(`respect_robots=False`)
- `job_notice`는 1페이지 고유 URL이 적은 경우를 보완하기 위해 `min_pages=2`를 적용

## 비활성 구현
