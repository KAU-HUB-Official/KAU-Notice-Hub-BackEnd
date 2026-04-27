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
    summary: str | None = None
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


class ChatRequestBody(BaseModel):
    question: str | None = None
    audienceGroup: str | None = None
    sourceGroup: str | None = None
    source: str | None = None
    category: str | None = None
    department: str | None = None

    model_config = ConfigDict(extra="ignore")


class ChatAnswer(BaseModel):
    answer: str
    references: list[NoticeReference]
    usedFallback: bool
    model: str


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
