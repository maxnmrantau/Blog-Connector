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
yang jelas bila kunci salah atau belum diisi. Endpoint /ai/test
memungkinkan admin menguji kunci Gemini yang tersimpan kapan saja
tanpa menunggu fitur dipakai.
"""
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import authenticate_agent_or_session
from app.services.rewrite import DEFAULT_MODEL, GeminiError, generate_text
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


class GeminiTestResult(BaseModel):
    ok: bool
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


def _map_gemini_error(e: GeminiError) -> str:
    """Terjemahkan GeminiError menjadi pesan Indonesia yang jelas.

    Pesan mentah Google tidak ditampilkan apa adanya: penyebab yang
    umum dipetakan ke penjelasan + langkah perbaikan. Isi kunci
    tidak pernah ada di pesan ini (kunci hanya dikirim di header).
    """
    raw = str(e) or ""
    low = raw.lower()
    if "free tier is not available" in low:
        return (
            "Free tier dikunci untuk proyek kunci Gemini ini (Google: "
            "\"free tier is not available for this project\"). Kunci baru "
            "di proyek yang sama akan gagal dengan cara yang sama — "
            "buatlah kunci baru di PROYEK BARU di Google AI Studio "
            "(Get API key → Create API key → Create new project), lalu "
            "tempel kunci itu di sini. Alternatif: lengkapi verifikasi "
            "umur + nomor HP + verifikasi 2 langkah di akun Google itu, "
            "atau pasang billing (berbayar, kuota gratis hilang)."
        )
    if e.status_code in (401, 403) or "api key not valid" in low or "api_key_invalid" in low:
        return (
            "Kunci Gemini tidak valid atau ditolak Google (HTTP "
            f"{e.status_code or '401'}). Periksa kunci yang ditempel di "
            "Pengaturan AI — pastikan disalin utuh tanpa spasi, dan kunci "
            "itu dibuat di Google AI Studio."
        )
    if e.status_code == 400:
        return (
            "Permintaan ke Gemini ditolak (HTTP 400). Kemungkinan model "
            "yang dipakai tidak tersedia — periksa setting model di "
            "Pengaturan AI."
        )
    if "tidak dapat menghubungi" in low:
        return (
            "Tidak dapat menghubungi Gemini API (jaringan/timeout). "
            "Periksa koneksi server lalu coba lagi."
        )
    return raw or "Tes kunci Gemini gagal tanpa pesan yang jelas."


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


@router.post("/ai/test", response_model=GeminiTestResult)
def test_gemini_key(
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Uji kunci Gemini yang tersimpan dengan satu panggilan kecil.

    Mengembalikan {ok: true, model, latency_ms} bila kunci berfungsi.
    Bila kunci belum dikonfigurasi → HTTP 400 yang jelas. Bila
    panggilan Gemini gagal → {ok: false, error} dengan pesan yang
    sudah dipetakan (bukan mentahan Google). Kunci tidak pernah
    dikembalikan atau ditulis ke log.
    """
    api_key = get_setting_value(db, GEMINI_API_KEY)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "Kunci Gemini belum dikonfigurasi. Tempel kunci di "
                "Pengaturan AI dulu, simpan, lalu tekan Tes Kunci."
            ),
        )
    model = get_setting_value(db, "gemini_model") or DEFAULT_MODEL
    started = time.monotonic()
    try:
        generate_text(
            api_key,
            "Balas hanya dengan kata: OK",
            model=model,
            max_output_tokens=16,
        )
    except GeminiError as e:
        return GeminiTestResult(
            ok=False, model=model, error=_map_gemini_error(e)
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    return GeminiTestResult(ok=True, model=model, latency_ms=latency_ms)
