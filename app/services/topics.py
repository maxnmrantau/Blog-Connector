"""Ide topik otomatis: usulan judul dari headline feed + niche channel.

Dua mode:
- Kata kunci (v1, tanpa LLM): judul dibuat dari kata kunci headline
  terbaru + template Bahasa Indonesia + ide turunan niche.
- Gemini (bila kunci terkonfigurasi di Pengaturan AI): judul dibuat AI
  dari headline + niche/tone channel; bila gagal, otomatis fallback
  ke mode kata kunci (respons membawa ai_error).

Setiap ide bisa diubah menjadi draf kerangka (judul + H2) lewat
create_draft_from_idea — draf saja, tidak pernah auto-publish.
"""
import html as html_lib
import re
from collections import Counter

from app.models import ArticleSource, FeedSource, Publication
from app.services.rewrite import DEFAULT_MODEL, GeminiError, generate_text
from app.services.seo import keywords_from_text, slugify
from app.services.settings import GEMINI_API_KEY, get_setting_value

IDEAS_LIMIT = 10
IDEAS_MIN = 5

TITLE_TEMPLATES = [
    "{kw} untuk Pemula: Panduan {niche} dari Nol",
    "Cara Memulai {kw}: Langkah demi Langkah",
    "{kw}: 5 Hal yang Perlu Kamu Tahu",
    "Mengenal {kw} Lebih Dekat",
    "Tips {kw} yang Wajib Dicoba",
    "Panduan Lengkap {kw} untuk {niche}",
]
NICHE_TEMPLATES = [
    "Panduan {niche} untuk Pemula: Mulai dari Nol",
    "{niche}: Cara Memulai dari Nol",
    "5 Kesalahan Umum dalam {niche} (dan Cara Menghindarinya)",
    "Mengenal {niche} Lebih Dekat: Panduan Lengkap",
    "{niche} untuk Pemula: Alat, Teknik, dan Tips",
]


def _headline_dict(source):
    return {
        "id": source.id,
        "title": source.title or "Tanpa Judul",
        "url": source.url or "",
        "source_name": source.source_name or "",
        "text": (source.title or "") + " " + (source.raw_content or "")[:500],
    }


def collect_headlines(db, channel, limit=30):
    """Headline terbaru untuk channel ini.

    Mengembalikan (headlines, headline_source): bila ada feed channel
    dan minimal 3 itemnya cocok dengan nama feed, pakai yang cocok
    ("channel_feeds"); bila tidak, pakai headline terbaru apa pun
    ("recent"); bila tidak ada sama sekali, ([], "none").
    """
    feeds = db.query(FeedSource).filter(FeedSource.channel_id == channel.id).all()
    active = [f for f in feeds if f.active]
    pool = active or feeds
    wanted_names = {(f.title or "").strip().lower() for f in pool if f.title}
    recent = (
        db.query(ArticleSource)
        .order_by(ArticleSource.ingested_at.desc())
        .limit(limit)
        .all()
    )
    headlines = [_headline_dict(s) for s in recent]
    if not headlines:
        return [], "none"
    if wanted_names:
        matched = [
            h
            for h in headlines
            if (h["source_name"] or "").strip().lower() in wanted_names
        ]
        if len(matched) >= 3:
            return matched, "channel_feeds"
        return headlines, "recent"
    return headlines, "recent"


def generate_keyword_ideas(headlines, channel, limit=IDEAS_LIMIT):
    """Ide judul berbasis kata kunci (tanpa LLM)."""
    niche = (channel.niche or "umum").strip()
    niche_cap = niche[:1].upper() + niche[1:] if niche else "Umum"
    ideas = []
    seen = set()

    def add(title, angle, keywords, headline=None, origin="headline"):
        key = title.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        ideas.append(
            {
                "title": title,
                "angle": angle,
                "keywords": keywords,
                "source_title": (headline or {}).get("title"),
                "source_url": (headline or {}).get("url"),
                "source_id": (headline or {}).get("id"),
                "origin": origin,
            }
        )

    # 1. Satu ide per headline (rotasi template).
    for i, h in enumerate(headlines):
        if len(ideas) >= limit:
            break
        kws = keywords_from_text(h["text"], top_n=3)
        if not kws:
            continue
        kw = kws[0][:1].upper() + kws[0][1:]
        template = TITLE_TEMPLATES[i % len(TITLE_TEMPLATES)]
        add(
            template.format(kw=kw, niche=niche_cap),
            f"Berdasarkan headline: {h['title']}",
            kws,
            headline=h,
            origin="headline",
        )
    # 2. Klaster: kata kunci yang muncul di >= 2 headline.
    counts = Counter()
    for h in headlines:
        for kw in set(keywords_from_text(h["text"], top_n=4)):
            counts[kw] += 1
    for kw, c in counts.most_common():
        if len(ideas) >= limit or c < 2:
            break
        kw_cap = kw[:1].upper() + kw[1:]
        add(
            f"Panduan Lengkap {kw_cap}: Semua yang Perlu Kamu Tahu",
            f"Topik '{kw}' muncul di {c} headline terbaru.",
            [kw],
            origin="keyword",
        )
    # 3. Top-up dari niche bila masih kurang dari minimum.
    for template in NICHE_TEMPLATES:
        if len(ideas) >= IDEAS_MIN:
            break
        add(
            template.format(niche=niche_cap),
            f"Ide dasar dari niche channel ({niche}).",
            [niche.lower()],
            origin="niche",
        )
    return ideas[:limit]


