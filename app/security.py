import os
import secrets
import hashlib
import datetime
from typing import Optional
from fastapi import Header, Request, HTTPException, status, Depends
from sqlalchemy.orm import Session
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.database import get_db

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.getenv("SECRET_KEY", "blog-konektor-secret-key-2026")
COOKIE_NAME = "bk_session"

serializer = URLSafeTimedSerializer(SECRET_KEY)

def hash_key(raw_key: str) -> str:
    """Meng-hash API Key dengan SHA-256."""
    return hashlib.sha256(raw_key.encode()).hexdigest()

def generate_api_key() -> str:
    """Membuat raw API Key baru berformat 'bk_live_...'"""
    return f"bk_live_{secrets.token_urlsafe(32)}"

def verify_admin_password(password: str) -> bool:
    """Memverifikasi password admin."""
    return password == ADMIN_PASSWORD

def create_session_token() -> str:
    """Membuat session token bertanda tangan kriptografis."""
    return serializer.dumps({"auth": True, "created_at": datetime.datetime.utcnow().isoformat()})

def is_session_valid(session_token: Optional[str]) -> bool:
    """Memeriksa keabsahan session token (maks 7 hari)."""
    if not session_token:
        return False
    try:
        data = serializer.loads(session_token, max_age=86400 * 7)
        return data.get("auth") is True
    except (BadSignature, SignatureExpired, Exception):
        return False

def authenticate_agent_or_session(
    request: Request,
    x_api_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Dependency gabungan:
    Mengizinkan akses jika membawa X-API-Key valid (untuk AI Agent)
    ATAU membawa cookie session aktif (untuk pengguna di dashboard browser).
    """
    # 1. Cek Cookie Sesi Browser
    session_token = request.cookies.get(COOKIE_NAME)
    if is_session_valid(session_token):
        return {"type": "session", "user": "admin"}

    # 2. Cek Header X-API-Key (AI Agent)
    if x_api_key:
        from app.models import ApiKey
        # Cek master override via env (opsional untuk kemudahan)
        master_key = os.getenv("MASTER_API_KEY")
        if master_key and x_api_key == master_key:
            return {"type": "master_key", "name": "Master Admin"}

        hashed = hash_key(x_api_key)
        key_record = db.query(ApiKey).filter(
            ApiKey.key_hash == hashed,
            ApiKey.is_active == True
        ).first()

        if key_record:
            key_record.last_used_at = datetime.datetime.utcnow()
            db.commit()
            return {"type": "api_key", "name": key_record.name}

    # Jika keduanya tidak valid
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Akses ditolak: Masukkan X-API-Key yang valid atau login ke dashboard."
    )
