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
