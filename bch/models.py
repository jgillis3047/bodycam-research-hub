"""SQLAlchemy ORM models."""
from __future__ import annotations

from . import clock
from datetime import date, datetime

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return clock.utcnow()


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Vocabulary (stored as strings so the DB stays readable)
# ---------------------------------------------------------------------------
class BodycamStatus:
    RELEASED = "Released (reported in source)"
    MENTIONED = "Exists (mentioned in source)"
    YOUTUBE_FOUND = "Footage found on YouTube"
    LIKELY = "Likely exists (estimate)"
    UNKNOWN = "Unknown"
    ALL = [RELEASED, YOUTUBE_FOUND, MENTIONED, LIKELY, UNKNOWN]


class YouTubeStatus:
    NOT_CHECKED = "Not checked"
    FOOTAGE = "Bodycam/dashcam footage uploaded"
    NEWS = "News coverage only"
    COMMENTARY = "Commentary coverage"
    RELATED_OTHER = "Related videos - different incidents"
    NONE_FOUND = "No match in checked results"
    ALL = [NOT_CHECKED, FOOTAGE, NEWS, COMMENTARY, RELATED_OTHER, NONE_FOUND]


class Verification:
    """How much we trust a piece of agency contact information."""
    USER_VERIFIED = "Verified by you"
    OFFICIAL_SITE = "Found on official .gov site"
    UNVERIFIED = "Unverified candidate"
    NOT_FOUND = "Not found"
    NOT_RESEARCHED = "Not researched"
    TRUSTED = {USER_VERIFIED, OFFICIAL_SITE}


REQUEST_STATUSES = [
    "Researching", "Ready to Request", "Submitted", "Acknowledged",
    "Fee Estimate Received", "Awaiting Payment", "Processing", "Footage Received",
    "Partially Fulfilled", "Denied", "Closed",
]
PENDING_REQUEST_STATUSES = {
    "Ready to Request", "Submitted", "Acknowledged", "Fee Estimate Received",
    "Awaiting Payment", "Processing",
}


# ---------------------------------------------------------------------------
class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


