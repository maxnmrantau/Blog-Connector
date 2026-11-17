# Blog Connector — Middleware API & Dashboard untuk Blogger

Blog Connector adalah middleware API + dashboard web yang menghubungkan **AI Agent** dengan **Google Blogger API v3**. Dipakai untuk mengelola beberapa blog Blogger dari satu tempat: menulis dan menerbitkan artikel, menjadwalkan terbit otomatis, menulis ulang (rewrite) bahan dari RSS/web dengan bantuan AI, memeriksa SEO, dan memantau Search Console.

- **Live:** deployment Vercel (alamatnya tidak ditulis di repo ini — lihat pengaturan proyek di Vercel)
- **Dokumentasi API (Swagger UI):** tersedia di path `/docs` pada deployment
- **Dokumen desain awal:** [docs/PROJECT_BLUEPRINT.md](docs/PROJECT_BLUEPRINT.md)
- **Panduan operasional AI Agent:** [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md)

> Catatan: dokumen di folder `docs/` adalah dokumen desain awal proyek dan sebagian isinya sudah tidak sesuai dengan aplikasi saat ini. README ini adalah sumber yang akurat.

## Tech Stack

| Lapisan | Teknologi |
|---|---|
| API | FastAPI (Python 3.12) |
| Database | PostgreSQL via `DATABASE_URL` (produksi: Supabase); tanpa `DATABASE_URL`, aplikasi memakai SQLite lokal |
| Deploy | Vercel Serverless (`api/index.py`, `@vercel/python`) |
| Blogger | Google Blogger API v3 (`google-api-python-client`) |
| Search Console | Google Search Console API |
| AI | Google Gemini API + OpenAI API (via `httpx`) |
| Ekstraksi web | trafilatura + feedparser |
| Gambar | Openverse API (tanpa kunci) + Pexels API (opsional) |

## Fitur Utama

- **Multi-channel:** beberapa blog Blogger, masing-masing dengan niche, tone, target kata, dan label default sendiri.
- **Tulis & terbitkan artikel:** form Tulis Artikel, edit artikel terbit, draf, jadwal terbit, terbitkan draf, hapus.
- **Halaman statis:** buat/lihat/hapus halaman Blogger (Tentang, Kontak, Kebijakan Privasi, dll).
- **Ingest RSS & web:** daftarkan feed RSS per blog, ambil item terbaru menjadi antrean bahan; ekstrak teks bersih dari URL web (trafilatura); cari feed RSS dari alamat website (`POST /api/v1/feeds/discover`).
- **Auto-Rewrite (AI):** tulis ulang bahan menjadi draf dengan Gemini/OpenAI — restrukturisasi, contoh baru, tautan atribusi ke sumber, skor kemiripan vs sumber, peringatan bila terlalu mirip. Hasil selalu draf, tidak pernah langsung terbit.
- **SEO:** Cek SEO (7 pemeriksaan, skor 0–100), optimasi SEO otomatis (meta description, slug, saran internal link, saran alt text).
- **Image Picker:** cari foto dari Openverse (CC, tanpa kunci) atau Pexels (butuh kunci, opsional); gambar dipakai sebagai URL hosting.
- **Penjadwal auto-publish:** artikel terjadwal diterbitkan otomatis oleh tick scheduler.
- **Search Console:** kueri teratas 28 hari (klik, impresi, CTR, posisi), daftar sitemap, kirim sitemap; sitemap dikirim ulang otomatis setiap artikel terbit.
- **Ide Topik:** ide judul dari sinyal nyata — berita Google News Indonesia, kueri Search Console, headline feed, celah konten sendiri, kata kunci bebas — plus perpustakaan ide dan pembuatan kerangka artikel.
- **Komentar:** moderasi komentar blog (setujui, tandai spam, hapus).
- **Statistik & backup:** kunjungan per periode, ringkasan per channel, ekspor backup (tanpa kredensial).
- **Dashboard web:** 12 menu dengan kotak panduan di tiap menu.

