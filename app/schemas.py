from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NoticeAttachment(BaseModel):
    name: str
    url: str


class Notice(BaseModel):
    id: str
    title: str
    content: str
    url: str | None = None
    source: str | None = None
    sources: list[str] | None = None
    audienceGroup: str | None = None
    sourceGroup: str | None = None
    sourceGroups: list[str] | None = None
    category: str | None = None
    department: str | None = None
    date: str | None = None
    tags: list[str] = Field(default_factory=list)
    attachments: list[NoticeAttachment] = Field(default_factory=list)


class NoticeFacets(BaseModel):
    audienceGroups: list[str] = Field(default_factory=list)
    sourceGroups: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)


class NoticeListResult(BaseModel):
    items: list[Notice]
    total: int
    page: int
    pageSize: int
    totalPages: int
    facets: NoticeFacets


class NoticeReference(BaseModel):
    id: str
    title: str
    url: str | None = None
    source: str | None = None
    date: str | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequestBody(BaseModel):
    question: str | None = None
    history: list[ChatMessage] = Field(default_factory=list)
    audienceGroup: str | None = None
    sourceGroup: str | None = None
    source: str | None = None
    category: str | None = None
    department: str | None = None
    # 클라이언트가 대화 시작 시 발급해 같은 대화의 매 요청에 함께 보내는 식별자.
    # 서버 로깅이 켜져 있을 때만 이 값으로 턴을 세션에 묶어 저장한다(없으면 저장 안 함).
    sessionId: str | None = None

    model_config = ConfigDict(extra="ignore")


class ChatAnswer(BaseModel):
    answer: str
    references: list[NoticeReference]
    usedFallback: bool
    model: str


class KakaoLoginRequest(BaseModel):
    code: str | None = None
    redirectUri: str | None = None

    model_config = ConfigDict(extra="ignore")


class User(BaseModel):
    # 내부 사용자 ID. 카카오 회원번호는 응답에 내보내지 않는다.
    id: str
    nickname: str | None = None


class AuthResult(BaseModel):
    accessToken: str
    tokenType: Literal["Bearer"] = "Bearer"
    expiresIn: int
    user: User


class Bookmark(BaseModel):
    noticeId: str
    bookmarkedAt: str
    # 현재 공지 스냅샷에 있으면 전체 공지, 1년이 지나 빠졌으면 None.
    notice: Notice | None
    # 북마크한 시점에 저장한 사본. 공지가 사라져도 제목·원문 링크를 보여줄 수 있다.
    saved: NoticeReference


class BookmarkListResult(BaseModel):
    items: list[Bookmark]
    total: int
    page: int
    pageSize: int
    totalPages: int


class BookmarkIdsResult(BaseModel):
    noticeIds: list[str]


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
