import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Body
from sqlalchemy import func, case

from core.db import get_session
from core.models import Video, ApiKey, EmailThread, PipelineRun, AuditLog, VideoMetrics, Influencer, VoicePreset, SocialConnection, ContentCalendarEntry, ImageGenerationHistory, AnalyticsSnapshot
from core import audit
from config.settings import (
    settings,
    get_platform_info,
    load_platform_config,
    load_platform_registry,
    save_platform_config,
    toggle_platform,
    load_blackout_dates,
    save_blackout_dates,
    list_account_ids,
    list_platform_ids,
    platform_display_name,
    resolve_project_path,
    ACCOUNTS,
    BASE_DIR,
)

router = APIRouter()


def _page_size(limit: int) -> int:
    return max(1, min(settings.dashboard_max_page_size, limit))


def _json_map(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _platform_counts_from_rows(rows) -> dict[str, int]:
    counts = {platform: 0 for platform in list_platform_ids()}
    for raw_results, tiktok_published, youtube_published in rows:
        results = _json_map(raw_results)
        for platform, result in results.items():
            if isinstance(result, dict) and result.get("ok"):
                counts[platform] = counts.get(platform, 0) + 1
        if not results:
            if tiktok_published:
                counts["tiktok"] = counts.get("tiktok", 0) + 1
            if youtube_published:
                counts["youtube"] = counts.get("youtube", 0) + 1
    return counts


@router.get("/videos")
async def get_videos(
    limit: int = Query(default=None, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    account: Optional[str] = None,
    status: Optional[str] = None,
):
    """Get recent videos with status and details. Paginated + filterable."""
    limit = _page_size(limit or settings.dashboard_default_page_size)
    with get_session() as session:
        query = session.query(Video).order_by(Video.created_at.desc())
        if account:
            query = query.filter(Video.account == account)
        if status:
            query = query.filter(Video.status == status)
        total = query.count()
        videos = query.offset(offset).limit(limit).all()

        items = [
            {
                "id": v.id,
                "account": v.account,
                "status": v.status,
                "title": v.title,
                "quality_score": v.quality_score,
                "drive_url": v.drive_url,
                "tiktok_url": v.tiktok_url,
                "youtube_url": v.youtube_url,
                "tiktok_published": v.tiktok_published,
                "youtube_published": v.youtube_published,
                "platforms_enabled": _json_map(v.platforms_enabled_json),
                "platform_results": _json_map(v.platform_results_json),
                "platform_errors": _json_map(v.platform_errors_json),
                "retry_count": v.retry_count,
                "error_message": v.error_message,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "published_at": v.published_at.isoformat() if v.published_at else None,
            }
            for v in videos
        ]

    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/videos/{video_id}")
async def get_video(video_id: int):
    with get_session() as session:
        v = session.query(Video).filter_by(id=video_id).first()
        if not v:
            raise HTTPException(404, "Video not found")
        return {
            "id": v.id,
            "account": v.account,
            "status": v.status,
            "title": v.title,
            "hook": v.hook,
            "script_text": v.script_text,
            "quality_score": v.quality_score,
            "quality_notes": v.quality_notes,
            "drive_url": v.drive_url,
            "tiktok_url": v.tiktok_url,
            "youtube_url": v.youtube_url,
            "platforms_enabled": _json_map(v.platforms_enabled_json),
            "platform_results": _json_map(v.platform_results_json),
            "platform_errors": _json_map(v.platform_errors_json),
            "retry_count": v.retry_count,
            "error_message": v.error_message,
            "estimated_duration": v.estimated_duration,
            "final_path": v.final_path,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "published_at": v.published_at.isoformat() if v.published_at else None,
        }


@router.delete("/videos/{video_id}")
async def delete_video(video_id: int, purge_files: bool = False):
    """Delete a video record (and optionally its on-disk artefacts)."""
    with get_session() as session:
        v = session.query(Video).filter_by(id=video_id).first()
        if not v:
            raise HTTPException(404, "Video not found")
        files_to_purge = [v.final_path, v.narration_path, v.subtitle_path]
        session.delete(v)
        # cascade-ish cleanup
        session.query(PipelineRun).filter_by(video_id=video_id).delete()
        session.query(VideoMetrics).filter_by(video_id=video_id).delete()

    if purge_files:
        for p in files_to_purge:
            if not p:
                continue
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass

    audit.record("video_deleted", actor="dashboard", target=str(video_id),
                 details={"purge_files": purge_files})
    return {"deleted": True, "video_id": video_id}


@router.post("/videos/{video_id}/retry")
async def retry_video(video_id: int):
    """Re-queue a failed/rejected video by spawning a new production for its account."""
    with get_session() as session:
        v = session.query(Video).filter_by(id=video_id).first()
        if not v:
            raise HTTPException(404, "Video not found")
        account = v.account

    audit.record("video_retry", actor="dashboard", target=str(video_id),
                 details={"account": account})

    import asyncio
    from pipeline.orchestrator import produce_video
    asyncio.create_task(produce_video(account))
    return {"queued": True, "account": account}


@router.post("/publish/{account}")
async def manual_publish(account: str):
    """Force a manual production for an account."""
    if account not in list_account_ids():
        raise HTTPException(404, f"Unknown account: {account}")

    audit.record("manual_publish", actor="dashboard", target=account)

    import asyncio
    from pipeline.orchestrator import produce_video
    asyncio.create_task(produce_video(account))
    return {"queued": True, "account": account}


@router.get("/stats")
async def get_stats():
    """Get aggregate statistics."""
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    with get_session() as session:
        total = session.query(Video).count()
        today_count = session.query(Video).filter(Video.created_at >= today).count()
        week_count = session.query(Video).filter(Video.created_at >= week_ago).count()
        month_count = session.query(Video).filter(Video.created_at >= month_ago).count()

        published = session.query(Video).filter(Video.status == "published").count()
        failed = session.query(Video).filter(Video.status == "failed").count()
        rejected = session.query(Video).filter(Video.status == "rejected").count()

        platform_rows = session.query(
            Video.platform_results_json,
            Video.tiktok_published,
            Video.youtube_published,
        ).all()
        platform_published = _platform_counts_from_rows(platform_rows)
        tiktok_published = platform_published.get("tiktok", 0)
        youtube_published = platform_published.get("youtube", 0)

        avg_score = session.query(func.avg(Video.quality_score)).filter(
            Video.quality_score != None  # noqa: E711
        ).scalar()

        # Per account stats — DYNAMIC across all registered accounts (built-in + custom)
        account_stats = {}
        for account in list_account_ids():
            account_published = session.query(Video).filter(
                Video.account == account, Video.status == "published",
            ).count()
            account_today = session.query(Video).filter(
                Video.account == account, Video.created_at >= today,
            ).count()
            account_platform_rows = session.query(
                Video.platform_results_json,
                Video.tiktok_published,
                Video.youtube_published,
            ).filter(Video.account == account).all()
            account_platforms = _platform_counts_from_rows(account_platform_rows)
            account_stats[account] = {
                "display_name": ACCOUNTS.get(account, {}).get("display_name", account),
                "published_total": account_published,
                "today": account_today,
                "tiktok": account_platforms.get("tiktok", 0),
                "youtube": account_platforms.get("youtube", 0),
                "platforms": account_platforms,
            }

        platform_config = load_platform_config()

        return {
            "total_videos": total,
            "published": published,
            "failed": failed,
            "rejected": rejected,
            "tiktok_published": tiktok_published,
            "youtube_published": youtube_published,
            "platform_published": platform_published,
            "today": today_count,
            "this_week": week_count,
            "this_month": month_count,
            "avg_quality_score": round(avg_score, 1) if avg_score else 0,
            "failure_rate": round(failed / total * 100, 1) if total > 0 else 0,
            "accounts": account_stats,
            "platforms": platform_config,
        }


@router.get("/keys")
async def get_keys():
    """Get API key pool health status."""
    with get_session() as session:
        keys = session.query(ApiKey).all()
        now = datetime.utcnow()

        return [
            {
                "id": k.id,
                "provider": k.provider,
                "label": k.label,
                "enabled": k.enabled,
                "usage_count": k.usage_count,
                "usage_chars": k.usage_chars,
                "failure_count": k.failure_count,
                "in_cooldown": k.cooldown_until is not None and k.cooldown_until > now,
                "cooldown_until": k.cooldown_until.isoformat() if k.cooldown_until else None,
                "last_used": k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in keys
        ]


@router.get("/emails")
async def get_emails(
    limit: int = Query(default=None, ge=1, le=500),
    account: Optional[str] = None,
):
    """Get recent email classifications and responses."""
    limit = _page_size(limit or settings.dashboard_default_page_size)
    with get_session() as session:
        query = session.query(EmailThread).order_by(EmailThread.created_at.desc())
        if account:
            query = query.filter(EmailThread.account == account)
        emails = query.limit(limit).all()

        return [
            {
                "id": e.id,
                "account": e.account,
                "sender": e.sender,
                "subject": e.subject,
                "category": e.category,
                "auto_responded": e.auto_responded,
                "needs_attention": e.needs_attention,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in emails
        ]


@router.get("/pipeline/{video_id}")
async def get_pipeline_details(video_id: int):
    """Get pipeline execution details for a specific video."""
    with get_session() as session:
        runs = (
            session.query(PipelineRun)
            .filter_by(video_id=video_id)
            .order_by(PipelineRun.started_at)
            .all()
        )

        return [
            {
                "step": r.step,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "error": r.error_message,
                "started_at": r.started_at.isoformat() if r.started_at else None,
            }
            for r in runs
        ]


@router.get("/platforms")
async def get_platforms():
    """Get platform toggle configuration."""
    return load_platform_config()


@router.get("/platform-registry")
async def get_platform_registry():
    """Get configured platform metadata without leaking webhook URLs."""
    registry = load_platform_registry()
    safe = {}
    for platform, info in registry.items():
        safe[platform] = {
            key: value
            for key, value in info.items()
            if key not in {"webhook_url"}
        }
        safe[platform]["display_name"] = platform_display_name(platform)
    return safe


@router.post("/platforms/{account}/{platform}")
async def set_platform(account: str, platform: str, enabled: bool = Body(..., embed=True)):
    """Enable or disable a platform for an account."""
    if account not in list_account_ids():
        raise HTTPException(404, f"Unknown account: {account}")
    if not get_platform_info(platform):
        raise HTTPException(400, f"Platform must be one of: {', '.join(list_platform_ids())}")
    try:
        cfg = toggle_platform(account, platform, bool(enabled))
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.record("platform_toggle", actor="dashboard",
                 target=f"{account}:{platform}", details={"enabled": bool(enabled)})
    return cfg


@router.get("/calendar")
async def get_calendar(days: int = Query(7, ge=1, le=30)):
    """Return the upcoming scheduled video productions for the next N days."""
    out = []
    for acc, cfg in ACCOUNTS.items():
        for w in cfg.get("schedule_windows", []):
            out.append({
                "account": acc,
                "display_name": cfg.get("display_name", acc),
                "hour": w["hour"],
                "minute": w["minute"],
                "timezone": settings.timezone,
            })
    out.sort(key=lambda x: (x["hour"], x["minute"], x["account"]))
    return {
        "windows": out,
        "blackout_dates": load_blackout_dates(),
        "skip_weekends": settings.schedule_skip_weekends,
    }


@router.get("/blackout")
async def get_blackout():
    return {"dates": load_blackout_dates()}


@router.post("/blackout")
async def add_blackout(date: str = Body(..., embed=True)):
    """Add a YYYY-MM-DD date on which production should NOT run."""
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    dates = load_blackout_dates()
    if date not in dates:
        dates.append(date)
        save_blackout_dates(dates)
    audit.record("blackout_add", actor="dashboard", target=date)
    return {"dates": load_blackout_dates()}


@router.delete("/blackout/{date}")
async def remove_blackout(date: str):
    dates = [d for d in load_blackout_dates() if d != date]
    save_blackout_dates(dates)
    audit.record("blackout_remove", actor="dashboard", target=date)
    return {"dates": dates}


@router.get("/accounts")
async def get_accounts():
    """Return the full live ACCOUNTS config (read-only)."""
    out = {}
    for acc, cfg in ACCOUNTS.items():
        # Avoid leaking absolute paths to tokens; report only their existence.
        safe = {k: v for k, v in cfg.items()
                if k not in {"youtube_token_path", "tiktok_cookies_path", "gmail_token_path"}}
        safe["has_youtube_token"] = bool(cfg.get("youtube_token_path"))
        safe["has_tiktok_cookies"] = bool(cfg.get("tiktok_cookies_path"))
        out[acc] = safe
    return out


@router.get("/influencers")
async def get_influencers(status: Optional[str] = None):
    """List all virtual influencers."""
    with get_session() as session:
        query = session.query(Influencer).order_by(Influencer.created_at.desc())
        if status:
            query = query.filter(Influencer.status == status)
        items = []
        for inf in query.all():
            items.append({
                "id": inf.id,
                "name": inf.name,
                "display_name": inf.display_name,
                "slug": inf.slug,
                "niche": inf.niche,
                "bio": inf.bio,
                "personality": inf.personality,
                "target_audience": inf.target_audience,
                "visual_description": inf.visual_description,
                "profile_picture_path": inf.profile_picture_path,
                "reference_images": json.loads(inf.reference_images_json) if inf.reference_images_json else [],
                "writing_style": inf.writing_style,
                "preferred_language": inf.preferred_language,
                "status": inf.status,
                "created_at": inf.created_at.isoformat() if inf.created_at else None,
                "updated_at": inf.updated_at.isoformat() if inf.updated_at else None,
            })
        return items


@router.get("/influencers/{influencer_id}")
async def get_influencer(influencer_id: int):
    with get_session() as session:
        inf = session.query(Influencer).filter_by(id=influencer_id).first()
        if not inf:
            raise HTTPException(404, "Influencer not found")
        return {
            "id": inf.id,
            "name": inf.name,
            "display_name": inf.display_name,
            "slug": inf.slug,
            "niche": inf.niche,
            "bio": inf.bio,
            "personality": inf.personality,
            "target_audience": inf.target_audience,
            "visual_description": inf.visual_description,
            "profile_picture_path": inf.profile_picture_path,
            "reference_images": json.loads(inf.reference_images_json) if inf.reference_images_json else [],
            "writing_style": inf.writing_style,
            "preferred_language": inf.preferred_language,
            "status": inf.status,
            "created_at": inf.created_at.isoformat() if inf.created_at else None,
            "updated_at": inf.updated_at.isoformat() if inf.updated_at else None,
        }


@router.post("/influencers")
async def create_influencer(payload: dict = Body(...)):
    required = ["name", "slug"]
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise HTTPException(400, f"Missing fields: {', '.join(missing)}")

    with get_session() as session:
        existing = session.query(Influencer).filter(
            (Influencer.name == payload["name"]) | (Influencer.slug == payload["slug"])
        ).first()
        if existing:
            raise HTTPException(400, "Influencer with this name or slug already exists")

        inf = Influencer(
            name=payload["name"],
            display_name=payload.get("display_name") or payload["name"],
            slug=payload["slug"],
            niche=payload.get("niche"),
            bio=payload.get("bio"),
            personality=payload.get("personality"),
            target_audience=payload.get("target_audience"),
            visual_description=payload.get("visual_description"),
            profile_picture_path=payload.get("profile_picture_path"),
            reference_images_json=json.dumps(payload.get("reference_images", [])),
            writing_style=payload.get("writing_style"),
            preferred_language=payload.get("preferred_language", "en"),
            status=payload.get("status", "active"),
        )
        session.add(inf)
        session.flush()
        result = {
            "id": inf.id,
            "name": inf.name,
            "display_name": inf.display_name,
            "slug": inf.slug,
        }
        audit.record("influencer_created", actor="dashboard", target=str(inf.id), details=result)
        return result


@router.put("/influencers/{influencer_id}")
async def update_influencer(influencer_id: int, payload: dict = Body(...)):
    with get_session() as session:
        inf = session.query(Influencer).filter_by(id=influencer_id).first()
        if not inf:
            raise HTTPException(404, "Influencer not found")

        for field in ("display_name", "niche", "bio", "personality", "target_audience",
                      "visual_description", "profile_picture_path", "writing_style",
                      "preferred_language", "status"):
            if field in payload:
                setattr(inf, field, payload[field])

        if "reference_images" in payload:
            inf.reference_images_json = json.dumps(payload["reference_images"])

        session.flush()
        audit.record("influencer_updated", actor="dashboard", target=str(inf.id))
        return {"updated": True, "id": inf.id}


@router.delete("/influencers/{influencer_id}")
async def delete_influencer(influencer_id: int):
    with get_session() as session:
        inf = session.query(Influencer).filter_by(id=influencer_id).first()
        if not inf:
            raise HTTPException(404, "Influencer not found")
        session.delete(inf)
        audit.record("influencer_deleted", actor="dashboard", target=str(influencer_id))
        return {"deleted": True, "id": influencer_id}


@router.get("/influencers/{influencer_id}/voice-presets")
async def get_voice_presets(influencer_id: int):
    with get_session() as session:
        presets = session.query(VoicePreset).filter_by(influencer_id=influencer_id).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "tts_backend": p.tts_backend,
                "voice_id": p.voice_id,
                "language": p.language,
                "speed": p.speed,
                "pitch": p.pitch,
                "is_default": p.is_default,
            }
            for p in presets
        ]


@router.post("/influencers/{influencer_id}/voice-presets")
async def create_voice_preset(influencer_id: int, payload: dict = Body(...)):
    with get_session() as session:
        inf = session.query(Influencer).filter_by(id=influencer_id).first()
        if not inf:
            raise HTTPException(404, "Influencer not found")

        preset = VoicePreset(
            influencer_id=influencer_id,
            name=payload.get("name", "Default"),
            tts_backend=payload.get("tts_backend", "edge_tts"),
            voice_id=payload.get("voice_id", ""),
            language=payload.get("language", "en"),
            speed=float(payload.get("speed", 1.0)),
            pitch=float(payload.get("pitch", 1.0)),
            is_default=bool(payload.get("is_default", False)),
        )
        session.add(preset)
        session.flush()
        return {"id": preset.id, "name": preset.name}


@router.get("/influencers/{influencer_id}/social-connections")
async def get_social_connections(influencer_id: int):
    with get_session() as session:
        connections = session.query(SocialConnection).filter_by(influencer_id=influencer_id).all()
        return [
            {
                "id": c.id,
                "platform": c.platform,
                "account_name": c.account_name,
                "account_id": c.account_id,
                "status": c.status,
                "last_error": c.last_error,
                "connected_at": c.connected_at.isoformat() if c.connected_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in connections
        ]


@router.post("/influencers/{influencer_id}/social-connections")
async def create_social_connection(influencer_id: int, payload: dict = Body(...)):
    with get_session() as session:
        inf = session.query(Influencer).filter_by(id=influencer_id).first()
        if not inf:
            raise HTTPException(404, "Influencer not found")

        conn = SocialConnection(
            influencer_id=influencer_id,
            platform=payload.get("platform"),
            account_name=payload.get("account_name"),
            account_id=payload.get("account_id"),
            access_token=payload.get("access_token"),
            refresh_token=payload.get("refresh_token"),
            credentials_json=json.dumps(payload.get("credentials", {})),
            status=payload.get("status", "connected"),
        )
        session.add(conn)
        session.flush()
        return {"id": conn.id, "platform": conn.platform}


@router.get("/influencers/{influencer_id}/calendar")
async def get_influencer_calendar(influencer_id: int, status: Optional[str] = None):
    with get_session() as session:
        query = session.query(ContentCalendarEntry).filter_by(influencer_id=influencer_id).order_by(ContentCalendarEntry.scheduled_at.desc())
        if status:
            query = query.filter(ContentCalendarEntry.status == status)
        return [
            {
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "content_type": c.content_type,
                "status": c.status,
                "scheduled_at": c.scheduled_at.isoformat() if c.scheduled_at else None,
                "published_at": c.published_at.isoformat() if c.published_at else None,
                "video_id": c.video_id,
                "platforms": json.loads(c.platforms_json) if c.platforms_json else [],
                "tags": c.tags,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in query.all()
        ]


@router.post("/influencers/{influencer_id}/calendar")
async def create_calendar_entry(influencer_id: int, payload: dict = Body(...)):
    with get_session() as session:
        inf = session.query(Influencer).filter_by(id=influencer_id).first()
        if not inf:
            raise HTTPException(404, "Influencer not found")

        entry = ContentCalendarEntry(
            influencer_id=influencer_id,
            title=payload.get("title"),
            description=payload.get("description"),
            content_type=payload.get("content_type", "video"),
            status=payload.get("status", "draft"),
            scheduled_at=datetime.fromisoformat(payload["scheduled_at"]) if payload.get("scheduled_at") else None,
            video_id=payload.get("video_id"),
            platforms_json=json.dumps(payload.get("platforms", [])),
            tags=payload.get("tags"),
        )
        session.add(entry)
        session.flush()
        return {"id": entry.id, "title": entry.title, "status": entry.status}


@router.get("/content-calendar")
async def get_content_calendar(influencer_id: Optional[int] = Query(None), status: Optional[str] = Query(None)):
    """List calendar entries, optionally filtered by influencer and status."""
    with get_session() as session:
        query = session.query(ContentCalendarEntry).order_by(ContentCalendarEntry.scheduled_at.desc())
        if influencer_id is not None:
            query = query.filter(ContentCalendarEntry.influencer_id == influencer_id)
        if status:
            query = query.filter(ContentCalendarEntry.status == status)
        return [
            {
                "id": c.id,
                "influencer_id": c.influencer_id,
                "title": c.title,
                "description": c.description,
                "content_type": c.content_type,
                "status": c.status,
                "scheduled_at": c.scheduled_at.isoformat() if c.scheduled_at else None,
                "published_at": c.published_at.isoformat() if c.published_at else None,
                "video_id": c.video_id,
                "platforms": json.loads(c.platforms_json) if c.platforms_json else [],
                "tags": c.tags,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in query.all()
        ]


@router.get("/prompts/{account}")
async def get_prompt(account: str):
    """Read a prompt YAML file. Falls back to config/prompts/{account}.yaml."""
    cfg = ACCOUNTS.get(account, {})
    path = Path(resolve_project_path(cfg.get("prompt_file"))) if cfg.get("prompt_file") else BASE_DIR / "config" / "prompts" / f"{account}.yaml"
    if not path.exists():
        raise HTTPException(404, f"Prompt file not found: {path}")
    return {"path": str(path), "content": path.read_text(encoding="utf-8")}


@router.put("/prompts/{account}")
async def put_prompt(account: str, content: str = Body(..., embed=True)):
    """Replace a prompt YAML file. Validates YAML before writing."""
    cfg = ACCOUNTS.get(account, {})
    path = Path(resolve_project_path(cfg.get("prompt_file"))) if cfg.get("prompt_file") else BASE_DIR / "config" / "prompts" / f"{account}.yaml"
    try:
        import yaml
        yaml.safe_load(content)
    except Exception as e:
        raise HTTPException(400, f"Invalid YAML: {e}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    audit.record("prompt_updated", actor="dashboard", target=account, details={"bytes": len(content)})
    return {"saved": True, "path": str(path)}


@router.get("/audit")
async def get_audit(limit: int = Query(100, ge=1, le=1000)):
    with get_session() as session:
        rows = session.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "actor": r.actor,
                "action": r.action,
                "target": r.target,
                "details": r.details,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


@router.post("/backup")
async def trigger_backup():
    """Trigger an on-demand SQLite backup."""
    from core.backup import backup_database
    path = backup_database()
    if not path:
        raise HTTPException(500, "Backup failed")
    audit.record("backup", actor="dashboard", target=str(path))
    return {"path": str(path), "size_bytes": Path(path).stat().st_size}


@router.get("/analytics/timeseries")
async def analytics_timeseries(days: int = Query(30, ge=1, le=180)):
    """Return per-day published counts for the last N days, grouped by account."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    with get_session() as session:
        rows = (
            session.query(
                func.date(Video.created_at).label("day"),
                Video.account,
                func.count(Video.id).label("total"),
                func.sum(
                    case((Video.status == "published", 1), else_=0)
                ).label("published"),
            )
            .filter(Video.created_at >= cutoff)
            .group_by("day", Video.account)
            .all()
        )

    series: dict = {}
    for r in rows:
        day = str(r.day)
        series.setdefault(day, {})[r.account] = {
            "total": int(r.total or 0),
            "published": int(r.published or 0),
        }
    return {"days": days, "series": series, "accounts": list_account_ids()}


@router.get("/llm/providers")
async def llm_providers_status():
    """Return the list of LLM providers and which ones are currently usable."""
    from core import llm_providers as _llm
    reg = _llm._registry()
    chain_names = [n.strip() for n in (settings.script_provider_chain or "").split(",") if n.strip()]
    out = []
    for name, prov in reg.items():
        out.append({
            "name": name,
            "available": prov.is_available(),
            "models": prov.models()[:8],
            "in_chain": name in chain_names,
            "chain_position": chain_names.index(name) + 1 if name in chain_names else None,
        })
    out.sort(key=lambda x: (x["chain_position"] is None, x["chain_position"] or 99, x["name"]))
    return {
        "chain": chain_names,
        "providers": out,
    }


@router.get("/settings")
async def safe_settings():
    """Return a *safe* (non-secret) view of settings. Useful for the UI."""
    keep = {
        "version", "language", "timezone",
        "quality_threshold", "max_retries_per_video", "pipeline_timeout_seconds",
        "min_video_seconds", "max_video_seconds", "image_display_seconds",
        "video_width", "video_height", "video_crf", "video_preset",
        "schedule_hour_start", "schedule_hour_end", "schedule_skip_weekends",
        "email_poll_interval_minutes", "enable_drive_upload",
        "music_volume_percent", "narration_volume_boost",
        "whisper_model", "whisper_device",
        "dashboard_auto_refresh_seconds",
        "platform_webhook_timeout_seconds",
        "publish_inter_platform_delay",
    }
    return {k: getattr(settings, k) for k in keep if hasattr(settings, k)}


@router.get("/image-generation/backends")
async def list_image_backends():
    """Check health of configured local image generation backends."""
    backends = ["comfyui", "automatic1111"]
    results = []
    for backend in backends:
        results.append(pipeline.image_gen.check_backend_health(backend))
    return {"backends": results}


@router.post("/image-generation/generate")
async def generate_image(payload: dict = Body(...)):
    """Generate an image using a local backend."""
    backend = payload.get("backend", "comfyui")
    prompt = payload.get("prompt", "")
    negative_prompt = payload.get("negative_prompt", "")
    width = int(payload.get("width", 512))
    height = int(payload.get("height", 768))
    steps = int(payload.get("steps", 30))
    cfg_scale = float(payload.get("cfg_scale", 7.0))
    seed = int(payload.get("seed", -1))
    model = payload.get("model", "")
    influencer_id = payload.get("influencer_id")

    if not prompt:
        raise HTTPException(400, "Prompt is required")

    try:
        path = pipeline.image_gen.generate_image(
            backend=backend,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            model=model,
            influencer_id=influencer_id,
        )
    except Exception as exc:
        audit.record("image_generation_failed", actor="dashboard", target=backend, details={"error": str(exc)[:200]})
        raise HTTPException(500, str(exc))

    with get_session() as session:
        record = ImageGenerationHistory(
            influencer_id=influencer_id,
            prompt=prompt,
            negative_prompt=negative_prompt,
            image_path=path,
            backend=backend,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed if seed != -1 else None,
            is_accepted=True,
        )
        session.add(record)
        session.flush()
        audit.record("image_generated", actor="dashboard", target=str(record.id), details={"backend": backend, "path": path})

    return {"path": path, "id": record.id}


@router.get("/image-generation/history")
async def get_image_history(influencer_id: Optional[int] = Query(None)):
    """Return recent image generation history."""
    with get_session() as session:
        query = session.query(ImageGenerationHistory).order_by(ImageGenerationHistory.created_at.desc()).limit(50)
        if influencer_id is not None:
            query = query.filter(ImageGenerationHistory.influencer_id == influencer_id)
        return [
            {
                "id": r.id,
                "influencer_id": r.influencer_id,
                "prompt": r.prompt,
                "negative_prompt": r.negative_prompt,
                "image_path": r.image_path,
                "backend": r.backend,
                "width": r.width,
                "height": r.height,
                "steps": r.steps,
                "cfg_scale": r.cfg_scale,
                "seed": r.seed,
                "is_reference": r.is_reference,
                "is_accepted": r.is_accepted,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in query.all()
        ]
