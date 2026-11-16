from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import Channel
from app.services.platforms.blogger import BloggerPlatform
from app.security import authenticate_agent_or_session

router = APIRouter(prefix="/api/v1/pages", tags=["Pages / Halaman Statis"])


class CreatePageRequest(BaseModel):
    channel_id: str
    title: str
    content_html: str
    status: str = "draft"


def _get_blogger_driver(channel: Channel) -> BloggerPlatform:
    """Ambil driver Blogger untuk sebuah channel (sudah divalidasi blogger)."""
    return BloggerPlatform(channel_id=channel.id, credentials=channel.get_credentials())


@router.post("")
def create_page(
    payload: CreatePageRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Membuat halaman statis (Page) di Blogger — dipakai untuk halaman
    Tentang, Kontak, dan Kebijakan Privasi. Pages tidak disimpan di
    database konektor; selalu dibaca live dari Blogger.
    """
    channel = db.query(Channel).filter(Channel.id == payload.channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404,
            detail=f"Channel ID '{payload.channel_id}' tidak ditemukan di database."
        )

    if channel.platform != "blogger":
        raise HTTPException(
            status_code=400,
            detail=f"Platform '{channel.platform}' belum mendukung halaman statis."
        )

    driver = _get_blogger_driver(channel)

    # Penjaga duplikat: kalau sudah ada page dengan judul yang sama
    # (case-insensitive), jangan membuat page baru di Blogger.
    existing_pages = driver.list_pages()
    title_lower = (payload.title or "").strip().lower()
    for page in existing_pages:
        if (page.get("title") or "").strip().lower() == title_lower:
            return {
                "ok": False,
                "error": (
                    f"Sudah ada halaman dengan judul '{payload.title}' "
                    f"(page id {page.get('id')}). Hapus halaman itu dulu "
                    "atau pakai judul lain."
                ),
            }

    is_draft = payload.status.lower() != "publish"
    res = driver.create_page(
        title=payload.title,
        content_html=payload.content_html,
        is_draft=is_draft
    )

    if not res.success:
        raise HTTPException(
            status_code=502,
            detail=res.error_message or "Gagal membuat halaman di Blogger."
        )

    return {
        "ok": True,
        "page_id": res.remote_post_id,
        "title": payload.title,
        "status": "draft" if is_draft else "published",
        "url": res.remote_url,
    }


@router.get("")
def list_pages(
    channel_id: str = Query(..., description="ID channel blogger"),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Mengambil daftar halaman statis (live dari Blogger) untuk sebuah channel."""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404,
            detail=f"Channel ID '{channel_id}' tidak ditemukan di database."
        )

    if channel.platform != "blogger":
        raise HTTPException(
            status_code=400,
            detail=f"Platform '{channel.platform}' belum mendukung halaman statis."
        )

    driver = _get_blogger_driver(channel)
    return driver.list_pages()


@router.delete("/{page_id}")
def delete_page(
    page_id: str,
    channel_id: str = Query(..., description="ID channel blogger"),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Menghapus sebuah halaman statis dari Blogger."""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404,
            detail=f"Channel ID '{channel_id}' tidak ditemukan di database."
        )

    if channel.platform != "blogger":
        raise HTTPException(
            status_code=400,
            detail=f"Platform '{channel.platform}' belum mendukung halaman statis."
        )

    driver = _get_blogger_driver(channel)
    res = driver.delete_page(page_id)

    if not res.success:
        raise HTTPException(
            status_code=502,
            detail=res.error_message or "Gagal menghapus halaman di Blogger."
        )

    return {
        "ok": True,
        "deleted_id": page_id,
    }
