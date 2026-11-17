"""Endpoint Image Picker: GET /api/v1/images/search.

Sumber utama Openverse (tanpa kunci, lisensi CC). Pexels ikut dicari
bila kunci Pexels terisi di Pengaturan AI; bila kunci kosong, endpoint
tetap berfungsi penuh dengan Openverse.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import authenticate_agent_or_session
from app.services.images import ImageSearchError, search_images

router = APIRouter(prefix="/api/v1/images", tags=["Image Picker"])


@router.get("/search")
def search_images_endpoint(
    q: str = Query(..., min_length=1, description="Kata kunci foto"),
    per_page: int = Query(8, ge=1, le=20, description="Hasil per sumber, maks 20"),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session),
):
    """Cari foto berlisensi bebas.

    Respons: {query, results[], sources[], openverse_error?, pexels_error?}
    Setiap hasil: source, id, title, url, thumbnail_url, width, height,
    suggested_alt, photographer, photographer_url, license, license_url,
    attribution, foreign_landing_url.
    """
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Parameter 'q' wajib diisi.")
    try:
        return search_images(query, per_page=per_page, db=db)
    except ImageSearchError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
