"""
Smoke test untuk memastikan rute FastAPI, database, dan logika platform berjalan dengan baik
"""
from app.database import init_db, SessionLocal, get_db
from app.models import Channel, ArticleSource
from app.schemas import ChannelCreate, IngestRequest
from app.api.routes_channels import create_or_update_channel, get_channel, list_channels, delete_channel
from app.api.routes_ingest import ingest_source
from app.main import root, health_check

# Inisialisasi DB untuk testing lokal
init_db()

def test_root_and_health():
    r = root()
    assert r["status"] == "online"
    h = health_check()
    assert h["status"] == "healthy"
    print("✅ Root and health check passed!")

def test_channel_flow():
    db = SessionLocal()
    try:
        data = ChannelCreate(
            id="blogger-tech-smoke",
            name="Smoke Test Blogger",
            platform="blogger",
            credentials={
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "refresh_token": "dummy_refresh_token",
                "blog_id": "123456789"
            },
            niche="Teknologi & AI",
            target_audience="Developer",
            tone_of_voice="Santai",
            target_word_count=700,
            default_labels="AI,Tech"
        )
        
        created = create_or_update_channel(data, db=db)
        assert created.id == "blogger-tech-smoke"
        
        fetched = get_channel("blogger-tech-smoke", db=db)
        assert fetched.niche == "Teknologi & AI"
        
        all_ch = list_channels(db=db)
        assert any(c.id == "blogger-tech-smoke" for c in all_ch)
        
        delete_channel("blogger-tech-smoke", db=db)
        print("✅ Channel CRUD flow passed!")
    finally:
        db.close()

def test_ingest_flow():
    db = SessionLocal()
    try:
        data = IngestRequest(
            source_name="Uji Coba Media",
            raw_text="Berita uji coba tentang inovasi kecerdasan buatan dan integrasi Google Blogger API v3."
        )
        res = ingest_source(data, db=db)
        assert res.id is not None
        assert "inovasi kecerdasan buatan" in res.extracted_text_snippet
        print("✅ Ingest flow passed!")
    finally:
        db.close()

if __name__ == "__main__":
    test_root_and_health()
    test_channel_flow()
    test_ingest_flow()
    print("\n🎉 Semua smoke tests berhasil 100%!")
