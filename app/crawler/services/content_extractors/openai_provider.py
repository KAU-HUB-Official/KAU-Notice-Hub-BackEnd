from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

import requests

from ..content_asset_downloader import DownloadedAsset
from .hwp_extractor import ExtractedText

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


@dataclass(frozen=True)
class GeneratedContent:
    content: str
    summary: str | None
    confidence: str
    warnings: list[str] = field(default_factory=list)
    source_asset_names: list[str] = field(default_factory=list)
    model: str = ""


class OpenAIProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OpenAIContentProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        fallback_model: str | None = None,
        image_detail: str = "high",
        timeout_seconds: int = 60,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise OpenAIProviderError("missing_openai_api_key", "OPENAI_API_KEY is required")

        self.api_key = api_key
        self.model = model
        self.fallback_model = fallback_model
        self.image_detail = image_detail
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def extract_image_text(
        self,
        downloaded: DownloadedAsset,
        *,
        notice_meta: dict,
        min_text_length: int,
    ) -> ExtractedText:
        prompt = "\n".join(
            [
                "이미지 안에 있는 한국어 공지 텍스트를 최대한 정확히 추출하세요.",
                "표, 일정, 신청 방법, 문의처, URL이 있으면 줄바꿈을 유지해 적으세요.",
                "보이지 않는 정보는 추측하지 말고 [판독 불가]라고 표시하세요.",
                "",
                f"공지 제목: {notice_meta.get('title') or ''}",
                f"게시일: {notice_meta.get('published_at') or notice_meta.get('date') or ''}",
                f"출처: {notice_meta.get('source_name') or notice_meta.get('source') or ''}",
            ]
        )
        image_part: dict[str, str] = {
            "type": "input_image",
            "image_url": self._to_data_url(downloaded),
        }
        if self.image_detail:
            image_part["detail"] = self.image_detail

        text = self._create_text_response(
            self.model,
            input_content=[
                {"type": "input_text", "text": prompt},
                image_part,
            ],
        )

        model_used = self.model
        if self._too_short(text, min_text_length) and self.fallback_model:
            text = self._create_text_response(
                self.fallback_model,
                input_content=[
                    {"type": "input_text", "text": prompt},
                    image_part,
                ],
            )
            model_used = self.fallback_model

        if self._too_short(text, min_text_length):
            raise OpenAIProviderError("image_text_too_short", "extracted image text is too short")

        return ExtractedText(
            text=text.strip(),
            format="image",
            method=f"openai:{model_used}",
            confidence="medium",
            warnings=[],
        )

    def generate_notice_content(
        self,
        *,
        notice_meta: dict,
        extracted_texts: list[ExtractedText],
    ) -> GeneratedContent:
        payload_text = "\n\n".join(
            [
                f"[asset {index} | format={item.format} | method={item.method}]\n{item.text}"
                for index, item in enumerate(extracted_texts, start=1)
            ]
        )
        prompt = "\n".join(
            [
                "아래 추출 텍스트와 공지 메타데이터만 근거로 공지 본문을 작성하세요.",
                "원문에 없는 날짜, 장소, 금액, 신청 조건, URL은 추측하지 마세요.",
                "학생이 검색/RAG로 찾을 수 있도록 핵심 일정, 대상, 방법, 제출 서류, 문의처를 한국어로 정리하세요.",
                "content 필드는 Markdown 문법으로 작성하세요.",
                "제목은 ##, 하위 항목은 ###, 목록은 - 또는 1.을 사용하세요.",
                "원문에 표가 있으면 가능한 한 Markdown table로 변환하세요.",
                "판독이 불확실한 정보는 확정 표현 대신 확인 필요라고 표시하세요.",
                "",
                f"제목: {notice_meta.get('title') or ''}",
                f"게시일: {notice_meta.get('published_at') or notice_meta.get('date') or ''}",
                f"출처: {notice_meta.get('source_name') or notice_meta.get('source') or ''}",
                f"원문 URL: {notice_meta.get('original_url') or notice_meta.get('url') or ''}",
                "",
                "추출 텍스트:",
                payload_text,
            ]
        )
        raw_text = self._create_text_response(
            self.model,
            input_content=[{"type": "input_text", "text": prompt}],
            text_format=self._content_json_schema(),
        )
        parsed = self._parse_json_object(raw_text)
        content = str(parsed.get("content") or "").strip()
        if not content:
            raise OpenAIProviderError("generated_content_empty", "generated content is empty")

        confidence = str(parsed.get("confidence") or "medium").strip().lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"

        warnings_raw = parsed.get("warnings")
        warnings = [str(item) for item in warnings_raw] if isinstance(warnings_raw, list) else []
        asset_names_raw = parsed.get("source_asset_names")
        source_asset_names = (
            [str(item) for item in asset_names_raw] if isinstance(asset_names_raw, list) else []
        )

        return GeneratedContent(
            content=content,
            summary=str(parsed.get("summary") or "").strip() or None,
            confidence=confidence,
            warnings=warnings,
            source_asset_names=source_asset_names,
            model=self.model,
        )

    def _create_text_response(
        self,
        model: str,
        *,
        input_content: list[dict[str, Any]],
        text_format: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": input_content,
                }
            ],
        }
        if text_format is not None:
            payload["text"] = {"format": text_format}

        response = self.session.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise OpenAIProviderError(
                "openai_request_failed",
                f"OpenAI request failed: status={response.status_code}",
            )

        try:
            response_data = response.json()
        except ValueError as exc:
            raise OpenAIProviderError(
                "openai_invalid_response",
                "OpenAI returned a non-JSON response",
            ) from exc

        if not isinstance(response_data, dict):
            raise OpenAIProviderError(
                "openai_invalid_response",
                "OpenAI response was not a JSON object",
            )

        text = self._extract_output_text(response_data)
        if not text:
            raise OpenAIProviderError("openai_empty_response", "OpenAI response text was empty")
        return text

    @staticmethod
    def _extract_output_text(data: dict[str, Any]) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return output_text

        text_parts: list[str] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                if content.get("type") in {"output_text", "text"} and isinstance(
                    content.get("text"), str
                ):
                    text_parts.append(content["text"])
        return "\n".join(text_parts).strip()

    @staticmethod
    def _parse_json_object(value: str) -> dict[str, Any]:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise OpenAIProviderError("llm_json_parse_failed", "LLM returned invalid JSON") from exc

        if not isinstance(parsed, dict):
            raise OpenAIProviderError("llm_json_parse_failed", "LLM did not return a JSON object")
        return parsed

    @staticmethod
    def _content_json_schema() -> dict[str, Any]:
        return {
            "type": "json_schema",
            "name": "notice_content_enrichment",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "content": {"type": "string"},
                    "summary": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                    "source_asset_names": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "content",
                    "summary",
                    "confidence",
                    "warnings",
                    "source_asset_names",
                ],
            },
        }

    @staticmethod
    def _to_data_url(downloaded: DownloadedAsset) -> str:
        encoded = base64.b64encode(downloaded.data).decode("ascii")
        content_type = downloaded.content_type or "image/png"
        return f"data:{content_type};base64,{encoded}"

    @staticmethod
    def _too_short(value: str, min_text_length: int) -> bool:
        return len("".join((value or "").split())) < min_text_length
