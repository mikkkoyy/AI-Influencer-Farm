"""
Comprehensive tests for the automated content pipeline and publishing queue.

Tests:
- Content template CRUD
- Publishing queue enqueue/dequeue/process/retry/cancel
- Manual export fallback
- Rate limiting
- Idempotency
- Content pipeline API endpoints
- Approval workflow
- Automation settings
- Analytics summary
- Scheduler integration

All tests must pass without requiring actual platform credentials or GPU.
"""
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.app import app
from core.db import init_db, get_session
from core.models import Video, ContentCalendarEntry, Influencer, ContentTemplate, PublishingQueue, AnalyticsSnapshot
from config.settings import settings
from pipeline import content_templates, publishing_queue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(tmp_path):
    db_path = str(tmp_path / "viralstack.db")
    settings.db_path = db_path
    from core import db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    new_engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    db_module.engine = new_engine
    db_module.SessionLocal = sessionmaker(bind=new_engine, autocommit=False, autoflush=False)
    init_db()
    return TestClient(app)


def _setup_db(tmp_path):
    db_path = str(tmp_path / "viralstack.db")
    settings.db_path = db_path
    from core import db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    new_engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    db_module.engine = new_engine
    db_module.SessionLocal = sessionmaker(bind=new_engine, autocommit=False, autoflush=False)
    init_db()
    return db_path


def _make_influencer(session, name="Test Influencer", slug="test-inf"):
    inf = Influencer(name=name, slug=slug, niche="technology")
    session.add(inf)
    session.flush()
    return inf


def _make_video(session, account="terror", status="reviewing", influencer_id=None):
    v = Video(account=account, status=status, title="Test Video", influencer_id=influencer_id)
    session.add(v)
    session.flush()
    return v


# ===========================================================================
# Content Template Tests
# ===========================================================================

class TestContentTemplates:
    def test_seed_builtin_templates(self, tmp_path):
        _setup_db(tmp_path)
        content_templates.seed_builtin_templates()
        templates = content_templates.list_templates()
        assert len(templates) >= 6
        platforms = {t["platform"] for t in templates}
        assert "tiktok" in platforms
        assert "youtube" in platforms
        assert "instagram" in platforms

    def test_list_templates_filter_by_platform(self, tmp_path):
        _setup_db(tmp_path)
        content_templates.seed_builtin_templates()
        tiktok_templates = content_templates.list_templates(platform="tiktok")
        for t in tiktok_templates:
            assert t["platform"] == "tiktok"

    def test_create_custom_template(self, tmp_path):
        _setup_db(tmp_path)
        content_templates.seed_builtin_templates()
        result = content_templates.create_template({
            "name": "Custom Template",
            "platform": "facebook",
            "content_style": "promotional",
            "recommended_duration": 60,
        })
        assert "id" in result
        assert result["name"] == "Custom Template"

    def test_update_template(self, tmp_path):
        _setup_db(tmp_path)
        content_templates.seed_builtin_templates()
        templates = content_templates.list_templates()
        tpl = templates[0]
        result = content_templates.update_template(tpl["id"], {"name": "Updated Name"})
        assert result["updated"] is True

    def test_delete_template_soft_delete(self, tmp_path):
        _setup_db(tmp_path)
        content_templates.seed_builtin_templates()
        templates = content_templates.list_templates()
        tpl = templates[0]
        ok = content_templates.delete_template(tpl["id"])
        assert ok is True
        active = content_templates.list_templates()
        assert all(t["id"] != tpl["id"] for t in active)

    def test_get_nonexistent_template(self, tmp_path):
        _setup_db(tmp_path)
        result = content_templates.get_template(99999)
        assert result is None


# ===========================================================================
# Publishing Queue Tests
# ===========================================================================

