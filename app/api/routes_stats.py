from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Channel
from app.services.platforms.blogger import BloggerPlatform
from app.security import authenticate_agent_or_session

router = APIRouter(prefix="/api/v1/stats", tags=["Statistik Kunjungan"])

# CATATAN — bentuk respons pageViews Blogger API v3 (terverifikasi dari
# dokumentasi resmi Google, developers.google.com/blogger/docs/3.0/
# reference/pageViews): GET /blogs/{blogId}/pageviews?range=...
# mengembalikan {"kind": "blogger#page_views", "blogId": ...,
# "counts": [{"timeRange": ..., "count": ...}]} — SATU angka agregat
# per rentang. Nilai range yang sah: "30DAYS", "7DAYS", dan "all"
# (BUKAN "ALL_TIME"). TIDAK ADA rincian per hari di API ini, jadi
# field "daily" di bawah SELALU [] — mengisi 30 angka harian dari
# total agregat berarti mengarang data. Kalau rincian harian
# dibutuhkan, sumbernya harus dari luar Blogger API (misal GA4 atau
# pencatatan kunjungan sendiri), bukan dari endpoint ini.


@router.get("")
def get_blog_stats(
    channel_id: str = Query(..., description="ID channel blogger"),
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Statistik kunjungan sebuah channel Blogger: total 30 hari, total
    7 hari, dan total sepanjang waktu, langsung dari Blogger API v3
    pageViews().get(). Kalau Blogger gagal, kembalikan 502 dengan
    pesan jelas (bukan 500 tanpa pesan).
    """
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404,
            detail=f"Channel ID '{channel_id}' tidak ditemukan di database."
        )

    if channel.platform != "blogger":
        raise HTTPException(
            status_code=400,
            detail=f"Platform '{channel.platform}' belum mendukung statistik kunjungan."
        )

    driver = BloggerPlatform(channel_id=channel.id, credentials=channel.get_credentials())
    try:
        total_30_days = driver.get_page_views("30DAYS")
        total_7_days = driver.get_page_views("7DAYS")
        total_all_time = driver.get_page_views("all")
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Gagal mengambil statistik kunjungan dari Blogger: {str(e)}"
        )

    return {
        "channel_id": channel.id,
        "total_30_days": total_30_days,
        "total_7_days": total_7_days,
        "total_all_time": total_all_time,
        # Blogger API v3 pageViews hanya memberi angka agregat per
        # rentang — tidak ada deret harian. Lihat catatan di atas.
        "daily": [],
    }
