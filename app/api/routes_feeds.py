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
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

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


# --- RSS discovery (Cari RSS dari Website) ---------------------------
# Tempel URL website (bukan URL feed): halaman diambil, dicari
# <link rel="alternate" type="application/rss+xml|atom+xml">, lalu bila
# tidak ada dicoba jalur umum (/feed, /rss, ...). Tiap kandidat
# divalidasi dengan feedparser sebelum dikembalikan. Discovery HANYA
# membaca — tidak menyimpan apa pun; penyimpanan tetap lewat
# POST /api/v1/feeds (tombol "Simpan sebagai Feed" di dashboard).

DISCOVER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)
DISCOVER_TIMEOUT = 10.0
DISCOVER_MAX_FOUND = 5
COMMON_FEED_PATHS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml")
FEED_LINK_TYPES = {
    "application/rss+xml": "rss",
    "application/atom+xml": "atom",
}


class _FeedLinkParser(HTMLParser):
    """Kumpulkan <link rel="alternate" type="...rss/atom+xml" href="...">."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        attrs = dict(attrs)
        if "alternate" not in (attrs.get("rel") or "").lower():
            return
        feed_type = FEED_LINK_TYPES.get(
            (attrs.get("type") or "").lower().strip())
        if not feed_type:
            return
        href = (attrs.get("href") or "").strip()
        if href:
            self.links.append(
                (href, feed_type, (attrs.get("title") or "").strip() or None))


def _parse_feed_bytes(content: bytes):
    """Kembalikan (valid, title, type) dari isi yang diduga feed.

    Valid bila feedparser menemukan entri atau judul feed — halaman
    HTML biasa / 404 tidak lolos (tanpa entri dan tanpa judul).
    """
    if feedparser is None:
        return False, None, None
    try:
        parsed = feedparser.parse(content)
    except Exception:
        return False, None, None
    feed = parsed.get("feed") or {}
    title = feed.get("title") or None
    entries = parsed.get("entries") or []
    version = (parsed.get("version") or "").lower()
    feed_type = "atom" if version.startswith("atom") else "rss"
    valid = bool(entries) or bool(title)
    return valid, title, feed_type


def _fetch_candidate(client, url):
    """GET satu kandidat; kembalikan response bila HTTP 200, else None."""
    try:
        resp = client.get(url)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return resp


class DiscoverRequest(BaseModel):
    url: str


class DiscoveredFeed(BaseModel):
    url: str
    title: Optional[str] = None
    type: str = "rss"


class DiscoverResponse(BaseModel):
    ok: bool = True
    found: List[DiscoveredFeed] = []
    message: str = ""


@router.post("/discover", response_model=DiscoverResponse)
def discover_feeds(
    data: DiscoverRequest,
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Cari feed RSS/Atom milik sebuah website (hanya membaca)."""
    url = (data.url or "").strip()
    if not _is_valid_feed_url(url):
        raise HTTPException(
            status_code=400,
            detail="URL wajib berupa alamat website http(s) yang valid.",
        )
    if feedparser is None:
        raise HTTPException(
            status_code=503,
            detail="feedparser belum terpasang di server.",
        )
    try:
        client = httpx.Client(
            timeout=DISCOVER_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DISCOVER_USER_AGENT},
        )
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"Gagal membuka website: {e}")
    found = []
    seen = set()
    try:
        try:
            resp = client.get(url)
        except Exception:
            raise HTTPException(
                status_code=502,
                detail=f"Tidak dapat membuka website {url} "
                       "(koneksi gagal atau timeout).",
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Website menjawab HTTP {resp.status_code} "
                       f"untuk {url}.",
            )
        page_url = str(resp.url)
        content_type = (resp.headers.get("content-type") or "").lower()
        # Bila URL yang ditempel ternyata LANGSUNG sebuah feed, kembalikan.
        if "xml" in content_type or "rss" in content_type or "atom" in content_type:
            valid, title, feed_type = _parse_feed_bytes(resp.content)
            if valid:
                return DiscoverResponse(
                    ok=True,
                    found=[DiscoveredFeed(
                        url=page_url, title=title, type=feed_type)],
                    message="URL yang ditempel ternyata sudah berupa "
                            "feed RSS/Atom.",
                )
        # Cari <link rel="alternate"> di HTML.
        parser = _FeedLinkParser()
        try:
            parser.feed(resp.text)
        except Exception:
            parser.links = []
        candidates = [
            (urljoin(page_url, href), feed_type, title)
            for href, feed_type, title in parser.links
        ]
        for cand_url, feed_type, title in candidates:
            if len(found) >= DISCOVER_MAX_FOUND or cand_url in seen:
                continue
            seen.add(cand_url)
            cand_resp = _fetch_candidate(client, cand_url)
            if cand_resp is None:
                continue
            valid, parsed_title, parsed_type = _parse_feed_bytes(
                cand_resp.content)
            if valid:
                found.append(DiscoveredFeed(
                    url=cand_url,
                    title=title or parsed_title,
                    type=parsed_type or feed_type,
                ))
        # Bila tidak ada dari <link>, coba jalur umum.
        if not found:
            for path in COMMON_FEED_PATHS:
                if len(found) >= DISCOVER_MAX_FOUND:
                    break
                cand_url = urljoin(page_url, path)
                if cand_url in seen:
                    continue
                seen.add(cand_url)
                cand_resp = _fetch_candidate(client, cand_url)
                if cand_resp is None:
                    continue
                valid, parsed_title, parsed_type = _parse_feed_bytes(
                    cand_resp.content)
                if valid:
                    found.append(DiscoveredFeed(
                        url=cand_url, title=parsed_title, type=parsed_type))
    finally:
        client.close()
    if found:
        return DiscoverResponse(
            ok=True, found=found,
            message=f"Ditemukan {len(found)} feed di website ini.",
        )
    return DiscoverResponse(
        ok=True, found=[],
        message="Tidak ditemukan feed RSS di website ini. Coba alamat lain, "
                "atau tempel langsung URL feed-nya di form Tambah Feed.",
    )


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
