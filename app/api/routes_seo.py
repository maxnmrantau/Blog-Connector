from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import List, Optional

from app.security import authenticate_agent_or_session
from app.services.seo import check_seo

router = APIRouter(prefix="/api/v1/seo-check", tags=["SEO"])


class SeoCheckRequest(BaseModel):
    title: str = ""
    meta_description: Optional[str] = ""
    content_html: str = ""
    target_word_count: int = Field(default=800, gt=0)


class SeoCheckItem(BaseModel):
    id: str
    label: str
    passed: bool
    detail: str


class SeoCheckResponse(BaseModel):
    score: int
    checks: List[SeoCheckItem]


@router.post("", response_model=SeoCheckResponse)
def seo_check(
    payload: SeoCheckRequest,
    auth: dict = Depends(authenticate_agent_or_session)
):
    """
    Cek SEO murni konten (tanpa channel): nilai judul, meta
    description, jumlah kata, gambar/alt, subheading, dan internal
    link, lalu kembalikan skor 0-100 + rincian tiap check.
    """
    return check_seo(
        title=payload.title,
        meta_description=payload.meta_description,
        content_html=payload.content_html,
        target_word_count=payload.target_word_count,
    )