class Agency(Base):
    __tablename__ = "agencies"
    __table_args__ = (UniqueConstraint("normalized_name", "state"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    agency_type: Mapped[str | None] = mapped_column(String(50))  # police/sheriff/state_patrol/other
    state: Mapped[str | None] = mapped_column(String(50), index=True)
    county: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))

    website: Mapped[str | None] = mapped_column(String(500))
    website_status: Mapped[str] = mapped_column(String(50), default=Verification.NOT_RESEARCHED)
    records_page_url: Mapped[str | None] = mapped_column(String(500))
    portal_url: Mapped[str | None] = mapped_column(String(500))
    portal_platform: Mapped[str | None] = mapped_column(String(100))
    portal_status: Mapped[str] = mapped_column(String(50), default=Verification.NOT_RESEARCHED)
    records_email: Mapped[str | None] = mapped_column(String(200))
    email_status: Mapped[str] = mapped_column(String(50), default=Verification.NOT_RESEARCHED)
    records_phone: Mapped[str | None] = mapped_column(String(50))
    fee_info: Mapped[str | None] = mapped_column(Text)
    fee_source_url: Mapped[str | None] = mapped_column(String(500))
    request_instructions: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    candidates: Mapped[list | None] = mapped_column(JSON, default=list)  # unverified finds
    evidence: Mapped[list | None] = mapped_column(JSON, default=list)    # [{field,url,snippet}]
    research_log: Mapped[str | None] = mapped_column(Text)
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    cases: Mapped[list["Case"]] = relationship(back_populates="agency")
    feeds: Mapped[list["Source"]] = relationship(back_populates="agency")


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    headline: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    summary_source_url: Mapped[str | None] = mapped_column(String(1000))
    state: Mapped[str | None] = mapped_column(String(50), index=True)
    state_basis: Mapped[str | None] = mapped_column(String(100))
    county: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    location_basis: Mapped[str | None] = mapped_column(String(100))

    incident_date: Mapped[date | None] = mapped_column(Date, index=True)
    incident_date_basis: Mapped[str | None] = mapped_column(String(100))
    incident_date_evidence: Mapped[str | None] = mapped_column(Text)
    first_published: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_published: Mapped[datetime | None] = mapped_column(DateTime)

    category: Mapped[str | None] = mapped_column(String(50), index=True)
    categories: Mapped[list | None] = mapped_column(JSON, default=list)
    agency_name: Mapped[str | None] = mapped_column(String(300))
    agency_basis: Mapped[str | None] = mapped_column(String(100))
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agencies.id"))
    suspect_names: Mapped[list | None] = mapped_column(JSON, default=list)

    bodycam_status: Mapped[str] = mapped_column(String(80), default=BodycamStatus.UNKNOWN)
    bodycam_evidence: Mapped[str | None] = mapped_column(Text)
    youtube_status: Mapped[str] = mapped_column(String(80), default=YouTubeStatus.NOT_CHECKED)
    youtube_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    youtube_queries: Mapped[list | None] = mapped_column(JSON, default=list)

    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_breakdown: Mapped[dict | None] = mapped_column(JSON, default=dict)
    risk_flags: Mapped[list | None] = mapped_column(JSON, default=list)
    ai_assessment: Mapped[dict | None] = mapped_column(JSON)
    timeline: Mapped[list | None] = mapped_column(JSON, default=list)

    est_cost: Mapped[float | None] = mapped_column(Float)  # estimated footage cost (USD)
    est_cost_basis: Mapped[str | None] = mapped_column(String(200))

    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    user_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    agency: Mapped[Agency | None] = relationship(back_populates="cases")
    articles: Mapped[list["Article"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="Article.published_at")
    videos: Mapped[list["YouTubeVideo"]] = relationship(
        back_populates="case", cascade="all, delete-orphan")
    requests: Mapped[list["RecordsRequest"]] = relationship(back_populates="case")


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    source_name: Mapped[str | None] = mapped_column(String(200))
    source_domain: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    summary: Mapped[str | None] = mapped_column(Text)
    text_excerpt: Mapped[str | None] = mapped_column(Text)
    collector: Mapped[str | None] = mapped_column(String(100))
    query: Mapped[str | None] = mapped_column(String(500))
    state_hint: Mapped[str | None] = mapped_column(String(50))
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_full_text: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    case: Mapped[Case | None] = relationship(back_populates="articles")


class YouTubeVideo(Base):
    __tablename__ = "youtube_videos"
    __table_args__ = (UniqueConstraint("case_id", "video_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    video_id: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    channel_title: Mapped[str | None] = mapped_column(String(200))
    channel_id: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    view_count: Mapped[int | None] = mapped_column(Integer)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    match_confidence: Mapped[int] = mapped_column(Integer, default=0)
    match_reasons: Mapped[list | None] = mapped_column(JSON, default=list)
    channel_kind: Mapped[str | None] = mapped_column(String(50))  # news/agency/commentary
    has_footage: Mapped[bool] = mapped_column(Boolean, default=False)
    footage_evidence: Mapped[str | None] = mapped_column(String(300))
    query: Mapped[str | None] = mapped_column(String(500))

    case: Mapped[Case] = relationship(back_populates="videos")

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


class Source(Base):
    """User-configured feeds (police newsrooms, local outlets, etc.)."""
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    kind: Mapped[str] = mapped_column(String(30), default="rss")  # rss / google_news_query
    state: Mapped[str | None] = mapped_column(String(50))
    county: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agencies.id"))
    last_fetched: Mapped[datetime | None] = mapped_column(DateTime)
    last_status: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    agency: Mapped[Agency | None] = relationship(back_populates="feeds")


class RecordsRequest(Base):
    __tablename__ = "records_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"))
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agencies.id"))
    agency_name: Mapped[str | None] = mapped_column(String(300))
    incident: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(50), default="Researching")
    submitted_date: Mapped[date | None] = mapped_column(Date)
    tracking_number: Mapped[str | None] = mapped_column(String(100))
    quoted_fee: Mapped[float | None] = mapped_column(Float)
    amount_paid: Mapped[float | None] = mapped_column(Float)
    response_info: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    request_text: Mapped[str | None] = mapped_column(Text)
    submission_method: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    case: Mapped[Case | None] = relationship(back_populates="requests")
    agency: Mapped[Agency | None] = relationship()


class TrackedChannel(Base):
    __tablename__ = "tracked_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    handle: Mapped[str] = mapped_column(String(200), unique=True)  # @handle or UC... id
    channel_id: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(200))
    uploads_playlist: Mapped[str | None] = mapped_column(String(100))
    subscriber_count: Mapped[int | None] = mapped_column(Integer)
    video_count: Mapped[int | None] = mapped_column(Integer)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime)
    last_status: Mapped[str | None] = mapped_column(String(300))

    videos: Mapped[list["ChannelVideo"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan")


class ChannelVideo(Base):
    __tablename__ = "channel_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_pk: Mapped[int] = mapped_column(ForeignKey("tracked_channels.id"), index=True)
    video_id: Mapped[str] = mapped_column(String(50), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    view_count: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[str | None] = mapped_column(String(30))
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    detected_state: Mapped[str | None] = mapped_column(String(50))
    detected_category: Mapped[str | None] = mapped_column(String(50))
    matched_case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"))

    channel: Mapped[TrackedChannel] = relationship(back_populates="videos")

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


class HttpCache(Base):
    __tablename__ = "http_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30), default="running")
    trigger: Mapped[str | None] = mapped_column(String(30))
    stats: Mapped[dict | None] = mapped_column(JSON, default=dict)
    log: Mapped[str | None] = mapped_column(Text)
