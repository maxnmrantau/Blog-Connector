from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import datetime

from app.database import get_db
from app.models import Channel, Publication
from app.schemas import PublishRequest, PublishBatchResponse, PublicationResult
from app.services.platforms.blogger import BloggerPlatform
from app.security import authenticate_agent_or_session

router = APIRouter(prefix="/api/v1/publish", tags=["Publish / Distribusi Konten"])

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

        # Penjaga duplikat: kalau slug yang sama sudah ada sebagai draf di
        # channel ini, jangan membuat postingan baru di Blogger. Terbitkan
        # draf yang sudah ada lewat POST /api/v1/publish/{id}/publish.
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

        # Simpan rekaman publikasi ke DB
        pub_record = Publication(
            source_id=payload.source_id,
            channel_id=channel.id,
            title=item.title,
            slug=item.slug,
            meta_description=item.meta_description,
            content_html=item.content_html,
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
                    content_html=item.content_html,
                    labels=merged_labels,
                    is_draft=is_draft
                )

                if res.success:
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


@router.get("/history")
def list_publication_history(
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Mengambil riwayat seluruh artikel yang pernah diposting melalui konektor."""
    return db.query(Publication).order_by(Publication.created_at.desc()).limit(100).all()
