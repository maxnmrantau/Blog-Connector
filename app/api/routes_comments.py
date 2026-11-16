from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import Channel
from app.services.platforms.blogger import BloggerPlatform
from app.security import authenticate_agent_or_session

router = APIRouter(prefix="/api/v1/comments", tags=["Komentar"])

# CATATAN — bentuk method komentar Blogger API v3 (terverifikasi dari
# dokumentasi resmi Google, developers.google.com/blogger/docs/3.0/
# reference/comments): hanya listByBlog yang tingkat blog —
# GET /blogs/{blogId}/comments. comments().list() justru per-postingan.
# Sedangkan approve / markAsSpam / delete semuanya PER-POSTINGAN:
# POST /blogs/{blogId}/posts/{postId}/comments/{commentId}/approve
# (dan .../spam, DELETE ...). Karena itu endpoint approve/spam/delete
# di bawah ini WAJIB menerima post_id (di body untuk POST, di query
# untuk DELETE) — body {channel_id} saja tidak cukup, Blogger akan
# menolak tanpa postId. post_id didapat dari field "post_id" tiap
# item hasil GET list (berasal dari item.post.id di respons Blogger).


class CommentActionRequest(BaseModel):
    channel_id: str
    post_id: str


def _get_blogger_channel(channel_id: str, db: Session) -> Channel:
    """Ambil channel dan pastikan ada + platform blogger (404/400)."""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404,
            detail=f"Channel ID '{channel_id}' tidak ditemukan di database."
        )
    if channel.platform != "blogger":
        raise HTTPException(
            status_code=400,
            detail=f"Platform '{channel.platform}' belum mendukung moderasi komentar."
        )
    return channel


def _blogger_status(exc: Exception):
    """
    Ambil status HTTP dari error Blogger (HttpError googleapiclient
    maupun objek tiruan di tes): coba .status_code, lalu .resp.status.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "resp", None)
        status = getattr(resp, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _map_blogger_error(exc: Exception, what: str):
    """HttpError 404 dari Blogger -> 404; error Blogger lain -> 502."""
    if _blogger_status(exc) == 404:
        raise HTTPException(
            status_code=404,
            detail=f"Komentar tidak ditemukan di Blogger ({what})."
        )
    raise HTTPException(
        status_code=502,
        detail=f"Gagal {what} di Blogger: {str(exc)}"
    )


@router.get("")
def list_comments(
    channel_id: str = Query(..., description="ID channel blogger"),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Mengambil daftar komentar blog (semua postingan) via comments().listByBlog()."""
    channel = _get_blogger_channel(channel_id, db)
    driver = BloggerPlatform(channel_id=channel.id, credentials=channel.get_credentials())
    try:
        return driver.list_comments()
    except Exception as e:
        _map_blogger_error(e, "mengambil daftar komentar")


@router.post("/{comment_id}/approve")
def approve_comment(
    comment_id: str,
    payload: CommentActionRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Menyetujui komentar (comments().approve) — butuh post_id, lihat catatan di atas."""
    channel = _get_blogger_channel(payload.channel_id, db)
    driver = BloggerPlatform(channel_id=channel.id, credentials=channel.get_credentials())
    try:
        driver.approve_comment(payload.post_id, comment_id)
    except Exception as e:
        _map_blogger_error(e, "menyetujui komentar")
    return {"ok": True, "comment_id": comment_id, "post_id": payload.post_id, "status": "LIVE"}


@router.post("/{comment_id}/spam")
def mark_comment_as_spam(
    comment_id: str,
    payload: CommentActionRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Menandai komentar sebagai spam (comments().markAsSpam) — butuh post_id, lihat catatan di atas."""
    channel = _get_blogger_channel(payload.channel_id, db)
    driver = BloggerPlatform(channel_id=channel.id, credentials=channel.get_credentials())
    try:
        driver.mark_comment_as_spam(payload.post_id, comment_id)
    except Exception as e:
        _map_blogger_error(e, "menandai komentar sebagai spam")
    return {"ok": True, "comment_id": comment_id, "post_id": payload.post_id, "status": "SPAM"}


@router.delete("/{comment_id}")
def delete_comment(
    comment_id: str,
    channel_id: str = Query(..., description="ID channel blogger"),
    post_id: str = Query(..., description="ID postingan tempat komentar itu berada"),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Menghapus komentar (comments().delete) — butuh post_id, lihat catatan di atas."""
    channel = _get_blogger_channel(channel_id, db)
    driver = BloggerPlatform(channel_id=channel.id, credentials=channel.get_credentials())
    try:
        driver.delete_comment(post_id, comment_id)
    except Exception as e:
        _map_blogger_error(e, "menghapus komentar")
    return {"ok": True, "deleted_id": comment_id}