## Menu Dashboard

| Menu | Fungsi |
|---|---|
| 📊 Dashboard | Ringkasan: jumlah channel, artikel terbit/draf/terjadwal, kunjungan per periode, ringkasan per channel |
| 🔗 Channel | Daftar blog yang terhubung, tambah blog via OAuth Blogger, pengaturan channel (niche, tone, target kata, label), tes koneksi, hubungkan ulang OAuth |
| ✍️ Artikel | Tulis artikel baru, edit artikel terbit, jadwal terbit, Cek SEO, Image Picker |
| 📄 Halaman | Daftar halaman statis, tambah/hapus halaman |
| 🕘 Riwayat | Riwayat publikasi: terbitkan draf, hapus, terbitkan semua draf, ekspor backup |
| 📥 Ingest | Daftar feed RSS, tambah feed, cari RSS dari website, antrean bahan, Rewrite jadi Draf |
| 💬 Komentar | Moderasi komentar: setujui, spam, hapus |
| 🔑 API Key | Buat/lihat/hapus kunci API (kunci lengkap hanya tampil sekali saat dibuat) |
| 🤖 Pengaturan AI | Provider AI aktif (Gemini/OpenAI), kunci API, model, Tes Kunci |
| ⏰ Penjadwal | Status scheduler, toggle auto-publish per channel, daftar antrean jatuh tempo, jalankan tick manual |
| 🔍 Search Console | Kueri teratas 28 hari, sitemap, Kirim Sitemap |
| 💡 Ide Topik | Ide judul multi-sumber, perpustakaan ide, buat kerangka/draf |

## API

Semua endpoint API di bawah `/api/v1/*`, autentikasi memakai header `x-api-key`. Dokumentasi interaktif: `/docs`.

| Kelompok | Prefix | Isi |
|---|---|---|
| Auth & API Keys | `/api/v1/auth` | Buat/daftar/hapus kunci API |
| Channels | `/api/v1/channels` | CRUD channel, tes blog Blogger, pengaturan channel |
| Ingest | `/api/v1/ingest` | Ekstrak teks dari URL atau teks mentah |
| Publish | `/api/v1/publish` | Terbitkan artikel/draf, riwayat, edit, terbitkan draf, hapus, bulk publish |
| Pages | `/api/v1/pages` | Buat/daftar/hapus halaman statis Blogger |
| Feeds | `/api/v1/feeds` | Daftar/tambah/hapus feed RSS, ambil item, cari RSS dari website |
| Rewrite | `/api/v1/rewrite` | Tulis ulang bahan menjadi draf (skor kemiripan + peringatan) |
| Pengaturan AI | `/api/v1/settings` | Simpan/lihat status kunci AI, Tes Kunci |
| Image Picker | `/api/v1/images` | Cari foto (Openverse / Pexels) |
| Scheduler | `/api/v1/scheduler` | Status scheduler, tick auto-publish |
| Search Console | `/api/v1/search-console` | Ringkasan kueri + sitemap, kirim sitemap |
| Ide Topik | `/api/v1/topics` | Ide multi-sumber, perpustakaan ide, kerangka artikel |
| SEO | `/api/v1/seo-check`, `/api/v1/seo-optimize` | Cek SEO 7 pemeriksaan, optimasi SEO |
| Statistik | `/api/v1/stats` | Kunjungan per periode |
| Komentar | `/api/v1/comments` | Daftar & moderasi komentar |
| Backup | `/api/v1/backup` | Ekspor data (tanpa kredensial) |

Endpoint lain: `GET /` (status sistem), `GET /health` (kesehatan + kesiapan database), `GET /oauth/blogger` (alur OAuth Blogger), `GET /dashboard` (dashboard web, butuh login password admin), `GET /login`.

## Provider AI

Pengaturan AI (menu 🤖 Pengaturan AI) memilih provider aktif untuk Auto-Rewrite dan Ide Topik. Kunci disimpan di database server dan tidak pernah ditampilkan lagi setelah disimpan; tombol **Tes Kunci** menguji provider yang sedang aktif.

