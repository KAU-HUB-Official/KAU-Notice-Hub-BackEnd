from __future__ import annotations

import random
import time
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from ..utils.logger import get_logger


class BaseClient:
    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        timeout: int,
        request_delay: tuple[float, float],
        respect_robots: bool = True,
        verify_ssl: bool = True,
    ) -> None:
        self.base_url = base_url
        self.user_agent = user_agent
        self.timeout = timeout
        self.request_delay = request_delay
        self.respect_robots = respect_robots
        self.verify_ssl = verify_ssl

        self.logger = get_logger(self.__class__.__name__)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )

        self._robots_loaded = False
        self._robots_parser: RobotFileParser | None = None
        self._robots_allow_paths: list[str] = []
        self._robots_disallow_paths: list[str] = []
        self._request_count = 0

    def _load_robots(self) -> None:
        if self._robots_loaded:
            return

        self._robots_loaded = True
        robots_url = urljoin(self.base_url, "/robots.txt")
        parser = RobotFileParser()

        try:
            response = self.session.get(
                robots_url,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            if response.status_code >= 400:
                self.logger.warning(
                    "robots.txt request failed (%s): %s",
                    response.status_code,
                    robots_url,
                )
                return
            robots_text = response.text
            parser.parse(robots_text.splitlines())
            self._robots_parser = parser
            self._parse_simple_robots_rules(robots_text)
        except requests.RequestException as exc:
            self.logger.warning("robots.txt 확인 실패: %s (%s)", robots_url, exc)

    def can_fetch(self, url: str) -> bool:
        if not self.respect_robots:
            return True

        self._load_robots()
        simple_allowed = self._can_fetch_with_simple_rules(url)
        if simple_allowed is not None:
            if not simple_allowed:
                self.logger.warning("robots.txt 정책으로 요청이 차단됨: %s", url)
            return simple_allowed

        if self._robots_parser is None:
            return True

        allowed = self._robots_parser.can_fetch(self.user_agent, url)
        if not allowed:
            self.logger.warning("robots.txt 정책으로 요청이 차단됨: %s", url)
        return allowed

    def _parse_simple_robots_rules(self, robots_text: str) -> None:
        """
        RobotFileParser가 Allow 규칙을 충분히 반영하지 못하는 사이트를 위해
        User-agent 그룹의 Allow/Disallow prefix를 함께 파싱한다.
        """
        self._robots_allow_paths = []
        self._robots_disallow_paths = []

        groups: list[dict[str, object]] = []
        current_group: dict[str, object] | None = None

        for raw_line in robots_text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue

            directive, value = line.split(":", 1)
            directive = directive.strip().lower()
            value = value.strip()

            if directive == "user-agent":
                if current_group is None or bool(current_group["has_rules"]):
                    current_group = {
                        "agents": [],
                        "allow": [],
                        "disallow": [],
                        "has_rules": False,
                    }
                    groups.append(current_group)
                agents = current_group["agents"]
                if isinstance(agents, list):
                    agents.append(value.lower())
                continue

            if directive not in {"allow", "disallow"} or current_group is None:
                continue

            current_group["has_rules"] = True
            if directive == "allow":
                allow_rules = current_group["allow"]
                if isinstance(allow_rules, list):
                    allow_rules.append(value)
            else:
                disallow_rules = current_group["disallow"]
                if isinstance(disallow_rules, list):
                    disallow_rules.append(value)

        if not groups:
            return

        user_agent = self.user_agent.lower()
        specific_groups = [
            group
            for group in groups
            if any(
                isinstance(agent, str) and agent != "*" and agent in user_agent
                for agent in group["agents"]  # type: ignore[index]
            )
        ]
        target_groups = specific_groups or [
            group
            for group in groups
            if any(agent == "*" for agent in group["agents"])  # type: ignore[index]
        ]

        for group in target_groups:
            allow_rules = group.get("allow", [])
            disallow_rules = group.get("disallow", [])
            if isinstance(allow_rules, list):
                for rule in allow_rules:
                    if isinstance(rule, str) and rule:
                        self._robots_allow_paths.append(rule)
            if isinstance(disallow_rules, list):
                for rule in disallow_rules:
                    if isinstance(rule, str):
                        # 빈 Disallow는 전체 허용 의미이므로 무시한다.
                        if not rule:
                            continue
                        self._robots_disallow_paths.append(rule)

    def _can_fetch_with_simple_rules(self, url: str) -> bool | None:
        if not self._robots_allow_paths and not self._robots_disallow_paths:
            return None

        path = urlparse(url).path or "/"

        best_rule_length = -1
        best_rule_action = "allow"

        for allow_rule in self._robots_allow_paths:
            if path.startswith(allow_rule):
                rule_length = len(allow_rule)
                if rule_length > best_rule_length or (
                    rule_length == best_rule_length and best_rule_action == "disallow"
                ):
                    best_rule_length = rule_length
                    best_rule_action = "allow"

        for disallow_rule in self._robots_disallow_paths:
            if path.startswith(disallow_rule):
                rule_length = len(disallow_rule)
                if rule_length > best_rule_length:
                    best_rule_length = rule_length
                    best_rule_action = "disallow"

        if best_rule_length == -1:
            return True
        return best_rule_action == "allow"

    def _sleep_between_requests(self) -> None:
        if self._request_count <= 0:
            return
        delay = random.uniform(self.request_delay[0], self.request_delay[1])
        time.sleep(delay)

    def get(self, url: str, *, referer: str | None = None) -> str | None:
        if not self.can_fetch(url):
            return None

        self._sleep_between_requests()

        headers = {}
        if referer:
            headers["Referer"] = referer

        try:
            response = self.session.get(
                url,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            self._request_count += 1
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            self.logger.error("요청 실패: %s (%s)", url, exc)
            return None

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        referer: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> str | None:
        if not self.can_fetch(url):
            return None

        self._sleep_between_requests()

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/plain, */*",
        }
        if referer:
            headers["Referer"] = referer
        if extra_headers:
            headers.update(extra_headers)

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            self._request_count += 1
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            self.logger.error("JSON POST 요청 실패: %s (%s)", url, exc)
            return None
