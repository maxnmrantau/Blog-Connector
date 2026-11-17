"""Auto-publish antrean terjadwal (scheduler tick).

Konteks penting — jangan salah paham cara kerja penjadwalan di sini:
artikel terjadwal di Blogger SUDAH dijadwalkan lewat
posts().publish(publishDate=...) — Blogger menerbitkannya OTOMATIS
pada waktu itu. Jadi tugas tick BUKAN menerbitkan ulang dari nol,
melainkan:
1. memeriksa status live tiap publikasi berstatus "scheduled" yang
   sudah jatuh tempo,
2. bila Blogger sudah menerbitkannya (LIVE), sinkronkan status DB
   menjadi "published",
3. bila masih draf/terjadwal di Blogger (misal penjadwalan gagal atau
   terlewat), terbitkan SEKARANG lewat publish_draft() yang sudah ada,
4. hanya untuk channel yang toggle auto-publish-nya aktif; channel
   yang toggle-nya mati dilewati (tetap tercatat di hasil tick).

Hasil tick terakhir disimpan di tabel settings
(scheduler_last_tick / scheduler_last_result) untuk kartu status
dashboard.
"""
import datetime
import json

from app.models import Channel, Publication
from app.services.platforms.blogger import BloggerPlatform
from app.services.search_console import try_submit_sitemap
from app.services.settings import get_setting_value, set_setting_value

WIB = datetime.timezone(datetime.timedelta(hours=7))
LAST_TICK_KEY = "scheduler_last_tick"
LAST_RESULT_KEY = "scheduler_last_result"


def _now_wib_naive():
    """Waktu sekarang (naive, WIB) — sama dengan cara scheduled_at disimpan."""
    return datetime.datetime.now(WIB).replace(tzinfo=None)


def get_due(db):
    """Publikasi berstatus scheduled yang waktunya sudah tiba, terurut."""
    now = _now_wib_naive()
    return (
        db.query(Publication)
        .filter(
            Publication.status == "scheduled",
            Publication.scheduled_at != None,  # noqa: E711
            Publication.scheduled_at <= now,
        )
        .order_by(Publication.scheduled_at.asc())
        .all()
    )


def get_status(db):
    """Status scheduler untuk dashboard: tick terakhir + antrean jatuh tempo."""
    last_tick = get_setting_value(db, LAST_TICK_KEY)
    last_result_raw = get_setting_value(db, LAST_RESULT_KEY)
    try:
        last_result = json.loads(last_result_raw) if last_result_raw else None
    except Exception:
        last_result = None
    due = get_due(db)
    return {
        "last_tick": last_tick,
        "last_result": last_result,
        "due_count": len(due),
        "due": [
            {
                "id": p.id,
                "title": p.title,
                "channel_id": p.channel_id,
                "scheduled_at": p.scheduled_at.isoformat() if p.scheduled_at else None,
                "auto_publish": bool(getattr(p.channel, "auto_publish", False))
                if p.channel
                else False,
            }
            for p in due
        ],
    }