| Provider | Model default | Keterangan |
|---|---|---|
| Gemini (default) | `gemini-3.8-flash` | Kunci gratis dari Google AI Studio. Model lama `gemini-2.0-flash` sudah dimatikan Google — jangan dipakai. |
| OpenAI | `gpt-4o-mini` | Berbayar sejak token pertama, **tanpa free tier** — butuh saldo/billing di platform.openai.com. |

Model OpenAI yang tersedia di dropdown (harga per 1 juta token, input/output):

| Model | Input | Output |
|---|---|---|
| `gpt-4o-mini` (default) | $0,15 | $0,60 |
| `gpt-4.1-nano` | $0,10 | $0,40 |
| `gpt-5-nano` | $0,05 | $0,40 |

Satu artikel ±800 kata biayanya di bawah $0,001. Tidak ada model bernama `gpt-4o-nano` — bila ingin model lain, isi kolom "atau model lain".

## Penjadwal (Auto-Publish)

Artikel terjadwal diterbitkan otomatis oleh endpoint tick `POST /api/v1/scheduler/tick`:

- **Cron Vercel** (`vercel.json`): sekali sehari, `0 1 * * *` (01:00 UTC = 08:00 WIB) — paket Hobby Vercel hanya mengizinkan cron harian.
- **GitHub Actions** (`.github/workflows/scheduler-tick.yml`): tick tiap jam (gratis), memakai header `x-api-key` dari repository secret `BLOG_CONNECTOR_API_KEY` (tambahkan di repo Settings → Secrets and variables → Actions). Tanpa secret ini, tick per jam gagal 401; cron harian tetap berjalan sebagai cadangan.
- Tick juga bisa dijalankan manual dari dashboard (menu Penjadwal) atau dengan API key biasa.
- Tick via cron Vercel memakai `Authorization: Bearer <CRON_SECRET>` (dibuat otomatis Vercel saat cron pertama kali di-deploy).

## Search Console

- Dashboard menampilkan kueri teratas 28 hari (klik, impresi, CTR, posisi) dan daftar sitemap.
- Koneksi memakai OAuth Blogger dengan scope tambahan `https://www.googleapis.com/auth/webmasters.readonly`. Karena refresh token tidak bisa mendapat scope baru, setelah scope ditambahkan koneksi OAuth harus dihubungkan ulang satu kali (tombol **Hubungkan Ulang** di baris channel / header Search Console; token baru tersimpan otomatis ke channel).
- OAuth membutuhkan **OAuth Client ID bertipe Web application** (bukan Desktop) dengan Authorized redirect URI `https://<domain-deployment-anda>/oauth/blogger/callback` (ganti `<domain-deployment-anda>` dengan domain deployment sendiri), dan Google Search Console API harus diaktifkan di Google Cloud.
- Setiap artikel yang berhasil terbit, sitemap blog (`/sitemap.xml`) dikirim ulang otomatis ke Search Console; ada juga tombol **Kirim Sitemap** manual.
- Jujur: **Google tidak menyediakan API untuk tombol "Request Indexing" per URL** — itu hanya bisa diklik manual di website Search Console. Indexing API Google hanya untuk halaman lowongan kerja/livestream, bukan artikel blog, jadi tidak dipakai.

## Menjalankan Lokal

```bash
git clone https://github.com/maxnmrantau/Blog-Connector.git
cd Blog-Connector
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
copy .env.example .env        # Windows
# cp .env.example .env       # Linux/macOS
uvicorn app.main:app --reload --port 8000
```

Buka http://localhost:8000/docs untuk dokumentasi API, http://localhost:8000/login untuk dashboard.

Variabel environment (lihat `.env.example`):

