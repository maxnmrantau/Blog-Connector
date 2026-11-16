"""RSS Feed + antrean rewrite (LANGKAH 1).

Endpoint untuk mendaftarkan feed RSS/Atom per channel dan mengambil
item-itemnya on-demand menjadi ArticleSource (bahan antrean rewrite).

TIDAK ada cron/background scheduler di sini: deploy di Vercel serverless
tidak punya cron persisten, jadi fetch hanya terjadi saat dipanggil
(POST /{feed_id}/fetch) dari dashboard atau oleh AI agent.

TIDAK ada penulisan-ulang otomatis: antrean hanya menyiapkan bahan.
Penulisan ulang dikerjakan AI agent lewat API/chat supaya konten tetap
orisinal, bukan spin mentah dari artikel orang lain.
"""
import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ArticleSource, Channel, FeedSource
from app.schemas import FeedFetchSummary, FeedSourceCreate, FeedSourceResponse
from app.security import authenticate_agent_or_session

# feedparser sudah ada di requirements.txt, tapi di-import secara malas
# supaya aplikasi tetap bisa boot di lingkungan yang belum memasangnya
# (mis. saat tes unit — modul ini di-mock di sana).
try:
    import feedparser
except ImportError:  # pragma: no cover
    feedparser = None

router = APIRouter(prefix="/api/v1/feeds", tags=["RSS Feeds"])


def _is_valid_feed_url(url: str) -> bool:
    """Feed URL wajib http(s) dengan host."""
    if not url:
        return False
    parsed = urlparse(url.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _entry_text(entry: dict) -> str:
    """Ambil ringkasan/konten item feed: content[0].value > summary > description."""
    content = entry.get("content")
    if content:
        try:
            value = content[0].get("value")
            if value:
                return value
        except (IndexError, AttributeError, TypeError):
            pass
    return entry.get("summary") or entry.get("description") or ""


@router.post("", response_model=FeedSourceResponse, status_code=201)
def add_feed(
    data: FeedSourceCreate,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Daftarkan feed RSS/Atom baru untuk sebuah channel."""
    channel = db.query(Channel).filter(Channel.id == data.channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{data.channel_id}' tidak ditemukan.",
        )
    if not _is_valid_feed_url(data.feed_url):
        raise HTTPException(
            status_code=400,
            detail="feed_url wajib berupa URL http(s) yang valid.",
        )
    feed = FeedSource(
        channel_id=data.channel_id,
        feed_url=data.feed_url.strip(),
        title=(data.title or "").strip() or None,
        active=True,
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


@router.get("", response_model=list[FeedSourceResponse])
def list_feeds(
    channel_id: str | None = Query(default=None, description="Filter feed per channel"),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Daftar feed; filter per channel bila channel_id diberikan."""
    query = db.query(FeedSource).order_by(FeedSource.created_at.desc())
    if channel_id:
        query = query.filter(FeedSource.channel_id == channel_id)
    return query.all()


@router.post("/{feed_id}/fetch", response_model=FeedFetchSummary)
def fetch_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Ambil feed SEKARANG (on-demand) dan simpan item baru sebagai ArticleSource.

    Item yang URL-nya sudah ada di article_sources DILEWATI (tidak duplikat).
    """
    feed = db.query(FeedSource).filter(FeedSource.id == feed_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed ID {feed_id} tidak ditemukan.")
    if feedparser is None:
        raise HTTPException(
            status_code=503,
            detail="feedparser belum terpasang di server.",
        )
    try:
        parsed = feedparser.parse(feed.feed_url)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Gagal mengambil feed: {e}",
        )

    entries = parsed.get("entries") or []
    # Isi judul feed dari feed itu sendiri bila belum diisi saat didaftar.
    feed_title = (parsed.get("feed") or {}).get("title")
    if not feed.title and feed_title:
        feed.title = feed_title

    existing_urls = {
        url for (url,) in db.query(ArticleSource.url)
        .filter(ArticleSource.url.isnot(None)).all()
    }
    seen_in_this_fetch = set()
    added = 0
    skipped = 0
    for entry in entries:
        link = (entry.get("link") or "").strip()
        if not link or link in existing_urls or link in seen_in_this_fetch:
            skipped += 1
            continue
        seen_in_this_fetch.add(link)
        db.add(ArticleSource(
            url=link,
            title=entry.get("title") or "Tanpa Judul",
            source_name=feed.title or feed_title or "RSS",
            raw_content=_entry_text(entry),
        ))
        added += 1

    feed.last_checked_at = datetime.datetime.utcnow()
    db.commit()
    return FeedFetchSummary(
        feed_id=feed.id,
        fetched=len(entries),
        added=added,
        skipped=skipped,
    )


@router.delete("/{feed_id}")
def delete_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Hapus feed. ArticleSource yang sudah diambil tidak ikut dihapus."""
    feed = db.query(FeedSource).filter(FeedSource.id == feed_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed ID {feed_id} tidak ditemukan.")
    db.delete(feed)
    db.commit()
    return {"ok": True, "deleted_id": feed_id}
