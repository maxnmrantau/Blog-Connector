from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List
import datetime
import html as html_lib
import re

from app.database import get_db
from app.models import Channel, Publication
from app.schemas import ArticleUpdate, PublishRequest, PublishBatchResponse, PublicationResult
from app.services.platforms.blogger import BloggerPlatform
from app.security import authenticate_agent_or_session

router = APIRouter(prefix="/api/v1/publish", tags=["Publish / Distribusi Konten"])

# Pola <img ...> di paling awal konten — dipakai untuk mengganti gambar
# sampul lama saat artikel diedit, supaya tidak ada dua <img> berurutan.
_LEADING_IMG_RE = re.compile(r"^\s*<img\b[^>]*>\s*", re.IGNORECASE | re.DOTALL)

# Zona waktu blog (WIB). Nilai scheduled_at yang naive (misal dari
# input datetime-local dashboard) dianggap waktu WIB.
WIB = datetime.timezone(datetime.timedelta(hours=7))


def _scheduled_future(scheduled_at):
    """
    Kembalikan datetime (aware) kalau scheduled_at ada dan di masa
    depan, kalau tidak kembalikan None. scheduled_at di masa lalu
    diabaikan — artikel diproses normal (draf/publish).
    """
    if not scheduled_at:
        return None
    dt = scheduled_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=WIB)
    if dt <= datetime.datetime.now(datetime.timezone.utc):
        return None
    return dt


