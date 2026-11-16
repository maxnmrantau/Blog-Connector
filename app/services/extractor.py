import trafilatura
from typing import Optional, Dict

class ArticleExtractor:
    """
    Menyedot teks bersih dan metadata (judul, tanggal, pengarang)
    dari URL berita/blog tanpa iklan, menu navigasi, atau popup.
    """

    @staticmethod
    def extract_from_url(url: str) -> Optional[Dict[str, str]]:
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return None

            # Ekstraksi teks artikel utama
            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=True,
                no_fallback=False
            )

            # Ekstraksi metadata tambahan (judul, tanggal)
            metadata = trafilatura.extract_metadata(downloaded)

            return {
                "url": url,
                "title": metadata.title if metadata and metadata.title else "Tanpa Judul",
                "text": text or "",
                "author": metadata.author if metadata and metadata.author else None,
                "date": metadata.date if metadata and metadata.date else None
            }
        except Exception as e:
            raise RuntimeError(f"Gagal mengekstrak artikel dari {url}: {str(e)}")
