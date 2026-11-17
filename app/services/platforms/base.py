from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class PublishResult(BaseModel):
    success: bool
    remote_post_id: Optional[str] = None
    remote_url: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None

class BaseBlogPlatform(ABC):
    def __init__(self, channel_id: str, credentials: dict):
        self.channel_id = channel_id
        self.credentials = credentials

    @abstractmethod
    def publish_post(
        self,
        title: str,
        content_html: str,
        labels: Optional[List[str]] = None,
        is_draft: bool = True
    ) -> PublishResult:
        """
        Mempublikasikan atau membuat draf artikel ke platform target.
        """
        pass

    @abstractmethod
    def publish_draft(self, post_id: str, publish_date: Optional[str] = None) -> PublishResult:
        """
        Menerbitkan draf yang sudah ada di platform target tanpa
        membuat postingan baru (menghindari duplikat). Kalau
        publish_date (RFC 3339) diisi dengan waktu masa depan, draf
        dijadwalkan: Blogger menerbitkannya otomatis pada waktu itu
        (posts().publish(publishDate=...)).
        """
        pass

    @abstractmethod
    def update_post(
        self,
        post_id: str,
        title: str,
        content_html: str,
        labels: Optional[List[str]] = None
    ) -> PublishResult:
        """
        Memperbarui judul dan/atau konten sebuah postingan yang sudah
        ada di platform target (draf maupun yang sudah published).

        labels: bila diisi, label postingan ikut diperbarui. Bila None,
        platform tidak menerima label sama sekali — pemanggil yang
        peduli label harus mengirimkan label yang sudah tersimpan,
        karena posts().update() di Blogger mengganti seluruh isi
        postingan dan label yang tidak dikirim akan hilang.
        """
        pass

    @abstractmethod
    def delete_post(self, post_id: str) -> PublishResult:
        """
        Menghapus sebuah postingan dari platform target.
        """
        pass

    @abstractmethod
    def create_page(
        self,
        title: str,
        content_html: str,
        is_draft: bool = True
    ) -> PublishResult:
        """
        Membuat halaman statis (Page) di platform target, sebagai
        draf atau langsung diterbitkan.
        """
        pass

    @abstractmethod
    def list_pages(self) -> List[Dict[str, Any]]:
        """
        Mengambil daftar halaman statis (Page) dari platform target.
        Tiap item: {"id", "title", "status", "url", "updated"}.
        """
        pass

    @abstractmethod
    def delete_page(self, page_id: str) -> PublishResult:
        """
        Menghapus sebuah halaman statis (Page) dari platform target.
        """
        pass

    @abstractmethod
    def get_page_views(self, time_range: str) -> int:
        """
        Mengambil total kunjungan blog untuk satu rentang waktu.
        time_range mengikuti Blogger API v3 pageViews.get:
        "30DAYS", "7DAYS", atau "all" (sepanjang waktu). Blogger
        HANYA mengembalikan angka agregat per rentang — tidak ada
        rincian per hari. Mengangkat RuntimeError kalau gagal.
        """
        pass

    @abstractmethod
    def list_comments(self) -> List[Dict[str, Any]]:
        """
        Mengambil daftar komentar blog (semua postingan) lewat
        comments().listByBlog(). Tiap item: {"id", "author",
        "content", "status", "published", "post_id"}.
        """
        pass

    @abstractmethod
    def approve_comment(self, post_id: str, comment_id: str) -> PublishResult:
        """
        Menyetujui komentar (comments().approve) — butuh post_id
        karena endpoint Blogger-nya per-postingan. Mengangkat
        HttpError supaya pemanggil bisa memetakan 404.
        """
        pass

    @abstractmethod
    def mark_comment_as_spam(self, post_id: str, comment_id: str) -> PublishResult:
        """
        Menandai komentar sebagai spam (comments().markAsSpam) —
        butuh post_id karena endpoint Blogger-nya per-postingan.
        Mengangkat HttpError supaya pemanggil bisa memetakan 404.
        """
        pass

    @abstractmethod
    def delete_comment(self, post_id: str, comment_id: str) -> PublishResult:
        """
        Menghapus komentar (comments().delete) — butuh post_id
        karena endpoint Blogger-nya per-postingan. Mengangkat
        HttpError supaya pemanggil bisa memetakan 404.
        """
        pass
