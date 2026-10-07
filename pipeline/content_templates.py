"""
Content templates for automated short-form video generation.

Templates define platform-specific parameters like duration, caption format,
hashtag strategy, CTA, and required media type.
"""
import logging
from typing import Optional
from core.db import get_session
from core.models import ContentTemplate

logger = logging.getLogger(__name__)

_BUILTIN_TEMPLATES = [
    {
        "name": "TikTok Short",
        "description": "Standard TikTok short-form video",
        "platform": "tiktok",
        "content_type": "video",
        "content_style": "entertaining",
        "recommended_duration": 30,
        "caption_format": "{title}\n\n{caption}\n\n{hashtags}",
        "hashtag_strategy": '["#fyp", "#viral", "#trending"]',
        "cta_text": "Follow for more!",
        "required_media": "video",
        "niche": None,
        "language": "en",
        "is_active": True,
    },
    {
        "name": "YouTube Short",
        "description": "YouTube Shorts vertical video",
        "platform": "youtube",
        "content_type": "video",
        "content_style": "educational",
        "recommended_duration": 45,
        "caption_format": "{title}\n\n{caption}\n\n{hashtags}",
        "hashtag_strategy": '["#shorts", "#youtubeshorts", "#viral"]',
        "cta_text": "Subscribe for more!",
        "required_media": "video",
        "niche": None,
        "language": "en",
        "is_active": True,
    },
    {
        "name": "Instagram Reel",
        "description": "Instagram Reel with engaging caption",
        "platform": "instagram",
        "content_type": "video",
        "content_style": "lifestyle",
        "recommended_duration": 30,
        "caption_format": "{caption}\n\n{hashtags}",
        "hashtag_strategy": '["#reels", "#instagram", "#viral"]',
        "cta_text": "Double tap if you agree!",
        "required_media": "video",
        "niche": None,
        "language": "en",
        "is_active": True,
    },
    {
        "name": "Promotional Post",
        "description": "Product or service promotion",
        "platform": "tiktok",
        "content_type": "video",
        "content_style": "promotional",
        "recommended_duration": 30,
        "caption_format": "{title}\n\n{caption}\n\n{cta}\n\n{hashtags}",
        "hashtag_strategy": '["#promo", "#deal", "#fyp"]',
        "cta_text": "Link in bio!",
        "required_media": "video",
        "niche": None,
        "language": "en",
        "is_active": True,
    },
    {
        "name": "Educational Post",
        "description": "How-to or educational content",
        "platform": "youtube",
        "content_type": "video",
        "content_style": "educational",
        "recommended_duration": 45,
        "caption_format": "{title}\n\n{caption}\n\n{hashtags}",
        "hashtag_strategy": '["#learn", "#tutorial", "#shorts"]',
        "cta_text": "Save this for later!",
        "required_media": "video",
        "niche": "education",
        "language": "en",
        "is_active": True,
    },
    {
        "name": "Story-style Post",
        "description": "Personal story or anecdote",
        "platform": "instagram",
        "content_type": "story",
        "content_style": "story",
        "recommended_duration": 15,
        "caption_format": "{caption}\n\n{hashtags}",
        "hashtag_strategy": '["#storytime", "#reels", "#viral"]',
        "cta_text": "Comment your thoughts!",
        "required_media": "video",
        "niche": None,
        "language": "en",
        "is_active": True,
    },
]


def seed_builtin_templates():
    """Insert built-in templates if they don't already exist."""
    with get_session() as session:
        existing_names = {r[0] for r in session.query(ContentTemplate.name).all()}
        for template_data in _BUILTIN_TEMPLATES:
            if template_data["name"] not in existing_names:
                tpl = ContentTemplate(**template_data)
                session.add(tpl)
        session.flush()


def list_templates(platform: Optional[str] = None, content_style: Optional[str] = None, niche: Optional[str] = None) -> list:
    """List active templates, optionally filtered."""
    with get_session() as session:
        query = session.query(ContentTemplate).filter(ContentTemplate.is_active.is_(True))
        if platform:
            query = query.filter(ContentTemplate.platform == platform)
        if content_style:
            query = query.filter(ContentTemplate.content_style == content_style)
        if niche:
            query = query.filter(ContentTemplate.niche == niche)
        results = query.order_by(ContentTemplate.name).all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "platform": t.platform,
                "content_type": t.content_type,
                "content_style": t.content_style,
                "recommended_duration": t.recommended_duration,
                "caption_format": t.caption_format,
                "hashtag_strategy": t.hashtag_strategy,
                "cta_text": t.cta_text,
                "required_media": t.required_media,
                "niche": t.niche,
                "language": t.language,
                "is_active": t.is_active,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in results
        ]


def get_template(template_id: int) -> Optional[dict]:
    """Get a single template by ID."""
    with get_session() as session:
        tpl = session.query(ContentTemplate).filter_by(id=template_id).first()
        if not tpl:
            return None
        return {
            "id": tpl.id,
            "name": tpl.name,
            "description": tpl.description,
            "platform": tpl.platform,
            "content_type": tpl.content_type,
            "content_style": t.content_style,
            "recommended_duration": t.recommended_duration,
            "caption_format": tpl.caption_format,
            "hashtag_strategy": tpl.hashtag_strategy,
            "cta_text": tpl.cta_text,
            "required_media": tpl.required_media,
            "niche": tpl.niche,
            "language": tpl.language,
            "is_active": tpl.is_active,
        }


def create_template(payload: dict) -> dict:
    """Create a new content template."""
    with get_session() as session:
        tpl = ContentTemplate(
            name=payload.get("name", "Untitled Template"),
            description=payload.get("description"),
            platform=payload.get("platform", "tiktok"),
            content_type=payload.get("content_type", "video"),
            content_style=payload.get("content_style"),
            recommended_duration=payload.get("recommended_duration"),
            caption_format=payload.get("caption_format", "{caption}\n\n{hashtags}"),
            hashtag_strategy=payload.get("hashtag_strategy", "[]"),
            cta_text=payload.get("cta_text"),
            required_media=payload.get("required_media", "video"),
            niche=payload.get("niche"),
            language=payload.get("language", "en"),
            is_active=bool(payload.get("is_active", True)),
        )
        session.add(tpl)
        session.flush()
        return {"id": tpl.id, "name": tpl.name}


def update_template(template_id: int, payload: dict) -> Optional[dict]:
    """Update an existing template."""
    with get_session() as session:
        tpl = session.query(ContentTemplate).filter_by(id=template_id).first()
        if not tpl:
            return None
        for field in ("name", "description", "platform", "content_type", "content_style",
                      "recommended_duration", "caption_format", "hashtag_strategy",
                      "cta_text", "required_media", "niche", "language", "is_active"):
            if field in payload:
                setattr(tpl, field, payload[field])
        session.flush()
        return {"updated": True, "id": tpl.id}


def delete_template(template_id: int) -> bool:
    """Soft-delete a template by marking it inactive."""
    with get_session() as session:
        tpl = session.query(ContentTemplate).filter_by(id=template_id).first()
        if not tpl:
            return False
        tpl.is_active = False
        session.flush()
        return True
