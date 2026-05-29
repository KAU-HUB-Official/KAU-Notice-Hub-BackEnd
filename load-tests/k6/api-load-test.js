import http from "k6/http";
import { check, fail, sleep } from "k6";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
const PROFILE = __ENV.PROFILE || "smoke";
const INCLUDE_CHAT = (__ENV.INCLUDE_CHAT || "false").toLowerCase() === "true";
const NOTICE_ID = __ENV.NOTICE_ID || "";
const SLEEP_MIN = Number(__ENV.SLEEP_MIN || "0.2");
const SLEEP_MAX = Number(__ENV.SLEEP_MAX || "1.0");

const SEARCH_TERMS = (
  __ENV.SEARCH_TERMS ||
  "%EC%88%98%EA%B0%95%EC%8B%A0%EC%B2%AD,%EC%9E%A5%ED%95%99%EA%B8%88,%EC%A1%B8%EC%97%85"
)
  .split(",")
  .map((value) => decodeURIComponent(value.trim()))
  .filter(Boolean);

const CHAT_QUESTIONS = (
  __ENV.CHAT_QUESTIONS ||
  "%EC%88%98%EA%B0%95%EC%8B%A0%EC%B2%AD%20%EA%B3%B5%EC%A7%80%20%EC%95%8C%EB%A0%A4%EC%A4%98,%EC%9E%A5%ED%95%99%EA%B8%88%20%EA%B4%80%EB%A0%A8%20%EA%B3%B5%EC%A7%80%20%EC%B0%BE%EC%95%84%EC%A4%98"
)
  .split(",")
  .map((value) => decodeURIComponent(value.trim()))
  .filter(Boolean);

const profiles = {
  smoke: [
    { duration: "10s", target: 1 },
    { duration: "20s", target: 1 },
    { duration: "5s", target: 0 },
  ],
  local: [
    { duration: "30s", target: 10 },
    { duration: "1m", target: 10 },
    { duration: "30s", target: 0 },
  ],
  stress: [
    { duration: "1m", target: 20 },
    { duration: "2m", target: 50 },
    { duration: "1m", target: 0 },
  ],
  remote_100: [
    { duration: "1m", target: 100 },
    { duration: "3m", target: 100 },
    { duration: "1m", target: 0 },
  ],
};

export const options = {
  scenarios: {
    api: {
      executor: "ramping-vus",
      stages: profiles[PROFILE] || profiles.smoke,
      gracefulRampDown: "10s",
    },
  },
  thresholds: {
    checks: ["rate>=0.99"],
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<800", "p(99)<1500"],
    "http_req_duration{endpoint:health}": ["p(95)<200"],
    "http_req_duration{endpoint:notices_list}": ["p(95)<1000"],
    "http_req_duration{endpoint:notices_search}": ["p(95)<1200"],
  },
};

export function setup() {
  const res = http.get(`${BASE_URL}/health`, {
    tags: { endpoint: "health", name: "GET /health" },
    timeout: "5s",
  });

  if (res.status !== 200) {
    fail(`Health check failed for ${BASE_URL}/health: ${res.status}`);
  }
}

export default function () {
  const roll = Math.random();

  if (roll < 0.15) {
    getHealth();
  } else if (roll < 0.7) {
    getNoticeList();
  } else if (roll < 0.9) {
    searchNotices();
  } else if (INCLUDE_CHAT) {
    postChat();
  } else {
    getNoticeDetail();
  }

  sleep(randomBetween(SLEEP_MIN, SLEEP_MAX));
}

function getHealth() {
  const res = http.get(`${BASE_URL}/health`, {
    tags: { endpoint: "health", name: "GET /health" },
    timeout: "5s",
  });
  const body = safeJson(res);

  check(res, {
    "health returns 200": (response) => response.status === 200,
    "health body is ok": () => body?.status === "ok",
  });
}

function getNoticeList(endpoint = "notices_list") {
  const page = randomInt(1, 5);
  const pageSize = randomItem([10, 20, 50]);
  const url = buildUrl("/api/notices", { page, pageSize });
  const res = http.get(url, {
    tags: { endpoint, name: "GET /api/notices" },
    timeout: "10s",
  });
  const body = safeJson(res);

  check(res, {
    "notice list returns 200": (response) => response.status === 200,
    "notice list has items array": () => Array.isArray(body?.items),
    "notice list has total": () => typeof body?.total === "number",
  });

  return body;
}

function searchNotices() {
  const q = randomItem(SEARCH_TERMS);
  const pageSize = randomItem([10, 20]);
  const url = buildUrl("/api/notices", { q, page: 1, pageSize });
  const res = http.get(url, {
    tags: { endpoint: "notices_search", name: "GET /api/notices?q=..." },
    timeout: "10s",
  });
  const body = safeJson(res);

  check(res, {
    "notice search returns 200": (response) => response.status === 200,
    "notice search has items array": () => Array.isArray(body?.items),
  });
}

function getNoticeDetail() {
  const id = NOTICE_ID || pickNoticeIdFromLatestList();
  if (!id) {
    return;
  }

  const res = http.get(`${BASE_URL}/api/notices/${encodeURIComponent(id)}`, {
    tags: { endpoint: "notice_detail", name: "GET /api/notices/:id" },
    timeout: "10s",
  });
  const body = safeJson(res);

  check(res, {
    "notice detail returns 200": (response) => response.status === 200,
    "notice detail has id": () => body?.id === id,
  });
}

function postChat() {
  const payload = JSON.stringify({ question: randomItem(CHAT_QUESTIONS) });
  const res = http.post(`${BASE_URL}/api/chat`, payload, {
    headers: { "Content-Type": "application/json" },
    tags: { endpoint: "chat", name: "POST /api/chat" },
    timeout: "30s",
  });
  const body = safeJson(res);

  check(res, {
    "chat returns 200": (response) => response.status === 200,
    "chat has answer": () => typeof body?.answer === "string",
  });
}

function pickNoticeIdFromLatestList() {
  const body = getNoticeList("notices_list_for_detail");
  if (!body || !Array.isArray(body.items) || body.items.length === 0) {
    return "";
  }

  return randomItem(body.items).id || "";
}

function buildUrl(path, params) {
  const query = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
    .join("&");

  return query ? `${BASE_URL}${path}?${query}` : `${BASE_URL}${path}`;
}

function safeJson(response) {
  try {
    return response.json();
  } catch {
    return null;
  }
}

function randomItem(values) {
  return values[randomInt(0, values.length - 1)];
}

function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomBetween(min, max) {
  return Math.random() * (max - min) + min;
}
