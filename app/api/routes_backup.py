import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import Channel, Publication
from app.services.platforms.blogger import BloggerPlatform
from app.security import authenticate_agent_or_session

router = APIRouter(prefix="/api/v1/backup", tags=["Backup / Ekspor"])


def _dt(value):
    """Datetime -> ISO 8601, atau None."""
    return value.isoformat() if isinstance(value, datetime.datetime) else None


def _channel_dict(channel: Channel) -> dict:
    # Kredensial TIDAK ikut di-export (berisi refresh token) — backup
    # ini hanya berisi konfigurasi channel, bukan rahasia.
    return {
        "id": channel.id,
        "name": channel.name,
        "platform": channel.platform,
        "niche": channel.niche,
        "tone_of_voice": channel.tone_of_voice,
        "target_word_count": channel.target_word_count,
        "default_labels": channel.default_labels,
        "blog_id": channel.blog_id,
        "blog_url": channel.blog_url,
        "created_at": _dt(channel.created_at),
    }


def _publication_dict(pub: Publication) -> dict:
    return {
        "id": pub.id,
        "source_id": pub.source_id,
        "channel_id": pub.channel_id,
        "title": pub.title,
        "slug": pub.slug,
        "meta_description": pub.meta_description,
        "content_html": pub.content_html,
        "labels": pub.labels,
        "status": pub.status,
        "remote_post_id": pub.remote_post_id,
        "remote_url": pub.remote_url,
        "error_message": pub.error_message,
        "scheduled_at": _dt(pub.scheduled_at),
        "published_at": _dt(pub.published_at),
        "created_at": _dt(pub.created_at),
    }


@router.get("")
def export_backup(
    channel_id: Optional[str] = Query(None, description="ID channel; kosongkan untuk semua channel"),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Export backup JSON: channels + publications (dari DB) + pages
    (live dari Blogger per channel). Kalau channel_id diisi, hanya
    channel itu yang di-export. Pages toleran gagal: kalau Blogger
    tidak bisa dihubungi untuk sebuah channel, pages channel itu
    jadi [] dan export tetap jalan.
    """
    if channel_id:
        channels = db.query(Channel).filter(Channel.id == channel_id).all()
        if not channels:
            raise HTTPException(
                status_code=404,
                detail=f"Channel ID '{channel_id}' tidak ditemukan di database."
            )
    else:
        channels = db.query(Channel).all()

    channel_ids = [ch.id for ch in channels]
    publications = (
        db.query(Publication)
        .filter(Publication.channel_id.in_(channel_ids))
        .order_by(Publication.created_at.asc())
        .all()
        if channel_ids else []
    )

    pages = []
    for ch in channels:
        if ch.platform != "blogger":
            continue
        try:
            driver = BloggerPlatform(channel_id=ch.id, credentials=ch.get_credentials())
            for page in driver.list_pages():
                pages.append({"channel_id": ch.id, **page})
        except Exception:
            # Pages channel ini gagal dimuat — lewati, export tetap jalan.
            continue

    return {
        "channels": [_channel_dict(ch) for ch in channels],
        "publications": [_publication_dict(pub) for pub in publications],
        "pages": pages,
    }
