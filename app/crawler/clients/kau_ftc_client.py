from __future__ import annotations

from .kau_community_php_client import KAUCommunityPHPClient


class KAUFTCClient(KAUCommunityPHPClient):
    """FTC 게시판 클라이언트. 요청 방식이 공용 PHP 게시판(mode=read&seq)과 같아 그대로 물려받는다."""
