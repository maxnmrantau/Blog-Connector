"""Endpoint Ide Topik v2: GET /api/v1/topics/ideas + POST /api/v1/topics/draft.

Ide v2 datang dari SINYAL NYATA (bukan string niche channel):
- trends: berita populer Indonesia (Google News RSS, tanpa kunci).
- search_console: kueri peluang (impresi tinggi, posisi 5-20, CTR
  di bawah rata-rata) — memakai ulang Search Console overview.
- feeds: headline FeedSource channel.
- gaps: celah dari konten sendiri (label 1 artikel, bagian 2).
- seed: kata kunci bebas pengguna — dicari di Google News Indonesia,
  ide dari headline nyata (bukan template); niche diabaikan total.

Setiap ide membawa skor 0-100 + alasan satu kalimat berbasis sinyal.
Sumber yang tidak tersedia mengembalikan list kosong + pesan jujur di
respons["sources"]. Gemini TIDAK dipanggil di endpoint ini.
"Buat Draf" membuat draf kerangka (judul + H2) — tidak pernah
auto-publish.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Channel, Publication, TopicIdea
from app.security import authenticate_agent_or_session
from app.services.topics import (
    VALID_IDEA_SOURCES,
    collect_v2_ideas,
    create_draft_from_idea,
    create_outline_draft,
    normalize_title,
)

router = APIRouter(prefix="/api/v1/topics", tags=["Ide Topik"])


@router.get("/ideas")
def topic_ideas(
    channel_id: str = Query(..., description="ID channel"),
    source: str = Query(
        "all",
        description="Sumber ide: all | trends | search_console | feeds | gaps | seed",
    ),
    seed: str = Query("", description="Kata kunci bebas (wajib bila source=seed)"),
    limit: int = Query(10, ge=1, le=20, description="Jumlah ide maks (1-20)"),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """5–10 usulan judul dari sinyal nyata untuk channel ini.

    Respons: {channel_id, niche, headline_source, headline_count,
    ai_used, ai_error, sources{...}, ideas[]}. Setiap ide: {title,
    keyword, source, score, reason, angle, keywords[], source_title,
    source_url, source_id, origin}. sources = status per sumber
    {available, count, message} — sumber mati tidak mengarang ide.
    """
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404, detail=f"Channel '{channel_id}' tidak ditemukan."
        )
    if source not in VALID_IDEA_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"source harus salah satu dari: {', '.join(VALID_IDEA_SOURCES)}."
            ),
        )
    if source == "seed" and not seed.strip():
        raise HTTPException(
            status_code=400,
            detail="Mode seed butuh kata kunci bebas (parameter seed).",
        )
    return collect_v2_ideas(channel, db, source=source, seed=seed, limit=limit)


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


# --- Perpustakaan ide (patch 02) -------------------------------------------

LIBRARY_STATUSES = ("baru", "dipakai", "dibuang")


def _library_to_dict(row):
    """Serialisasi satu baris TopicIdea untuk API."""
    return {
        "id": row.id,
        "channel_id": row.channel_id,
        "title": row.title,
        "keyword": row.keyword,
        "source": row.source,
        "score": row.score,
        "reason": row.reason,
        "angle": row.angle,
        "keywords": [k for k in (row.keywords or "").split(",") if k.strip()],
        "source_url": row.source_url,
        "source_title": row.source_title,
        "status": row.status,
        "publication_id": row.publication_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


class TopicLibraryCreate(BaseModel):
    channel_id: str
    title: str
    keyword: Optional[str] = ""
    source: Optional[str] = ""
    score: Optional[int] = 50
    reason: Optional[str] = ""
    angle: Optional[str] = ""
    keywords: Optional[List[str]] = None
    source_url: Optional[str] = ""
    source_title: Optional[str] = ""


class TopicLibraryStatusUpdate(BaseModel):
    status: str


@router.post("/library", status_code=201)
def topic_library_create(
    data: TopicLibraryCreate,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Simpan satu ide ke perpustakaan.

    Dedupe: judul yang sudah ada di channel yang sama (huruf besar/kecil
    dan spasi berlebih diabaikan) TIDAK dibuat ganda — respons 200
    mengembalikan baris yang sudah ada dengan duplicate=true.
    """
    channel = db.query(Channel).filter(Channel.id == data.channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404, detail=f"Channel '{data.channel_id}' tidak ditemukan."
        )
    title = (data.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Judul ide tidak boleh kosong.")
    title_norm = normalize_title(title)
    existing = (
        db.query(TopicIdea)
        .filter(
            TopicIdea.channel_id == data.channel_id,
            TopicIdea.title_norm == title_norm,
        )
        .first()
    )
    if existing is not None:
        result = _library_to_dict(existing)
        result["duplicate"] = True
        # 200 (bukan 201 dari decorator): tidak ada baris baru yang dibuat.
        return JSONResponse(status_code=200, content=result)
    row = TopicIdea(
        channel_id=data.channel_id,
        title=title,
        title_norm=title_norm,
        keyword=(data.keyword or "").strip() or None,
        source=(data.source or "").strip() or None,
        score=max(0, min(100, data.score if data.score is not None else 50)),
        reason=(data.reason or "").strip() or None,
        angle=(data.angle or "").strip() or None,
        keywords=",".join(data.keywords or []) or None,
        source_url=(data.source_url or "").strip() or None,
        source_title=(data.source_title or "").strip() or None,
        status="baru",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    result = _library_to_dict(row)
    result["duplicate"] = False
    return result


@router.get("/library")
def topic_library_list(
    channel_id: str = Query(..., description="ID channel"),
    status: Optional[str] = Query(default=None, description="Filter: baru | dipakai | dibuang"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Daftar ide di perpustakaan, terbaru dulu."""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404, detail=f"Channel '{channel_id}' tidak ditemukan."
        )
    if status is not None and status not in LIBRARY_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status harus salah satu dari: {', '.join(LIBRARY_STATUSES)}.",
        )
    query = (
        db.query(TopicIdea)
        .filter(TopicIdea.channel_id == channel_id)
        .order_by(TopicIdea.created_at.desc(), TopicIdea.id.desc())
    )
    if status is not None:
        query = query.filter(TopicIdea.status == status)
    return [_library_to_dict(row) for row in query.limit(limit).all()]


@router.patch("/library/{idea_id}")
def topic_library_update_status(
    idea_id: int,
    data: TopicLibraryStatusUpdate,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Ubah status ide: baru | dipakai | dibuang."""
    row = db.query(TopicIdea).filter(TopicIdea.id == idea_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Ide ID {idea_id} tidak ditemukan.")
    if data.status not in LIBRARY_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status harus salah satu dari: {', '.join(LIBRARY_STATUSES)}.",
        )
    row.status = data.status
    db.commit()
    db.refresh(row)
    return _library_to_dict(row)


@router.delete("/library/{idea_id}")
def topic_library_delete(
    idea_id: int,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Hapus ide dari perpustakaan (draf/artikel yang sudah dibuat tidak
    ikut terhapus)."""
    row = db.query(TopicIdea).filter(TopicIdea.id == idea_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Ide ID {idea_id} tidak ditemukan.")
    db.delete(row)
    db.commit()
    return {"ok": True, "deleted_id": idea_id}


# --- Buat Kerangka / outline (patch 03) ------------------------------------

@router.post("/ideas/{idea_id}/outline", status_code=201)
def topic_outline(
    idea_id: int,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Buat draf kerangka LENGKAP dari satu ide perpustakaan: judul + H2/H3
    + poin-poin per bagian + kata kunci target + label yang disarankan +
    draf meta description. Selalu berstatus draft — tidak pernah
    auto-publish. Gemini memperkaya judul/kerangka hanya bila kuncinya
    berfungsi; bila Gemini gagal, template tetap menghasilkan kerangka
    lengkap (respons membawa ai_error). Ide yang sudah pernah dibuatkan
    kerangka mengembalikan draf yang sudah ada (duplicate=true, 200).
    """
    row = db.query(TopicIdea).filter(TopicIdea.id == idea_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Ide ID {idea_id} tidak ditemukan.")
    if row.status == "dipakai" and row.publication_id:
        pub = db.query(Publication).filter(Publication.id == row.publication_id).first()
        if pub is not None:
            return JSONResponse(
                status_code=200,
                content={
                    "publication_id": pub.id,
                    "title": pub.title,
                    "slug": pub.slug,
                    "status": pub.status,
                    "ai_used": False,
                    "ai_error": None,
                    "duplicate": True,
                },
            )
    channel = db.query(Channel).filter(Channel.id == row.channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404, detail=f"Channel '{row.channel_id}' tidak ditemukan."
        )
    try:
        pub, ai_used, ai_error = create_outline_draft(db, channel, row)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "publication_id": pub.id,
        "title": pub.title,
        "slug": pub.slug,
        "status": pub.status,
        "ai_used": ai_used,
        "ai_error": ai_error,
        "duplicate": False,
    }
