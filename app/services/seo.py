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


def slugify(title: str) -> str:
    """Slug URL dari judul: huruf kecil, spasi/simbol menjadi '-', dan
    karakter non-ASCII dibuang. Dipakai draf hasil rewrite (dan nanti
    SEO otomatis)."""
    import unicodedata
    text = unicodedata.normalize("NFKD", title or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


# --- SEO otomatis (Patch 3) -------------------------------------------
# Semua fungsi di bawah ini pure (tanpa I/O): dipakai endpoint
# POST /api/v1/seo-optimize dan tombol "Terapkan SEO" di dashboard.

# Kata umum Bahasa Indonesia yang diabaikan saat mencari kata kunci.
STOPWORDS_ID = {
    "yang", "dan", "di", "ke", "dari", "untuk", "dengan", "ini", "itu",
    "adalah", "pada", "sebagai", "dalam", "atau", "juga", "akan", "bisa",
    "oleh", "saat", "karena", "jika", "tidak", "lebih", "sangat", "para",
    "setiap", "sebuah", "agar", "lalu", "kemudian", "serta", "maupun",
    "antara", "tanpa", "sudah", "telah", "masih", "hanya", "bahwa",
    "tentang", "setelah", "sebelum", "ketika", "sambil", "hingga",
    "sampai", "bagi", "kepada", "saya", "kamu", "kita", "mereka", "dia",
    "anda", "kalau", "supaya", "namun", "tetapi", "justru", "malah",
    "pun", "sih", "dong", "nya", "kah", "lah", "punya", "ada", "jadi",
    "cara", "membuat", "bagian", "hal", "satu", "dua", "tiga",
}


def _plain_text(content_html: str) -> str:
    """Teks polos dari HTML (dipakai generator meta & keterbacaan)."""
    parser = _ArticleParser()
    parser.feed(content_html or "")
    return re.sub(r"\s+", " ", parser.plain_text()).strip()


def _strip_tags(fragment: str) -> str:
    return re.sub(r"<[^>]+>", " ", fragment or "")


def keywords_from_text(text: str, top_n: int = 10):
    """Kata kunci dari teks: kata >= 4 huruf, bukan stopword, diurutkan
    berdasarkan frekuensi (lalu alfabetis bila seri)."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    freq = {}
    for w in words:
        if len(w) < 4 or w in STOPWORDS_ID:
            continue
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:top_n]]


def generate_meta_description(title, content_html, target_len=150):
    """Meta description otomatis dari isi artikel (~150 karakter).

    Mengambil kalimat-kalimat dari awal isi; kalimat pertama yang
    mengandung kata kunci judul diutamakan. Dipotong pada batas kata
    bila melewati 160 karakter. Bila isi terlalu pendek, kembalikan
    apa adanya (cek SEO tetap akan menandainya)."""
    text = _plain_text(content_html)
    if not text:
        return ""
    title_words = set(keywords_from_text(title or "", top_n=20))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return text[:160]
    start = 0
    for i, s in enumerate(sentences):
        words = set(re.findall(r"[a-z0-9]+", s.lower()))
        if words & title_words:
            start = i
            break
    desc = ""
    for s in sentences[start:]:
        candidate = (desc + " " + s).strip()
        if len(candidate) <= 160:
            desc = candidate
            if len(desc) >= 140:
                break
        else:
            # Kalimat berikutnya tidak muat utuh: isi sisa ruang dengan
            # potongannya (batas kata) bila deskripsi masih pendek.
            if len(desc) < 140:
                room = 160 - len(desc) - 1
                part = s[:room]
                last_space = part.rfind(" ")
                if last_space > 20:
                    part = part[:last_space]
                desc = (desc + " " + part).strip()
            break
    return desc.strip()


def suggest_internal_links(current, candidates, max_results=4):
    """Saran tautan internal: artikel lain yang SUDAH published di channel
    yang sama (punya remote_url), dinilai dari irisan kata kunci judul +
    label + isi. Kembalikan maks 4 kandidat + anchor text + skor."""
    current_keys = set(keywords_from_text(
        (current.title or "") + " "
        + (current.labels or "").replace(",", " ") + " "
        + _plain_text(current.content_html or ""), top_n=20))
    scored = []
    for cand in candidates:
        if cand.id == current.id:
            continue
        if (cand.status or "") != "published" or not cand.remote_url:
            continue
        cand_keys = set(keywords_from_text(
            (cand.title or "") + " " + (cand.labels or "").replace(",", " "),
            top_n=20))
        overlap = current_keys & cand_keys
        if not overlap:
            continue
        scored.append({
            "publication_id": cand.id,
            "title": cand.title,
            "url": cand.remote_url,
            "anchor": cand.title,
            "score": len(overlap),
            "matched_keywords": sorted(overlap),
        })
    scored.sort(key=lambda x: (-x["score"], x["title"] or ""))
    return scored[:max_results]


def readability(content_html):
    """Skor keterbacaan 0-100 dari panjang kalimat & paragraf rata-rata.

    Kalimat <= 15 kata dan paragraf <= 60 kata dianggap mudah dibaca.
    Mengembalikan skor, label, dan angka-angka pendukungnya."""
    text = _plain_text(content_html)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    para_blocks = re.findall(r"<p[^>]*>(.*?)</p>", content_html or "",
                             re.S | re.I)
    if para_blocks:
        paras = [_strip_tags(p).strip() for p in para_blocks]
        paras = [p for p in paras if p]
    else:
        paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    words_total = len(text.split()) if text else 0
    avg_sentence = round(words_total / len(sentences), 1) if sentences else 0
    avg_para = round(words_total / len(paras), 1) if paras else 0
    s_score = 100 if avg_sentence <= 15 else (70 if avg_sentence <= 20 else 40)
    p_score = 100 if avg_para <= 60 else (70 if avg_para <= 100 else 40)
    score = round(s_score * 0.6 + p_score * 0.4)
    label = ("Mudah dibaca" if score >= 80
             else ("Sedang" if score >= 60 else "Perlu dipersingkat"))
    return {
        "score": score,
        "label": label,
        "avg_sentence_words": avg_sentence,
        "avg_paragraph_words": avg_para,
        "sentence_count": len(sentences),
        "paragraph_count": len(paras),
    }


def suggest_alt_texts(content_html):
    """Saran alt text untuk setiap <img> yang alt-nya kosong/tidak ada.

    Saran diambil dari 8 kata pertama heading/paragraph terdekat
    sebelumnya; bila tidak ada konteks, dipakai nama file gambarnya."""
    results = []
    html = content_html or ""
    for m in re.finditer(r"<img\b[^>]*>", html, re.I):
        tag = m.group(0)
        alt_m = re.search(r"""alt\s*=\s*['"]([^'"]*)['"]""", tag)
        if alt_m and alt_m.group(1).strip():
            continue
        src_m = re.search(r"""src\s*=\s*['"]([^'"]+)['"]""", tag)
        src = src_m.group(1) if src_m else ""
        before = html[:m.start()]
        headings = re.findall(r"<h[23][^>]*>(.*?)</h[23]>", before, re.S | re.I)
        paras = re.findall(r"<p[^>]*>(.*?)</p>", before, re.S | re.I)
        context = ""
        if headings:
            context = _strip_tags(headings[-1])
        elif paras:
            context = _strip_tags(paras[-1])
        words = re.sub(r"\s+", " ", context).strip().split(" ")
        words = [w for w in words if w]
        if words:
            suggestion = " ".join(words[:8])
        else:
            fname = src.split("/")[-1].split("?")[0]
            fname = re.sub(r"\.(jpe?g|png|webp|gif)$", "", fname, flags=re.I)
            fname = re.sub(r"[-_]+", " ", fname).strip()
            suggestion = fname or "Gambar artikel"
        results.append({
            "src": src,
            "current_alt": alt_m.group(1) if alt_m else "",
            "suggested_alt": suggestion,
        })
    return results


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
