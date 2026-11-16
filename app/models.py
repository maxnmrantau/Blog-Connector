import datetime
import json
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base

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

    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    channel = relationship("Channel", back_populates="publications")
    source = relationship("ArticleSource", back_populates="publications")
