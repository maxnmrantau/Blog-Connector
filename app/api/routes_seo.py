from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.orm import Session
import html as html_lib
import re

from app.database import get_db
from app.models import Publication
from app.security import authenticate_agent_or_session
from app.services.seo import (
    check_seo,
    generate_meta_description,
    readability,
    slugify,
    suggest_alt_texts,
    suggest_internal_links,
)
from app.services.platforms.blogger import BloggerPlatform

router = APIRouter(prefix="/api/v1/seo-check", tags=["SEO"])


class SeoCheckRequest(BaseModel):
    title: str = ""
    meta_description: Optional[str] = ""
    content_html: str = ""
    target_word_count: int = Field(default=800, gt=0)


class SeoCheckItem(BaseModel):
    id: str
    label: str
    passed: bool
    detail: str


class SeoCheckResponse(BaseModel):
    score: int
    checks: List[SeoCheckItem]


@router.post("", response_model=SeoCheckResponse)
def seo_check(
    payload: SeoCheckRequest,
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Cek SEO murni konten (tanpa channel): nilai judul, meta
    description, jumlah kata, gambar/alt, subheading, dan internal
    link, lalu kembalikan skor 0-100 + rincian tiap check.
    """
    return check_seo(
        title=payload.title,
        meta_description=payload.meta_description,
        content_html=payload.content_html,
        target_word_count=payload.target_word_count,
    )


# --- SEO otomatis (Patch 3) -------------------------------------------
# GET saran TANPA mengubah apa pun; penerapan hanya terjadi lewat
# POST /{id}/apply saat pengguna mengklik "Terapkan SEO" di dashboard.

router_optimize = APIRouter(prefix="/api/v1/seo-optimize", tags=["SEO"])


class SeoOptimizeRequest(BaseModel):
    publication_id: int


class InternalLinkSuggestion(BaseModel):
    publication_id: int
    title: str
    url: str
    anchor: str
    score: int
    matched_keywords: List[str]


class AltSuggestion(BaseModel):
    src: str
    current_alt: str
    suggested_alt: str


class ReadabilityResult(BaseModel):
    score: int
    label: str
    avg_sentence_words: float
    avg_paragraph_words: float
    sentence_count: int
    paragraph_count: int


class SeoOptimizeResponse(BaseModel):
    publication_id: int
    title: str
    meta_description: str
    slug: str
    internal_links: List[InternalLinkSuggestion]
    readability: ReadabilityResult
    alt_suggestions: List[AltSuggestion]
    seo_check: dict


class SeoApplyRequest(BaseModel):
    link_ids: List[int] = Field(default_factory=list)
    apply_meta: bool = True
    apply_slug: bool = True
    apply_alts: bool = True


class SeoApplyResponse(BaseModel):
    publication_id: int
    applied_meta: bool
    applied_slug: bool
    links_inserted: int
    alts_fixed: int
    blogger_updated: bool
    blogger_error: Optional[str] = None
    meta_description: Optional[str] = None
    slug: Optional[str] = None


def _suggestions(db: Session, pub: Publication) -> SeoOptimizeResponse:
    """Hitung semua saran SEO untuk satu publikasi (tanpa mengubah DB)."""
    candidates = db.query(Publication).filter(
        Publication.channel_id == pub.channel_id).all()
    channel = pub.channel
    try:
        target_words = int(channel.target_word_count or 800) if channel else 800
    except (TypeError, ValueError):
        target_words = 800
    return SeoOptimizeResponse(
        publication_id=pub.id,
        title=pub.title,
        meta_description=generate_meta_description(pub.title, pub.content_html),
        slug=slugify(pub.title),
        internal_links=suggest_internal_links(pub, candidates),
        readability=readability(pub.content_html),
        alt_suggestions=suggest_alt_texts(pub.content_html),
        seo_check=check_seo(
            title=pub.title,
            meta_description=pub.meta_description or "",
            content_html=pub.content_html,
            target_word_count=target_words,
        ),
    )


def _apply_alt_to_img(content_html: str, src: str, alt: str) -> str:
    """Sisipkan/ganti atribut alt pada <img> dengan src yang cocok
    (hanya kemunculan pertama)."""
    pattern = r"<img\b[^>]*" + re.escape(src) + r"[^>]*>"
    alt_attr = 'alt="' + html_lib.escape(alt, quote=True) + '"'

    def repl(m):
        tag = m.group(0)
        if re.search(r"""\salt\s*=""", tag):
            return re.sub(r"""alt\s*=\s*['"][^'"]*['"]""", alt_attr, tag, count=1)
        stripped = tag.rstrip()
        if stripped.endswith("/>"):
            return stripped[:-2] + " " + alt_attr + "/>"
        return stripped[:-1] + " " + alt_attr + ">"

    return re.sub(pattern, repl, content_html, count=1)


@router_optimize.post("", response_model=SeoOptimizeResponse)
def seo_optimize(
    payload: SeoOptimizeRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Tampilkan saran SEO otomatis untuk satu publikasi. TIDAK mengubah
    apa pun — penerapan hanya lewat endpoint /{id}/apply."""
    pub = db.query(Publication).filter(
        Publication.id == payload.publication_id).first()
    if not pub:
        raise HTTPException(
            status_code=404,
            detail=f"Publikasi dengan id {payload.publication_id} tidak ditemukan.",
        )
    return _suggestions(db, pub)


@router_optimize.post("/{publication_id}/apply", response_model=SeoApplyResponse)
def seo_apply(
    publication_id: int,
    payload: SeoApplyRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Terapkan saran SEO pada sebuah DRAF (hanya saat pengguna mengklik).

    Mengisi meta_description/slug di database, menyisipkan tautan internal
    yang DIPILIH sebagai blok "Baca juga" di akhir konten, dan mengisi alt
    text gambar yang kosong. Bila draf punya remote_post_id, konten yang
    sudah diperbarui ikut disinkronkan ke Blogger lewat update_post
    (label dipertahankan seperti pada update_publication).

    Catatan jujur: meta_description dan slug tersimpan di database konektor;
    Blogger API tidak menyediakan kolom meta description dan membuat URL
    dari judul, jadi nilai ini TIDAK mengubah meta/URL live di Blogger —
    untuk itu isi "Search Description" di editor Blogger (lihat panduan).
    """
    pub = db.query(Publication).filter(Publication.id == publication_id).first()
    if not pub:
        raise HTTPException(
            status_code=404,
            detail=f"Publikasi dengan id {publication_id} tidak ditemukan.",
        )
    if pub.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="Hanya draf yang bisa dioptimasi SEO-nya dari sini "
                   f"(status publikasi ini: '{pub.status}').",
        )

    suggestions = _suggestions(db, pub)
    applied_meta = False
    applied_slug = False
    links_inserted = 0
    alts_fixed = 0
    new_content = pub.content_html or ""

    if payload.apply_meta and suggestions.meta_description:
        pub.meta_description = suggestions.meta_description
        applied_meta = True
    if payload.apply_slug and suggestions.slug:
        pub.slug = suggestions.slug
        applied_slug = True

    chosen = [l for l in suggestions.internal_links
              if l.publication_id in (payload.link_ids or [])]
    if chosen:
        items = "".join(
            '<li><a href="' + html_lib.escape(l.url, quote=True) + '">'
            + html_lib.escape(l.anchor) + "</a></li>"
            for l in chosen
        )
        new_content += "\n<h3>Baca juga</h3>\n<ul>\n" + items + "\n</ul>"
        links_inserted = len(chosen)

    if payload.apply_alts:
        for alt in suggestions.alt_suggestions:
            updated = _apply_alt_to_img(new_content, alt.src, alt.suggested_alt)
            if updated != new_content:
                new_content = updated
                alts_fixed += 1

    pub.content_html = new_content

    # Sinkronkan konten ke Blogger bila draf sudah ada di sana.
    blogger_updated = False
    blogger_error = None
    channel = pub.channel
    if pub.remote_post_id and channel and channel.platform == "blogger":
        if pub.labels:
            effective_labels = [l.strip() for l in pub.labels.split(",") if l.strip()]
        else:
            effective_labels = None
        try:
            driver = BloggerPlatform(
                channel_id=channel.id, credentials=channel.get_credentials())
            res = driver.update_post(
                pub.remote_post_id,
                title=pub.title,
                content_html=new_content,
                labels=effective_labels,
            )
            if res.success:
                blogger_updated = True
                if res.remote_url:
                    pub.remote_url = res.remote_url
            else:
                blogger_error = res.error_message or "Gagal memperbarui draf di Blogger."
        except Exception as e:
            blogger_error = str(e)
    elif not pub.remote_post_id:
        blogger_error = ("Draf ini belum punya remote_post_id di Blogger — "
                         "perubahan hanya tersimpan di database.")

    db.commit()
    return SeoApplyResponse(
        publication_id=pub.id,
        applied_meta=applied_meta,
        applied_slug=applied_slug,
        links_inserted=links_inserted,
        alts_fixed=alts_fixed,
        blogger_updated=blogger_updated,
        blogger_error=blogger_error,
        meta_description=pub.meta_description,
        slug=pub.slug,
    )


class SeoCheckRequest(BaseModel):
    title: str = ""
    meta_description: Optional[str] = ""
    content_html: str = ""
    target_word_count: int = Field(default=800, gt=0)


class SeoCheckItem(BaseModel):
    id: str
    label: str
    passed: bool
    detail: str


class SeoCheckResponse(BaseModel):
    score: int
    checks: List[SeoCheckItem]


@router.post("", response_model=SeoCheckResponse)
def seo_check(
    payload: SeoCheckRequest,
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Cek SEO murni konten (tanpa channel): nilai judul, meta
    description, jumlah kata, gambar/alt, subheading, dan internal
    link, lalu kembalikan skor 0-100 + rincian tiap check.
    """
    return check_seo(
        title=payload.title,
        meta_description=payload.meta_description,
        content_html=payload.content_html,
        target_word_count=payload.target_word_count,
    )