| Variabel | Keterangan |
|---|---|
| `DATABASE_URL` | URL PostgreSQL (mis. Supabase). Bila kosong, aplikasi memakai SQLite lokal (`connector.db`). |
| `ADMIN_PASSWORD` | Password login dashboard (`/login`). |
| `SECRET_KEY` | Kunci penanda sesi dashboard (wajib diganti di produksi). |
| `APP_PORT` | Port aplikasi (default 8000). |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Default kredensial OAuth Blogger (opsional; bisa diisi per channel dari halaman OAuth). |

## Deploy ke Vercel

1. Import repo ini ke Vercel (framework: Other, root directory: repo).
2. Atur environment variables: `DATABASE_URL` (Postgres, mis. Supabase), `ADMIN_PASSWORD`, `SECRET_KEY`.
3. Deploy — Vercel memakai `api/index.py` (`@vercel/python`) dan `vercel.json` (cron harian + routing).
4. (Opsional, untuk tick per jam) Tambahkan repository secret `BLOG_CONNECTOR_API_KEY` di GitHub — lihat bagian Penjadwal.

Migrasi database: setiap kolom/tabel baru wajib disertai fungsi migrasi `_ensure_*` di `app/database.py`, karena `create_all()` tidak menambah kolom pada tabel produksi yang sudah ada.

## Batasan yang Diketahui

- **Blogger API tidak bisa mengunggah gambar.** Gambar dipakai sebagai URL hosting (mis. Openverse/Pexels).
- **Blogger API tidak bisa mengubah tema/layout blog.** Pengaturan tema, gadget (mis. Contact Form), dan judul blog dilakukan manual di Blogger.
- **Statistik kunjungan hanya agregat per periode** (7 hari / 30 hari / sepanjang waktu). Blogger API tidak menyediakan rincian harian.
- **WordPress masih direncanakan ("next"), belum live.** Saat ini hanya Blogger yang didukung (`app/services/platforms/` hanya berisi implementasi Blogger).
- **Tidak ada Telegram Bot.** Variabel `TELEGRAM_BOT_TOKEN` di `.env.example` tidak dipakai oleh kode mana pun.
- **Rewrite bukan spin mentah.** Hasil rewrite dihitung skor kemiripannya dengan sumber (peringatan bila >60% mirip) dan selalu menyertakan tautan atribusi; penulisan ulang tetap dikerjakan AI, bukan penggantian sinonim otomatis.
- **Meta description & slug SEO tersimpan di database connector**, bukan di Blogger — meta description artikel tetap harus diisi manual di editor Blogger (kolom "Search Description") karena Blogger API tidak menyediakan field tersebut.
- **Halaman yang dihapus tidak membebaskan slug-nya.** Halaman Blogger yang dibuat ulang mendapat URL bersufiks — hindari hapus-buat ulang untuk perbaikan kecil.
- **Vercel paket Hobby:** cron maksimal 1x sehari dan fungsi serverless dibatasi ~10 detik.

## Struktur Direktori

```
.
├── api/index.py            # Entry point Vercel (@vercel/python)
├── app/
│   ├── main.py             # Aplikasi FastAPI, registrasi router, / dan /health
│   ├── database.py         # Engine SQLAlchemy + migrasi _ensure_*
│   ├── models.py           # Channel, Publication, FeedSource, ArticleSource, dsb.
│   ├── schemas.py          # Skema Pydantic
│   ├── security.py         # Autentikasi x-api-key + sesi dashboard
│   ├── routes_dashboard.py # Dashboard web (12 menu) + login
│   ├── routes_oauth.py     # Alur OAuth Blogger
│   ├── api/                # Router REST /api/v1/*
│   └── services/           # Logika: rewrite, seo, topics, images, scheduler, search_console
├── docs/                   # Dokumen desain awal (sebagian sudah usang — lihat catatan di atas)
├── scripts/setup_blogger_auth.py
├── tests/test_smoke.py
├── vercel.json
├── .github/workflows/scheduler-tick.yml
└── requirements.txt
```

## Lisensi

Repo ini tidak memiliki file LICENSE — belum ada lisensi yang ditetapkan.
