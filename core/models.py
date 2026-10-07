from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean, Index
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account = Column(String(50), nullable=False, index=True)
    influencer_id = Column(Integer, nullable=True, index=True)
    status = Column(String(30), nullable=False, default="pending")
    # Status values: pending, scripting, generating_video, generating_tts,
    # subtitling, compositing, reviewing, uploading_drive, publishing,
    # published, failed, rejected

    title = Column(String(500))
    script_text = Column(Text)
    visual_prompts = Column(Text)       # JSON array
    hashtags = Column(Text)             # JSON array
    hook = Column(Text)

    narration_path = Column(String(500))
    video_clips = Column(Text)          # JSON array of paths
    subtitle_path = Column(String(500))
    final_path = Column(String(500))
    music_path = Column(String(500))

    quality_score = Column(Float)
    quality_notes = Column(Text)

    drive_file_id = Column(String(200))
    drive_url = Column(String(500))

    # Multi-platform publishing
    tiktok_url = Column(String(500))
    youtube_url = Column(String(500))
    tiktok_published = Column(Boolean, default=False)
    youtube_published = Column(Boolean, default=False)
    tiktok_enabled = Column(Boolean, default=True)   # per-video toggle
    youtube_enabled = Column(Boolean, default=True)   # per-video toggle
    platforms_enabled_json = Column(Text)             # JSON dict: platform -> bool
    platform_results_json = Column(Text)              # JSON dict: platform -> result metadata
    platform_errors_json = Column(Text)               # JSON dict: platform -> last error

    retry_count = Column(Integer, default=0)
    error_message = Column(Text)
    estimated_duration = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime)

    __table_args__ = (
        Index("idx_videos_account_status", "account", "status"),
        Index("idx_videos_status_created", "status", "created_at"),
        Index("idx_videos_created", "created_at"),
        Index("idx_videos_published_at", "published_at"),
    )

    def __repr__(self):
        return f"<Video {self.id} [{self.account}] {self.status}>"


class IdeaHistory(Base):
    __tablename__ = "idea_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account = Column(String(50), nullable=False, index=True)
    summary = Column(Text, nullable=False)
    title = Column(String(500))
    keywords = Column(String(200))  # compact tags for dedup: "haunted doll revenge"
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(50), nullable=False)  # gemini, kling, elevenlabs
    label = Column(String(100))
    api_key = Column(String(500), nullable=False)
    enabled = Column(Boolean, default=True)

    usage_count = Column(Integer, default=0)
    usage_chars = Column(Integer, default=0)        # for ElevenLabs
    usage_reset_at = Column(DateTime)               # monthly reset

    failure_count = Column(Integer, default=0)
    cooldown_until = Column(DateTime)
    last_used_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_keys_provider", "provider", "enabled"),
    )

    def __repr__(self):
        return f"<ApiKey {self.id} [{self.provider}] {self.label}>"


class EmailThread(Base):
    __tablename__ = "email_threads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gmail_thread_id = Column(String(200), unique=True, nullable=False)
    gmail_message_id = Column(String(200))
    account = Column(String(50), index=True)  # which account's Gmail

    sender = Column(String(300))
    subject = Column(String(500))
    body_preview = Column(Text)

    category = Column(String(30))   # spam, sponsor, collab, legal, fan, otro
    confidence = Column(Float)

    auto_responded = Column(Boolean, default=False)
    response_text = Column(Text)
    needs_attention = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<EmailThread {self.id} [{self.account}:{self.category}] {self.subject}>"


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, nullable=False, index=True)
    step = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)     # success, failed, skipped

    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_ms = Column(Integer)
    error_message = Column(Text)
    metadata_json = Column(Text)    # JSON: key used, retry count, etc.

    __table_args__ = (
        Index("idx_runs_video_step", "video_id", "step"),
        Index("idx_runs_status", "status"),
    )


