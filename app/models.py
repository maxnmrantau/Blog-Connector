import datetime
import json
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base

class Setting(Base):
    """
    Pengaturan key/value — dipakai untuk menyimpan kunci API pihak
    ketiga (mis. gemini_api_key, pexels_api_key) yang dibutuhkan
    fitur otomatis. Nilai kunci TIDAK PERNAH dikembalikan utuh lewat
    API (lihat routes_settings) dan tidak ikut di-export backup.
    """
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ApiKey(Base):
    """
    Menyimpan API Key untuk AI Agent / integrasi eksternal.
    Hanya hash SHA-256 yang disimpan untuk keamanan maksimal.
    """
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    key_prefix = Column(String(16), nullable=False)  # Contoh: "bk_a1b2c3..."
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)


class Channel(Base):
    """
    Menyimpan profil blog tujuan (WordPress / Blogger),
    kredensial API, serta panduan persona/niche untuk AI.
    """
    __tablename__ = "channels"

    id = Column(String(50), primary_key=True)  # contoh: 'blogger-tech-01', 'wp-bisnis'
    name = Column(String(100), nullable=False)
    platform = Column(String(20), nullable=False)  # 'blogger' atau 'wordpress'
    
    # Alamat blog Blogger yang sebenarnya, diisi dari credentials.blog_id
    # dan dari Blogger API listByUser saat Test. Tanpa ini, dashboard dan
    # API tidak pernah bisa menampilkan alamat .blogspot.com channel.
    blog_id = Column(String(50), nullable=True)
    blog_url = Column(String(500), nullable=True)

    # Kredensial disimpan dalam JSON
    credentials_json = Column(Text, nullable=False, default="{}")

    # Profil Niche & Persona AI
    niche = Column(String(100), nullable=False)
    target_audience = Column(String(150), nullable=True)
    tone_of_voice = Column(String(100), nullable=True)
    target_word_count = Column(Integer, default=800)
    default_labels = Column(String(255), nullable=True)

    # Auto-publish terjadwal: bila True, scheduler tick menerbitkan
    # publikasi berstatus scheduled yang sudah jatuh tempo di channel ini.
    # Default False — admin mengaktifkannya per channel dari dashboard.
    auto_publish = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    publications = relationship("Publication", back_populates="channel", cascade="all, delete-orphan")

    def get_credentials(self) -> dict:
        try:
            return json.loads(self.credentials_json)
        except Exception:
            return {}

    def set_credentials(self, creds: dict):
        self.credentials_json = json.dumps(creds)


class TopicIdea(Base):
    """
    Perpustakaan ide topik (Ide Topik v2): ide yang disimpan dari
    endpoint /ideas (atau dibuat manual) supaya bisa dipakai,
    dibuang, atau dibuatkan kerangka nanti.

    status: 'baru' (belum diproses), 'dipakai' (sudah jadi draf/artikel),
    'dibuang' (ditolak admin). Ide berstatus dipakai/dibuang TIDAK
    muncul lagi sebagai ide baru di GET /ideas. title_norm dipakai
    dedupe (judul sama, huruf besar/kecil dan spasi diabaikan).
    """
    __tablename__ = "topic_ideas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(50), ForeignKey("channels.id"), nullable=False)
    title = Column(String(300), nullable=False)
    title_norm = Column(String(300), nullable=False, index=True)
    keyword = Column(String(200), nullable=True)
    source = Column(String(30), nullable=True)
    score = Column(Integer, default=50)
    reason = Column(Text, nullable=True)
    angle = Column(Text, nullable=True)
    keywords = Column(String(255), nullable=True)  # dipisah koma
    source_url = Column(String(500), nullable=True)
    source_title = Column(String(300), nullable=True)
    status = Column(String(20), default="baru")
    publication_id = Column(Integer, ForeignKey("publications.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    channel = relationship("Channel")


class ArticleSource(Base):
    """
    Menyimpan riwayat sumber artikel asli yang di-ingest (baik via URL maupun RSS)
    """
    __tablename__ = "article_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(500), nullable=True, index=True)
    title = Column(String(300), nullable=True)
    source_name = Column(String(100), nullable=True)
    raw_content = Column(Text, nullable=False)
    ingested_at = Column(DateTime, default=datetime.datetime.utcnow)

    publications = relationship("Publication", back_populates="source")


class FeedSource(Base):
    """
    Menyimpan sumber RSS/Atom yang dipantau per channel.
    Fetch dilakukan on-demand (tanpa cron/background scheduler) karena
    deploy di Vercel serverless tidak punya cron persisten.
    """
    __tablename__ = "feed_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(50), ForeignKey("channels.id"), nullable=False)
    feed_url = Column(String(500), nullable=False)
    title = Column(String(300), nullable=True)
    active = Column(Boolean, default=True)
    last_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    channel = relationship("Channel")


class Publication(Base):
    """
    Menyimpan catatan hasil posting/draf ke masing-masing channel/blog
    """
    __tablename__ = "publications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("article_sources.id"), nullable=True)
    channel_id = Column(String(50), ForeignKey("channels.id"), nullable=False)

    title = Column(String(300), nullable=False)
    slug = Column(String(300), nullable=True)
    meta_description = Column(String(255), nullable=True)
    content_html = Column(Text, nullable=False)
    labels = Column(String(255), nullable=True)

    status = Column(String(20), default="draft")  # 'draft', 'published', 'failed', 'scheduled'
    remote_post_id = Column(String(100), nullable=True)
    remote_url = Column(String(500), nullable=True)
    error_message = Column(Text, nullable=True)
    # Waktu terbit yang dijadwalkan (hanya untuk status 'scheduled').
    # Disimpan sebagai waktu lokal WIB tanpa tzinfo, sama seperti yang
    # dipilih di dashboard (datetime-local) — jadi tampilannya cocok.
    scheduled_at = Column(DateTime, nullable=True)

    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    channel = relationship("Channel", back_populates="publications")
    source = relationship("ArticleSource", back_populates="publications")