def _to_rfc3339(dt):
    """Format datetime sebagai RFC 3339 (naive dianggap WIB)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=WIB)
    return dt.isoformat()


def prepend_cover_image(
    content_html: str,
    image_url: str | None,
    image_alt: str | None = None
) -> str:
    """
    Menyisipkan gambar sampul sebagai <img> di AWAL konten artikel.
    Kalau konten sudah diawali <img> (gambar sampul lama dari edit
    sebelumnya), tag lama itu diganti dengan yang baru supaya tidak
    duplikat. Kalau image_url kosong, konten dikembalikan apa adanya.

    Catatan: gambar HARUS berupa URL yang sudah di-host di tempat lain
    (Blogger/Drive/CDN/dll) — Blogger API v3 tidak menyediakan endpoint
    upload gambar, jadi konektor tidak pernah mengunggah file gambar.
    """
    if not image_url or not image_url.strip():
        return content_html
    content = _LEADING_IMG_RE.sub("", content_html or "", count=1)
    src = html_lib.escape(image_url.strip(), quote=True)
    alt = html_lib.escape(image_alt or "", quote=True)
    return f'<img src="{src}" alt="{alt}">\n{content}'

@router.post("", response_model=PublishBatchResponse)
def publish_articles(
    payload: PublishRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Endpoint utama untuk AI Agent memposting artikel ke beberapa channel blog.
    Dapat mengirim draf atau langsung publish.
    """
    results: List[PublicationResult] = []
    success_count = 0
    fail_count = 0

    for item in payload.publications:
        channel = db.query(Channel).filter(Channel.id == item.channel_id).first()
        if not channel:
            results.append(
                PublicationResult(
                    channel_id=item.channel_id,
                    channel_name="Unknown",
                    platform="unknown",
                    status="failed",
                    title=item.title,
                    error_message=f"Channel ID '{item.channel_id}' tidak ditemukan di database."
                )
            )
            fail_count += 1
            continue

        creds = channel.get_credentials()
        is_draft = item.status.lower() != "publish"

        # Penjadwalan (hasil verifikasi dokumentasi Blogger API v3):
        # field `published` di body posts().insert() TIDAK didukung
        # untuk menjadwalkan postingan baru — cara yang didokumentasikan
        # adalah posts().publish(publishDate=...) pada sebuah draf.
        # Jadi artikel terjadwal: insert sebagai draf, lalu panggil
        # publish_draft(publish_date=...) — Blogger menerbitkannya
        # otomatis pada waktu itu. scheduled_at di masa lalu diabaikan.
        schedule_dt = _scheduled_future(item.scheduled_at)
        is_scheduled = schedule_dt is not None
        if is_scheduled:
            is_draft = True

        # Penjaga duplikat: kalau slug yang sama sudah ada sebagai draf di
        # channel ini, jangan membuat postingan baru di Blogger. Terbitkan
        # draf yang sudah ada lewat POST /api/v1/publish/{id}/publish.
        # Penjaga ini HANYA untuk status "draft": publikasi berstatus
        # "scheduled" tidak ikut memblokir (dan tidak diblokir sebagai
        # draf) — draf dan jadwal dengan slug sama boleh hidup berdampingan.
        if item.slug:
            existing_draft = db.query(Publication).filter(
                Publication.channel_id == channel.id,
                Publication.slug == item.slug,
                Publication.status == "draft"
            ).first()
            if existing_draft:
                results.append(
                    PublicationResult(
                        channel_id=channel.id,
                        channel_name=channel.name,
                        platform=channel.platform,
                        status="failed",
                        title=item.title,
                        error_message=(
                            f"Sudah ada draf dengan slug '{item.slug}' "
                            f"(publikasi id {existing_draft.id}). Terbitkan draf itu "
                            f"lewat POST /api/v1/publish/{existing_draft.id}/publish, "
                            "jangan mengirim artikel yang sama lagi."
                        )
                    )
                )
                fail_count += 1
                continue

        # Gambar sampul (kalau diisi): sisipkan <img> di awal konten
        # sebelum disimpan ke DB dan dikirim ke Blogger.
        final_content = prepend_cover_image(
            item.content_html,
            item.cover_image_url,
            item.cover_image_alt
        )

        # Simpan rekaman publikasi ke DB
        pub_record = Publication(
            source_id=payload.source_id,
            channel_id=channel.id,
            title=item.title,
            slug=item.slug,
            meta_description=item.meta_description,
            content_html=final_content,
            labels=",".join(item.labels) if item.labels else channel.default_labels,
            status="pending"
        )
        db.add(pub_record)
        db.commit()
        db.refresh(pub_record)

        # Proses kirim ke platform yang sesuai
        try:
            if channel.platform == "blogger":
                driver = BloggerPlatform(channel_id=channel.id, credentials=creds)
                merged_labels = item.labels or []
                if channel.default_labels and not merged_labels:
                    merged_labels = [l.strip() for l in channel.default_labels.split(",") if l.strip()]

                res = driver.publish_post(
                    title=item.title,
                    content_html=final_content,
                    labels=merged_labels,
                    is_draft=is_draft
                )

                if res.success:
                    if is_scheduled:
                        # Draf sudah dibuat di Blogger; jadwalkan lewat
                        # posts().publish(publishDate=...). Kalau ini
                        # gagal, drafnya tetap ada di Blogger, tapi
                        # rekaman ditandai failed supaya admin tahu
                        # jadwalnya tidak aktif.
                        sched_res = driver.publish_draft(
                            res.remote_post_id,
                            publish_date=_to_rfc3339(schedule_dt)
                        )
                        if sched_res.success:
                            pub_record.status = "scheduled"
                            pub_record.remote_post_id = res.remote_post_id
                            pub_record.remote_url = sched_res.remote_url or res.remote_url
                            pub_record.scheduled_at = schedule_dt.astimezone(WIB).replace(tzinfo=None)
                            db.commit()
                            results.append(
                                PublicationResult(
                                    channel_id=channel.id,
                                    channel_name=channel.name,
                                    platform=channel.platform,
                                    status="scheduled",
                                    title=item.title,
                                    remote_post_id=res.remote_post_id,
                                    remote_url=pub_record.remote_url
                                )
                            )
                            success_count += 1
                        else:
                            pub_record.status = "failed"
                            pub_record.remote_post_id = res.remote_post_id
                            pub_record.remote_url = res.remote_url
                            pub_record.error_message = (
                                "Draf dibuat di Blogger, tapi penjadwalan gagal: "
                                + (sched_res.error_message or "tidak diketahui")
                            )
                            db.commit()
                            results.append(
                                PublicationResult(
                                    channel_id=channel.id,
                                    channel_name=channel.name,
                                    platform=channel.platform,
                                    status="failed",
                                    title=item.title,
                                    remote_post_id=res.remote_post_id,
                                    remote_url=res.remote_url,
                                    error_message=pub_record.error_message
                                )
                            )
                            fail_count += 1
                        continue
                    pub_record.status = "draft" if is_draft else "published"
                    pub_record.remote_post_id = res.remote_post_id
                    pub_record.remote_url = res.remote_url
                    pub_record.published_at = datetime.datetime.utcnow()
                    db.commit()

                    results.append(
                        PublicationResult(
                            channel_id=channel.id,
                            channel_name=channel.name,
                            platform=channel.platform,
                            status="draft" if is_draft else "published",
                            title=item.title,
                            remote_post_id=res.remote_post_id,
                            remote_url=res.remote_url
                        )
                    )
                    success_count += 1
                else:
                    pub_record.status = "failed"
                    pub_record.error_message = res.error_message
                    db.commit()

                    results.append(
                        PublicationResult(
                            channel_id=channel.id,
                            channel_name=channel.name,
                            platform=channel.platform,
                            status="failed",
                            title=item.title,
                            error_message=res.error_message
                        )
                    )
                    fail_count += 1
            else:
                err_msg = f"Platform '{channel.platform}' belum diaktifkan."
                pub_record.status = "failed"
                pub_record.error_message = err_msg
                db.commit()
                results.append(
                    PublicationResult(
                        channel_id=channel.id,
                        channel_name=channel.name,
                        platform=channel.platform,
                        status="failed",
                        title=item.title,
                        error_message=err_msg
                    )
                )
                fail_count += 1

        except Exception as e:
            pub_record.status = "failed"
            pub_record.error_message = str(e)
            db.commit()
            results.append(
                PublicationResult(
                    channel_id=channel.id,
                    channel_name=channel.name,
                    platform=channel.platform,
                    status="failed",
                    title=item.title,
                    error_message=str(e)
                )
            )
            fail_count += 1

    return PublishBatchResponse(
        total=len(payload.publications),
        successful=success_count,
        failed=fail_count,
        results=results
    )

