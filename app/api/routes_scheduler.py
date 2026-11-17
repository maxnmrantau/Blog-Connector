"""Endpoint scheduler: tick auto-publish + status.

KEAMANAN TICK — keputusan desain (baca laporan patch 5):
- Vercel Cron memanggil endpoint dengan GET dan otomatis mengirim header
  `Authorization: Bearer <CRON_SECRET>`. Tick menerima itu bila token
  cocok dengan env CRON_SECRET. Tanpa CRON_SECRET di env, jalur ini
  selalu ditolak (fail closed).
- Pemicu manual (dashboard / AI agent / curl) memakai auth normal
  konektor: header x-api-key atau sesi dashboard.
- TIDAK ADA `?key=` di URL: secret di query string tercatat di access
  log dan log Vercel. Pemicu manual lewat curl memakai header
  `-H "x-api-key: <kunci>"` atau `-H "Authorization: Bearer $CRON_SECRET"`.
"""
import os

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import authenticate_agent_or_session
from app.services import scheduler as scheduler_service

router = APIRouter(prefix="/api/v1/scheduler", tags=["Scheduler"])


def _cron_authorized(request: Request) -> bool:
    """True bila header Authorization cocok dengan env CRON_SECRET."""
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        return False
    return request.headers.get("authorization", "") == f"Bearer {secret}"


def _authorize_tick(request: Request, db: Session):
    """Izinkan tick bila: (a) cron Vercel dengan Bearer CRON_SECRET, atau
    (b) auth normal konektor (x-api-key / sesi dashboard)."""
    if _cron_authorized(request):
        return {"type": "cron"}
    x_api_key = request.headers.get("x-api-key")
    return authenticate_agent_or_session(request, x_api_key, db)


@router.get("/status")
def scheduler_status(
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Status scheduler untuk dashboard: tick terakhir + antrean jatuh tempo."""
    status = scheduler_service.get_status(db)
    status["cron_configured"] = bool(os.environ.get("CRON_SECRET"))
    return status


@router.get("/tick")
@router.post("/tick")
def scheduler_tick(request: Request, db: Session = Depends(get_db)):
    """Jalankan satu tick auto-publish.

    GET dipakai Vercel Cron (dengan header Bearer CRON_SECRET);
    POST dipakai pemicu manual (dengan x-api-key / sesi dashboard).
    """
    _authorize_tick(request, db)
    return scheduler_service.run_tick(db)
