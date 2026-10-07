"""
Publishing queue: persistent, restart-safe queue for platform dispatch.

Features:
- Idempotency keys to prevent duplicate publishing
- Safe retries with backoff
- Manual export fallback when platform auth is missing
- Rate limiting per platform/day
- Audit logging for every attempt
"""
import json
import logging
import os
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config.settings import settings, get_platform_info, is_platform_supported
from core.db import get_session
from core.models import PublishingQueue, Video, AuditLog
from core import audit
from pipeline import platform_publishers

logger = logging.getLogger(__name__)

_QUEUE_STATUSES = {"queued", "processing", "published", "failed", "cancelled"}
_RETRY_BACKOFF_BASE = 60  # seconds
_RETRY_BACKOFF_MAX = 600   # 10 minutes


def _now() -> datetime:
    return datetime.utcnow()


def _utc_to_local(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt


def enqueue_publish(
    video_id: int,
    platform: str,
    account: str,
    influencer_id: Optional[int] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    caption: Optional[str] = None,
    hashtags: Optional[list] = None,
    thumbnail_path: Optional[str] = None,
    scheduled_at: Optional[datetime] = None,
    max_retries: int = 3,
) -> dict:
    """Add a publishing job to the queue."""
    if not is_platform_supported(platform):
        raise ValueError(f"Unsupported platform: {platform}")

    idempotency_key = f"pub_{video_id}_{platform}_{int(_now().timestamp())}"

    with get_session() as session:
        existing = session.query(PublishingQueue).filter(
            PublishingQueue.video_id == video_id,
            PublishingQueue.platform == platform,
            PublishingQueue.status.in_(["queued", "processing"]),
        ).first()
        if existing:
            logger.warning("Duplicate publish job prevented: video %d platform %s", video_id, platform)
            return {"queued": False, "reason": "duplicate", "queue_id": existing.id}

        job = PublishingQueue(
            video_id=video_id,
            influencer_id=influencer_id,
            account=account,
            platform=platform,
            status="queued",
            title=title,
            description=description,
            caption=caption,
            hashtags=json.dumps(hashtags or []),
            thumbnail_path=thumbnail_path,
            scheduled_at=scheduled_at,
            max_retries=max_retries,
            idempotency_key=idempotency_key,
        )
        session.add(job)
        session.flush()
        job_id = job.id

    audit.record("publish_queued", actor="system", target=str(job_id),
                 details={"video_id": video_id, "platform": platform, "account": account})
    return {"queued": True, "queue_id": job_id, "idempotency_key": idempotency_key}


def list_queue(
    platform: Optional[str] = None,
    account: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> list:
    """List queue jobs with optional filters."""
    with get_session() as session:
        query = session.query(PublishingQueue).order_by(PublishingQueue.created_at.desc())
        if platform:
            query = query.filter(PublishingQueue.platform == platform)
        if account:
            query = query.filter(PublishingQueue.account == account)
        if status:
            query = query.filter(PublishingQueue.status == status)
        jobs = query.limit(limit).all()
        return [_serialize_job(j) for j in jobs]


def get_queue_job(queue_id: int) -> Optional[dict]:
    """Get a single queue job."""
    with get_session() as session:
        job = session.query(PublishingQueue).filter_by(id=queue_id).first()
        if not job:
            return None
        return _serialize_job(job)


def cancel_queue_job(queue_id: int) -> bool:
    """Cancel a queued or processing job."""
    with get_session() as session:
        job = session.query(PublishingQueue).filter_by(id=queue_id).first()
        if not job or job.status in {"published", "cancelled"}:
            return False
        job.status = "cancelled"
        job.error_message = "Cancelled by user"
        session.flush()
    audit.record("publish_cancelled", actor="dashboard", target=str(queue_id))
    return True


def retry_queue_job(queue_id: int) -> Optional[dict]:
    """Retry a failed or cancelled publishing job."""
    with get_session() as session:
        job = session.query(PublishingQueue).filter_by(id=queue_id).first()
        if not job or job.status not in {"failed", "cancelled"}:
            return None
        if job.retry_count >= job.max_retries:
            return {"error": "max_retries_exceeded", "retry_count": job.retry_count}
        job.status = "queued"
        job.error_message = None
        job.retry_count += 1
        session.flush()
        job_id = job.id
        retry_count = job.retry_count

    audit.record("publish_retry", actor="dashboard", target=str(queue_id),
                 details={"retry_count": retry_count})
    return {"queued": True, "queue_id": job_id}


def process_queue_job(queue_id: int) -> dict:
    """Execute a single queue job. Call from scheduler or background worker."""
    with get_session() as session:
        job = session.query(PublishingQueue).filter_by(id=queue_id).first()
        if not job:
            return {"error": "not_found"}
        if job.status != "queued":
            return {"error": f"invalid_status:{job.status}"}

        # Check rate limits
        if not _check_rate_limit(job.platform, job.account):
            return {"error": "rate_limited"}

        job.status = "processing"
        session.flush()
        video_id = job.video_id
        platform = job.platform
        account = job.account
        title = job.title
        description = job.description
        caption = job.caption
        hashtags = job.hashtags
        thumbnail_path = job.thumbnail_path
        scheduled_at = job.scheduled_at
        created_at = job.created_at

    video_path = None
    with get_session() as session:
        video = session.query(Video).filter_by(id=video_id).first()
        if video:
            video_path = video.final_path

    # Check if we have credentials
    credentials_available = _check_credentials(platform, account)

    if not credentials_available:
        # Manual export fallback
        export_path = _create_manual_export(
            queue_id=queue_id,
            video_id=video_id,
            platform=platform,
            account=account,
            title=title,
            description=description,
            caption=caption,
            hashtags=hashtags,
            scheduled_at=scheduled_at,
            created_at=created_at,
            video_path=video_path,
            thumbnail_path=thumbnail_path,
        )
        with get_session() as session:
            job = session.query(PublishingQueue).filter_by(id=queue_id).first()
            job.status = "failed"
            job.error_message = "Credentials unavailable — manual export created"
            job.export_path = export_path
            job.platform_response = json.dumps({"fallback": "manual_export", "path": export_path})
            session.flush()
        audit.record("publish_failed", actor="system", target=str(queue_id),
                     details={"reason": "no_credentials", "export_path": export_path})
        return {"status": "manual_export", "export_path": export_path}

    # Attempt publish
    try:
        result = platform_publishers.publish_to_platform(
            platform,
            video_path or "",
            title or "",
            account,
            description=description or caption,
            hashtags=json.loads(hashtags or "[]"),
            thumbnail_path=thumbnail_path,
        )
    except Exception as exc:
        result = platform_publishers.PublishResult(
            platform=platform,
            ok=False,
            error=str(exc),
        )

    with get_session() as session:
        job = session.query(PublishingQueue).filter_by(id=queue_id).first()
        if result.ok:
            job.status = "published"
            job.published_at = _now()
            job.error_message = None
            job.platform_response = json.dumps(result.to_dict())
        else:
            job.status = "failed"
            job.error_message = result.error or "Unknown publish error"
            job.platform_response = json.dumps(result.to_dict())
        session.flush()

    if result.ok:
        audit.record("publish_succeeded", actor="system", target=str(queue_id),
                     details={"platform": platform, "url": result.url})
        return {"status": "published", "url": result.url}
    else:
        audit.record("publish_failed", actor="system", target=str(queue_id),
                     details={"error": result.error})
        return {"status": "failed", "error": result.error}


def _check_rate_limit(platform: str, account: str) -> bool:
    """Check if we're within rate limits for this platform/account."""
    today = _now().date()
    with get_session() as session:
        count = session.query(PublishingQueue).filter(
            PublishingQueue.platform == platform,
            PublishingQueue.account == account,
            PublishingQueue.status == "published",
            PublishingQueue.published_at >= today,
        ).count()
    max_per_day = getattr(settings, f"max_posts_per_day_{platform}", getattr(settings, "max_posts_per_day", 10))
    return count < max_per_day


def _check_credentials(platform: str, account: str) -> bool:
    """Check if platform credentials are available."""
    if platform == "tiktok":
        path = settings.get_cookies_path(account)
        return Path(path).exists() if path else False
    elif platform == "youtube":
        path = settings.get_youtube_token_path(account)
        return Path(path).exists() if path else False
    elif platform == "instagram":
        return bool(getattr(settings, "instagram_webhook_url", ""))
    elif platform == "facebook":
        return bool(getattr(settings, "facebook_access_token", ""))
    return False


def _create_manual_export(
    queue_id: int,
    video_id: int,
    platform: str,
    account: str,
    title: Optional[str],
    description: Optional[str],
    caption: Optional[str],
    hashtags: str,
    scheduled_at: Optional[datetime],
    created_at: Optional[datetime],
    video_path: Optional[str],
    thumbnail_path: Optional[str],
) -> str:
    """Create a local export package for manual publishing."""
    export_dir = Path(settings.db_path).parent / "storage" / "exports" / str(queue_id)
    export_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "queue_id": queue_id,
        "video_id": video_id,
        "platform": platform,
        "account": account,
        "title": title,
        "description": description or caption,
        "caption": caption,
        "hashtags": json.loads(hashtags or "[]"),
        "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
        "created_at": created_at.isoformat() if created_at else None,
        "exported_at": _now().isoformat(),
        "reason": "credentials_unavailable",
    }

    if video_path and Path(video_path).exists():
        shutil.copy2(video_path, export_dir / "video.mp4")
        manifest["video_file"] = "video.mp4"

    if thumbnail_path and Path(thumbnail_path).exists():
        shutil.copy2(thumbnail_path, export_dir / "thumbnail.jpg")
        manifest["thumbnail_file"] = "thumbnail.jpg"

    manifest_path = export_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    zip_path = str(export_dir.parent / f"export_{queue_id}_{platform}.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in export_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(export_dir.parent))

    return zip_path


def process_due_jobs():
    """Process all queued publishing jobs. Called by scheduler."""
    jobs = list_queue(status="queued", limit=50)
    for job in jobs:
        scheduled_at = job.get("scheduled_at")
        if scheduled_at:
            try:
                sched = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
                if sched > _now():
                    continue
            except Exception:
                pass
        try:
            process_queue_job(job["id"])
        except Exception as exc:
            logger.error("Failed to process queue job %d: %s", job["id"], exc)


def _serialize_job(job: PublishingQueue) -> dict:
    return {
        "id": job.id,
        "video_id": job.video_id,
        "influencer_id": job.influencer_id,
        "account": job.account,
        "platform": job.platform,
        "status": job.status,
        "title": job.title,
        "description": job.description,
        "caption": job.caption,
        "hashtags": json.loads(job.hashtags or "[]"),
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "published_at": job.published_at.isoformat() if job.published_at else None,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "error_message": job.error_message,
        "export_path": job.export_path,
        "platform_response": json.loads(job.platform_response) if job.platform_response else None,
        "idempotency_key": job.idempotency_key,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }
