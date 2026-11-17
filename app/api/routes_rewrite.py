"""Auto-Rewrite: sumber (RSS/URL/teks mentah) -> draf artikel baru via Gemini.

Alur: ambil teks lengkap sumber (lewat ArticleSource atau extractor yang
sudah ada) -> susun prompt dari profil channel -> panggil Gemini dengan
kunci tersimpan -> simpan sebagai Publication status draft di database
DAN sebagai draf di Blogger (supaya bisa diterbitkan dari dashboard).

Hasil TIDAK PERNAH diterbitkan otomatis. Bila pembuatan draf di Blogger
gagal, isi hasil rewrite tetap tersimpan di database (status "failed")
supaya tidak hilang, dan respons membawa `blogger_draft_error`.
"""
import html as html_lib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ArticleSource, Channel, Publication
from app.security import authenticate_agent_or_session
from app.services.extractor import ArticleExtractor
from app.services.rewrite import (
    DEFAULT_MODEL,
    REWRITE_MODES,
    GeminiError,
    build_rewrite_prompt,
    count_words,
    generate_text,
    parse_model_output,
    similarity_ratio,
)
from app.services.seo import slugify
from app.services.settings import GEMINI_API_KEY, get_setting_value
from app.services.platforms.blogger import BloggerPlatform

router = APIRouter(prefix="/api/v1/rewrite", tags=["Auto-Rewrite"])

# Di atas 60% kemiripan, hasil dianggap terlalu mirip sumber.
SIMILARITY_WARN_THRESHOLD = 0.6


class RewriteRequest(BaseModel):
    channel_id: str
    source_id: Optional[int] = None
    url: Optional[str] = None
    raw_text: Optional[str] = None
    title: Optional[str] = None
    mode: str = Field(default="sedang")


class RewriteResponse(BaseModel):
    publication_id: int
    title: str
    status: str
    word_count: int
    similarity: float
    similarity_warning: bool
    word_count_warning: bool
    source_title: Optional[str] = None
    source_url: Optional[str] = None
    blogger_draft_error: Optional[str] = None


def _resolve_source(db: Session, payload: RewriteRequest):
    """Kembalikan (source_id, source_title, source_text, source_url).

    Prioritas: source_id (antrean) -> url (ekstrak penuh) -> raw_text.
    """
    if payload.source_id is not None:
        source = db.query(ArticleSource).filter(
            ArticleSource.id == payload.source_id).first()
        if not source:
            raise HTTPException(
                status_code=404,
                detail=f"Sumber ID {payload.source_id} tidak ditemukan.",
            )
        return source.id, source.title, source.raw_content or "", source.url

    if payload.url:
        try:
            extracted = ArticleExtractor.extract_from_url(payload.url)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Gagal mengekstrak artikel dari URL: {e}",
            )
        if not extracted or not (extracted.get("text") or "").strip():
            raise HTTPException(
                status_code=422,
                detail=f"Tidak dapat mengekstrak teks artikel dari URL: {payload.url}. "
                       "Pastikan URL dapat diakses publik.",
            )
        # Simpan sebagai ArticleSource supaya terlacak di antrean.
        domain = ""
        if "://" in payload.url:
            domain = payload.url.split("://", 1)[1].split("/", 1)[0].replace("www.", "")
        source = ArticleSource(
            url=payload.url,
            title=extracted.get("title") or "Tanpa Judul",
            source_name=domain or "Web",
            raw_content=extracted.get("text") or "",
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        return source.id, source.title, source.raw_content, source.url

    if payload.raw_text and payload.raw_text.strip():
        return None, payload.title or "Tanpa Judul", payload.raw_text, None

    raise HTTPException(
        status_code=400,
        detail="Wajib menyertakan salah satu antara 'source_id', 'url', atau 'raw_text'.",
    )


@router.post("", response_model=RewriteResponse)
def rewrite_article(
    payload: RewriteRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Tulis ulang satu sumber menjadi draf artikel baru (status draft)."""
    if payload.mode not in REWRITE_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Mode '{payload.mode}' tidak dikenal. "
                   f"Pilih salah satu: {', '.join(REWRITE_MODES)}.",
        )

    channel = db.query(Channel).filter(Channel.id == payload.channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404,
            detail=f"Channel ID '{payload.channel_id}' tidak ditemukan di database.",
        )
    if channel.platform != "blogger":
        raise HTTPException(
            status_code=400,
            detail=f"Platform '{channel.platform}' belum mendukung Auto-Rewrite "
                   "(baru Blogger).",
        )

    source_id, source_title, source_text, source_url = _resolve_source(db, payload)
    if not (source_text or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Teks sumber kosong — tidak ada yang bisa ditulis ulang.",
        )

    api_key = get_setting_value(db, GEMINI_API_KEY)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Kunci Gemini belum diisi. Isi dulu di dashboard → Pengaturan AI.",
        )
    model = get_setting_value(db, "gemini_model") or DEFAULT_MODEL

    prompt = build_rewrite_prompt(
        channel, source_title, source_text, payload.mode, source_url)
    mode_info = REWRITE_MODES[payload.mode]
    try:
        raw_output = generate_text(
            api_key, prompt, model=model,
            temperature=mode_info["temperature"],
        )
    except GeminiError as e:
        raise HTTPException(status_code=502, detail=str(e))

    new_title, body_html = parse_model_output(raw_output)
    new_title = new_title or source_title or "Tanpa Judul"
    if source_url:
        body_html += (
            '\n<p><em>Sumber inspirasi: <a href="'
            + html_lib.escape(source_url, quote=True)
            + '" target="_blank" rel="noopener">'
            + html_lib.escape(source_title or source_url)
            + "</a></em></p>"
        )

    words = count_words(body_html)
    similarity = similarity_ratio(source_text, body_html)
    try:
        target_words = int(channel.target_word_count or 800)
    except (TypeError, ValueError):
        target_words = 800

    pub = Publication(
        source_id=source_id,
        channel_id=channel.id,
        title=new_title,
        slug=slugify(new_title),
        content_html=body_html,
        labels=channel.default_labels,
        status="pending",
    )
    db.add(pub)
    db.commit()
    db.refresh(pub)

    # Buat draf di Blogger supaya bisa diterbitkan dari dashboard.
    # Kegagalan di sini TIDAK menghapus hasil rewrite (tetap di DB).
    blogger_error = None
    merged_labels = []
    if channel.default_labels:
        merged_labels = [l.strip() for l in channel.default_labels.split(",") if l.strip()]
    try:
        driver = BloggerPlatform(channel_id=channel.id, credentials=channel.get_credentials())
        res = driver.publish_post(
            title=new_title,
            content_html=body_html,
            labels=merged_labels,
            is_draft=True,
        )
    except Exception as e:
        res = None
        blogger_error = str(e)
    if res is not None and res.success:
        pub.status = "draft"
        pub.remote_post_id = res.remote_post_id
        pub.remote_url = res.remote_url
    else:
        pub.status = "failed"
        blogger_error = blogger_error or (
            res.error_message if res is not None else "Gagal membuat draf di Blogger."
        )
        pub.error_message = blogger_error
    db.commit()

    return RewriteResponse(
        publication_id=pub.id,
        title=new_title,
        status=pub.status,
        word_count=words,
        similarity=similarity,
        similarity_warning=similarity > SIMILARITY_WARN_THRESHOLD,
        word_count_warning=words < target_words * 0.5,
        source_title=source_title,
        source_url=source_url,
        blogger_draft_error=blogger_error,
    )
