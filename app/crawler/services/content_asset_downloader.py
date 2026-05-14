from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import mimetypes
import socket
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, unquote_to_bytes, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..config import REQUEST_TIMEOUT_SECONDS, USER_AGENT

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
HWP_EXTENSIONS = {".hwp", ".hwpx"}
IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
HWP_CONTENT_TYPES = {
    "application/haansofthwp",
    "application/hwp",
    "application/x-hwp",
    "application/vnd.hancom.hwp",
    "application/vnd.hancom.hwpx",
}

CONTENT_IMAGE_SELECTORS = [
    "div.view_conts",
    "div.view_content",
    "div.bbs_view div.view_content",
    "section.board_read div.br_con",
    "#bo_v_con",
    "#bo_v_atc",
    "article#bo_v",
    "#ModuleBoardunivBodyPrintBox [data-role='wysiwyg-content']",
    "[data-role='wysiwyg-content']",
    "div.ubboard_view .content",
]


@dataclass(frozen=True)
class ContentAsset:
    type: str
    name: str
    url: str
    source: str


@dataclass(frozen=True)
class DownloadedAsset:
    asset: ContentAsset
    data: bytes
    content_type: str
    sha256: str


class ContentAssetDownloadError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _url_path_suffix(value: str) -> str:
    path = urlparse(value).path
    return PurePosixPath(unquote(path)).suffix.lower()


def _name_suffix(value: str) -> str:
    return PurePosixPath(unquote(value)).suffix.lower()


