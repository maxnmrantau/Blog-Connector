"""Endpoint Search Console: GET /api/v1/search-console/overview.

Bila kredensial OAuth belum punya scope Search Console, endpoint
mengembalikan 403 dengan pesan yang jelas ("hubungkan ulang OAuth
dengan scope Search Console") — bukan data kosong.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Channel
from app.security import authenticate_agent_or_session
from app.services.search_console import SearchConsoleError, get_overview

router = APIRouter(prefix="/api/v1/search-console", tags=["Search Console"])


@router.get("/overview")
def search_console_overview(
    channel_id: str = Query(..., description="ID channel"),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Ringkasan Search Console: 10 kueri teratas (28 hari) + sitemap.

    Respons: {site_url, connected, scope_ok, date_range, top_queries[],
    totals{}, sitemaps[]}. Setiap kueri: {query, clicks, impressions,
    ctr, position}.
    """
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404, detail=f"Channel '{channel_id}' tidak ditemukan."
        )
    try:
        return get_overview(channel)
    except SearchConsoleError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
