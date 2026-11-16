"""
Cek SEO artikel — pure function, tanpa I/O, tanpa dependency baru.

Memakai html.parser (stdlib) untuk membaca tag <img>, <h2>/<h3>, dan
<a> dari konten HTML. Dipakai endpoint POST /api/v1/seo-check dan
tombol "Cek SEO" di dashboard. Skor = persen check yang lolos.
"""
import re
from html.parser import HTMLParser

# Batas panjang yang dipakai para praktisi SEO (dan yang diminta tugas):
# judul 50-60 karakter, meta description 140-160 karakter.
TITLE_MIN, TITLE_MAX = 50, 60
META_MIN, META_MAX = 140, 160
INTERNAL_DOMAIN = "blogspot.com"


class _ArticleParser(HTMLParser):
    """Kumpulkan gambar (+alt), subheading, dan link dari konten HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []        # list alt ("" kalau tidak ada)
        self.has_subheading = False
        self.has_internal_link = False
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "img":
            self.images.append(attrs_d.get("alt"))
        elif tag in ("h2", "h3"):
            self.has_subheading = True
        elif tag == "a":
            href = attrs_d.get("href") or ""
            if INTERNAL_DOMAIN in href:
                self.has_internal_link = True

    def handle_data(self, data):
        self._text_parts.append(data)

    def plain_text(self) -> str:
        return " ".join(self._text_parts)


def _word_count(content_html: str) -> int:
    parser = _ArticleParser()
    parser.feed(content_html or "")
    text = parser.plain_text()
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def check_seo(title, meta_description, content_html, target_word_count=800):
    """
    Cek SEO sebuah artikel. Mengembalikan dict:
        {"score": int 0-100, "checks": [{id, label, passed, detail}]}
    Masing-masing check: judul 50-60 karakter; meta 140-160 karakter;
    jumlah kata >= target; ada >= 1 gambar; semua gambar punya alt;
    ada >= 1 subheading (h2/h3); ada >= 1 internal link (blogspot.com).
    """
    title = (title or "").strip()
    meta = (meta_description or "").strip()
    content_html = content_html or ""
    try:
        target = int(target_word_count or 0)
    except (TypeError, ValueError):
        target = 0

    parser = _ArticleParser()
    parser.feed(content_html)
    words = _word_count(content_html)
    n_images = len(parser.images)
    missing_alt = sum(1 for alt in parser.images if not (alt or "").strip())

    checks = [
        {
            "id": "title_length",
            "label": f"Judul 50-60 karakter (saat ini {len(title)})",
            "passed": TITLE_MIN <= len(title) <= TITLE_MAX,
            "detail": f"Judul berisi {len(title)} karakter.",
        },
        {
            "id": "meta_length",
            "label": f"Meta description 140-160 karakter (saat ini {len(meta)})",
            "passed": META_MIN <= len(meta) <= META_MAX,
            "detail": (
                f"Meta description berisi {len(meta)} karakter."
                if meta else "Meta description kosong."
            ),
        },
        {
            "id": "word_count",
            "label": f"Jumlah kata >= {target} (saat ini {words})",
            "passed": words >= target if target > 0 else words > 0,
            "detail": f"Artikel berisi {words} kata, target {target} kata.",
        },
        {
            "id": "has_image",
            "label": "Ada minimal 1 gambar",
            "passed": n_images >= 1,
            "detail": (
                f"Ditemukan {n_images} gambar."
                if n_images else "Tidak ada gambar di konten."
            ),
        },
        {
            "id": "image_alt",
            "label": "Semua gambar punya alt text",
            "passed": missing_alt == 0,
            "detail": (
                "Tidak ada gambar, jadi tidak ada alt yang diperiksa."
                if n_images == 0 else
                f"{missing_alt} dari {n_images} gambar tanpa alt text."
                if missing_alt else
                f"Semua {n_images} gambar punya alt text."
            ),
        },
        {
            "id": "has_subheading",
            "label": "Ada minimal 1 subheading (h2/h3)",
            "passed": parser.has_subheading,
            "detail": (
                "Ditemukan subheading h2/h3."
                if parser.has_subheading else "Tidak ada subheading h2/h3."
            ),
        },
        {
            "id": "has_internal_link",
            "label": "Ada minimal 1 internal link (blogspot.com)",
            "passed": parser.has_internal_link,
            "detail": (
                "Ditemukan link ke blogspot.com."
                if parser.has_internal_link
                else "Tidak ada link ke blogspot.com."
            ),
        },
    ]

    passed = sum(1 for c in checks if c["passed"])
    score = round(passed / len(checks) * 100) if checks else 0
    return {"score": score, "checks": checks}
