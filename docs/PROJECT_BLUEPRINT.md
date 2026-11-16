# BluePrint: Multi-Channel Blog Connector & AI Content Engine

## 1. Ringkasan Sistem (System Overview)
Sistem ini adalah **Web Connector & Content Middleware** yang menghubungkan AI Agent dengan berbagai platform publikasi blog (**WordPress** dan **Blogger/Blogspot**). Sistem ini dirancang untuk menangani multi-akun, mengadaptasi konten sesuai niche blog masing-masing (*Multi-Angle Content Adaptation*), menghindari duplikasi konten (SEO-friendly), serta mengotomatisasi pengambilan sumber berita (RSS & Universal URL Extractor).

---

## 2. Arsitektur Sistem

```
┌────────────────────────────────────────────────────────┐
│                   SUMBER INGESTI                      │
│   [RSS Feeds]       [Paste URL Web]     [User Prompt]  │
└───────────┬─────────────────┬──────────────────┬───────┘
            │                 │                  │
            ▼                 ▼                  ▼
┌────────────────────────────────────────────────────────┐
│             INTELLIGENT EXTRACTOR                      │
│   (Trafilatura / Readability - Teks Murni Tanpa Iklan) │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                  AI AGENT ENGINE                       │
│  - Analisis Fakta & Intisari Sumber                    │
│  - Angle Adaptation berdasarkan Niche Profil Blog      │
│  - SEO Formatting (Title, Slug, Meta, Headings, Tags) │
│  - Penyisipan Atribusi Sumber Etis                     │
│  - Smart Interlinking (Internal Links)                 │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│              CONNECTOR MIDDLEWARE                      │
│  - Database Profil Akun & Log Publikasi                │
│  - Human-in-the-Loop (Telegram Bot / Web UI)           │
│  - Drip-Feed Scheduler (Jadwal Publikasi Bertahap)     │
│  - Media Optimizer (WebP Converter & Upload)           │
└───────────────┬────────────────────────┬───────────────┘
                │                        │
                ▼                        ▼
     ┌──────────────────────┐ ┌──────────────────────┐
     │   WORDPRESS API      │ │   BLOGGER API v3     │
     │ (/wp-json/wp/v2/...) │ │ (OAuth2 + Refresh)   │
     └──────────────────────┘ └──────────────────────┘
```

---

## 3. Matriks Fitur (Feature Matrix)

### Fase 1: MVP (Core Engine & Publishing)
1. **Multi-Account Manager:**
   - Registrasi & manajemen banyak kredensial WordPress (Application Passwords).
   - Registrasi & manajemen banyak akun/blog Blogger (OAuth 2.0 Client + Refresh Token).
2. **Channel Profiling:**
   - Konfigurasi profil per blog (Nama, Niche, Target Pembaca, Tone of Voice, Batas Kata, Kategori Default).
3. **Smart Source Ingestion:**
   - **Mode URL:** Ekstraksi konten murni dari URL berita/web menggunakan *intelligent article extractor* (membuang iklan, menu navigasi, popup).
   - **Mode RSS:** Membaca feed berkala untuk memantau berita baru.
4. **Publishing Endpoints:**
   - Publish langsung (`publish`) atau jadikan Draf (`draft`).
   - Penanganan tag, kategori/label, dan metadata dasar.

### Fase 2: Content Intelligence & SEO
1. **Multi-Angle Recontextualization:**
   - Dari 1 sumber berita, AI menulis versi artikel yang berbeda secara drastis untuk tiap niche (bukan sekadar spin kata).
2. **Ethical SEO & Source Attribution:**
   - Penyisipan link sumber asli secara alami ("Dilansir dari...") untuk meningkatkan kredibilitas E-E-A-T.
3. **Smart Interlinking:**
   - Database riwayat artikel lama per blog untuk otomatis menyisipkan tautan silang relevan.
4. **Drip-Feed Scheduler:**
   - Penjadwalan acak/bertahap agar waktu publikasi antar blog terlihat organik dan terhindar dari deteksi bot spam.

### Fase 3: Media & Human-in-the-Loop Control
1. **Telegram / Web Approval Bot:**
   - Kirim notifikasi ringkasan draf ke Telegram, dengan tombol `[Setujui]`, `[Edit]`, atau `[Tolak]`.
2. **Auto-Image & WebP Optimizer:**
   - Pembuatan featured image otomatis / pencarian gambar stok bebas royalti.
   - Kompresi ke format WebP sebelum upload ke media library WordPress / Blogger.

---

## 4. Rekomendasi Tech Stack

* **Backend / API Engine:** Python (FastAPI) — cepat, asinkron (`asyncio`), dan memiliki ekosistem AI/scraping terbaik.
* **Intelligent Web Extraction:** `trafilatura` / `newspaper4k`.
* **RSS Parser:** `feedparser`.
* **Database:** SQLite (untuk tahap lokal/ringan) atau PostgreSQL (untuk produksi) via `SQLAlchemy` / `SQLModel`.
* **Blog Integrations:**
  * WordPress: `httpx` (Asynchronous HTTP client untuk WP REST API).
  * Blogger: `google-api-python-client`, `google-auth-oauthlib`.
* **Task Scheduling:** `APScheduler` (Advanced Python Scheduler).
* **Bot Approval:** `python-telegram-bot` (opsional tapi sangat direkomendasikan).

---

## 5. Struktur Folder Project yang Direkomendasikan

```
d:\CODING\Blog Konektor\
├── app/
│   ├── __init__.py
│   ├── main.py                  # Entrypoint FastAPI
│   ├── config.py                # Konfigurasi & Environment
│   ├── database.py              # Koneksi Database
│   ├── models/                  # Tabel Database (Channels, Posts, Logs)
│   ├── services/
│   │   ├── extractor.py         # Ekstraksi konten dari URL / RSS
│   │   ├── ai_writer.py         # Logika AI & Prompt Niche Adaptation
│   │   ├── scheduler.py         # Drip-feed scheduler
│   │   └── platforms/
│   │       ├── base.py          # Abstract Base Class untuk platform
│   │       ├── wordpress.py     # Integrasi WordPress REST API
│   │       └── blogger.py       # Integrasi Google Blogger API v3
│   ├── api/
│   │   ├── routes_channels.py   # Endpoint tambah/edit akun blog
│   │   ├── routes_ingest.py     # Endpoint ingest URL / RSS
│   │   └── routes_publish.py    # Endpoint publish/distribusi artikel
│   └── bot/
│       └── telegram_bot.py      # Notifikasi & Approval bot
├── data/                        # SQLite DB & storage lokal
├── docs/
│   ├── AGENT_GUIDE.md           # Panduan Lengkap untuk AI Agent
│   └── API_REFERENCE.md         # Dokumentasi Endpoint
├── .env.example
├── requirements.txt
└── README.md
```
