"""Penyimpanan kunci API pihak ketiga (Gemini, Pexels) di tabel settings.

Kunci TIDAK PERNAH dikembalikan utuh lewat API dan tidak pernah ditulis
ke log. GET /api/v1/settings/ai hanya mengembalikan status boolean +
petunjuk bermask (4 karakter terakhir) supaya admin tahu kunci mana
yang sudah terisi tanpa melihat isinya.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Setting

GEMINI_API_KEY = "gemini_api_key"
PEXELS_API_KEY = "pexels_api_key"


def get_setting_value(db: Session, key: str) -> Optional[str]:
    """Ambil nilai setting; None bila belum ada atau kosong."""
    row = db.query(Setting).filter(Setting.key == key).first()
    if row and (row.value or "").strip():
        return row.value
    return None


def set_setting_value(db: Session, key: str, value: str) -> None:
    """Simpan/ubah nilai setting (upsert)."""
    row = db.query(Setting).filter(Setting.key == key).first()
    if row is None:
        row = Setting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


def delete_setting_value(db: Session, key: str) -> None:
    """Hapus satu setting (dipakai untuk mengosongkan kunci)."""
    row = db.query(Setting).filter(Setting.key == key).first()
    if row is not None:
        db.delete(row)
        db.commit()


def masked_hint(value: Optional[str]) -> Optional[str]:
    """Petunjuk aman untuk menampilkan status kunci: 4 karakter
    terakhir saja, mis. '••••abcd'. None bila tidak ada kunci."""
    if not value or len(value) < 4:
        return None
    return "••••" + value[-4:]
