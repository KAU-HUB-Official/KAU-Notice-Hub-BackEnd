import pytest

from app.crawler.services.url_normalizer import canonicalize_original_url


@pytest.mark.parametrize(
    "host",
    [
        # 전공별 도메인 이전 후 주소와, 기존 데이터에 남아 있는 옛 포트 주소
        "ai.kau.ac.kr",
        "com.kau.ac.kr",
        "eae.kau.ac.kr",
        "sse.kau.ac.kr",
        "ict.kau.ac.kr",
        "ai.kau.ac.kr:8130",
    ],
)
def test_card_major_detail_url_drops_page_and_search_params(host) -> None:
    url = f"https://{host}/pages/notice.php?searchkey=&searchvalue=&code=s1401&page=3&mode=read&seq=22"

    canonical = canonicalize_original_url(url)

    assert host in canonical
    assert "page=" not in canonical and "searchkey" not in canonical
    assert canonical.endswith("notice.php?code=s1401&mode=read&seq=22")
