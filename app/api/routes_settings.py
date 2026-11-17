"""Endpoint pengaturan kunci API AI (Gemini, OpenAI, Pexels).

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
memungkinkan admin menguji kunci provider AKTIF yang tersimpan kapan
saja tanpa menunggu fitur dipakai.
"""
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import authenticate_agent_or_session
from app.services.rewrite import (
    DEFAULT_MODEL,
    DEFAULT_OPENAI_MODEL,
    GeminiError,
    OpenAIError,
    generate_text,
    generate_text_openai,
)
from app.services.settings import (
    AI_PROVIDER,
    GEMINI_API_KEY,
    OPENAI_API_KEY,
    OPENAI_MODEL,
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
    ai_provider: Optional[str] = Field(default=None, max_length=20)
    openai_api_key: Optional[str] = Field(default=None, max_length=500)
    openai_model: Optional[str] = Field(default=None, max_length=100)


class AiSettingsStatus(BaseModel):
    gemini_configured: bool
    gemini_hint: Optional[str] = None
    pexels_configured: bool
    pexels_hint: Optional[str] = None
    ai_provider: str = "gemini"
    openai_configured: bool = False
    openai_hint: Optional[str] = None
    openai_model: str = DEFAULT_OPENAI_MODEL


class AiTestResult(BaseModel):
    ok: bool
    provider: str = "gemini"
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


# Nama lama (kompatibilitas): hasil tes dulunya khusus Gemini.
GeminiTestResult = AiTestResult


def _tech_detail(raw: str, prefix: str) -> str:
    """Ambil detail teknis mentah dari pesan error provider.

    Pesan generate_* berbentuk "Tidak dapat menghubungi X API: <detail
    httpx>" — bagian setelah ": " adalah jenis error transport
    (ConnectError/Timeout/dsb.) tanpa kunci apa pun (kunci hanya ada
    di header, bukan di URL/pesan). Dipakai supaya diagnosis jaringan
    lebih mudah tanpa menampilkan mentahan Google/OpenAI.
    """
    if prefix and raw.startswith(prefix):
        return raw[len(prefix):].strip()
    return raw


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
            "atau pasang billing (berbayar, kuota gratis hilang). "
            "Alternatif lain: pindah ke provider OpenAI di Pengaturan AI."
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
        tech = _tech_detail(raw, "Tidak dapat menghubungi Gemini API: ")
        return (
            "Tidak dapat menghubungi Gemini API (jaringan/timeout). "
            "Periksa koneksi server lalu coba lagi."
            + (f" Detail teknis: {tech}" if tech and tech != raw else "")
        )
    return raw or "Tes kunci Gemini gagal tanpa pesan yang jelas."


def _map_openai_error(e: OpenAIError) -> str:
    """Terjemahkan OpenAIError menjadi pesan Indonesia yang jelas.

    Isi kunci tidak pernah ada di pesan ini (kunci hanya dikirim di
    header Authorization). OpenAI berbayar dari token pertama — tidak
    ada free tier — jadi sebagian error berkaitan dengan saldo/billing.
    """
    raw = str(e) or ""
    low = raw.lower()
    if e.status_code == 401 or "invalid_api_key" in low or "incorrect api key" in low:
        return (
            "Kunci OpenAI tidak valid atau ditolak (HTTP 401). Periksa "
            "kunci yang ditempel di Pengaturan AI — pastikan disalin utuh "
            "tanpa spasi, dan kunci itu dibuat di platform.openai.com "
            "(API Keys)."
        )
    if e.status_code == 429 or "insufficient_quota" in low or "quota" in low:
        return (
            "Kuota/saldo OpenAI habis atau rate limit tercapai (HTTP 429). "
            "Periksa billing/saldo di platform.openai.com (Billing) dan "
            "tambah saldo bila perlu. OpenAI berbayar dari token pertama "
            "— tidak ada free tier."
        )
    if e.status_code == 400 or "model_not_found" in low:
        return (
            "Permintaan ke OpenAI ditolak (HTTP 400). Kemungkinan model "
            "yang dipakai tidak tersedia untuk kunci ini — periksa pilihan "
            "model OpenAI di Pengaturan AI (mis. gpt-4o-mini)."
        )
    if "tidak dapat menghubungi" in low:
        tech = _tech_detail(raw, "Tidak dapat menghubungi OpenAI API: ")
        return (
            "Tidak dapat menghubungi OpenAI API (jaringan/timeout). "
            "Periksa koneksi server lalu coba lagi."
            + (f" Detail teknis: {tech}" if tech and tech != raw else "")
        )
    return raw or "Tes kunci OpenAI gagal tanpa pesan yang jelas."


def _active_provider(db: Session) -> str:
    """Provider AI aktif dari settings; "gemini" bila kosong/tak dikenal."""
    provider = (get_setting_value(db, AI_PROVIDER) or "gemini").strip().lower()
    return provider if provider in ("gemini", "openai") else "gemini"


def _status(db: Session) -> AiSettingsStatus:
    gemini = get_setting_value(db, GEMINI_API_KEY)
    pexels = get_setting_value(db, PEXELS_API_KEY)
    openai = get_setting_value(db, OPENAI_API_KEY)
    return AiSettingsStatus(
        gemini_configured=bool(gemini),
        gemini_hint=masked_hint(gemini),
        pexels_configured=bool(pexels),
        pexels_hint=masked_hint(pexels),
        ai_provider=_active_provider(db),
        openai_configured=bool(openai),
        openai_hint=masked_hint(openai),
        openai_model=get_setting_value(db, OPENAI_MODEL) or DEFAULT_OPENAI_MODEL,
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
    if payload.ai_provider is not None:
        provider = payload.ai_provider.strip().lower()
        if provider not in ("gemini", "openai"):
            raise HTTPException(
                status_code=422,
                detail="Provider AI tidak dikenal. Pilih 'gemini' atau 'openai'.",
            )
        set_setting_value(db, AI_PROVIDER, provider)
    if payload.openai_api_key is not None:
        value = payload.openai_api_key.strip()
        if value:
            set_setting_value(db, OPENAI_API_KEY, value)
        else:
            delete_setting_value(db, OPENAI_API_KEY)
    if payload.openai_model is not None:
        value = payload.openai_model.strip()
        if value:
            set_setting_value(db, OPENAI_MODEL, value)
        else:
            delete_setting_value(db, OPENAI_MODEL)
    return _status(db)


@router.post("/ai/test", response_model=AiTestResult)
def test_ai_key(
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Uji kunci provider AI AKTIF yang tersimpan dengan satu panggilan kecil.

    Mengembalikan {ok: true, provider, model, latency_ms} bila kunci
    berfungsi. Bila kunci provider aktif belum dikonfigurasi → HTTP 400
    yang jelas. Bila panggilan gagal → {ok: false, provider, model,
    error} dengan pesan yang sudah dipetakan (bukan mentahan provider).
    Kunci tidak pernah dikembalikan atau ditulis ke log.
    """
    provider = _active_provider(db)
    if provider == "openai":
        api_key = get_setting_value(db, OPENAI_API_KEY)
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Kunci OpenAI belum dikonfigurasi. Tempel kunci di "
                    "Pengaturan AI dulu, simpan, lalu tekan Tes Kunci."
                ),
            )
        model = get_setting_value(db, OPENAI_MODEL) or DEFAULT_OPENAI_MODEL
        started = time.monotonic()
        try:
            generate_text_openai(
                api_key,
                "Balas hanya dengan kata: OK",
                model=model,
                max_output_tokens=16,
            )
        except OpenAIError as e:
            return AiTestResult(
                ok=False, provider="openai", model=model,
                error=_map_openai_error(e),
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        return AiTestResult(
            ok=True, provider="openai", model=model, latency_ms=latency_ms
        )

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
        return AiTestResult(
            ok=False, provider="gemini", model=model,
            error=_map_gemini_error(e),
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    return AiTestResult(
        ok=True, provider="gemini", model=model, latency_ms=latency_ms
    )