class AuditLog(Base):
    """Append-only log of administrative actions (manual publish, toggles, etc.)."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor = Column(String(100))           # discord user id, "scheduler", "dashboard:<api-key-prefix>", "system"
    action = Column(String(80), nullable=False, index=True)
    target = Column(String(200))          # account, video id, platform, ...
    details = Column(Text)                # free-form, often JSON
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class VideoMetrics(Base):
    """Per-video, per-platform engagement snapshots (views/likes/shares).

    Filled in by an optional analytics job. Not used by core pipeline so it stays
    NULL-safe for users who never enable analytics.
    """
    __tablename__ = "video_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, nullable=False, index=True)
    platform = Column(String(20), nullable=False)        # tiktok | youtube
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    captured_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_metrics_video_platform", "video_id", "platform"),
    )


class Influencer(Base):
    """Virtual AI influencer identity."""
    __tablename__ = "influencers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    display_name = Column(String(200))
    slug = Column(String(100), nullable=False, unique=True, index=True)
    niche = Column(String(50))               # technology, fitness, travel, fashion, gaming, education
    bio = Column(Text)
    personality = Column(Text)
    target_audience = Column(Text)
    visual_description = Column(Text)
    profile_picture_path = Column(String(500))
    reference_images_json = Column(Text)    # JSON list of paths
    writing_style = Column(String(200))
    preferred_language = Column(String(10), default="en")
    status = Column(String(20), default="active")  # active, paused, archived
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_influencers_slug", "slug"),
        Index("idx_influencers_niche", "niche"),
    )

    def __repr__(self):
        return f"<Influencer {self.id} [{self.slug}] {self.display_name or self.name}>"


class VoicePreset(Base):
    """Per-influencer voice configuration."""
    __tablename__ = "voice_presets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    influencer_id = Column(Integer, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    tts_backend = Column(String(50), default="edge_tts")   # edge_tts, piper, elevenlabs
    voice_id = Column(String(200))                          # e.g. "en-US-JennyNeural"
    language = Column(String(10), default="en")
    speed = Column(Float, default=1.0)
    pitch = Column(Float, default=1.0)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<VoicePreset {self.id} [{self.influencer_id}] {self.name}>"


class SocialConnection(Base):
    """Social media account linked to an influencer."""
    __tablename__ = "social_connections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    influencer_id = Column(Integer, nullable=False, index=True)
    platform = Column(String(30), nullable=False)   # tiktok, youtube, instagram, facebook
    account_name = Column(String(200))
    account_id = Column(String(200))
    access_token = Column(String(500))
    refresh_token = Column(String(500))
    token_expires_at = Column(DateTime)
    credentials_json = Column(Text)                 # JSON blob for platform-specific data
    status = Column(String(30), default="connected") # connected, expired, error, disconnected
    last_error = Column(Text)
    connected_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_social_influencer_platform", "influencer_id", "platform"),
    )

    def __repr__(self):
        return f"<SocialConnection {self.id} [{self.influencer_id}:{self.platform}] {self.account_name}>"


class ContentCalendarEntry(Base):
    """Calendar entry for content planning and scheduling."""
    __tablename__ = "content_calendar"

    id = Column(Integer, primary_key=True, autoincrement=True)
    influencer_id = Column(Integer, nullable=False, index=True)
    title = Column(String(500))
    description = Column(Text)
    content_type = Column(String(50))            # video, image, carousel, story
    status = Column(String(30), default="draft") # draft, approved, scheduled, publishing, published, failed, cancelled
    scheduled_at = Column(DateTime, index=True)
    published_at = Column(DateTime)
    video_id = Column(Integer, index=True)       # linked video if already produced
    platforms_json = Column(Text)                # JSON list of target platforms
    tags = Column(String(300))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_calendar_influencer_status", "influencer_id", "status"),
        Index("idx_calendar_scheduled_at", "scheduled_at"),
    )

    def __repr__(self):
        return f"<ContentCalendarEntry {self.id} [{self.influencer_id}] {self.status} {self.title}>"


class ImageGenerationHistory(Base):
    """Track generated images for reference and audit."""
    __tablename__ = "image_generation_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    influencer_id = Column(Integer, nullable=True, index=True)
    prompt = Column(Text, nullable=False)
    negative_prompt = Column(Text)
    image_path = Column(String(500), nullable=False)
    backend = Column(String(50))                 # comfyui, automatic1111, dall_e, imagen
    width = Column(Integer)
    height = Column(Integer)
    steps = Column(Integer)
    cfg_scale = Column(Float)
    seed = Column(Integer)
    generation_time_ms = Column(Integer)
    is_reference = Column(Boolean, default=False)
    is_accepted = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_image_history_influencer", "influencer_id"),
    )

    def __repr__(self):
        return f"<ImageGenerationHistory {self.id} [{self.backend}] {self.image_path}>"


class AnalyticsSnapshot(Base):
    """Daily/weekly/monthly analytics snapshots per influencer."""
    __tablename__ = "analytics_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    influencer_id = Column(Integer, nullable=False, index=True)
    platform = Column(String(30), nullable=False)
    date = Column(DateTime, nullable=False, index=True)
    period = Column(String(20), default="daily")  # daily, weekly, monthly
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    followers = Column(Integer, default=0)
    engagement_rate = Column(Float)
    source = Column(String(30), default="api")    # api, manual, import
    raw_json = Column(Text)                       # raw platform response for audit
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_analytics_influencer_platform_date", "influencer_id", "platform", "date"),
    )

    def __repr__(self):
        return f"<AnalyticsSnapshot {self.id} [{self.influencer_id}:{self.platform}] {self.date}>"