class BulkPublishRequest(BaseModel):
    channel_id: str


@router.post("/bulk/publish")
def bulk_publish_drafts(
    payload: BulkPublishRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Menerbitkan SEMUA publikasi berstatus draft pada satu channel,
    satu per satu lewat driver.publish_draft yang sudah ada (tidak
    membuat postingan baru, jadi tidak ada duplikat). Draf yang
    gagal (misal remote_post_id hilang atau Blogger menolak) tetap
    berstatus draft, dicatat error-nya, dan dilaporkan di results.
    Didaftarkan SEBELUM route "/{publication_id}/publish" supaya
    path literal "/bulk/publish" tidak tertangkap sebagai
    publication_id="bulk".
    """
    channel = db.query(Channel).filter(Channel.id == payload.channel_id).first()
    if not channel:
        raise HTTPException(
            status_code=404,
            detail=f"Channel ID '{payload.channel_id}' tidak ditemukan di database."
        )

    if channel.platform != "blogger":
        raise HTTPException(
            status_code=400,
            detail=f"Platform '{channel.platform}' belum mendukung penerbitan draf."
        )

    drafts = db.query(Publication).filter(
        Publication.channel_id == channel.id,
        Publication.status == "draft"
    ).order_by(Publication.created_at.asc()).all()

    driver = BloggerPlatform(channel_id=channel.id, credentials=channel.get_credentials())
    published = 0
    failed = 0
    results = []

    for pub in drafts:
        if not pub.remote_post_id:
            pub.error_message = (
                "Draf ini tidak punya remote_post_id, jadi tidak bisa "
                "diterbitkan dari Blogger. Kirim ulang sebagai artikel baru."
            )
            db.commit()
            failed += 1
            results.append({"id": pub.id, "title": pub.title, "status": "failed"})
            continue

        res = driver.publish_draft(pub.remote_post_id)
        if res.success:
            pub.status = "published"
            pub.published_at = datetime.datetime.utcnow()
            if res.remote_url:
                pub.remote_url = res.remote_url
            pub.error_message = None
            db.commit()
            published += 1
            results.append({"id": pub.id, "title": pub.title, "status": "published"})
        else:
            pub.error_message = res.error_message or "Gagal menerbitkan draf di Blogger."
            db.commit()
            failed += 1
            results.append({"id": pub.id, "title": pub.title, "status": "failed"})

    return {
        "channel_id": channel.id,
        "published": published,
        "failed": failed,
        "results": results,
    }


@router.post("/{publication_id}/publish", response_model=PublicationResult)
def publish_existing_draft(
    publication_id: int,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Menerbitkan draf yang sudah ada tanpa membuat postingan baru.
    Memakai Blogger posts().publish() pada remote_post_id yang tersimpan,
    jadi tidak ada duplikat di Blogger.
    """
    pub = db.query(Publication).filter(Publication.id == publication_id).first()
    if not pub:
        raise HTTPException(
            status_code=404,
            detail=f"Publikasi dengan id {publication_id} tidak ditemukan."
        )

    channel = pub.channel
    channel_name = channel.name if channel else "Unknown"
    platform = channel.platform if channel else "unknown"

    def _failed(message: str) -> PublicationResult:
        pub.error_message = message
        db.commit()
        return PublicationResult(
            channel_id=pub.channel_id,
            channel_name=channel_name,
            platform=platform,
            status="failed",
            title=pub.title,
            remote_post_id=pub.remote_post_id,
            remote_url=pub.remote_url,
            error_message=message
        )

    if pub.status != "draft":
        return _failed(
            "Hanya draf yang bisa diterbitkan. "
            f"Status publikasi ini adalah '{pub.status}'."
        )

    if not channel or channel.platform != "blogger":
        return _failed(
            f"Platform '{platform}' belum mendukung penerbitan draf."
        )

    if not pub.remote_post_id:
        return _failed(
            "Draf ini tidak punya remote_post_id, jadi tidak bisa "
            "diterbitkan dari Blogger. Kirim ulang sebagai artikel baru."
        )

    driver = BloggerPlatform(channel_id=channel.id, credentials=channel.get_credentials())
    res = driver.publish_draft(pub.remote_post_id)

    if not res.success:
        return _failed(res.error_message or "Gagal menerbitkan draf di Blogger.")

    pub.status = "published"
    pub.published_at = datetime.datetime.utcnow()
    if res.remote_url:
        pub.remote_url = res.remote_url
    pub.error_message = None
    db.commit()

    return PublicationResult(
        channel_id=pub.channel_id,
        channel_name=channel_name,
        platform=platform,
        status="published",
        title=pub.title,
        remote_post_id=pub.remote_post_id,
        remote_url=pub.remote_url
    )


@router.delete("/{publication_id}")
def delete_publication(
    publication_id: int,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Menghapus sebuah draf: hapus postingannya di Blogger (kalau ada
    remote_post_id) lalu hapus rekamannya di database. Hanya draf yang
    boleh dihapus dari sini; artikel yang sudah published harus dihapus
    langsung di Blogger supaya tidak terhapus tanpa sengaja.
    """
    pub = db.query(Publication).filter(Publication.id == publication_id).first()
    if not pub:
        raise HTTPException(
            status_code=404,
            detail=f"Publikasi dengan id {publication_id} tidak ditemukan."
        )

    if pub.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=(
                "Hanya draf yang bisa dihapus dari sini. Artikel yang sudah "
                "published harus dihapus langsung di Blogger."
            )
        )

    blogger_error = None
    channel = pub.channel
    if pub.remote_post_id and channel and channel.platform == "blogger":
        driver = BloggerPlatform(channel_id=channel.id, credentials=channel.get_credentials())
        res = driver.delete_post(pub.remote_post_id)
        if not res.success:
            # Tetap hapus rekaman DB-nya, tapi laporkan error Blogger-nya
            # supaya admin tahu drafnya mungkin masih ada di Blogger.
            blogger_error = res.error_message

    db.delete(pub)
    db.commit()

    return {
        "ok": True,
        "deleted_id": publication_id,
        "blogger_error": blogger_error,
    }


@router.put("/{publication_id}", response_model=PublicationResult)
def update_publication(
    publication_id: int,
    payload: ArticleUpdate,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Mengedit artikel yang sudah ada (draf maupun published): perbarui
    judul dan/atau konten di Blogger lewat posts().update() lalu
    sinkronkan rekaman di database. Status publikasi (draft/published)
    tidak berubah. Minimal salah satu dari title / content_html /
    labels harus diisi; kalau ada cover_image_url, gambar sampul
    disisipkan di awal konten (menggantikan gambar sampul lama bila ada).

    Label: posts().update() mengganti seluruh postingan, jadi label
    yang tidak dikirim akan terhapus di Blogger. Karena itu, bila
    payload tidak membawa labels, endpoint ini memakai label yang
    sudah tersimpan di database (pub.labels) supaya edit dari
    dashboard atau API lama tidak menghilangkan label.
    """
    pub = db.query(Publication).filter(Publication.id == publication_id).first()
    if not pub:
        raise HTTPException(
            status_code=404,
            detail=f"Publikasi dengan id {publication_id} tidak ditemukan."
        )

    if not payload.title and not payload.content_html and payload.labels is None:
        raise HTTPException(
            status_code=400,
            detail="Isi minimal judul baru, konten_html baru, atau labels baru."
        )

    channel = pub.channel
    channel_name = channel.name if channel else "Unknown"
    platform = channel.platform if channel else "unknown"

    new_title = payload.title or pub.title
    new_content = payload.content_html if payload.content_html is not None else pub.content_html
    if payload.cover_image_url:
        new_content = prepend_cover_image(
            new_content, payload.cover_image_url, payload.cover_image_alt
        )

    # Label efektif: yang dikirim klien, atau yang sudah tersimpan.
    if payload.labels is not None:
        effective_labels = payload.labels
    elif pub.labels:
        effective_labels = [l.strip() for l in pub.labels.split(",") if l.strip()]
    else:
        effective_labels = None

    if pub.remote_post_id and channel and channel.platform == "blogger":
        driver = BloggerPlatform(channel_id=channel.id, credentials=channel.get_credentials())
        res = driver.update_post(
            pub.remote_post_id,
            title=new_title,
            content_html=new_content,
            labels=effective_labels
        )
        if not res.success:
            pub.error_message = res.error_message
            db.commit()
            return PublicationResult(
                channel_id=pub.channel_id,
                channel_name=channel_name,
                platform=platform,
                status="failed",
                title=new_title,
                remote_post_id=pub.remote_post_id,
                remote_url=pub.remote_url,
                error_message=res.error_message or "Gagal memperbarui artikel di Blogger."
            )
        if res.remote_url:
            pub.remote_url = res.remote_url

    pub.title = new_title
    pub.content_html = new_content
    if payload.labels is not None:
        pub.labels = ",".join(payload.labels)
    pub.error_message = None
    db.commit()

    return PublicationResult(
        channel_id=pub.channel_id,
        channel_name=channel_name,
        platform=platform,
        status=pub.status,
        title=pub.title,
        remote_post_id=pub.remote_post_id,
        remote_url=pub.remote_url
    )


@router.get("/history")
def list_publication_history(
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Mengambil riwayat seluruh artikel yang pernah diposting melalui konektor."""
    return db.query(Publication).order_by(Publication.created_at.desc()).limit(100).all()


@router.get("/{publication_id}")
def get_publication(
    publication_id: int,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Mengambil satu publikasi beserta konten HTML-nya — dipakai modal
    Edit di dashboard kalau konten tidak tersedia di halaman riwayat.
    Didaftarkan SETELAH GET /history supaya path literal "/history"
    tidak tertangkap sebagai publication_id.
    """
    pub = db.query(Publication).filter(Publication.id == publication_id).first()
    if not pub:
        raise HTTPException(
            status_code=404,
            detail=f"Publikasi dengan id {publication_id} tidak ditemukan."
        )
    return {
        "id": pub.id,
        "channel_id": pub.channel_id,
        "title": pub.title,
        "slug": pub.slug,
        "meta_description": pub.meta_description,
        "content_html": pub.content_html,
        "labels": pub.labels,
        "status": pub.status,
        "remote_post_id": pub.remote_post_id,
        "remote_url": pub.remote_url,
        "error_message": pub.error_message,
        "scheduled_at": pub.scheduled_at.isoformat() if pub.scheduled_at else None,
        "published_at": pub.published_at.isoformat() if pub.published_at else None,
        "created_at": pub.created_at.isoformat() if pub.created_at else None,
    }
