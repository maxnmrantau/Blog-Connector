from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models import ApiKey
from app.security import (
    generate_api_key,
    hash_key,
    authenticate_agent_or_session
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & AI Keys"])

class CreateKeyRequest(BaseModel):
    name: str  # Contoh: "AI Agent Gemini" atau "Antigravity Assistant"

class KeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None

class CreateKeyResponse(BaseModel):
    id: int
    name: str
    key: str  # Hanya ditampilkan satu kali saat pembuatan!
    message: str

@router.get("/keys", response_model=List[KeyResponse])
def list_keys(
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Melihat daftar seluruh API Key yang pernah dibuat (hanya prefix yang tampil)."""
    return db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()

@router.post("/keys", response_model=CreateKeyResponse)
def create_key(
    data: CreateKeyRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Membuat API Key baru untuk AI Agent.
    Simpan key ini dengan aman karena tidak dapat dilihat kembali setelah ini!
    """
    raw_key = generate_api_key()
    hashed = hash_key(raw_key)
    prefix = raw_key[:12] + "..."

    new_key = ApiKey(
        name=data.name,
        key_prefix=prefix,
        key_hash=hashed,
        is_active=True
    )
    db.add(new_key)
    db.commit()
    db.refresh(new_key)

    return CreateKeyResponse(
        id=new_key.id,
        name=new_key.name,
        key=raw_key,
        message="API Key berhasil dibuat. Salin dan berikan kepada AI Agent Anda!"
    )

@router.delete("/keys/{key_id}")
def delete_key(
    key_id: int,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Menonaktifkan / mencabut hak akses suatu API Key."""
    key_record = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key_record:
        raise HTTPException(status_code=404, detail="API Key tidak ditemukan.")
    
    db.delete(key_record)
    db.commit()
    return {"status": "success", "message": f"API Key '{key_record.name}' berhasil dicabut."}
