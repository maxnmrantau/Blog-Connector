from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

# --- Schemas untuk Channel ---
class ChannelCreate(BaseModel):
    id: str = Field(..., description="ID unik channel, contoh: 'blogger-tech-01'")
    name: str = Field(..., description="Nama display blog, contoh: 'Blog Teknologi'")
    platform: str = Field(..., description="'blogger' atau 'wordpress'")
    credentials: dict = Field(..., description="Kredensial API")
    niche: str = Field(..., description="Niche blog, contoh: 'Teknologi & AI'")
    target_audience: Optional[str] = Field("Umum", description="Target audiens")
    tone_of_voice: Optional[str] = Field("Informatif & Santai", description="Gaya bahasa")
    target_word_count: Optional[int] = Field(800, description="Target jumlah kata")
    default_labels: Optional[str] = Field(None, description="Label default dipisah koma")

class ChannelUpdate(BaseModel):
    """Partial update pengaturan artikel sebuah channel (hanya field yang dikirim yang diubah)."""
    niche: Optional[str] = None
    tone_of_voice: Optional[str] = None
    target_word_count: Optional[int] = Field(default=None, gt=0)
    default_labels: Optional[str] = None


class ChannelResponse(BaseModel):
    id: str
    name: str
    platform: str
    blog_id: Optional[str] = None
    blog_url: Optional[str] = None
    niche: str
    target_audience: Optional[str]
    tone_of_voice: Optional[str]
    target_word_count: int
    default_labels: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# --- Schemas untuk Ingesti Sumber Berita ---
class IngestRequest(BaseModel):
    url: Optional[str] = None
    source_name: Optional[str] = None
    raw_text: Optional[str] = None

class IngestResponse(BaseModel):
    id: int
    url: Optional[str]
    title: Optional[str]
    source_name: Optional[str]
    extracted_text_snippet: str
    ingested_at: datetime


# --- Schemas untuk RSS Feed (antrean rewrite) ---
class FeedSourceCreate(BaseModel):
    channel_id: str
    feed_url: str
    title: Optional[str] = None

class FeedSourceResponse(BaseModel):
    id: int
    channel_id: str
    feed_url: str
    title: Optional[str] = None
    active: bool = True
    last_checked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class FeedFetchSummary(BaseModel):
    feed_id: int
    fetched: int  # jumlah item yang dibaca dari feed
    added: int    # item baru yang disimpan sebagai ArticleSource
    skipped: int  # item yang sudah ada (duplikat) atau tanpa URL


# --- Schemas untuk Publikasi ---
class ArticleItem(BaseModel):
    channel_id: str
    title: str
    content_html: str
    slug: Optional[str] = None
    meta_description: Optional[str] = None
    labels: Optional[List[str]] = Field(default_factory=list)
    status: Optional[str] = Field("draft", description="'draft' atau 'publish'")
    # Gambar sampul: HARUS berupa URL yang sudah di-host (misal di
    # Blogger/Drive/CDN). Blogger API v3 tidak menyediakan upload gambar.
    cover_image_url: Optional[str] = None
    cover_image_alt: Optional[str] = None
    # Jadwal terbit (opsional). Kalau diisi dengan waktu di masa depan,
    # artikel dijadwalkan lewat Blogger API: dibuat sebagai draf lalu
    # posts().publish(publishDate=...) — lihat routes_publish.py.
    # Nilai naive dianggap waktu WIB (zona blog). Kalau di masa lalu,
    # diabaikan dan artikel diproses normal (draf/publish).
    scheduled_at: Optional[datetime] = None

class ArticleUpdate(BaseModel):
    """Partial update sebuah publikasi (judul dan/atau konten baru).
    Minimal salah satu dari title / content_html harus diisi."""
    title: Optional[str] = None
    content_html: Optional[str] = None
    cover_image_url: Optional[str] = None
    cover_image_alt: Optional[str] = None

class PublishRequest(BaseModel):
    source_id: Optional[int] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    publications: List[ArticleItem]

class PublicationResult(BaseModel):
    channel_id: str
    channel_name: str
    platform: str
    status: str
    title: str
    remote_post_id: Optional[str] = None
    remote_url: Optional[str] = None
    error_message: Optional[str] = None

class PublishBatchResponse(BaseModel):
    total: int
    successful: int
    failed: int
    results: List[PublicationResult]
