"""Endpoint Ide Topik: GET /api/v1/topics/ideas + POST /api/v1/topics/draft.

Ide dibuat dari headline feed channel + niche; Gemini dipakai bila kunci
terkonfigurasi, kalau tidak (atau bila gagal) dipakai mode kata kunci.
"Buat Draf" membuat draf kerangka (judul + H2) — tidak pernah
auto-publish.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Channel
from app.security import authenticate_agent_or_session
from app.services.topics import create_draft_from_idea, get_ideas

router = APIRouter(prefix="/api/v1/topics", tags=["Ide Topik"])


@router.get("/ideas")
def topic_ideas(
    channel_id: str = Query(..., description="ID channel"),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """5–10 usulan judul untuk channel ini.

    Respons: {channel_id, niche, headline_source, headline_count,
    ai_used, ai_error, ideas[]}. Setiap ide: {title, angle, keywords[],
    source_title, source_url, source_id, origin}.
    """
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404, detail=f"Channel '{channel_id}' tidak ditemukan."
        )
    return get_ideas(channel, db)


class TopicDraftRequest(BaseModel):
    channel_id: str
    title: str
    angle: Optional[str] = ""
    keywords: Optional[List[str]] = None
    source_id: Optional[int] = None
    source_url: Optional[str] = ""
    source_title: Optional[str] = ""


@router.post("/draft", status_code=201)
def topic_draft(
    data: TopicDraftRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Buat draf kerangka (judul + H2) dari satu ide topik."""
    channel = db.query(Channel).filter(Channel.id == data.channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404, detail=f"Channel '{data.channel_id}' tidak ditemukan."
        )
    try:
        pub = create_draft_from_idea(db, channel, data.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "publication_id": pub.id,
        "title": pub.title,
        "slug": pub.slug,
        "status": pub.status,
    }
