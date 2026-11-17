"""Ide topik otomatis: usulan judul dari headline feed + niche channel.

Dua mode:
- Kata kunci (v1, tanpa LLM): judul dibuat dari kata kunci headline
  terbaru + template Bahasa Indonesia + ide turunan niche.
- Gemini (bila kunci terkonfigurasi di Pengaturan AI): judul dibuat AI
  dari headline + niche/tone channel; bila gagal, otomatis fallback
  ke mode kata kunci (respons membawa ai_error).

Setiap ide bisa diubah menjadi draf kerangka (judul + H2) lewat
create_draft_from_idea — draf saja, tidak pernah auto-publish.

Ide Topik v2 (collect_v2_ideas): ide datang dari SINYAL NYATA, bukan
dari string niche channel — niche TIDAK dipakai sama sekali di v2:
- trends: berita populer Indonesia (Google News RSS, tanpa kunci).
- search_console: kueri dengan impresi tinggi, posisi 5-20, CTR di
  bawah rata-rata (peluang konten) — memakai ulang get_overview.
- feeds: headline FeedSource channel (logika feed yang sudah ada).
- gaps: analisis Publication channel (label yang baru 1 artikel,
  artikel yang layak dibuat bagian 2).
- seed: kata kunci bebas dari pengguna — dicari di Google News
  Indonesia, ide dari headline nyata (bukan template); niche
  diabaikan total. Bila tidak ada berita tentang kata kunci itu,
  sumber ini kosong + pesan jujur.

Gemini TIDAK dipanggil di endpoint ide v2 — ia hanya memperkaya
kerangka di topics-outline (patch 03), dan selalu ada fallback
template bila Gemini gagal. Setiap ide v2 membawa skor 0-100 dan
alasan satu kalimat yang menyebut sinyalnya; skor dihitung dari
sinyal yang terlihat (bukan angka palsu presisi). Sumber yang tidak
bisa diakses mengembalikan list kosong + pesan jujur di
respons["sources"], bukan ide palsu.
"""
import html as html_lib
import re
import urllib.parse
from collections import Counter

from app.models import ArticleSource, FeedSource, Publication, TopicIdea
from app.services.rewrite import DEFAULT_MODEL, GeminiError, generate_text
from app.services.search_console import SearchConsoleError, get_overview
from app.services.seo import keywords_from_text, slugify
from app.services.settings import GEMINI_API_KEY, get_setting_value

# feedparser dipakai untuk RSS Google News; di-import malas seperti
# routes_feeds supaya aplikasi tetap boot bila belum terpasang.
try:
    import feedparser
except ImportError:  # pragma: no cover
    feedparser = None

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
    # Bila ide ini ada di perpustakaan (judul sama), tandai dipakai dan
    # tautkan ke draf ini — supaya tidak muncul lagi sebagai ide baru.
    _mark_library_used(db, channel.id, title, pub.id)
    return pub


def _mark_library_used(db, channel_id, title, publication_id):
    """Tandai ide perpustakaan berjudul sama sebagai 'dipakai'.

    Dipakai create_draft_from_idea dan (patch 03) outline. Aman bila
    tabel belum ada (database lama sebelum migrasi berjalan).
    """
    try:
        row = (
            db.query(TopicIdea)
            .filter(
                TopicIdea.channel_id == channel_id,
                TopicIdea.title_norm == normalize_title(title),
                TopicIdea.status == "baru",
            )
            .first()
        )
    except Exception:
        return
    if row is None:
        return
    row.status = "dipakai"
    row.publication_id = publication_id
    db.commit()


# ---------------------------------------------------------------------------
# Ide Topik v2 — multi-sumber berbasis sinyal nyata (tanpa niche).
# ---------------------------------------------------------------------------

