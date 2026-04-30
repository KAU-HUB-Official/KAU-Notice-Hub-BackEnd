from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..clients.kau_admission_client import KAUAdmissionClient
from ..clients.kau_amtc_client import KAUAMTCClient
from ..clients.kau_asbt_client import KAUASBTClient
from ..clients.kau_career_client import KAUCareerClient
from ..clients.kau_college_client import KAUCollegeClient
from ..clients.kau_community_php_client import KAUCommunityPHPClient
from ..clients.kau_ctl_client import KAUCTLClient
from ..clients.kau_ftc_client import KAUFTCClient
from ..clients.kau_library_client import KAULibraryClient
from ..clients.kau_lms_client import KAULMSClient
from ..clients.kau_official_client import KAUOfficialClient
from ..clients.kau_research_client import KAUResearchClient
from ..config import (
    AISW_BASE_URL,
    AISW_NOTICE_LIST_URL,
    AMTC_BASE_URL,
    AMTC_NOTICE_LIST_URL,
    ASBT_BASE_URL,
    ASBT_NOTICE_LIST_URL,
    DEFAULT_POSTS_PER_BOARD,
    FSC_BASE_URL,
    FSC_NOTICE_LIST_URL,
    FTC_BASE_URL,
    FTC_NOTICE_LIST_URL,
    GRAD_BASE_URL,
    GRAD_NOTICE_LIST_URL,
    GRADBUS_BASE_URL,
    GRADBUS_NOTICE_LIST_URL,
    LMS_BASE_URL,
    LMS_NOTICE_LIST_URL,
)
from ..parsers.kau_admission_parser import KAUAdmissionParser
from ..parsers.kau_amtc_parser import KAUAMTCParser
from ..parsers.kau_asbt_parser import KAUASBTParser
from ..parsers.kau_card_notice_parser import KAUCardNoticeParser
from ..parsers.kau_career_parser import KAUCareerParser
from ..parsers.kau_college_parser import KAUCollegeParser
from ..parsers.kau_ctl_parser import KAUCTLParser
from ..parsers.kau_ftc_parser import KAUFTCParser
from ..parsers.kau_library_parser import KAULibraryParser
from ..parsers.kau_lms_parser import KAULMSParser
from ..parsers.kau_official_parser import KAUOfficialParser
from ..parsers.kau_research_parser import KAUResearchParser
from ..services.board_crawler import BoardAdapter, DetailFetchResult


@dataclass(frozen=True)
class ClientRegistry:
    official: KAUOfficialClient
    career: KAUCareerClient
    college: KAUCollegeClient
    research: KAUResearchClient
    admission: KAUAdmissionClient
    ctl: KAUCTLClient
    library: KAULibraryClient
    ftc: KAUFTCClient
    amtc: KAUAMTCClient
    community_php: dict[str, KAUCommunityPHPClient]
    lms: KAULMSClient
    asbt: KAUASBTClient

    def close(self) -> None:
        for client in (
            self.official,
            self.career,
            self.college,
            self.research,
            self.admission,
            self.ctl,
            self.library,
            self.ftc,
            self.amtc,
            self.lms,
            self.asbt,
        ):
            client.session.close()
        for client in self.community_php.values():
            client.session.close()


def build_clients() -> ClientRegistry:
    return ClientRegistry(
        official=KAUOfficialClient(),
        career=KAUCareerClient(),
        college=KAUCollegeClient(),
        research=KAUResearchClient(),
        admission=KAUAdmissionClient(),
        ctl=KAUCTLClient(),
        library=KAULibraryClient(),
        ftc=KAUFTCClient(base_url=FTC_BASE_URL, notice_list_url=FTC_NOTICE_LIST_URL),
        amtc=KAUAMTCClient(base_url=AMTC_BASE_URL, notice_list_url=AMTC_NOTICE_LIST_URL),
        community_php={
            FSC_BASE_URL: KAUCommunityPHPClient(
                base_url=FSC_BASE_URL,
                notice_list_url=FSC_NOTICE_LIST_URL,
            ),
            GRAD_BASE_URL: KAUCommunityPHPClient(
                base_url=GRAD_BASE_URL,
                notice_list_url=GRAD_NOTICE_LIST_URL,
            ),
            GRADBUS_BASE_URL: KAUCommunityPHPClient(
                base_url=GRADBUS_BASE_URL,
                notice_list_url=GRADBUS_NOTICE_LIST_URL,
            ),
            AISW_BASE_URL: KAUCommunityPHPClient(
                base_url=AISW_BASE_URL,
                notice_list_url=AISW_NOTICE_LIST_URL,
            ),
        },
        lms=KAULMSClient(
            base_url=LMS_BASE_URL,
            notice_list_url=LMS_NOTICE_LIST_URL,
        ),
        asbt=KAUASBTClient(
            base_url=ASBT_BASE_URL,
            notice_list_url=ASBT_NOTICE_LIST_URL,
        ),
    )