class TestPublishingQueue:
    def test_enqueue_publish_creates_job(self, tmp_path):
        _setup_db(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        result = publishing_queue.enqueue_publish(
            video_id=video_id, platform="tiktok", account="terror"
        )
        assert result["queued"] is True
        assert "queue_id" in result

    def test_enqueue_prevents_duplicates(self, tmp_path):
        _setup_db(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        publishing_queue.enqueue_publish(video_id=video_id, platform="tiktok", account="terror")
        result = publishing_queue.enqueue_publish(video_id=video_id, platform="tiktok", account="terror")
        assert result["queued"] is False
        assert result["reason"] == "duplicate"

    def test_enqueue_rejects_unknown_platform(self, tmp_path):
        _setup_db(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        with pytest.raises(ValueError, match="Unsupported platform"):
            publishing_queue.enqueue_publish(video_id=video_id, platform="unknown", account="terror")

    def test_list_queue_filters(self, tmp_path):
        _setup_db(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        publishing_queue.enqueue_publish(video_id=video_id, platform="tiktok", account="terror")
        publishing_queue.enqueue_publish(video_id=video_id, platform="youtube", account="terror")
        tiktok_jobs = publishing_queue.list_queue(platform="tiktok")
        assert len(tiktok_jobs) == 1
        assert tiktok_jobs[0]["platform"] == "tiktok"

    def test_cancel_queued_job(self, tmp_path):
        _setup_db(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        result = publishing_queue.enqueue_publish(video_id=video_id, platform="tiktok", account="terror")
        ok = publishing_queue.cancel_queue_job(result["queue_id"])
        assert ok is True
        job = publishing_queue.get_queue_job(result["queue_id"])
        assert job["status"] == "cancelled"

    def test_retry_failed_job(self, tmp_path):
        _setup_db(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        result = publishing_queue.enqueue_publish(video_id=video_id, platform="tiktok", account="terror")
        with get_session() as session:
            job = session.query(PublishingQueue).filter_by(id=result["queue_id"]).first()
            job.status = "failed"
            job.error_message = "Test error"
            session.flush()
        retry = publishing_queue.retry_queue_job(result["queue_id"])
        assert retry["queued"] is True
        job = publishing_queue.get_queue_job(result["queue_id"])
        assert job["status"] == "queued"

    def test_retry_max_retries_exceeded(self, tmp_path):
        _setup_db(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        result = publishing_queue.enqueue_publish(video_id=video_id, platform="tiktok", account="terror", max_retries=1)
        with get_session() as session:
            job = session.query(PublishingQueue).filter_by(id=result["queue_id"]).first()
            job.status = "failed"
            job.retry_count = 1
            session.flush()
        retry = publishing_queue.retry_queue_job(result["queue_id"])
        assert "error" in retry

    def test_process_job_no_credentials_creates_export(self, tmp_path):
        _setup_db(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        result = publishing_queue.enqueue_publish(video_id=video_id, platform="tiktok", account="terror")
        process_result = publishing_queue.process_queue_job(result["queue_id"])
        assert process_result["status"] == "manual_export"
        assert "export_path" in process_result
        job = publishing_queue.get_queue_job(result["queue_id"])
        assert job["status"] == "failed"
        assert "manual export" in (job["error_message"] or "")

    def test_idempotency_key_is_unique(self, tmp_path):
        _setup_db(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        result1 = publishing_queue.enqueue_publish(video_id=video_id, platform="tiktok", account="terror")
        result2 = publishing_queue.enqueue_publish(video_id=video_id, platform="tiktok", account="terror")
        assert result1["queued"] is True
        assert "idempotency_key" in result1
        assert result2["queued"] is False
        assert result2["reason"] == "duplicate"

    def test_rate_limit_check(self, tmp_path):
        _setup_db(tmp_path)
        assert publishing_queue._check_rate_limit("tiktok", "terror") is True

    def test_manual_export_zip_created(self, tmp_path):
        _setup_db(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        result = publishing_queue.enqueue_publish(video_id=video_id, platform="tiktok", account="terror")
        process_result = publishing_queue.process_queue_job(result["queue_id"])
        export_path = process_result["export_path"]
        assert Path(export_path).exists()
        assert Path(export_path).suffix == ".zip"


# ===========================================================================
# Publishing Queue API Tests
# ===========================================================================

class TestPublishingQueueAPI:
    def test_list_queue_endpoint(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        with get_session() as session:
            job = PublishingQueue(video_id=video_id, account="terror", platform="tiktok", status="queued")
            session.add(job)
            session.flush()
            queue_id = job.id
        r = client.get("/api/publishing-queue")
        assert r.status_code == 200
        data = r.json()
        assert any(j["id"] == queue_id for j in data)

    def test_enqueue_endpoint(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
        r = client.post("/api/publishing-queue", json={
            "video_id": video_id,
            "platform": "tiktok",
            "account": "terror",
        })
        assert r.status_code == 200
        assert r.json()["queued"] is True

    def test_enqueue_missing_fields(self, tmp_path):
        client = _make_client(tmp_path)
        r = client.post("/api/publishing-queue", json={"video_id": 1})
        assert r.status_code == 400

    def test_retry_endpoint(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
            job = PublishingQueue(video_id=video_id, account="terror", platform="tiktok", status="failed")
            session.add(job)
            session.flush()
            queue_id = job.id
        r = client.post(f"/api/publishing-queue/{queue_id}/retry")
        assert r.status_code == 200
        assert r.json()["queued"] is True

    def test_cancel_endpoint(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
            job = PublishingQueue(video_id=video_id, account="terror", platform="tiktok", status="queued")
            session.add(job)
            session.flush()
            queue_id = job.id
        r = client.post(f"/api/publishing-queue/{queue_id}/cancel")
        assert r.status_code == 200
        assert r.json()["cancelled"] is True

    def test_get_single_job(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
            job = PublishingQueue(video_id=video_id, account="terror", platform="tiktok", status="queued")
            session.add(job)
            session.flush()
            queue_id = job.id
        r = client.get(f"/api/publishing-queue/{queue_id}")
        assert r.status_code == 200
        assert r.json()["id"] == queue_id

    def test_get_nonexistent_job(self, tmp_path):
        client = _make_client(tmp_path)
        r = client.get("/api/publishing-queue/99999")
        assert r.status_code == 404

    def test_process_due_endpoint(self, tmp_path):
        client = _make_client(tmp_path)
        r = client.post("/api/publishing-queue/process-due")
        assert r.status_code == 200

    def test_export_endpoint(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            v = _make_video(session)
            video_id = v.id
            job = PublishingQueue(video_id=video_id, account="terror", platform="tiktok",
                                  status="failed", export_path=str(tmp_path / "export.zip"))
            session.add(job)
            session.flush()
            queue_id = job.id
        (tmp_path / "export.zip").write_bytes(b"fake zip")
        r = client.get(f"/api/publishing-queue/export/{queue_id}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"

    def test_export_not_available(self, tmp_path):
        client = _make_client(tmp_path)
        r = client.get("/api/publishing-queue/export/99999")
        assert r.status_code == 404


# ===========================================================================
# Automation Settings API Tests
# ===========================================================================

class TestAutomationAPI:
    def test_get_automation_settings(self, tmp_path):
        client = _make_client(tmp_path)
        r = client.get("/api/automation/settings")
        assert r.status_code == 200
        data = r.json()
        assert "enabled" in data
        assert "require_approval" in data
        assert "max_daily_posts" in data

    def test_update_automation_settings(self, tmp_path):
        client = _make_client(tmp_path)
        r = client.put("/api/automation/settings", json={"enabled": True, "max_daily_posts": 10})
        assert r.status_code == 200
        assert r.json()["updated"]["enabled"] is True

    def test_get_rate_limits(self, tmp_path):
        client = _make_client(tmp_path)
        r = client.get("/api/automation/rate-limits")
        assert r.status_code == 200
        data = r.json()
        assert "tiktok" in data
        assert "total" in data


# ===========================================================================
# Content Pipeline API Tests
# ===========================================================================

class TestContentPipelineAPI:
    def test_list_content_pipeline(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            _make_video(session)
        r = client.get("/api/content-pipeline")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert len(data["items"]) >= 1

    def test_approve_content(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            v = _make_video(session, status="reviewing")
            video_id = v.id
        r = client.post(f"/api/content-pipeline/{video_id}/approve")
        assert r.status_code == 200
        with get_session() as session:
            v = session.query(Video).filter_by(id=video_id).first()
            assert v.status == "approved"

    def test_reject_content(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            v = _make_video(session, status="reviewing")
            video_id = v.id
        r = client.post(f"/api/content-pipeline/{video_id}/reject", json={"reason": "bad quality"})
        assert r.status_code == 200
        with get_session() as session:
            v = session.query(Video).filter_by(id=video_id).first()
            assert v.status == "rejected"

    def test_approve_non_reviewing_fails(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            v = _make_video(session, status="scripting")
            video_id = v.id
        r = client.post(f"/api/content-pipeline/{video_id}/approve")
        assert r.status_code == 400

    def test_content_pipeline_filters(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            inf = _make_influencer(session)
            influencer_id = inf.id
            _make_video(session, influencer_id=influencer_id, status="scripting")
        r = client.get(f"/api/content-pipeline?influencer_id={influencer_id}&status=scripting")
        assert r.status_code == 200
        data = r.json()
        assert all(v["status"] == "scripting" for v in data["items"])


# ===========================================================================
# Analytics API Tests
# ===========================================================================

class TestAnalyticsAPI:
    def test_analytics_summary_no_data(self, tmp_path):
        client = _make_client(tmp_path)
        r = client.get("/api/publishing-queue/analytics/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "unavailable"

    def test_analytics_summary_with_data(self, tmp_path):
        client = _make_client(tmp_path)
        with get_session() as session:
            inf = _make_influencer(session)
            snapshot = AnalyticsSnapshot(
                influencer_id=inf.id, platform="tiktok", date=datetime.utcnow(),
                views=100, likes=10, comments=2, shares=1, engagement_rate=0.13,
            )
            session.add(snapshot)
            session.flush()
        r = client.get("/api/publishing-queue/analytics/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "available"
        assert data["total_views"] == 100
