from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import datetime

from app.database import get_db
from app.models import Channel, Publication
from app.schemas import PublishRequest, PublishBatchResponse, PublicationResult
from app.services.platforms.blogger import BloggerPlatform

router = APIRouter(prefix="/api/v1/publish", tags=["Publish / Distribusi Konten"])

@router.post("", response_model=PublishBatchResponse)
def publish_articles(payload: PublishRequest, db: Session = Depends(get_db)):
    """
    Endpoint utama untuk AI Agent atau User memposting artikel ke beberapa channel blog.
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
                err_msg = f"Platform '{channel.platform}' belum diaktifkan (Fase Blogspot aktif)."
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

@router.get("/history")
def list_publication_history(db: Session = Depends(get_db)):
    """Mengambil riwayat seluruh artikel yang pernah diposting melalui konektor."""
    return db.query(Publication).order_by(Publication.created_at.desc()).limit(100).all()
