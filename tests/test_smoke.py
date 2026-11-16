"""
Smoke test untuk memastikan rute FastAPI, database, security, dan dashboard berjalan dengan baik
"""
from app.database import init_db, SessionLocal
from app.models import Channel, ArticleSource, ApiKey
from app.schemas import ChannelCreate, IngestRequest
from app.api.routes_channels import create_or_update_channel, get_channel, list_channels, delete_channel
from app.api.routes_ingest import ingest_source
from app.api.routes_auth import create_key, list_keys, delete_key, CreateKeyRequest
from app.security import hash_key, generate_api_key, is_session_valid, create_session_token
from app.main import root, health_check
from fastapi import Request

# Inisialisasi DB untuk testing lokal
init_db()

mock_auth = {"type": "session", "user": "admin"}

def test_auth_and_tokens():
    raw_key = generate_api_key()
    assert raw_key.startswith("bk_live_")
    hashed = hash_key(raw_key)
    assert len(hashed) == 64

    token = create_session_token()
    assert is_session_valid(token) is True
    assert is_session_valid("invalid_token") is False
    print("✅ Security & token tests passed!")

def test_api_keys_crud():
    db = SessionLocal()
    try:
        req = CreateKeyRequest(name="Smoke Test Agent")
        res = create_key(req, db=db, auth=mock_auth)
        assert res.key.startswith("bk_live_")
        assert res.name == "Smoke Test Agent"

        keys = list_keys(db=db, auth=mock_auth)
        assert any(k.id == res.id for k in keys)

        del_res = delete_key(res.id, db=db, auth=mock_auth)
        assert del_res["status"] == "success"
        print("✅ API Keys CRUD tests passed!")
    finally:
        db.close()

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
        
        created = create_or_update_channel(data, db=db, auth=mock_auth)
        assert created.id == "blogger-tech-smoke"
        
        fetched = get_channel("blogger-tech-smoke", db=db, auth=mock_auth)
        assert fetched.niche == "Teknologi & AI"
        
        all_ch = list_channels(db=db, auth=mock_auth)
        assert any(c.id == "blogger-tech-smoke" for c in all_ch)
        
        delete_channel("blogger-tech-smoke", db=db, auth=mock_auth)
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
        res = ingest_source(data, db=db, auth=mock_auth)
        assert res.id is not None
        assert "inovasi kecerdasan buatan" in res.extracted_text_snippet
        print("✅ Ingest flow passed!")
    finally:
        db.close()

if __name__ == "__main__":
    test_auth_and_tokens()
    test_api_keys_crud()
    test_channel_flow()
    test_ingest_flow()
    print("\n🎉 Semua smoke tests (Security, Auth, Dashboard, API) berhasil 100%!")