# Sumber "Tren" memakai Google News RSS Indonesia — Google Trends RSS
# sudah mati (daily + realtime keduanya HTTP 404 sejak lama; Google
# menonaktifkan endpoint-nya), jadi tren tidak lagi diambil dari sana.
# Top stories (tanpa kunci) + search RSS bila dipanggil dengan seed.
NEWS_RSS_URL = "https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id"
NEWS_SEARCH_RSS_URL = (
    "https://news.google.com/rss/search?q={q}&hl=id&gl=ID&ceid=ID:id"
)
VALID_IDEA_SOURCES = ("all", "trends", "search_console", "feeds", "gaps", "seed")

SC_TITLE_TEMPLATES = [
    "{kw}: Panduan Lengkap dan Tips Praktis",
    "Mengenal {kw} Lebih Dekat",
    "{kw} — Semua yang Perlu Kamu Tahu",
]


def normalize_title(title):
    """Judul ternormalisasi untuk dedupe: huruf kecil, spasi tunggal."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _fmt_num(n):
    """Angka dengan pemisah ribuan gaya Indonesia (titik)."""
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def _clean_news_title(raw):
    """Judul Google News berbentuk 'Headline - Nama Media'.

    Buang segmen media terakhir (setelah ' - ' terakhir) supaya yang
    tersisa headline-nya saja; judul tanpa ' - ' dibiarkan utuh.
    """
    title = (raw or "").strip()
    if " - " in title:
        head, _, _tail = title.rpartition(" - ")
        if head.strip():
            title = head.strip()
    return title


def _news_keyword(title):
    """Topik singkat dari judul berita untuk kata kunci + label.

    Ambil bagian sebelum ':' bila 1-6 kata (mis. 'Gubernur Andra
    Soni: ...' -> 'Gubernur Andra Soni'); bila tidak ada ':', ambil
    4 kata pertama. Judul berita utuh terlalu panjang untuk kata kunci.
    """
    head = (title or "").strip()
    if ":" in head:
        before = head.split(":", 1)[0].strip()
        if 1 <= len(before.split()) <= 6:
            return before
    words = head.split()
    return " ".join(words[:4]).rstrip(":.,;!?") or head


def _v2_idea(title, keyword, source, score, reason, origin, **extra):
    """Satu ide v2 — selalu membawa skor + alasan berbasis sinyal."""
    idea = {
        "title": title,
        "keyword": keyword,
        "source": source,
        "score": max(0, min(100, int(score))),
        "reason": reason,
        "angle": reason,
        "keywords": [keyword] if keyword else [],
        "source_title": extra.get("source_title"),
        "source_url": extra.get("source_url"),
        "source_id": extra.get("source_id"),
        "origin": origin,
    }
    return idea


def fetch_trends_items(feed_parser=None, seed=None):
    """Ambil berita populer Indonesia dari Google News RSS (tanpa kunci).

    Tanpa seed: top stories (https://news.google.com/rss?...). Dengan
    seed: search RSS untuk kata kunci itu. Nama fungsi dipertahankan
    (param `source=trends` dan label 'Tren' tidak berubah) — yang
    diganti hanya backend fetcher-nya, karena Google Trends RSS sudah
    mati (HTTP 404).

    Mengembalikan (items, status): items = [{title, url}]; status =
    {"available": bool, "count": int, "message": str}. Bila RSS tidak
    bisa diakses atau kosong, items = [] dan status menjelaskan kenapa
    — TIDAK PERNAH mengarang berita palsu.
    """
    parse = feed_parser or (feedparser.parse if feedparser else None)
    if parse is None:
        return [], {
            "available": False,
            "message": "feedparser belum terpasang di server, sumber Tren tidak tersedia.",
        }
    seed = (seed or "").strip()
    url = (
        NEWS_SEARCH_RSS_URL.format(q=urllib.parse.quote_plus(seed))
        if seed
        else NEWS_RSS_URL
    )
    try:
        parsed = parse(url)
    except Exception as e:
        return [], {
            "available": False,
            "message": f"Google News RSS tidak dapat diakses ({e}). Sumber Tren dilewati.",
        }
    entries = (parsed or {}).get("entries") or []
    if not entries:
        return [], {
            "available": False,
            "message": (
                "Google News RSS tidak mengembalikan data — sumber Tren "
                "dilewati; sumber lain tetap jalan."
            ),
        }
    items = []
    for entry in entries:
        title = _clean_news_title(entry.get("title"))
        if not title:
            continue
        items.append(
            {
                "title": title,
                "url": (entry.get("link") or "").strip(),
            }
        )
    if not items:
        return [], {
            "available": False,
            "message": "Google News RSS tidak mengembalikan judul berita.",
        }
    if seed:
        message = (
            f"{len(items)} berita populer tentang '{seed}' dari Google "
            "News Indonesia."
        )
    else:
        message = f"{len(items)} berita populer dari Google News Indonesia."
    return items, {
        "available": True,
        "count": len(items),
        "message": message,
    }


def generate_trend_ideas(items, limit=IDEAS_LIMIT, seed=None, source="trends"):
    """Ide judul dari berita populer Indonesia (tanpa niche, tanpa Gemini).

    Judul ide = headline berita itu sendiri (topiknya); kata kunci =
    topik singkat dari headline. Skor berdasarkan urutan di feed
    (Google mengurutkan dari yang paling populer): 85 untuk berita
    pertama, turun 2 per posisi, minimal 60.

    source: 'trends' (top stories / tren tentang seed) atau 'seed'
    (pencarian kata kunci bebas) — judul, skor, dan alasan sama;
    hanya label sumber + origin yang berbeda.
    """
    ideas = []
    seed = (seed or "").strip()
    origin = "seed" if source == "seed" else "trend"
    for i, item in enumerate(items):
        if len(ideas) >= limit:
            break
        title = (item.get("title") or "").strip()
        if not title:
            continue
        keyword = _news_keyword(title)
        if seed:
            reason = (
                f"Berita populer tentang '{seed}' di Google News "
                "Indonesia hari ini."
            )
        else:
            reason = "Berita populer di Google News Indonesia hari ini."
        ideas.append(
            _v2_idea(
                title,
                keyword,
                source,
                max(60, 85 - i * 2),
                reason,
                origin,
                source_title="Google News Indonesia",
                source_url=item.get("url") or "",
            )
        )
    return ideas


def generate_search_console_ideas(channel, db, service_factory=None):
    """Ide 'peluang' dari Search Console: kueri impresi tinggi, posisi
    5-20, CTR di bawah rata-rata kueri teratas blog.

    Mengembalikan (ideas, status). Bila SC belum terhubung, ideas = []
    dan status menjelaskan kenapa (bukan ide palsu).
    """
    try:
        overview = get_overview(channel, service_factory=service_factory)
    except SearchConsoleError as e:
        return [], {"available": False, "message": str(e)}
    rows = (overview or {}).get("top_queries") or []
    avg_ctr = ((overview or {}).get("totals") or {}).get("avg_ctr") or 0
    ideas = []
    for i, row in enumerate(rows):
        query = ((row.get("query") or "").strip())
        impressions = row.get("impressions") or 0
        position = row.get("position") or 0
        ctr = row.get("ctr") or 0
        if not query or impressions < 20:
            continue
        if not (5 <= position <= 20):
            continue
        if avg_ctr > 0 and ctr >= avg_ctr:
            continue  # hanya peluang: CTR di bawah rata-rata
        q_cap = query[:1].upper() + query[1:]
        template = SC_TITLE_TEMPLATES[i % len(SC_TITLE_TEMPLATES)]
        score = min(95, 60 + min(25, int(impressions // 100)) + max(0, int(20 - position)))
        avg_txt = f"{avg_ctr * 100:.1f}".replace(".", ",")
        ctr_txt = f"{ctr * 100:.1f}".replace(".", ",")
        reason = (
            f"{_fmt_num(impressions)} impresi di posisi {position:.1f} tapi CTR "
            f"hanya {ctr_txt}% (rata-rata kueri teratas {avg_txt}%) — artikel "
            f"baru/optimalisasi bisa menaikkan klik."
        )
        ideas.append(
            _v2_idea(
                template.format(kw=q_cap),
                query,
                "search_console",
                score,
                reason,
                "search_console",
                source_title="Google Search Console",
            )
        )
    if not ideas:
        return [], {
            "available": True,
            "count": 0,
            "message": (
                "Search Console terhubung, tapi tidak ada kueri peluang "
                "(impresi >= 20, posisi 5-20, CTR di bawah rata-rata) dalam "
                "28 hari terakhir."
            ),
        }
    return ideas, {
        "available": True,
        "count": len(ideas),
        "message": f"{len(ideas)} kueri peluang dari Search Console (28 hari terakhir).",
    }


def generate_gap_ideas(channel, db, limit=IDEAS_LIMIT):
    """Ide celah dari konten sendiri: label yang baru punya 1 artikel
    (peluang pendalaman) + artikel terbit terbaru yang layak dibuat
    bagian 2. Mengembalikan (ideas, status)."""
    pubs = (
        db.query(Publication)
        .filter(Publication.channel_id == channel.id)
        .order_by(Publication.created_at.desc())
        .all()
    )
    if not pubs:
        return [], {
            "available": False,
            "message": (
                "Belum ada artikel di blog ini — tulis artikel pertama dulu, "
                "celah topik akan muncul setelah ada konten."
            ),
        }
    label_counts = Counter()
    for pub in pubs:
        for label in (pub.labels or "").split(","):
            label = label.strip()
            if label:
                label_counts[label] += 1
    ideas = []
    for label, count in label_counts.most_common():
        if len(ideas) >= limit:
            break
        if count != 1:
            continue
        label_cap = label[:1].upper() + label[1:]
        ideas.append(
            _v2_idea(
                f"{label_cap}: Panduan Lanjutan dan Pendalaman",
                label,
                "gaps",
                62,
                f"Label '{label}' baru punya 1 artikel — peluang pendalaman topik ini.",
                "gap",
            )
        )
    published = [p for p in pubs if p.status == "published"]
    if published and len(ideas) < limit:
        first = published[0]
        title = (first.title or "").strip()
        if title:
            ideas.append(
                _v2_idea(
                    f"{title} (Bagian 2): Lanjutan dan Studi Kasus",
                    title,
                    "gaps",
                    55,
                    f"Artikel '{title}' sudah terbit — bagian 2 bisa memperdalam dengan contoh baru.",
                    "gap",
                )
            )
    if not ideas:
        return [], {
            "available": True,
            "count": 0,
            "message": (
                "Semua label sudah punya lebih dari 1 artikel dan belum ada "
                "artikel terbit untuk dibuat bagian 2."
            ),
        }
    return ideas, {
        "available": True,
        "count": len(ideas),
        "message": f"{len(ideas)} celah dari konten blog sendiri.",
    }


def collect_v2_ideas(
    channel,
    db,
    source="all",
    seed=None,
    limit=IDEAS_LIMIT,
    trends_fetcher=None,
    sc_factory=None,
):
    """Kumpulkan ide v2 dari sinyal nyata (tanpa niche, tanpa Gemini).

    source: all | trends | search_console | feeds | gaps | seed.
    trends_fetcher / sc_factory hanya untuk tes (mock).
    Mengembalikan dict dengan keys kompatibel v1 (channel_id, niche,
    headline_source, headline_count, ai_used, ai_error, ideas) plus
    "sources" = status per sumber {available, count, message}.
    """
    wanted = (
        ["trends", "search_console", "feeds", "gaps", "seed"]
        if source == "all"
        else [source]
    )
    sources_status = {}
    pooled = []
    headline_count = 0
    headline_source = "none"

    if "trends" in wanted:
        # Mode seed hanya bila sumber yang diminta persis 'trends':
        # berita populer dicari berdasarkan kata kunci itu. Bila
        # source=all, tren memakai top stories (seed ditangani sumber
        # 'seed' sendiri).
        trend_seed = seed if source == "trends" else None
        items, status = fetch_trends_items(
            feed_parser=trends_fetcher, seed=trend_seed
        )
        sources_status["trends"] = status
        pooled.extend(generate_trend_ideas(items, limit=limit, seed=trend_seed))

    if "search_console" in wanted:
        sc_ideas, status = generate_search_console_ideas(
            channel, db, service_factory=sc_factory
        )
        sources_status["search_console"] = status
        pooled.extend(sc_ideas)

    if "feeds" in wanted:
        headlines, headline_source = collect_headlines(db, channel)
        headline_count = len(headlines)
        if not headlines:
            sources_status["feeds"] = {
                "available": False,
                "message": (
                    "Belum ada headline dari feed — tambah RSS dulu di seksi "
                    "Ingest, lalu klik Ambil (Fetch)."
                ),
            }
        else:
            kw_ideas = generate_keyword_ideas(headlines, channel, limit=limit)
            wrapped = []
            for idea in kw_ideas:
                # v2: ide turunan niche DIBUANG — niche tidak dipakai.
                if idea.get("origin") == "niche":
                    continue
                score = 65 if idea.get("origin") == "keyword" else 50
                kws = idea.get("keywords") or []
                wrapped.append(
                    _v2_idea(
                        idea["title"],
                        kws[0] if kws else "",
                        "feeds",
                        score,
                        idea.get("angle") or "",
                        idea.get("origin") or "headline",
                        source_title=idea.get("source_title"),
                        source_url=idea.get("source_url"),
                        source_id=idea.get("source_id"),
                    )
                )
                wrapped[-1]["keywords"] = kws
            sources_status["feeds"] = {
                "available": True,
                "count": len(wrapped),
                "message": f"{headline_count} headline dipakai dari feed channel.",
            }
            pooled.extend(wrapped)

    if "gaps" in wanted:
        gap_ideas, status = generate_gap_ideas(channel, db, limit=limit)
        sources_status["gaps"] = status
        pooled.extend(gap_ideas)

    if "seed" in wanted:
        if not (seed or "").strip():
            sources_status["seed"] = {
                "available": False,
                "message": (
                    "Mode kata kunci bebas butuh kata kunci — isi kolom kata "
                    "kunci dulu."
                ),
            }
        else:
            # Kata kunci bebas BERBASIS DATA (bukan template): cari kata
            # kunci itu di Google News Indonesia, jadikan headline nyata
            # sebagai ide dengan skor berbasis sinyal. Bila tidak ada
            # berita tentang kata kunci itu, kembalikan kosong + pesan
            # jujur — tidak ada lagi judul template generik skor 50.
            seed_items, seed_status = fetch_trends_items(
                feed_parser=trends_fetcher, seed=seed
            )
            sources_status["seed"] = seed_status
            pooled.extend(
                generate_trend_ideas(
                    seed_items, limit=limit, seed=seed, source="seed"
                )
            )

    # Dedupe berdasarkan judul ternormalisasi (skor tertinggi menang),
    # lalu urutkan berdasarkan skor tertinggi dulu.
    best = {}
    for idea in pooled:
        key = normalize_title(idea["title"])
        if key not in best or idea["score"] > best[key]["score"]:
            best[key] = idea
    ideas = sorted(best.values(), key=lambda i: i["score"], reverse=True)
    if source == "all":
        # Mode "all": round-robin per sumber supaya satu sumber
        # berskor tinggi (mis. tren berita 85-67) tidak memborong
        # semua slot dan sumber lain (seed/gaps) tidak pernah terlihat.
        ideas = _diverse_pick(ideas, limit)
    else:
        ideas = ideas[:limit]

    # Perpustakaan: ide yang sudah dipakai/dibuang tidak muncul lagi
    # sebagai baru; sisanya dianotasi dengan status perpustakaannya.
    ideas = _apply_library_filter(db, channel.id, ideas)

    return {
        "channel_id": channel.id,
        "niche": channel.niche,
        "headline_source": headline_source,
        "headline_count": headline_count,
        "ai_used": False,
        "ai_error": None,
        "sources": sources_status,
        "ideas": ideas,
    }


def _diverse_pick(ideas, limit):
    """Pilih ide teratas dengan round-robin per sumber.

    `ideas` sudah terurut skor menurun. Ambil bergiliran satu ide
    terbaik dari tiap sumber (putaran 1: terbaik tiap sumber, putaran
    2: terbaik kedua, dst.) sampai limit terpenuhi, lalu urutkan lagi
    berdasarkan skor. Hasil: tiap sumber kebagian slot, hasil akhir
    tetap terurut skor menurun.
    """
    by_source = {}
    for idea in ideas:
        by_source.setdefault(idea["source"], []).append(idea)
    picked = []
    while len(picked) < limit and any(by_source.values()):
        for src in list(by_source):
            if len(picked) >= limit:
                break
            if by_source[src]:
                picked.append(by_source[src].pop(0))
    return sorted(picked, key=lambda i: i["score"], reverse=True)


def _apply_library_filter(db, channel_id, ideas):
    """Filter ide v2 terhadap perpustakaan (patch 02).

    Ide yang di perpustakaan berstatus 'dipakai'/'dibuang' dibuang dari
    daftar; sisanya mendapat library_status ('baru'/None) + library_id.
    Aman bila tabel topic_ideas belum ada (dianggap kosong).
    """
    try:
        rows = (
            db.query(TopicIdea)
            .filter(TopicIdea.channel_id == channel_id)
            .all()
        )
    except Exception:
        rows = []
    by_title = {row.title_norm: row for row in rows}
    visible = []
    for idea in ideas:
        row = by_title.get(normalize_title(idea["title"]))
        if row is not None and row.status in ("dipakai", "dibuang"):
            continue
        idea["library_status"] = row.status if row is not None else None
        idea["library_id"] = row.id if row is not None else None
        visible.append(idea)
    return visible


def get_ideas(channel, db, http_client=None):
    """Kumpulkan ide topik v2: sinyal nyata, tanpa niche, tanpa Gemini.

    http_client dipertahankan demi kompatibilitas pemanggil lama —
    tidak lagi dipakai (Gemini tidak dipanggil di endpoint ide v2;
    pengayaan AI pindah ke kerangka/outline di patch topics-outline).
    """
    return collect_v2_ideas(channel, db)


def get_ideas(channel, db, http_client=None):
    """Kumpulkan ide topik v2: sinyal nyata, tanpa niche, tanpa Gemini.

    http_client dipertahankan demi kompatibilitas pemanggil lama —
    tidak lagi dipakai (Gemini tidak dipanggil di endpoint ide v2;
    pengayaan AI pindah ke kerangka/outline di patch topics-outline).
    """
    return collect_v2_ideas(channel, db)


# ---------------------------------------------------------------------------
# Ide Topik v2 (patch 03) — "Buat Kerangka": draf outline lengkap sekali klik.
# ---------------------------------------------------------------------------

def _outline_template_sections(keyword):
    """Kerangka template (fallback): 5 bagian H2 + poin-poin penting.

    Selalu lengkap tanpa Gemini — Gemini hanya memperkaya judul/bagian
    bila kuncinya berfungsi (lihat enrich_outline_with_ai).
    """
    kw = (keyword or "topik ini").strip()
    kw_cap = kw[:1].upper() + kw[1:] if kw else "Topik Ini"
    return [
        (
            f"Apa Itu {kw_cap}?",
            [
                f"Definisi {kw} dalam satu paragraf singkat dan mudah dipahami.",
                "Kenapa topik ini penting dan relevan untuk pemula saat ini.",
                "Siapa yang paling cocok mempelajari topik ini.",
            ],
        ),
        (
            f"Cara Memulai {kw_cap}",
            [
                "Langkah pertama yang paling mudah dilakukan hari ini.",
                "Alat atau bahan dasar yang dibutuhkan (pilih yang gratis dulu).",
                "Contoh latihan 15 menit untuk hari pertama.",
            ],
        ),
        (
            f"Kesalahan Umum dalam {kw_cap}",
            [
                "Kesalahan 1 yang paling sering dilakukan pemula — dan cara menghindarinya.",
                "Kesalahan 2: terlalu cepat ingin hasil sempurna.",
                "Cara mengevaluasi progres sendiri tanpa membandingkan dengan orang lain.",
            ],
        ),
        (
            f"Tips {kw_cap} untuk Pemula",
            [
                "Tips praktis 1: konsisten sedikit demi sedikit.",
                "Tips praktis 2: cari satu contoh untuk ditiru strukturnya.",
                "Tips praktis 3: catat progres dan ulangi yang berhasil.",
            ],
        ),
        (
            "Penutup",
            [
                f"Rangkuman: tiga hal terpenting tentang {kw}.",
                "Ajakan: coba langkah pertama hari ini dan catat hasilnya.",
                "Artikel terkait yang bisa dibaca selanjutnya (isi tautan internal).",
            ],
        ),
    ]


def _outline_meta_description(keyword):
    """Draf meta description ~140-160 karakter dari kata kunci target."""
    kw = (keyword or "topik ini").strip()
    text = (
        f"Panduan {kw} untuk pemula: pengertian, cara memulai, kesalahan "
        f"umum, dan tips praktis — lengkap dengan contoh nyata dan langkah "
        f"latihan harian."
    )
    if len(text) > 160:
        text = text[:157].rsplit(" ", 1)[0] + "..."
    return text


def _render_outline_html(title, keyword, angle, sections, source_url=None, source_title=None):
    """Rangkai HTML kerangka: H2 + poin-poin + placeholder penjelasan."""
    parts = ["<!-- Kerangka draf lengkap dari Ide Topik v2 — lengkapi sebelum diterbitkan -->"]
    if angle:
        parts.append(f"<p>{html_lib.escape(angle)}</p>")
    parts.append(
        "<p>Kata kunci target: "
        f"<strong>{html_lib.escape(keyword)}</strong>. Tulis untuk pembaca "
        "pemula, dengan contoh nyata dari pengalaman sendiri.</p>"
    )
    for h2, bullets in sections:
        parts.append(f"<h2>{html_lib.escape(h2)}</h2>")
        if bullets:
            items = "".join(f"<li>{html_lib.escape(b)}</li>" for b in bullets)
            parts.append(f"<ul>{items}</ul>")
        parts.append(f"<p>[Tulis penjelasan {html_lib.escape(h2.lower())} di sini]</p>")
    if source_url:
        parts.append(
            "<p>Sumber inspirasi: "
            f"<a href=\"{html_lib.escape(source_url)}\">"
            f"{html_lib.escape(source_title or 'tautan sumber')}</a></p>"
        )
    return "\n".join(parts)


def _parse_ai_outline(text):
    """Parse kerangka Gemini: baris 'Judul: ...' + '1. H2 — poin; poin'.

    Mengembalikan (title|None, sections[(h2, [poin])]). Bila bagian
    kurang dari 3, dianggap gagal parse (pemanggil memakai template).
    """
    title = None
    sections = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = re.match(r"^Judul\s*:\s*(.+)$", line, re.IGNORECASE)
        if m:
            title = m.group(1).strip().strip("\"'")
            continue
        m = re.match(r"^\d+[.)]\s*(.+?)\s*$", line)
        if not m:
            continue
        raw = m.group(1)
        if "—" in raw:
            h2, pts = raw.split("—", 1)
        elif " - " in raw:
            h2, pts = raw.split(" - ", 1)
        else:
            h2, pts = raw, ""
        h2 = h2.strip()
        points = [p.strip() for p in pts.split(";") if p.strip()]
        if len(h2) >= 3:
            sections.append((h2, points))
    if title is not None and not (10 <= len(title) <= 80):
        title = None
    if len(sections) < 3:
        return None, []
    return title, sections


def enrich_outline_with_ai(idea_title, keyword, db, http_client=None):
    """Coba perkaya judul + kerangka dengan Gemini.

    Mengembalikan (title|None, sections|None, ai_used, ai_error).
    TIDAK PERNAH raise: bila tidak ada kunci, kunci gagal (403 dsb.),
    atau respons tidak bisa diparse, pemanggil memakai template.
    """
    api_key = get_setting_value(db, GEMINI_API_KEY)
    if not api_key:
        return None, None, False, None
    model = get_setting_value(db, "gemini_model") or DEFAULT_MODEL
    prompt = (
        f"Kamu editor blog. Buatkan kerangka artikel Bahasa Indonesia untuk "
        f"judul \"{idea_title}\" (kata kunci: {keyword}).\n"
        "Format persis seperti ini, jangan tambah penjelasan lain:\n"
        "Judul: <judul yang lebih menarik, maks 60 karakter>\n"
        "1. <H2> — <poin penting>; <poin penting>\n"
        "2. <H2> — <poin penting>; <poin penting>\n"
        "3. <H2> — <poin penting>; <poin penting>\n"
        "4. <H2> — <poin penting>; <poin penting>\n"
        "5. Penutup — <poin rangkuman>; <poin ajakan>\n"
    )
    try:
        text = generate_text(
            api_key,
            prompt,
            model=model,
            temperature=0.7,
            max_output_tokens=1024,
            http_client=http_client,
        )
    except GeminiError as e:
        return None, None, False, str(e)
    title, sections = _parse_ai_outline(text)
    if not sections:
        return (
            None,
            None,
            False,
            "Respons Gemini tidak dapat dipahami sebagai kerangka — dipakai template.",
        )
    return title, sections, True, None


def create_outline_draft(db, channel, idea, http_client=None):
    """Buat Publication DRAF berisi kerangka lengkap dari satu TopicIdea.

    Mengembalikan (pub, ai_used, ai_error). Status selalu 'draft' —
    tidak pernah auto-publish. Ide perpustakaan ditandai 'dipakai' dan
    ditautkan ke draf. Gemini hanya memperkaya; bila gagal, template
    tetap menghasilkan kerangka lengkap.
    """
    title = (idea.title or "").strip()
    if not title:
        raise ValueError("Judul ide tidak boleh kosong.")
    keyword = (idea.keyword or "").strip()
    if not keyword:
        kws = [k.strip() for k in (idea.keywords or "").split(",") if k.strip()]
        keyword = kws[0] if kws else (channel.niche or "topik")
    ai_title, ai_sections, ai_used, ai_error = enrich_outline_with_ai(
        title, keyword, db, http_client=http_client
    )
    final_title = ai_title or title
    sections = ai_sections or _outline_template_sections(keyword)
    angle = (idea.reason or idea.angle or "").strip()
    content = _render_outline_html(
        final_title,
        keyword,
        angle,
        sections,
        source_url=idea.source_url,
        source_title=idea.source_title,
    )
    labels_list = [k.strip() for k in (idea.keywords or "").split(",") if k.strip()][:3]
    labels = (
        ", ".join(labels_list)
        if labels_list
        else (channel.default_labels or channel.niche or "")
    )
    pub = Publication(
        channel_id=channel.id,
        title=final_title,
        slug=slugify(final_title),
        meta_description=_outline_meta_description(keyword),
        content_html=content,
        labels=labels,
        status="draft",
    )
    db.add(pub)
    db.commit()
    db.refresh(pub)
    idea.status = "dipakai"
    idea.publication_id = pub.id
    db.commit()
    return pub, ai_used, ai_error