def _fetch_college_detail(
    board: dict[str, Any],
    detail_url: str,
    *,
    client: KAUCollegeClient,
) -> DetailFetchResult:
    query = parse_qs(urlparse(detail_url).query)
    ntt_id = (query.get("nttId") or [""])[-1]
    bbs_id = (query.get("bbsId") or [board["bbs_id"]])[-1]
    if not ntt_id:
        return DetailFetchResult(html=None, failure_reason="missing_ntt_id")

    html = client.fetch_notice_detail(
        site_flag=board["site_flag"],
        bbs_id=bbs_id,
        ntt_id=ntt_id,
        mnu_id=board["mnu_id"],
        bbs_auth=board["bbs_auth"],
    )
    return DetailFetchResult(html=html, failure_reason="request_failed")


def _resolve_community_client(
    board: dict[str, Any],
    *,
    clients: ClientRegistry,
) -> KAUCommunityPHPClient:
    base_url = str(board.get("base_url") or "").strip()
    if not base_url:
        raise KeyError("community board requires base_url")

    client = clients.community_php.get(base_url)
    if client is None:
        client = KAUCommunityPHPClient(
            base_url=base_url,
            notice_list_url=board["list_url"],
        )
        clients.community_php[base_url] = client
    return client


def build_board_adapters(clients: ClientRegistry) -> dict[str, BoardAdapter]:
    return {
        "kau_official": BoardAdapter(
            parser_factory=lambda board: KAUOfficialParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
            ),
            build_list_page_url=lambda board, page: clients.official.build_board_list_url(
                list_url=board["list_url"],
                code=board["code"],
                page=page,
            ),
            fetch_list_html=lambda board, page: clients.official.fetch_board_list(
                list_url=board["list_url"],
                code=board["code"],
                page=page,
            ),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=clients.official.fetch_detail(detail_url, referer=board["list_url"]),
                failure_reason="request_failed",
            ),
        ),
        "kau_career": BoardAdapter(
            parser_factory=lambda board: KAUCareerParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
            ),
            build_list_page_url=lambda board, page: clients.career.build_notice_list_url(page),
            fetch_list_html=lambda board, page: clients.career.fetch_notice_list(page),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=clients.career.fetch_notice_detail(detail_url),
                failure_reason="request_failed",
            ),
            can_fetch=clients.career.can_fetch,
            check_robots_on_list=True,
            check_robots_on_detail=True,
            min_pages_field="min_pages",
        ),
        "kau_college": BoardAdapter(
            parser_factory=lambda board: KAUCollegeParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
                notice_page_url=board["list_url"],
                site_flag=board["site_flag"],
                mnu_id=board["mnu_id"],
                bbs_id=board["bbs_id"],
                category_raw=board.get("name"),
            ),
            build_list_page_url=lambda board, page: board["list_url"],
            fetch_list_html=lambda board, page: clients.college.fetch_notice_list(
                site_flag=board["site_flag"],
                bbs_id=board["bbs_id"],
                bbs_auth=board["bbs_auth"],
                page_index=page,
                page_unit=max(
                    1,
                    int(board.get("page_unit", board.get("max_posts", DEFAULT_POSTS_PER_BOARD))),
                ),
            ),
            fetch_detail=lambda board, detail_url: _fetch_college_detail(
                board,
                detail_url,
                client=clients.college,
            ),
            can_fetch=clients.college.can_fetch,
            check_robots_on_list=True,
        ),
        "kau_card_notice": BoardAdapter(
            parser_factory=lambda board: KAUCardNoticeParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
                category_fallback=board.get("name"),
            ),
            build_list_page_url=lambda board, page: _resolve_community_client(
                board,
                clients=clients,
            ).build_notice_list_url(
                code=board["code"],
                page=page,
            ),
            fetch_list_html=lambda board, page: _resolve_community_client(
                board,
                clients=clients,
            ).fetch_notice_list(
                code=board["code"],
                page=page,
            ),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=_resolve_community_client(
                    board,
                    clients=clients,
                ).fetch_notice_detail(detail_url),
                failure_reason="request_failed",
            ),
        ),
        "kau_research": BoardAdapter(
            parser_factory=lambda board: KAUResearchParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
                category_fallback=board.get("name"),
            ),
            build_list_page_url=lambda board, page: clients.research.build_board_list_url(
                list_url=board["list_url"],
                code=board["code"],
                page=page,
            ),
            fetch_list_html=lambda board, page: clients.research.fetch_board_list(
                list_url=board["list_url"],
                code=board["code"],
                page=page,
            ),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=clients.research.fetch_detail(detail_url, referer=board["list_url"]),
                failure_reason="request_failed",
            ),
        ),
        "kau_admission": BoardAdapter(
            parser_factory=lambda board: KAUAdmissionParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
                default_board_id=board["board_id"],
                category_fallback=board.get("name"),
            ),
            build_list_page_url=lambda board, page: clients.admission.build_notice_list_url(
                list_url=board["list_url"],
                board_id=board["board_id"],
                site_type=board["site_type"],
                page=page,
            ),
            fetch_list_html=lambda board, page: clients.admission.fetch_notice_list(
                list_url=board["list_url"],
                board_id=board["board_id"],
                site_type=board["site_type"],
                page=page,
            ),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=clients.admission.fetch_notice_detail(detail_url, referer=board["list_url"]),
                failure_reason="request_failed",
            ),
        ),
        "kau_ctl": BoardAdapter(
            parser_factory=lambda board: KAUCTLParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
                category_fallback=board.get("name"),
            ),
            build_list_page_url=lambda board, page: clients.ctl.build_notice_list_url(
                code=board["code"],
                page=page,
            ),
            fetch_list_html=lambda board, page: clients.ctl.fetch_notice_list(
                code=board["code"],
                page=page,
            ),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=clients.ctl.fetch_notice_detail(detail_url),
                failure_reason="request_failed",
            ),
        ),
        "kau_library": BoardAdapter(
            parser_factory=lambda board: KAULibraryParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
                category_fallback=board.get("name"),
            ),
            build_list_page_url=lambda board, page: clients.library.build_notice_list_url(page),
            fetch_list_html=lambda board, page: clients.library.fetch_notice_list(page),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=clients.library.fetch_notice_detail(detail_url),
                failure_reason="request_failed",
            ),
        ),
        "kau_ftc": BoardAdapter(
            parser_factory=lambda board: KAUFTCParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
                category_fallback=board.get("name"),
            ),
            build_list_page_url=lambda board, page: clients.ftc.build_notice_list_url(
                code=board["code"],
                page=page,
            ),
            fetch_list_html=lambda board, page: clients.ftc.fetch_notice_list(
                code=board["code"],
                page=page,
            ),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=clients.ftc.fetch_notice_detail(detail_url),
                failure_reason="request_failed",
            ),
        ),
        "kau_community_php": BoardAdapter(
            parser_factory=lambda board: KAUFTCParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
                category_fallback=board.get("name"),
            ),
            build_list_page_url=lambda board, page: _resolve_community_client(
                board,
                clients=clients,
            ).build_notice_list_url(
                code=board["code"],
                page=page,
            ),
            fetch_list_html=lambda board, page: _resolve_community_client(
                board,
                clients=clients,
            ).fetch_notice_list(
                code=board["code"],
                page=page,
            ),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=_resolve_community_client(
                    board,
                    clients=clients,
                ).fetch_notice_detail(detail_url),
                failure_reason="request_failed",
            ),
        ),
        "kau_lms_ubboard": BoardAdapter(
            parser_factory=lambda board: KAULMSParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
                category_fallback=board.get("name"),
            ),
            build_list_page_url=lambda board, page: clients.lms.build_notice_list_url(page=page),
            fetch_list_html=lambda board, page: clients.lms.fetch_notice_list(page=page),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=clients.lms.fetch_notice_detail(detail_url),
                failure_reason="request_failed",
            ),
        ),
        "kau_asbt": BoardAdapter(
            parser_factory=lambda board: KAUASBTParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
                category_fallback=board.get("name"),
            ),
            build_list_page_url=lambda board, page: clients.asbt.build_notice_list_url(page=page),
            fetch_list_html=lambda board, page: clients.asbt.fetch_notice_list(page=page),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=clients.asbt.fetch_notice_detail(detail_url),
                failure_reason="request_failed",
            ),
        ),
        "kau_amtc": BoardAdapter(
            parser_factory=lambda board: KAUAMTCParser(
                source_name=board["source_name"],
                source_type=board["source_type"],
                category_fallback=board.get("name"),
                bo_table=board["bo_table"],
            ),
            build_list_page_url=lambda board, page: clients.amtc.build_notice_list_url(
                bo_table=board["bo_table"],
                page=page,
            ),
            fetch_list_html=lambda board, page: clients.amtc.fetch_notice_list(
                bo_table=board["bo_table"],
                page=page,
            ),
            fetch_detail=lambda board, detail_url: DetailFetchResult(
                html=clients.amtc.fetch_notice_detail(detail_url),
                failure_reason="request_failed",
            ),
        ),
    }