def _parse_ai_ideas(text):
    """Parse baris '1. Judul — sudut singkat' dari respons Gemini."""
    ideas = []
    for line in (text or "").splitlines():
        m = re.match(r"^\s*\d+[.)]\s*(.+?)\s*$", line)
        if not m:
            continue
        raw = m.group(1)
        if "—" in raw:
            title, angle = raw.split("—", 1)
        elif " - " in raw:
            title, angle = raw.split(" - ", 1)
        else:
            title, angle = raw, ""
        title = title.strip().strip("\"'")
        if len(title) < 10:
            continue
        ideas.append(
            {
                "title": title,
                "angle": angle.strip(),
                "keywords": keywords_from_text(title, top_n=4),
                "source_title": None,
                "source_url": None,
                "source_id": None,
                "origin": "ai",
            }
        )
    return ideas


def generate_ai_ideas(headlines, channel, api_key, model, http_client=None):
    """Ide judul dari Gemini berdasarkan headline + profil channel."""
    niche = channel.niche or "umum"
    tone = channel.tone_of_voice or "Informatif & Santai"
    target = channel.target_word_count or 800
    lines = "\n".join(f"- {h['title']}" for h in headlines[:10])
    prompt = (
        f"Kamu adalah editor blog niche '{niche}' (gaya: {tone}).\n"
        f"Buatkan 8 ide judul artikel blog dalam Bahasa Indonesia untuk pembaca pemula, "
        f"berdasarkan headline terbaru berikut (boleh terinspirasi, jangan menyalin judulnya):\n"
        f"{lines}\n\n"
        f"Aturan: setiap judul harus orisinal, spesifik, dan cocok untuk artikel sekitar {target} kata. "
        f"Tulis SATU ide per baris dengan format persis: '1. Judul Artikel — sudut singkat (maks 12 kata)'. "
        f"Jangan tambah penjelasan lain."
    )
    text = generate_text(
        api_key,
        prompt,
        model=model,
        temperature=0.7,
        max_output_tokens=1024,
        http_client=http_client,
    )
    return _parse_ai_ideas(text)


def get_ideas(channel, db, http_client=None):
    """Kumpulkan ide topik: Gemini bila ada kunci, fallback kata kunci."""
    headlines, headline_source = collect_headlines(db, channel)
    api_key = get_setting_value(db, GEMINI_API_KEY)
    model = get_setting_value(db, "gemini_model") or DEFAULT_MODEL
    ai_used = False
    ai_error = None
    ideas = []
    if api_key:
        try:
            ideas = generate_ai_ideas(
                headlines, channel, api_key, model, http_client=http_client
            )
            ai_used = True
        except GeminiError as e:
            ai_error = str(e)
            ideas = []
    if len(ideas) < IDEAS_MIN:
        kw_ideas = generate_keyword_ideas(headlines, channel)
        seen = {i["title"].strip().lower() for i in ideas}
        for k in kw_ideas:
            if len(ideas) >= IDEAS_MIN and ai_used:
                break
            if k["title"].strip().lower() not in seen:
                ideas.append(k)
                seen.add(k["title"].strip().lower())
    # ai_used hanya True bila benar-benar ada ide dari AI di hasil akhir.
    ai_used = any(i.get("origin") == "ai" for i in ideas)
    return {
        "channel_id": channel.id,
        "niche": channel.niche,
        "headline_source": headline_source,
        "headline_count": len(headlines),
        "ai_used": ai_used,
        "ai_error": ai_error,
        "ideas": ideas[:IDEAS_LIMIT],
    }


def create_draft_from_idea(db, channel, idea):
    """Buat draf kerangka (judul + H2 + placeholder) dari satu ide.

    Status selalu 'draft'. Bila ide berasal dari headline, tautan
    atribusi ke sumber disertakan di akhir konten.
    """
    title = (idea.get("title") or "").strip()
    if not title:
        raise ValueError("Judul ide tidak boleh kosong.")
    angle = (idea.get("angle") or "").strip()
    keywords = idea.get("keywords") or []
    kw = (keywords[0] if keywords else (channel.niche or "topik")).strip()
    kw_cap = kw[:1].upper() + kw[1:]
    h2s = [
        f"Apa Itu {kw_cap}?",
        f"Cara Memulai {kw_cap}",
        f"Tips {kw_cap} untuk Pemula",
        "Penutup",
    ]
    parts = [
        "<!-- Kerangka draf otomatis dari Ide Topik — lengkapi sebelum diterbitkan -->"
    ]
    if angle:
        parts.append(f"<p>{html_lib.escape(angle)}</p>")
    else:
        parts.append(f"<p>Artikel tentang {html_lib.escape(title.lower())}.</p>")
    for h2 in h2s:
        parts.append(f"<h2>{html_lib.escape(h2)}</h2>")
        parts.append(f"<p>[Tulis penjelasan {html_lib.escape(h2.lower())} di sini]</p>")
    if idea.get("source_url"):
        src_title = idea.get("source_title") or "tautan sumber"
        parts.append(
            "<p>Sumber inspirasi: "
            f"<a href=\"{html_lib.escape(idea['source_url'])}\">"
            f"{html_lib.escape(src_title)}</a></p>"
        )
    pub = Publication(
        source_id=idea.get("source_id"),
        channel_id=channel.id,
        title=title,
        slug=slugify(title),
        meta_description="",
        content_html="\n".join(parts),
        labels=channel.default_labels or channel.niche,
        status="draft",
    )
    db.add(pub)
    db.commit()
    db.refresh(pub)
    return pub