def run_tick(db, driver_factory=None, sc_factory=None):
    """Jalankan satu tick: proses semua publikasi scheduled yang jatuh tempo.

    driver_factory(channel_id, credentials) -> driver dipakai untuk
    menguji (mock). Default: BloggerPlatform asli.
    sc_factory(credentials) -> service Search Console, dipakai untuk
    menguji auto-submit sitemap (mock). Default: service asli.
    Mengembalikan ringkasan {tick_at, due, published, already_live,
    skipped, failed, details[]}.
    """
    factory = driver_factory or (
        lambda cid, creds: BloggerPlatform(channel_id=cid, credentials=creds)
    )
    now = _now_wib_naive()
    due = get_due(db)
    details = []
    counts = {
        "due": len(due),
        "published": 0,
        "already_live": 0,
        "skipped": 0,
        "failed": 0,
    }
    for pub in due:
        channel = db.query(Channel).filter(Channel.id == pub.channel_id).first()
        if not channel or channel.platform != "blogger":
            counts["skipped"] += 1
            details.append(
                {
                    "publication_id": pub.id,
                    "title": pub.title,
                    "action": "skipped",
                    "reason": "Channel bukan Blogger atau tidak ditemukan.",
                }
            )
            continue
        if not getattr(channel, "auto_publish", False):
            counts["skipped"] += 1
            details.append(
                {
                    "publication_id": pub.id,
                    "title": pub.title,
                    "action": "skipped",
                    "reason": "Auto-publish channel ini mati. Aktifkan di seksi Penjadwal.",
                }
            )
            continue
        if not pub.remote_post_id:
            pub.error_message = (
                "Tidak punya remote_post_id; tidak bisa diterbitkan otomatis."
            )
            counts["failed"] += 1
            details.append(
                {
                    "publication_id": pub.id,
                    "title": pub.title,
                    "action": "failed",
                    "reason": pub.error_message,
                }
            )
            continue
        driver = factory(channel.id, channel.get_credentials())
        try:
            live = driver.get_post_status(pub.remote_post_id)
        except Exception as e:
            counts["failed"] += 1
            details.append(
                {
                    "publication_id": pub.id,
                    "title": pub.title,
                    "action": "failed",
                    "reason": f"Gagal memeriksa status di Blogger: {e}",
                }
            )
            continue
        if not live.get("success"):
            pub.error_message = live.get("error_message") or "Gagal memeriksa status di Blogger."
            counts["failed"] += 1
            details.append(
                {
                    "publication_id": pub.id,
                    "title": pub.title,
                    "action": "failed",
                    "reason": pub.error_message,
                }
            )
            continue
        if live.get("status") == "LIVE":
            # Blogger sudah menerbitkan otomatis (publishDate) — sinkronkan DB.
            pub.status = "published"
            pub.published_at = datetime.datetime.utcnow()
            if live.get("url"):
                pub.remote_url = live["url"]
            pub.error_message = None
            counts["already_live"] += 1
            sc_info = try_submit_sitemap(channel, service_factory=sc_factory)
            details.append(
                {
                    "publication_id": pub.id,
                    "title": pub.title,
                    "action": "already_live",
                    "reason": "Blogger sudah menerbitkan otomatis; status DB disinkronkan.",
                    "sitemap_submitted": sc_info["sitemap_submitted"],
                    "sitemap_note": sc_info["note"],
                }
            )
            continue
        # Masih draf/terjadwal di Blogger — terbitkan sekarang.
        res = driver.publish_draft(pub.remote_post_id)
        if res.success:
            pub.status = "published"
            pub.published_at = datetime.datetime.utcnow()
            if res.remote_url:
                pub.remote_url = res.remote_url
            pub.error_message = None
            counts["published"] += 1
            sc_info = try_submit_sitemap(channel, service_factory=sc_factory)
            details.append(
                {
                    "publication_id": pub.id,
                    "title": pub.title,
                    "action": "published",
                    "reason": "Diterbitkan sekarang lewat publish_draft.",
                    "sitemap_submitted": sc_info["sitemap_submitted"],
                    "sitemap_note": sc_info["note"],
                }
            )
        else:
            pub.error_message = res.error_message or "Gagal menerbitkan draf di Blogger."
            counts["failed"] += 1
            details.append(
                {
                    "publication_id": pub.id,
                    "title": pub.title,
                    "action": "failed",
                    "reason": pub.error_message,
                }
            )
    db.commit()
    summary = {"tick_at": now.isoformat(), **counts, "details": details}
    try:
        set_setting_value(db, LAST_TICK_KEY, now.isoformat())
        set_setting_value(db, LAST_RESULT_KEY, json.dumps(summary, ensure_ascii=False))
    except Exception:
        # Jangan gagalkan tick hanya karena pencatatan status.
        pass
    return summary
