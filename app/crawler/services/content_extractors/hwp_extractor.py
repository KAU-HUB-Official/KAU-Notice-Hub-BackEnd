from __future__ import annotations

import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree

from ..content_asset_downloader import DownloadedAsset, is_hwp_asset


@dataclass(frozen=True)
class ExtractedText:
    text: str
    format: str
    method: str
    confidence: str = "medium"
    warnings: list[str] = field(default_factory=list)


class HwpTextExtractionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _clean_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _suffix_from_asset(downloaded: DownloadedAsset) -> str:
    name_suffix = PurePosixPath(downloaded.asset.name).suffix.lower()
    if name_suffix:
        return name_suffix
    return PurePosixPath(downloaded.asset.url).suffix.lower()


class HwpTextExtractor:
    def __init__(self, *, min_text_length: int = 30) -> None:
        self.min_text_length = min_text_length

    def extract(self, downloaded: DownloadedAsset) -> ExtractedText:
        if not is_hwp_asset(
            downloaded.asset.name,
            downloaded.asset.url,
            downloaded.content_type,
        ):
            raise HwpTextExtractionError("unsupported_hwp_format", "asset is not HWP/HWPX")

        suffix = _suffix_from_asset(downloaded)
        if suffix == ".hwpx":
            extracted = self._extract_hwpx_xml(downloaded.data)
            if self._has_enough_text(extracted.text):
                return extracted

        extracted = self._extract_with_optional_library(downloaded, suffix)
        if not self._has_enough_text(extracted.text):
            raise HwpTextExtractionError("hwp_text_too_short", "extracted HWP text is too short")
        return extracted

    def _extract_hwpx_xml(self, data: bytes) -> ExtractedText:
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                xml_names = [
                    name
                    for name in archive.namelist()
                    if name.lower().endswith(".xml")
                    and (
                        name.startswith("Contents/")
                        or name.startswith("contents/")
                        or name.startswith("Sections/")
                        or name.startswith("sections/")
                    )
                ]
                text_parts: list[str] = []
                for name in sorted(xml_names):
                    try:
                        root = ElementTree.fromstring(archive.read(name))
                    except ElementTree.ParseError:
                        continue
                    text_parts.append(" ".join(root.itertext()))
        except zipfile.BadZipFile as exc:
            raise HwpTextExtractionError("unsupported_hwp_format", "invalid HWPX zip") from exc

        text = _clean_text("\n".join(text_parts))
        return ExtractedText(
            text=text,
            format="hwpx",
            method="hwpx-xml",
            confidence="high" if text else "low",
        )

    def _extract_with_optional_library(
        self,
        downloaded: DownloadedAsset,
        suffix: str,
    ) -> ExtractedText:
        try:
            return self._extract_with_unhwp(downloaded, suffix)
        except ImportError:
            pass

        return self._extract_with_extract_hwp(downloaded, suffix)

    def _extract_with_unhwp(
        self,
        downloaded: DownloadedAsset,
        suffix: str,
    ) -> ExtractedText:
        try:
            import unhwp  # type: ignore[import-not-found]
        except ImportError:
            raise

        suffix = suffix if suffix in {".hwp", ".hwpx"} else ".hwp"
        with tempfile.NamedTemporaryFile(suffix=suffix) as fp:
            fp.write(downloaded.data)
            fp.flush()

            try:
                text = unhwp.extract_text(fp.name)
            except Exception as exc:
                message = str(exc)
                if "password" in message.lower() or "encrypted" in message.lower():
                    raise HwpTextExtractionError(
                        "password_protected_hwp",
                        "HWP file is password protected",
                    ) from exc
                raise HwpTextExtractionError("hwp_text_extract_failed", message) from exc

        return ExtractedText(
            text=_clean_text(text),
            format="hwpx" if suffix == ".hwpx" else "hwp",
            method="unhwp",
            confidence="medium",
        )

    def _extract_with_extract_hwp(
        self,
        downloaded: DownloadedAsset,
        suffix: str,
    ) -> ExtractedText:
        try:
            from extract_hwp import (  # type: ignore[import-not-found]
                extract_text_from_hwp,
                is_hwp_file_password_protected,
            )
        except ImportError as exc:
            raise HwpTextExtractionError(
                "hwp_text_extractor_unavailable",
                "HWP text extractor package is not installed",
            ) from exc

        suffix = suffix if suffix in {".hwp", ".hwpx"} else ".hwp"
        with tempfile.NamedTemporaryFile(suffix=suffix) as fp:
            fp.write(downloaded.data)
            fp.flush()

            try:
                if is_hwp_file_password_protected(fp.name):
                    raise HwpTextExtractionError(
                        "password_protected_hwp",
                        "HWP file is password protected",
                    )
            except HwpTextExtractionError:
                raise
            except Exception:
                # Password detection is best-effort; continue to extraction.
                pass

            text, error = extract_text_from_hwp(fp.name)

        if error:
            raise HwpTextExtractionError("hwp_text_extract_failed", str(error))

        return ExtractedText(
            text=_clean_text(text),
            format="hwpx" if suffix == ".hwpx" else "hwp",
            method="extract-hwp",
            confidence="medium",
        )

    def _has_enough_text(self, text: str) -> bool:
        return len(re.sub(r"\s+", "", text or "")) >= self.min_text_length
