from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ArticleSource
from app.schemas import IngestRequest, IngestResponse
from app.services.extractor import ArticleExtractor
from app.security import authenticate_agent_or_session

router = APIRouter(prefix="/api/v1/ingest", tags=["Ingest / Ekstraksi Berita"])

@router.post("", response_model=IngestResponse)
def ingest_source(
    data: IngestRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Menyedot isi berita/artikel dari URL web secara bersih (tanpa iklan/menu)
    atau menyimpan teks mentah yang diinput langsung.
    """
    if not data.url and not data.raw_text:
        raise HTTPException(
            status_code=400,
            detail="Wajib menyertakan salah satu antara 'url' atau 'raw_text'."
        )

    title = "Tanpa Judul"
    raw_content = data.raw_text or ""
    source_name = data.source_name or "Web"

    if data.url:
        extracted = ArticleExtractor.extract_from_url(data.url)
        if not extracted or not extracted.get("text"):
            raise HTTPException(
                status_code=422,
                detail=f"Tidak dapat mengekstrak teks artikel dari URL: {data.url}. Pastikan URL dapat diakses publik."
            )
        title = extracted.get("title") or title
        raw_content = extracted.get("text") or ""
        if not data.source_name and "://" in data.url:
            domain = data.url.split("://")[1].split("/")[0].replace("www.", "")
            source_name = domain

    new_source = ArticleSource(
        url=data.url,
        title=title,
        source_name=source_name,
        raw_content=raw_content
    )
    db.add(new_source)
    db.commit()
    db.refresh(new_source)

    return IngestResponse(
        id=new_source.id,
        url=new_source.url,
        title=new_source.title,
        source_name=new_source.source_name,
        extracted_text_snippet=new_source.raw_content[:300] + ("..." if len(new_source.raw_content) > 300 else ""),
        ingested_at=new_source.ingested_at
    )

@router.get("/{source_id}")
def get_source(
    source_id: int,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Mengambil teks artikel lengkap hasil ekstraksi berdasarkan ID sumber."""
    source = db.query(ArticleSource).filter(ArticleSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail=f"Sumber ID {source_id} tidak ditemukan.")
    return {
        "id": source.id,
        "url": source.url,
        "title": source.title,
        "source_name": source.source_name,
        "raw_content": source.raw_content,
        "ingested_at": source.ingested_at
    }
