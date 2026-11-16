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
    def publish_draft(self, post_id: str) -> PublishResult:
        """
        Menerbitkan draf yang sudah ada di platform target tanpa
        membuat postingan baru (menghindari duplikat).
        """
        pass

    @abstractmethod
    def delete_post(self, post_id: str) -> PublishResult:
        """
        Menghapus sebuah postingan dari platform target.
        """
        pass
