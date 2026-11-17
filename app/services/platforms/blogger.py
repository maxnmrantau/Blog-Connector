from typing import List, Optional, Dict, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.services.platforms.base import BaseBlogPlatform, PublishResult

class BloggerPlatform(BaseBlogPlatform):
    """
    Driver untuk Google Blogger API v3 menggunakan OAuth 2.0 Credentials (Refresh Token)
    """

    def _get_service(self):
        client_id = self.credentials.get("client_id")
        client_secret = self.credentials.get("client_secret")
        refresh_token = self.credentials.get("refresh_token")

        if not all([client_id, client_secret, refresh_token]):
            raise ValueError(
                "Kredensial Blogger tidak lengkap. Butuh: client_id, client_secret, refresh_token."
            )

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/blogger"]
        )
        return build("blogger", "v3", credentials=creds, cache_discovery=False)

    def publish_post(
        self,
        title: str,
        content_html: str,
        labels: Optional[List[str]] = None,
        is_draft: bool = True
    ) -> PublishResult:
        blog_id = self.credentials.get("blog_id")
        if not blog_id:
            return PublishResult(
                success=False,
                error_message="blog_id belum ditentukan pada profil akun Blogger ini."
            )

        try:
            service = self._get_service()
            body = {
                "title": title,
                "content": content_html,
                "labels": labels or []
            }

            # isDraft: True untuk Draf, False untuk langsung terbit (Published)
            request = service.posts().insert(
                blogId=str(blog_id),
                body=body,
                isDraft=is_draft
            )
            response = request.execute()

            post_id = response.get("id")
            post_url = response.get("url")

            return PublishResult(
                success=True,
                remote_post_id=str(post_id) if post_id else None,
                remote_url=post_url,
                raw_response=response
            )

        except HttpError as error:
            error_details = error.error_details if hasattr(error, 'error_details') else str(error)
            return PublishResult(
                success=False,
                error_message=f"Google Blogger API Error [{error.status_code}]: {error_details}"
            )
        except Exception as e:
            return PublishResult(
                success=False,
                error_message=f"Terjadi kesalahan saat memposting ke Blogger: {str(e)}"
            )

    def publish_draft(self, post_id: str, publish_date: Optional[str] = None) -> PublishResult:
        """
        Menerbitkan draf yang sudah ada di Blogger lewat
        posts().publish() — tidak membuat postingan baru, jadi
        tidak ada duplikat. Kalau publish_date (RFC 3339, masa
        depan) diisi, draf dijadwalkan: Blogger menerbitkannya
        otomatis pada waktu itu. Ini cara penjadwalan yang
        didokumentasikan Blogger API v3 (parameter publishDate);
        field `published` di body insert TIDAK didukung untuk
        menjadwalkan postingan baru.
        """
        blog_id = self.credentials.get("blog_id")
        if not blog_id:
            return PublishResult(
                success=False,
                error_message="blog_id belum ditentukan pada profil akun Blogger ini."
            )

        try:
            service = self._get_service()
            kwargs: Dict[str, Any] = {}
            if publish_date:
                kwargs["publishDate"] = publish_date
            response = service.posts().publish(
                blogId=str(blog_id),
                postId=str(post_id),
                **kwargs
            ).execute()

            post_url = response.get("url") if isinstance(response, dict) else None

            return PublishResult(
                success=True,
                remote_post_id=str(post_id),
                remote_url=post_url,
                raw_response=response if isinstance(response, dict) else None
            )

        except HttpError as error:
            error_details = error.error_details if hasattr(error, 'error_details') else str(error)
            return PublishResult(
                success=False,
                error_message=f"Google Blogger API Error [{error.status_code}]: {error_details}"
            )
        except Exception as e:
            return PublishResult(
                success=False,
                error_message=f"Terjadi kesalahan saat menerbitkan draf di Blogger: {str(e)}"
            )

    def update_post(
        self,
        post_id: str,
        title: str,
        content_html: str,
        labels: Optional[List[str]] = None
    ) -> PublishResult:
        """
        Memperbarui judul dan konten postingan yang sudah ada di Blogger
        lewat posts().update() — berlaku untuk draf maupun artikel yang
        sudah published, tanpa membuat postingan baru.

        labels yang diberikan ikut dikirim dalam body. Ini penting
        karena posts().update() mengganti seluruh postingan: label yang
        tidak disertakan akan terhapus di Blogger (terbukti 2026-11-17:
        dua artikel kehilangan label setelah diedit lewat PUT).
        """
        blog_id = self.credentials.get("blog_id")
        if not blog_id:
            return PublishResult(
                success=False,
                error_message="blog_id belum ditentukan pada profil akun Blogger ini."
            )

        try:
            service = self._get_service()
            body = {
                "title": title,
                "content": content_html,
            }
            if labels is not None:
                body["labels"] = labels

            request = service.posts().update(
                blogId=str(blog_id),
                postId=str(post_id),
                body=body
            )
            response = request.execute()

            post_url = response.get("url") if isinstance(response, dict) else None

            return PublishResult(
                success=True,
                remote_post_id=str(post_id),
                remote_url=post_url,
                raw_response=response if isinstance(response, dict) else None
            )

        except HttpError as error:
            error_details = error.error_details if hasattr(error, 'error_details') else str(error)
            return PublishResult(
                success=False,
                error_message=f"Google Blogger API Error [{error.status_code}]: {error_details}"
            )
        except Exception as e:
            return PublishResult(
                success=False,
                error_message=f"Terjadi kesalahan saat memperbarui postingan di Blogger: {str(e)}"
            )

    def delete_post(self, post_id: str) -> PublishResult:
        """Menghapus sebuah postingan dari Blogger lewat posts().delete()."""
        blog_id = self.credentials.get("blog_id")
        if not blog_id:
            return PublishResult(
                success=False,
                error_message="blog_id belum ditentukan pada profil akun Blogger ini."
            )

        try:
            service = self._get_service()
            service.posts().delete(
                blogId=str(blog_id),
                postId=str(post_id)
            ).execute()

            return PublishResult(
                success=True,
                remote_post_id=str(post_id)
            )

        except HttpError as error:
            error_details = error.error_details if hasattr(error, 'error_details') else str(error)
            return PublishResult(
                success=False,
                error_message=f"Google Blogger API Error [{error.status_code}]: {error_details}"
            )
        except Exception as e:
            return PublishResult(
                success=False,
                error_message=f"Terjadi kesalahan saat menghapus postingan di Blogger: {str(e)}"
            )

    def create_page(
        self,
        title: str,
        content_html: str,
        is_draft: bool = True
    ) -> PublishResult:
        """
        Membuat halaman statis di Blogger lewat pages().insert() —
        dipakai untuk halaman Tentang, Kontak, dan Kebijakan Privasi.
        """
        blog_id = self.credentials.get("blog_id")
        if not blog_id:
            return PublishResult(
                success=False,
                error_message="blog_id belum ditentukan pada profil akun Blogger ini."
            )

        try:
            service = self._get_service()
            body = {
                "title": title,
                "content": content_html,
            }

            # isDraft: True untuk Draf, False untuk langsung terbit (LIVE)
            request = service.pages().insert(
                blogId=str(blog_id),
                body=body,
                isDraft=is_draft
            )
            response = request.execute()

            page_id = response.get("id")
            page_url = response.get("url")

            return PublishResult(
                success=True,
                remote_post_id=str(page_id) if page_id else None,
                remote_url=page_url,
                raw_response=response
            )

        except HttpError as error:
            error_details = error.error_details if hasattr(error, 'error_details') else str(error)
            return PublishResult(
                success=False,
                error_message=f"Google Blogger API Error [{error.status_code}]: {error_details}"
            )
        except Exception as e:
            return PublishResult(
                success=False,
                error_message=f"Terjadi kesalahan saat membuat halaman di Blogger: {str(e)}"
            )

    def list_pages(self) -> List[Dict[str, Any]]:
        """
        Mengambil daftar halaman statis dari Blogger lewat
        pages().list(). Kalau blog_id belum ada atau API gagal,
        kembalikan list kosong supaya dashboard tetap bisa render.
        """
        blog_id = self.credentials.get("blog_id")
        if not blog_id:
            return []

        try:
            service = self._get_service()
            response = service.pages().list(
                blogId=str(blog_id),
                fetchBodies=False
            ).execute()
            items = response.get("items", [])
            return [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "status": item.get("status"),
                    "url": item.get("url"),
                    "updated": item.get("updated"),
                }
                for item in items
            ]
        except Exception as e:
            # Dashboard menangkap error ini dan menampilkan baris
            # "Gagal memuat halaman" tanpa membuat halaman jadi 500.
            raise RuntimeError(f"Gagal mengambil daftar halaman dari Blogger: {str(e)}")

    def delete_page(self, page_id: str) -> PublishResult:
        """Menghapus sebuah halaman statis dari Blogger lewat pages().delete()."""
        blog_id = self.credentials.get("blog_id")
        if not blog_id:
            return PublishResult(
                success=False,
                error_message="blog_id belum ditentukan pada profil akun Blogger ini."
            )

        try:
            service = self._get_service()
            service.pages().delete(
                blogId=str(blog_id),
                pageId=str(page_id)
            ).execute()

            return PublishResult(
                success=True,
                remote_post_id=str(page_id)
            )

        except HttpError as error:
            error_details = error.error_details if hasattr(error, 'error_details') else str(error)
            return PublishResult(
                success=False,
                error_message=f"Google Blogger API Error [{error.status_code}]: {error_details}"
            )
        except Exception as e:
            return PublishResult(
                success=False,
                error_message=f"Terjadi kesalahan saat menghapus halaman di Blogger: {str(e)}"
            )

    def list_user_blogs(self) -> List[Dict[str, Any]]:
        """
        Membantu menemukan daftar blog dan blogId yang dimiliki oleh akun Google ini.
        """
        try:
            service = self._get_service()
            response = service.blogs().listByUser(userId="self").execute()
            items = response.get("items", [])
            return [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "url": item.get("url"),
                    "posts_count": item.get("posts", {}).get("totalItems", 0)
                }
                for item in items
            ]
        except Exception as e:
            raise RuntimeError(f"Gagal mengambil daftar blog dari akun Google: {str(e)}")

    def get_page_views(self, time_range: str) -> int:
        """
        Total kunjungan blog untuk satu rentang waktu lewat
        pageViews().get(blogId, range=...). Nilai range yang sah
        menurut dokumentasi Blogger API v3: "30DAYS", "7DAYS", dan
        "all" (sepanjang waktu) — BUKAN "ALL_TIME". Responsnya
        {"kind": "blogger#page_views", "blogId": ..., "counts":
        [{"timeRange": ..., "count": ...}]} — satu angka agregat
        per rentang, TANPA rincian per hari. Mengangkat RuntimeError
        kalau blog_id belum ada atau API gagal, supaya pemanggil
        bisa menampilkan "belum tersedia" / 502 dengan pesan jelas.
        """
        blog_id = self.credentials.get("blog_id")
        if not blog_id:
            raise RuntimeError("blog_id belum ditentukan pada profil akun Blogger ini.")

        try:
            service = self._get_service()
            response = service.pageViews().get(
                blogId=str(blog_id),
                range=time_range
            ).execute()
        except HttpError as error:
            error_details = error.error_details if hasattr(error, 'error_details') else str(error)
            raise RuntimeError(
                f"Google Blogger API Error [{error.status_code}]: {error_details}"
            )
        except Exception as e:
            raise RuntimeError(f"Gagal mengambil statistik kunjungan dari Blogger: {str(e)}")

        if not isinstance(response, dict):
            return 0
        counts = response.get("counts", []) or []
        wanted = time_range.upper()
        for entry in counts:
            entry_range = (entry.get("timeRange") or "").upper()
            # Untuk range "all", Blogger mengembalikan timeRange
            # "ALL_TIME" (atau "all" di beberapa versi discovery doc).
            if entry_range == wanted or (wanted == "ALL" and entry_range in ("ALL_TIME", "ALL")):
                return int(entry.get("count") or 0)
        if len(counts) == 1:
            return int(counts[0].get("count") or 0)
        return sum(int(entry.get("count") or 0) for entry in counts)

    def list_comments(self) -> List[Dict[str, Any]]:
        """
        Daftar komentar blog (semua postingan) lewat
        comments().listByBlog(blogId) — ini satu-satunya method
        list komentar tingkat blog; comments().list() justru
        per-postingan. Mengangkat HttpError supaya pemanggil bisa
        memetakan 404 (blog/komentar tidak ditemukan).
        """
        blog_id = self.credentials.get("blog_id")
        if not blog_id:
            raise RuntimeError("blog_id belum ditentukan pada profil akun Blogger ini.")

        service = self._get_service()
        response = service.comments().listByBlog(
            blogId=str(blog_id),
            fetchBodies=True,
            maxResults=100
        ).execute()
        items = response.get("items", []) if isinstance(response, dict) else []
        return [
            {
                "id": item.get("id"),
                "author": (item.get("author") or {}).get("displayName") or "Anonim",
                "content": item.get("content"),
                "status": item.get("status"),
                "published": item.get("published"),
                "post_id": (item.get("post") or {}).get("id"),
            }
            for item in items
        ]

    def _moderate_comment(
        self, action: str, post_id: str, comment_id: str
    ) -> PublishResult:
        """
        Jalur bersama approve / markAsSpam / delete komentar.
        Ketiga method Blogger API v3 ini per-postingan:
        POST /blogs/{blogId}/posts/{postId}/comments/{commentId}/approve
        (dan .../spam, DELETE ...). HttpError dibiarkan naik supaya
        pemanggil bisa memetakan 404 — berbeda dengan method publish
        yang mengembalikan PublishResult(success=False).
        """
        blog_id = self.credentials.get("blog_id")
        if not blog_id:
            raise RuntimeError("blog_id belum ditentukan pada profil akun Blogger ini.")

        service = self._get_service()
        comments = service.comments()
        if action == "approve":
            request = comments.approve(
                blogId=str(blog_id), postId=str(post_id), commentId=str(comment_id)
            )
        elif action == "spam":
            request = comments.markAsSpam(
                blogId=str(blog_id), postId=str(post_id), commentId=str(comment_id)
            )
        else:
            request = comments.delete(
                blogId=str(blog_id), postId=str(post_id), commentId=str(comment_id)
            )
        response = request.execute()
        return PublishResult(
            success=True,
            remote_post_id=str(comment_id),
            raw_response=response if isinstance(response, dict) else None
        )

    def approve_comment(self, post_id: str, comment_id: str) -> PublishResult:
        """Menyetujui komentar lewat comments().approve() (per-postingan)."""
        return self._moderate_comment("approve", post_id, comment_id)

    def mark_comment_as_spam(self, post_id: str, comment_id: str) -> PublishResult:
        """Menandai komentar sebagai spam lewat comments().markAsSpam() (per-postingan)."""
        return self._moderate_comment("spam", post_id, comment_id)

    def delete_comment(self, post_id: str, comment_id: str) -> PublishResult:
        """Menghapus komentar lewat comments().delete() (per-postingan)."""
        return self._moderate_comment("delete", post_id, comment_id)
