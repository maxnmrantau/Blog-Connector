from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Channel
from app.schemas import ChannelCreate, ChannelResponse, ChannelUpdate
from app.services.platforms.blogger import BloggerPlatform
from app.security import authenticate_agent_or_session

router = APIRouter(prefix="/api/v1/channels", tags=["Channels / Blog Accounts"])

@router.get("", response_model=List[ChannelResponse])
def list_channels(
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Mengambil daftar seluruh akun blog yang terdaftar beserta profil niche-nya."""
    return db.query(Channel).all()

@router.post("", response_model=ChannelResponse)
def create_or_update_channel(
    data: ChannelCreate,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Menambahkan akun blog baru atau memperbarui akun yang sudah ada."""
    # Blog ID hanya ada di dalam credentials JSON, jadi simpan juga sebagai
    # kolom agar dashboard dan API bisa menampilkannya tanpa membongkar JSON.
    blog_id = str(data.credentials.get("blog_id")) if data.credentials.get("blog_id") else None
    blog_url = data.credentials.get("blog_url") or data.credentials.get("url") or None

    existing = db.query(Channel).filter(Channel.id == data.id).first()
    if existing:
        existing.name = data.name
        existing.platform = data.platform.lower()
        existing.blog_id = blog_id or existing.blog_id
        existing.blog_url = blog_url or existing.blog_url
        existing.set_credentials(data.credentials)
        existing.niche = data.niche
        existing.target_audience = data.target_audience
        existing.tone_of_voice = data.tone_of_voice
        existing.target_word_count = data.target_word_count
        existing.default_labels = data.default_labels
        db.commit()
        db.refresh(existing)
        return existing

    new_channel = Channel(
        id=data.id,
        name=data.name,
        platform=data.platform.lower(),
        blog_id=blog_id,
        blog_url=blog_url,
        niche=data.niche,
        target_audience=data.target_audience,
        tone_of_voice=data.tone_of_voice,
        target_word_count=data.target_word_count,
        default_labels=data.default_labels
    )
    new_channel.set_credentials(data.credentials)
    db.add(new_channel)
    db.commit()
    db.refresh(new_channel)
    return new_channel

@router.get("/{channel_id}", response_model=ChannelResponse)
def get_channel(
    channel_id: str,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Mendapatkan detail profil dan kredensial suatu channel."""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' tidak ditemukan.")
    return channel

@router.patch("/{channel_id}", response_model=ChannelResponse)
def update_channel_settings(
    channel_id: str,
    data: ChannelUpdate,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Memperbarui pengaturan artikel sebuah channel (niche, tone of voice,
    target kata, labels default). Partial update: hanya field yang dikirim
    yang diubah. target_word_count harus bilangan > 0 (422 bila tidak valid).
    """
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' tidak ditemukan.")

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(channel, field, value)
    db.commit()
    db.refresh(channel)
    return channel

@router.delete("/{channel_id}")
def delete_channel(
    channel_id: str,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """Menghapus akun blog dari sistem."""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' tidak ditemukan.")
    db.delete(channel)
    db.commit()
    return {"status": "success", "message": f"Channel '{channel_id}' berhasil dihapus."}

@router.get("/{channel_id}/test-blogger-blogs")
def test_blogger_blogs(
    channel_id: str,
    db: Session = Depends(get_db),
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Menguji koneksi OAuth Blogger dan menampilkan seluruh blog ID
    yang bisa diakses oleh akun Google ini.
    """
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' tidak ditemukan.")

    if channel.platform != "blogger":
        raise HTTPException(status_code=400, detail="Channel ini bukan platform Blogger.")

    creds = channel.get_credentials()
    try:
        platform = BloggerPlatform(channel_id=channel.id, credentials=creds)
        blogs = platform.list_user_blogs()
        # list_user_blogs sudah mengembalikan url tiap blog, tapi selama ini
        # tidak pernah disimpan. Cocokkan dengan blog_id channel lalu simpan
        # agar dashboard dan GET /channels bisa menampilkan alamat blog.
        target_id = str(channel.blog_id or creds.get("blog_id") or "")
        matched = next((b for b in blogs if str(b.get("id")) == target_id), blogs[0] if blogs else None)
        if matched:
            if not channel.blog_id:
                channel.blog_id = str(matched.get("id"))
            channel.blog_url = matched.get("url")
            db.commit()
        return {
            "status": "success",
            "message": f"Berhasil terhubung ke akun Google! Ditemukan {len(blogs)} blog.",
            "blogs": blogs,
            "resolved_blog_id": channel.blog_id,
            "resolved_blog_url": channel.blog_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
