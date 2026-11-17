"""Endpoint pengaturan kunci API AI (Gemini, Pexels).

Keamanan:
- GET hanya mengembalikan status boolean "terkonfigurasi" + petunjuk
  bermask (4 karakter terakhir). Nilai kunci TIDAK PERNAH dikembalikan.
- POST hanya menyimpan field yang dikirim dan tidak kosong. Field yang
  dikirim sebagai string kosong berarti HAPUS kunci yang tersimpan.
- Nilai kunci tidak pernah ditulis ke log di mana pun.
- Kunci TIDAK ikut di-export oleh backup (backup hanya mengekspor
  channels tanpa kredensial, publications, dan pages).

Kunci belum divalidasi ke provider saat disimpan — validasi terjadi
saat fitur dipakai (Auto-Rewrite / Image Picker), dengan pesan error
yang jelas bila kunci salah atau belum diisi.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import authenticate_agent_or_session
from app.services.settings import (
    GEMINI_API_KEY,
    PEXELS_API_KEY,
    delete_setting_value,
    get_setting_value,
    masked_hint,
    set_setting_value,
)

router = APIRouter(prefix="/api/v1/settings", tags=["Pengaturan"])


class AiSettingsUpdate(BaseModel):
    gemini_api_key: Optional[str] = Field(default=None, max_length=500)
    pexels_api_key: Optional[str] = Field(default=None, max_length=500)


class AiSettingsStatus(BaseModel):
    gemini_configured: bool
    gemini_hint: Optional[str] = None
    pexels_configured: bool
    pexels_hint: Optional[str] = None


def _status(db: Session) -> AiSettingsStatus:
    gemini = get_setting_value(db, GEMINI_API_KEY)
    pexels = get_setting_value(db, PEXELS_API_KEY)
    return AiSettingsStatus(
        gemini_configured=bool(gemini),
        gemini_hint=masked_hint(gemini),
        pexels_configured=bool(pexels),
        pexels_hint=masked_hint(pexels),
    )


@router.get("/ai", response_model=AiSettingsStatus)
def get_ai_settings(
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Status kunci AI: hanya boolean + petunjuk bermask, bukan nilainya."""
    return _status(db)


@router.post("/ai", response_model=AiSettingsStatus)
def save_ai_settings(
    payload: AiSettingsUpdate,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Simpan kunci AI. Hanya field yang dikirim yang diubah; string
    kosong berarti hapus kunci tersebut. Field yang tidak dikirim
    dibiarkan apa adanya."""
    if payload.gemini_api_key is not None:
        value = payload.gemini_api_key.strip()
        if value:
            set_setting_value(db, GEMINI_API_KEY, value)
        else:
            delete_setting_value(db, GEMINI_API_KEY)
    if payload.pexels_api_key is not None:
        value = payload.pexels_api_key.strip()
        if value:
            set_setting_value(db, PEXELS_API_KEY, value)
        else:
            delete_setting_value(db, PEXELS_API_KEY)
    return _status(db)