def _content_type_base(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _is_data_url(url: str) -> bool:
    return str(url or "").strip().lower().startswith("data:")


def is_image_asset(name: str, url: str, content_type: str | None = None) -> bool:
    content_type_base = _content_type_base(content_type)
    if content_type_base in IMAGE_CONTENT_TYPES:
        return True
    return _name_suffix(name) in IMAGE_EXTENSIONS or _url_path_suffix(url) in IMAGE_EXTENSIONS


def is_hwp_asset(name: str, url: str, content_type: str | None = None) -> bool:
    content_type_base = _content_type_base(content_type)
    if content_type_base in HWP_CONTENT_TYPES:
        return True
    return _name_suffix(name) in HWP_EXTENSIONS or _url_path_suffix(url) in HWP_EXTENSIONS


def classify_attachment(name: str, url: str) -> str | None:
    if is_image_asset(name, url):
        return "image_attachment"
    if is_hwp_asset(name, url):
        return "hwp_attachment"
    return None


def _host_matches_allowed_domain(hostname: str, allowed_domains: list[str]) -> bool:
    if not allowed_domains:
        return True

    hostname = hostname.lower().rstrip(".")
    for domain in allowed_domains:
        normalized = domain.lower().rstrip(".")
        if hostname == normalized or hostname.endswith(f".{normalized}"):
            return True
    return False


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_global


def _hostname_resolves_to_public_ips(hostname: str) -> bool:
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False

    addresses = {item[4][0] for item in addr_infos if item and item[4]}
    return bool(addresses) and all(_is_public_ip(address) for address in addresses)


def is_safe_asset_url(url: str, allowed_domains: list[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    if hostname.lower() in {"localhost"}:
        return False

    if not _host_matches_allowed_domain(hostname, allowed_domains):
        return False

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return _hostname_resolves_to_public_ips(hostname)

    return address.is_global


def _asset_name_from_url(url: str, fallback: str) -> str:
    if _is_data_url(url):
        return fallback
    path_name = PurePosixPath(unquote(urlparse(url).path)).name
    return path_name or fallback


def _clean_html_url(value: object) -> str:
    return str(value or "").strip().replace("\\", "").strip("\"'")


def _select_content_nodes(soup: BeautifulSoup, selector: str) -> list:
    containers = [
        node
        for container_selector in CONTENT_IMAGE_SELECTORS
        for node in soup.select(container_selector)
    ]
    if containers:
        nodes = []
        for container in containers:
            nodes.extend(container.select(selector))
        return nodes
    return soup.select(selector)


def extract_inline_image_assets(
    html: str,
    detail_url: str,
    *,
    max_assets: int = 10,
) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    image_nodes = _select_content_nodes(soup, "img[src]")

    assets: list[dict] = []
    seen_urls: set[str] = set()
    for index, image_node in enumerate(image_nodes, start=1):
        src = _clean_html_url(image_node.get("src"))
        if not src:
            continue
        absolute_url = urljoin(detail_url, src)
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)

        alt = str(image_node.get("alt") or "").strip()
        name = alt or _asset_name_from_url(absolute_url, f"inline-image-{index}")
        assets.append(
            {
                "type": "inline_image",
                "name": name,
                "url": absolute_url,
                "source": "body",
            }
        )
        if len(assets) >= max_assets:
            break

    return assets


def extract_inline_embed_assets(
    html: str,
    detail_url: str,
    *,
    max_assets: int = 10,
) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    embed_nodes = _select_content_nodes(soup, "iframe[src]")

    assets: list[dict] = []
    seen_urls: set[str] = set()
    for index, embed_node in enumerate(embed_nodes, start=1):
        src = _clean_html_url(embed_node.get("src"))
        if not src:
            continue
        absolute_url = urljoin(detail_url, src)
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)

        title = str(embed_node.get("title") or embed_node.get("aria-label") or "").strip()
        name = title or _asset_name_from_url(absolute_url, f"inline-embed-{index}")
        assets.append(
            {
                "type": "inline_embed",
                "name": name,
                "url": absolute_url,
                "source": "body",
            }
        )
        if len(assets) >= max_assets:
            break

    return assets


class ContentAssetDownloader:
    def __init__(
        self,
        *,
        allowed_domains: list[str],
        max_file_bytes: int,
        timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        self.allowed_domains = allowed_domains
        self.max_file_bytes = max_file_bytes
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def download(self, asset: ContentAsset) -> DownloadedAsset:
        if _is_data_url(asset.url):
            return self._download_data_url(asset)

        if not is_safe_asset_url(asset.url, self.allowed_domains):
            raise ContentAssetDownloadError("unsafe_asset_url", f"unsafe asset URL: {asset.url}")

        try:
            response = self.session.get(
                asset.url,
                headers={"User-Agent": USER_AGENT},
                timeout=self.timeout_seconds,
                allow_redirects=True,
                stream=True,
            )
        except requests.RequestException as exc:
            raise ContentAssetDownloadError(
                "asset_download_failed",
                f"asset download failed: {exc.__class__.__name__}",
            ) from exc
        if response.status_code >= 400:
            raise ContentAssetDownloadError(
                "asset_download_failed",
                f"asset download failed: status={response.status_code}",
            )
        if response.url and not is_safe_asset_url(response.url, self.allowed_domains):
            raise ContentAssetDownloadError(
                "unsafe_asset_redirect",
                f"asset redirected to unsafe URL: {response.url}",
            )

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > self.max_file_bytes:
                    raise ContentAssetDownloadError("asset_too_large", "asset exceeds max size")
            except ValueError:
                pass

        chunks: list[bytes] = []
        total_size = 0
        try:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                total_size += len(chunk)
                if total_size > self.max_file_bytes:
                    raise ContentAssetDownloadError("asset_too_large", "asset exceeds max size")
                chunks.append(chunk)
        except requests.RequestException as exc:
            raise ContentAssetDownloadError(
                "asset_download_failed",
                f"asset download failed: {exc.__class__.__name__}",
            ) from exc

        data = b"".join(chunks)
        content_type = _content_type_base(response.headers.get("Content-Type"))
        if not self._matches_expected_type(asset, content_type):
            guessed = mimetypes.guess_type(asset.name or asset.url)[0] or content_type
            raise ContentAssetDownloadError(
                "unsupported_asset_type",
                f"unsupported asset type: {guessed}",
            )

        return DownloadedAsset(
            asset=asset,
            data=data,
            content_type=content_type,
            sha256=hashlib.sha256(data).hexdigest(),
        )

    @staticmethod
    def _matches_expected_type(asset: ContentAsset, content_type: str) -> bool:
        if asset.type in {"inline_image", "image_attachment"}:
            return is_image_asset(asset.name, asset.url, content_type)
        if asset.type == "hwp_attachment":
            return is_hwp_asset(asset.name, asset.url, content_type)
        return False

    def _download_data_url(self, asset: ContentAsset) -> DownloadedAsset:
        content_type, data = self._decode_data_url(asset.url)
        if len(data) > self.max_file_bytes:
            raise ContentAssetDownloadError("asset_too_large", "asset exceeds max size")

        if not self._matches_expected_type(asset, content_type):
            raise ContentAssetDownloadError(
                "unsupported_asset_type",
                f"unsupported asset type: {content_type or 'unknown'}",
            )

        return DownloadedAsset(
            asset=asset,
            data=data,
            content_type=content_type,
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def _decode_data_url(self, url: str) -> tuple[str, bytes]:
        header, separator, payload = url.partition(",")
        if not separator or not header.lower().startswith("data:"):
            raise ContentAssetDownloadError("asset_download_failed", "invalid data URL")

        metadata = header[5:]
        parts = [part.strip() for part in metadata.split(";") if part.strip()]
        content_type = "text/plain"
        parameters = parts
        if parts and "/" in parts[0]:
            content_type = _content_type_base(parts[0])
            parameters = parts[1:]

        is_base64_encoded = any(part.lower() == "base64" for part in parameters)
        try:
            if is_base64_encoded:
                normalized_payload = "".join(unquote(payload).split())
                if (len(normalized_payload) * 3) // 4 > self.max_file_bytes:
                    raise ContentAssetDownloadError("asset_too_large", "asset exceeds max size")
                data = base64.b64decode(normalized_payload, validate=True)
            else:
                data = unquote_to_bytes(payload)
        except binascii.Error as exc:
            raise ContentAssetDownloadError("asset_download_failed", "invalid data URL payload") from exc

        return content_type, data
