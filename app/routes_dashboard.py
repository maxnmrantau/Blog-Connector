import datetime
from html import escape as html_escape
import os
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ArticleSource, Channel, FeedSource, Publication, ApiKey
from app.services.platforms.blogger import BloggerPlatform
from app.services.settings import get_setting_value
from app.security import (
    verify_admin_password,
    create_session_token,
    is_session_valid,
    COOKIE_NAME
)

router = APIRouter(include_in_schema=False)

def get_current_session(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    return is_session_valid(token)


def _rel_time(dt):
    """Waktu relatif dalam Bahasa Indonesia, misal '5 mnt lalu'."""
    if not dt:
        return ""
    diff = datetime.datetime.utcnow() - dt
    seconds = max(0, int(diff.total_seconds()))
    if seconds < 60:
        return "baru saja"
    if seconds < 3600:
        return f"{seconds // 60} mnt lalu"
    if seconds < 86400:
        return f"{seconds // 3600} jam lalu"
    if seconds < 604800:
        return f"{seconds // 86400} hari lalu"
    return ""


def _ai_key_badge(configured):
    """Badge status kunci AI (hanya boolean, nilai kunci tidak pernah
    dirender ke halaman)."""
    if configured:
        return '<span class="px-2 py-0.5 rounded text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">Terkonfigurasi</span>'
    return '<span class="px-2 py-0.5 rounded text-xs bg-amber-500/10 text-amber-400 border border-amber-500/30">Belum diisi</span>'

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = None):
    if get_current_session(request):
        return RedirectResponse(url="/dashboard", status_code=303)

    error_html = f"""
    <div class="mb-4 bg-red-900/50 border border-red-500/50 text-red-200 px-4 py-3 rounded-lg text-sm flex items-center gap-2">
        <svg class="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
        <span>Password admin salah. Silakan coba lagi.</span>
    </div>
    """ if error else ""

    html = f"""
    <!DOCTYPE html>
    <html lang="id" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Login - Blog Konektor</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script>
            tailwind.config = {{
                darkMode: 'class',
                theme: {{ extend: {{ colors: {{ brand: {{ 500: '#10b981', 600: '#059669' }} }} }} }}
            }}
        </script>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen flex items-center justify-center p-4 antialiased">
        <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl backdrop-blur-xl">
            <div class="text-center mb-8">
                <div class="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-tr from-emerald-500 to-teal-400 mb-4 shadow-lg shadow-emerald-500/20">
                    <svg class="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z"></path></svg>
                </div>
                <h1 class="text-2xl font-bold tracking-tight text-white">Blog Konektor</h1>
                <p class="text-sm text-slate-400 mt-1">Multi-Channel AI Content Engine</p>
            </div>

            {error_html}

            <form action="/login" method="POST" class="space-y-5">
                <div>
                    <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Password Admin</label>
                    <input type="password" name="password" required autofocus placeholder="Masukkan password admin..."
                        class="w-full bg-slate-800/80 border border-slate-700 rounded-xl px-4 py-3 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent transition">
                </div>
                <button type="submit"
                    class="w-full bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold py-3 px-3 sm:px-4 rounded-xl shadow-lg shadow-emerald-500/20 hover:shadow-emerald-500/30 transition transform active:scale-95">
                    Masuk ke Dashboard
                </button>
            </form>

            <div class="mt-6 pt-6 border-t border-slate-800 text-center text-xs text-slate-500">
                Dilindungi otentikasi sesi & enkripsi API Key
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@router.post("/login")
def login_post(password: str = Form(...)):
    if verify_admin_password(password):
        token = create_session_token()
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            max_age=86400 * 7,
            httponly=True,
            samesite="lax"
        )
        return response
    return RedirectResponse(url="/login?error=1", status_code=303)

@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key=COOKIE_NAME)
    return response

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    if not get_current_session(request):
        return RedirectResponse(url="/login", status_code=303)

    channels = db.query(Channel).all()
    publications = db.query(Publication).order_by(Publication.created_at.desc()).limit(50).all()
    api_keys = db.query(ApiKey).all()
    # Feed RSS per channel + item hasil fetch terbaru (antrean rewrite).
    feeds = db.query(FeedSource).order_by(FeedSource.created_at.desc()).all()
    recent_sources = db.query(ArticleSource).order_by(ArticleSource.ingested_at.desc()).limit(20).all()
    # Hitung dari database, bukan dari daftar yang dibatasi 50 baris,
    # supaya angka di kartu statistik selalu benar.
    total_published = db.query(Publication).filter(Publication.status == "published").count()
    total_drafts = db.query(Publication).filter(Publication.status == "draft").count()

    # Status kunci AI untuk section Pengaturan AI (hanya boolean, bukan nilai).
    gemini_configured = bool(get_setting_value(db, "gemini_api_key"))
    pexels_configured = bool(get_setting_value(db, "pexels_api_key"))
    gemini_badge = _ai_key_badge(gemini_configured)
    pexels_badge = _ai_key_badge(pexels_configured)

    # Buat baris tabel channel
    channel_rows = ""
    for ch in channels:
        creds = ch.get_credentials()
        blog_url = ch.blog_url or creds.get("blog_url") or creds.get("url") or None
        blog_id = ch.blog_id or creds.get("blog_id") or None
        if blog_url:
            blog_cell = (
                f'<a href="{blog_url}" target="_blank" class="text-xs text-emerald-400 hover:underline">Lihat Blog</a>'
                f' <button type="button" data-url="{html_escape(blog_url, quote=True)}" onclick="copyBlogUrl(this)" class="text-[11px] bg-slate-800 hover:bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded border border-slate-700 transition ml-1">Salin</button>'
                f'<div class="text-[11px] text-slate-500 break-all mt-0.5">{html_escape(blog_url)}</div>'
            )
        else:
            blog_cell = '<span class="text-xs text-slate-500">Belum diketahui — klik Test</span>'
        if blog_id:
            blog_cell += f'<div class="text-[11px] text-slate-500 font-mono mt-0.5">ID: {blog_id}</div>'
        # Tombol Pengaturan: membuka modal edit niche/tone/target kata/labels
        # untuk channel ini. Nilai dibawa lewat data-* (di-escape) supaya
        # modal bisa diisi tanpa request tambahan.
        settings_btn = (
            f'<button type="button" onclick="openChannelSettings(this)" '
            f'data-id="{html_escape(ch.id, quote=True)}" '
            f'data-name="{html_escape(ch.name, quote=True)}" '
            f'data-niche="{html_escape(ch.niche or "", quote=True)}" '
            f'data-tone="{html_escape(ch.tone_of_voice or "", quote=True)}" '
            f'data-words="{ch.target_word_count}" '
            f'data-labels="{html_escape(ch.default_labels or "", quote=True)}" '
            f'class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-2 py-1 rounded border border-slate-700 transition">Pengaturan</button>'
        )
        test_btn = f"""
        {settings_btn}
        <button onclick="testChannel('{ch.id}', this)" class="text-xs bg-slate-800 hover:bg-slate-700 text-emerald-400 px-2 py-1 rounded border border-slate-700 transition">Test</button>
        <button onclick="deleteChannel('{ch.id}', this)" class="text-xs bg-red-950/40 hover:bg-red-900/60 text-red-400 px-2 py-1 rounded border border-red-500/30 transition ml-1">Hapus</button>
        """ if ch.platform == 'blogger' else f"""
        {settings_btn}
        <button onclick="deleteChannel('{ch.id}', this)" class="text-xs bg-red-950/40 hover:bg-red-900/60 text-red-400 px-2 py-1 rounded border border-red-500/30 transition">Hapus</button>
        """
        # Tabel disederhanakan jadi 4 kolom: Channel ID, Niche, Tone of Voice
        # dan Target Kata tidak lagi jadi kolom sendiri, melainkan teks kecil
        # di bawah nama blog (tetap terlihat, tapi tidak memakan lebar tabel).
        blog_sub = (
            f'<span class="font-mono text-emerald-400">{html_escape(ch.id)}</span>'
            f'<span class="text-slate-500"> · {html_escape(ch.niche)}</span>'
            f'<span class="text-slate-500"> · {html_escape(ch.tone_of_voice or "-")}</span>'
            f'<span class="text-slate-500"> · {ch.target_word_count} kata</span>'
        )
        channel_rows += f"""
        <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 transition">
            <td class="py-3 px-3 sm:px-4"><div class="font-medium text-slate-200">{html_escape(ch.name)}</div><div class="text-[11px] mt-0.5">{blog_sub}</div></td>
            <td class="py-3 px-3 sm:px-4"><span class="px-2 py-1 rounded text-xs font-semibold {'bg-orange-500/10 text-orange-400 border border-orange-500/30' if ch.platform == 'blogger' else 'bg-blue-500/10 text-blue-400 border border-blue-500/30'}">{ch.platform.upper()}</span></td>
            <td class="py-3 px-3 sm:px-4">{blog_cell}</td>
            <td class="py-3 px-3 sm:px-4 text-right">{test_btn}</td>
        </tr>
        """
    if not channels:
        channel_rows = """<tr><td colspan="4" class="py-8 text-center text-slate-500">Belum ada akun blog yang didaftarkan. Klik tombol "+ Tambah Akun Blog" di atas untuk menghubungkan!</td></tr>"""

    # Buat baris tabel halaman statis (Pages) per channel Blogger.
    # Pages dibaca live dari Blogger; kalau gagal dimuat, tampilkan
    # baris "Gagal memuat halaman" dan lanjutkan render, jangan 500.
    blogger_channels = [ch for ch in channels if ch.platform == 'blogger']
    # Statistik kunjungan (server-side, toleran gagal): ambil dari
    # Blogger pageViews untuk channel Blogger pertama. Blogger API v3
    # pageViews HANYA mengembalikan angka agregat per rentang
    # (30DAYS / 7DAYS / all) — tidak ada rincian per hari, jadi
    # dashboard menampilkan total agregat, bukan deret harian.
    stats_channel = blogger_channels[0] if blogger_channels else None
    stats_30 = stats_7 = stats_all = None
    stats_failed = False
    if stats_channel:
        try:
            stats_driver = BloggerPlatform(channel_id=stats_channel.id, credentials=stats_channel.get_credentials())
            stats_30 = stats_driver.get_page_views("30DAYS")
            stats_7 = stats_driver.get_page_views("7DAYS")
            stats_all = stats_driver.get_page_views("all")
        except Exception:
            stats_failed = True
    if stats_channel is None:
        stats_html = '<div class="text-sm text-slate-500">Belum ada blog Blogger yang terhubung.</div>'
    elif stats_failed or stats_30 is None:
        stats_html = '<div class="text-sm text-amber-400">Statistik belum tersedia — gagal mengambil data kunjungan dari Blogger.</div>'
    else:
        stats_html = f"""
        <div class="text-3xl font-extrabold text-white">{stats_30}</div>
        <div class="text-xs text-slate-400 mt-2">Total kunjungan 30 hari terakhir · {html_escape(stats_channel.name)}</div>
        <div class="mt-4 space-y-1 text-sm">
            <div class="flex justify-between border-t border-slate-800 pt-2"><span class="text-slate-400">7 hari terakhir</span><span class="font-semibold text-slate-200">{stats_7}</span></div>
            <div class="flex justify-between border-t border-slate-800 pt-2"><span class="text-slate-400">Sepanjang waktu</span><span class="font-semibold text-slate-200">{stats_all}</span></div>
        </div>
        """
    page_counts = {}
    page_rows = ""
    for ch in blogger_channels:
        try:
            page_driver = BloggerPlatform(channel_id=ch.id, credentials=ch.get_credentials())
            pages = page_driver.list_pages()
        except Exception:
            pages = None
        # Jumlah halaman per channel dipakai tabel ringkasan multi-blog
        # di section Dashboard; None = gagal dimuat -> tampil "-".
        page_counts[ch.id] = len(pages) if pages is not None else None
        page_rows += f"""
        <tr class="border-b border-slate-800/60">
            <td colspan="3" class="py-2 px-3 sm:px-4 text-xs font-semibold text-slate-400">📄 {html_escape(ch.name)} <span class="font-mono text-emerald-400">{html_escape(ch.id)}</span></td>
        </tr>
        """
        if pages is None:
            page_rows += """<tr class="border-b border-slate-800/60"><td colspan="3" class="py-3 px-3 sm:px-4 text-xs text-amber-400">Gagal memuat halaman — coba lagi nanti atau klik Test pada channel di atas.</td></tr>"""
        elif not pages:
            page_rows += """<tr class="border-b border-slate-800/60"><td colspan="3" class="py-3 px-3 sm:px-4 text-xs text-slate-500">Belum ada halaman statis.</td></tr>"""
        else:
            for pg in pages:
                is_live = (pg.get("status") or "").upper() == "LIVE"
                page_status_badge = '<span class="px-2 py-0.5 rounded text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">LIVE</span>' if is_live else '<span class="px-2 py-0.5 rounded text-xs bg-amber-500/10 text-amber-400 border border-amber-500/30">Draf</span>'
                page_link_btn = f'<a href="{html_escape(pg.get("url") or "", quote=True)}" target="_blank" class="text-xs text-emerald-400 hover:underline">Buka Link →</a>' if pg.get("url") else '<span class="text-xs text-slate-500">-</span>'
                page_rows += f"""
        <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 transition">
            <td class="py-3 px-3 sm:px-4 text-sm font-medium text-slate-200">{html_escape(pg.get("title") or '(tanpa judul)')}</td>
            <td class="py-3 px-3 sm:px-4">{page_status_badge}</td>
            <td class="py-3 px-3 sm:px-4 text-right">
                <div class="flex gap-2 justify-end items-center">{page_link_btn}
                <button onclick="deletePage('{html_escape(ch.id, quote=True)}', '{html_escape(str(pg.get('id') or ''), quote=True)}', this)" class="text-xs bg-red-950/40 hover:bg-red-900/60 text-red-400 px-2 py-1 rounded border border-red-500/30 transition">Hapus</button></div>
            </td>
        </tr>
        """
    if not blogger_channels:
        page_rows = """<tr><td colspan="3" class="py-8 text-center text-slate-500">Belum ada blog Blogger yang terhubung. Tambahkan akun blog dulu di atas.</td></tr>"""

    # Tabel ringkasan multi-blog untuk section Dashboard: hitung dari
    # tabel publications di DB; jumlah halaman dari driver.list_pages
    # (sudah diambil di atas — kalau gagal tampil "-"); terakhir
    # terbit = published_at terbaru channel itu (fallback created_at).
    summary_rows = ""
    for ch in channels:
        n_pub = db.query(Publication).filter(Publication.channel_id == ch.id, Publication.status == "published").count()
        n_draft = db.query(Publication).filter(Publication.channel_id == ch.id, Publication.status == "draft").count()
        n_pages = page_counts.get(ch.id)
        pages_cell = str(n_pages) if n_pages is not None else "-"
        last_pub = db.query(Publication).filter(
            Publication.channel_id == ch.id, Publication.status == "published"
        ).order_by(Publication.published_at.desc()).first()
        last_dt = (last_pub.published_at or last_pub.created_at) if last_pub else None
        last_str = last_dt.strftime('%d/%m/%Y %H:%M') if last_dt else "-"
        summary_rows += f"""
        <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 transition">
            <td class="py-3 px-3 sm:px-4"><div class="text-sm font-medium text-slate-200">{html_escape(ch.name)}</div><div class="text-[11px] text-slate-500 font-mono">{html_escape(ch.id)}</div></td>
            <td class="py-3 px-3 sm:px-4 text-sm text-slate-200">{n_pub}</td>
            <td class="py-3 px-3 sm:px-4 text-sm text-slate-200">{n_draft}</td>
            <td class="py-3 px-3 sm:px-4 text-sm text-slate-200">{pages_cell}</td>
            <td class="py-3 px-3 sm:px-4 text-xs text-slate-400">{last_str}</td>
        </tr>
        """
    if not channels:
        summary_rows = """<tr><td colspan="5" class="py-8 text-center text-slate-500">Belum ada blog yang terhubung.</td></tr>"""

    # Opsi dropdown channel untuk form tambah halaman
    page_channel_options = "".join(
        f'<option value="{html_escape(ch.id, quote=True)}">{html_escape(ch.name)} ({html_escape(ch.id)})</option>'
        for ch in blogger_channels
    )

    # Opsi dropdown channel untuk form Tulis Artikel (semua channel;
    # channel blogger pertama terpilih sebagai default). data-words
    # membawa target_word_count channel untuk tombol Cek SEO.
    first_blogger_id = blogger_channels[0].id if blogger_channels else None
    article_channel_options = ""
    for ch in channels:
        sel = " selected" if ch.id == first_blogger_id else ""
        article_channel_options += (
            f'<option value="{html_escape(ch.id, quote=True)}"{sel} '
            f'data-words="{ch.target_word_count}">'
            f'{html_escape(ch.name)} ({html_escape(ch.id)})</option>'
        )
    if not channels:
        article_channel_options = '<option value="">Belum ada channel — tambahkan dulu</option>'

    # Opsi dropdown draf untuk kartu Optimasi SEO (maks 30 draf terbaru).
    seo_drafts = db.query(Publication).filter(
        Publication.status == "draft").order_by(
        Publication.created_at.desc()).limit(30).all()
    seo_draft_options = "".join(
        f'<option value="{p.id}">{html_escape(p.title)}</option>'
        for p in seo_drafts
    ) or '<option value="">Belum ada draf</option>'

    # Opsi dropdown channel untuk form tambah feed (semua channel).
    feed_channel_options = ""
    for ch in channels:
        sel = " selected" if ch.id == first_blogger_id else ""
        feed_channel_options += (
            f'<option value="{html_escape(ch.id, quote=True)}"{sel}>'
            f'{html_escape(ch.name)} ({html_escape(ch.id)})</option>'
        )
    if not channels:
        feed_channel_options = '<option value="">Belum ada channel — tambahkan dulu</option>'

    # Buat baris tabel feed RSS per channel.
    feed_rows = ""
    for f in feeds:
        feed_title = f.title or f.feed_url
        last = f.last_checked_at.strftime('%d/%m/%Y %H:%M') if f.last_checked_at else 'Belum pernah'
        status_badge = '<span class="px-2 py-0.5 rounded text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">Aktif</span>' if f.active else '<span class="px-2 py-0.5 rounded text-xs bg-slate-500/10 text-slate-400 border border-slate-500/30">Nonaktif</span>'
        feed_rows += f"""
        <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 transition">
            <td class="py-3 px-3 sm:px-4"><div class="text-sm font-medium text-slate-200">{html_escape(feed_title)}</div><div class="text-[11px] text-slate-500 mt-0.5">{html_escape(f.channel_id)}</div></td>
            <td class="py-3 px-3 sm:px-4 text-xs text-slate-400 break-all max-w-xs">{html_escape(f.feed_url)}</td>
            <td class="py-3 px-3 sm:px-4">{status_badge}</td>
            <td class="py-3 px-3 sm:px-4 text-xs text-slate-400">{last}</td>
            <td class="py-3 px-3 sm:px-4 text-right">
                <div class="flex gap-1 justify-end">
                    <button onclick="fetchFeed({f.id}, this)" class="text-xs bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 px-2 py-1 rounded border border-emerald-500/30 transition">Ambil Sekarang</button>
                    <button onclick="deleteFeed({f.id}, this)" class="text-xs bg-red-950/40 hover:bg-red-900/60 text-red-400 px-2 py-1 rounded border border-red-500/30 transition">Hapus</button>
                </div>
            </td>
        </tr>
        """
    if not feeds:
        feed_rows = """<tr><td colspan="5" class="py-8 text-center text-slate-500">Belum ada feed RSS. Tambahkan feed di bawah untuk mulai mengumpulkan bahan artikel.</td></tr>"""

    # Buat baris tabel item hasil fetch terbaru (antrean rewrite).
    source_rows = ""
    for s in recent_sources:
        date_str = s.ingested_at.strftime('%d/%m/%Y %H:%M') if s.ingested_at else '-'
        link_btn = f'<a href="{html_escape(s.url or "", quote=True)}" target="_blank" class="text-xs text-emerald-400 hover:underline">Buka Sumber →</a>' if s.url else '<span class="text-xs text-slate-500">-</span>'
        source_rows += f"""
        <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 transition">
            <td class="py-3 px-3 sm:px-4 text-sm font-medium text-slate-200 max-w-xs truncate">{html_escape(s.title or '(tanpa judul)')}</td>
            <td class="py-3 px-3 sm:px-4 text-xs text-slate-400">{html_escape(s.source_name or '-')}</td>
            <td class="py-3 px-3 sm:px-4">{link_btn}</td>
            <td class="py-3 px-3 sm:px-4 text-xs text-slate-400">{date_str}</td>
            <td class="py-3 px-3 sm:px-4 text-right">
                <div class="flex gap-1 justify-end">
                    <button onclick="useSourceAsDraft({s.id}, this)" class="text-xs bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 px-2 py-1 rounded border border-emerald-500/30 transition">Jadikan Draf</button>
                    <button onclick="rewriteSourceAsDraft({s.id}, this)" class="text-xs bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-2 py-1 rounded transition">✨ Rewrite jadi Draf</button>
                </div>
            </td>
        </tr>
        """
    if not recent_sources:
        source_rows = """<tr><td colspan="5" class="py-8 text-center text-slate-500">Belum ada bahan dari feed. Klik "Ambil Sekarang" pada feed di atas.</td></tr>"""

    # Ringkasan artikel terbaru untuk section Dashboard.
    if publications:
        lp = publications[0]
        lp_date = lp.created_at.strftime('%d/%m/%Y %H:%M') if lp.created_at else '-'
        latest_pub_html = (
            f'<div class="text-sm text-slate-200 font-medium">{html_escape(lp.title or "")}</div>'
            f'<div class="text-xs text-slate-500 mt-1">{html_escape(lp.channel_id)} · {html_escape(lp.status)} · {lp_date}</div>'
        )
    else:
        latest_pub_html = '<div class="text-sm text-slate-500">Belum ada artikel.</div>'

    # Buat baris tabel publikasi. Baris di luar 15 pertama disembunyikan
    # (class pub-extra) dan dibuka lewat tombol "Muat lebih banyak".
    pub_rows = ""
    for idx, p in enumerate(publications):
        if p.status == 'published':
            status_badge = '<span class="px-2 py-0.5 rounded text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">Published</span>'
        elif p.status == 'scheduled':
            status_badge = '<span class="px-2 py-0.5 rounded text-xs bg-sky-500/10 text-sky-400 border border-sky-500/30">Terjadwal</span>'
        else:
            status_badge = '<span class="px-2 py-0.5 rounded text-xs bg-amber-500/10 text-amber-400 border border-amber-500/30">Draft</span>'
        link_btn = f'<a href="{p.remote_url}" target="_blank" class="text-xs text-emerald-400 hover:underline">Buka Link →</a>' if p.remote_url else '<span class="text-xs text-slate-500">-</span>'
        date_str = p.created_at.strftime('%d/%m/%Y %H:%M') if p.created_at else '-'
        rel = _rel_time(p.created_at)
        time_cell = f'{date_str}<div class="text-[11px] text-slate-500">{rel}</div>' if rel else date_str
        if p.status == 'draft':
            actions = f"""
            <div class="flex gap-1 justify-end">
                <button onclick="publishDraft({p.id}, this)" class="text-xs bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 px-2 py-1 rounded border border-emerald-500/30 transition">Terbitkan</button>
                <button onclick="openEditPublication(this)" data-id="{p.id}" data-title="{html_escape(p.title or '', quote=True)}" data-content="{html_escape(p.content_html or '', quote=True)}" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-2 py-1 rounded border border-slate-700 transition">Edit</button>
                <button onclick="deletePublication({p.id}, this)" class="text-xs bg-red-950/40 hover:bg-red-900/60 text-red-400 px-2 py-1 rounded border border-red-500/30 transition">Hapus</button>
            </div>
            """
        else:
            actions = f"""
            <div class="flex gap-1 justify-end">
                <button onclick="openEditPublication(this)" data-id="{p.id}" data-title="{html_escape(p.title or '', quote=True)}" data-content="{html_escape(p.content_html or '', quote=True)}" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-2 py-1 rounded border border-slate-700 transition">Edit</button>
            </div>
            """
        extra_class = " pub-extra hidden" if idx >= 15 else ""
        pub_rows += f"""
        <tr class="pub-row border-b border-slate-800/60 hover:bg-slate-800/30 transition{extra_class}" data-status="{p.status}" data-title="{html_escape((p.title or '').lower(), quote=True)}">
            <td class="py-3 px-3 sm:px-4 text-sm font-medium text-slate-200 max-w-xs truncate">{html_escape(p.title or '')}</td>
            <td class="py-3 px-3 sm:px-4 text-xs font-mono text-slate-400">{p.channel_id}</td>
            <td class="py-3 px-3 sm:px-4">{status_badge}</td>
            <td class="py-3 px-3 sm:px-4 text-xs text-slate-400">{time_cell}</td>
            <td class="py-3 px-3 sm:px-4">{link_btn}</td>
            <td class="py-3 px-3 sm:px-4 text-right">{actions}</td>
        </tr>
        """
    if not publications:
        pub_rows = """<tr><td colspan="6" class="py-8 text-center text-slate-500">Belum ada riwayat posting artikel.</td></tr>"""
    # Baris ini hanya muncul saat filter/pencarian tidak menemukan apa pun.
    pub_rows += """<tr id="pubNoMatchRow" class="hidden"><td colspan="6" class="py-8 text-center text-slate-500">Tidak ada artikel yang cocok dengan filter atau pencarian.</td></tr>"""

    # Buat baris API keys
    key_rows = ""
    for k in api_keys:
        key_rows += f"""
        <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 transition">
            <td class="py-3 px-3 sm:px-4 text-sm font-medium text-slate-200">{k.name}</td>
            <td class="py-3 px-3 sm:px-4 font-mono text-xs text-slate-400">{k.key_prefix}</td>
            <td class="py-3 px-3 sm:px-4 text-xs text-slate-400">{k.created_at.strftime('%d/%m/%Y')}</td>
            <td class="py-3 px-3 sm:px-4 text-xs text-slate-400">{k.last_used_at.strftime('%d/%m/%Y %H:%M') if k.last_used_at else 'Belum pernah'}</td>
            <td class="py-3 px-3 sm:px-4"><span class="px-2 py-0.5 rounded text-xs bg-emerald-500/10 text-emerald-400">Aktif</span></td>
            <td class="py-3 px-3 sm:px-4 text-right">
                <button onclick="copyKeyPrefix(this)" data-prefix="{k.key_prefix}" class="text-xs text-slate-300 hover:text-white mr-2">Salin</button>
                <button onclick="revokeKey({k.id}, this)" class="text-xs text-red-400 hover:text-red-300">Cabut</button>
            </td>
        </tr>
        """
    if not api_keys:
        key_rows = """<tr><td colspan="6" class="py-8 text-center text-slate-500">Belum ada API Key untuk AI Agent. Buat key baru di bawah!</td></tr>"""

    # Daftar artikel terjadwal (status "scheduled"), urut tanggal jadwal.
    # Penjadwalan dilakukan lewat Blogger API posts().publish(publishDate)
    # jadi Blogger menerbitkannya otomatis — bukan draf pengingat.
    scheduled_pubs = db.query(Publication).filter(
        Publication.status == "scheduled"
    ).order_by(Publication.scheduled_at.asc()).limit(20).all()
    scheduled_rows = ""
    for sp in scheduled_pubs:
        sched_str = sp.scheduled_at.strftime('%d/%m/%Y %H:%M') if sp.scheduled_at else '-'
        sched_link = f'<a href="{sp.remote_url}" target="_blank" class="text-xs text-emerald-400 hover:underline">Buka Link →</a>' if sp.remote_url else '<span class="text-xs text-slate-500">-</span>'
        scheduled_rows += f"""
        <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 transition">
            <td class="py-3 px-3 sm:px-4 text-sm font-medium text-slate-200 max-w-xs truncate">{html_escape(sp.title or '')}</td>
            <td class="py-3 px-3 sm:px-4 text-xs font-mono text-slate-400">{sp.channel_id}</td>
            <td class="py-3 px-3 sm:px-4 text-xs text-slate-300">{sched_str} WIB</td>
            <td class="py-3 px-3 sm:px-4"><span class="px-2 py-0.5 rounded text-xs bg-sky-500/10 text-sky-400 border border-sky-500/30">Terjadwal</span></td>
            <td class="py-3 px-3 sm:px-4 text-right">{sched_link}</td>
        </tr>
        """
    if not scheduled_pubs:
        scheduled_rows = """<tr><td colspan="5" class="py-8 text-center text-slate-500">Belum ada artikel terjadwal. Isi "Jadwal Terbit" di form di atas, lalu klik Terbitkan.</td></tr>"""

    html = f"""
    <!DOCTYPE html>
    <html lang="id" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dashboard - Blog Konektor</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script>
            tailwind.config = {{
                darkMode: 'class',
                theme: {{ extend: {{ colors: {{ brand: {{ 500: '#10b981', 600: '#059669' }} }} }} }}
            }}
        </script>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen antialiased">
        <!-- Sidebar: tetap di kiri (desktop), off-canvas di HP -->
        <div id="sidebarBackdrop" onclick="toggleSidebar(false)" class="hidden fixed inset-0 bg-black/70 z-40 lg:hidden"></div>
        <aside id="sidebar" class="fixed inset-y-0 left-0 w-64 bg-slate-900 border-r border-slate-800 z-50 transform -translate-x-full lg:translate-x-0 transition-transform flex flex-col">
            <div class="h-16 flex items-center gap-3 px-5 border-b border-slate-800 shrink-0">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 flex items-center justify-center shadow-lg shadow-emerald-500/20 shrink-0">
                    <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z"></path></svg>
                </div>
                <div class="min-w-0">
                    <span class="text-base font-bold text-white block leading-tight">Blog Konektor</span>
                    <span class="text-xs text-slate-400 block leading-tight">Control Panel</span>
                </div>
                <button onclick="toggleSidebar(false)" class="lg:hidden ml-auto text-slate-400 hover:text-white text-lg leading-none">✕</button>
            </div>
            <nav id="sidebarNav" class="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
                <button type="button" data-section="dashboard" onclick="showSection('dashboard')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">📊 Dashboard</button>
                <button type="button" data-section="channel" onclick="showSection('channel')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">🔗 Channel</button>
                <button type="button" data-section="artikel" onclick="showSection('artikel')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">✍️ Artikel</button>
                <button type="button" data-section="halaman" onclick="showSection('halaman')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">📄 Halaman</button>
                <button type="button" data-section="riwayat" onclick="showSection('riwayat')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">🕘 Riwayat</button>
                <button type="button" data-section="ingest" onclick="showSection('ingest')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">📥 Ingest</button>
                <button type="button" data-section="komentar" onclick="showSection('komentar')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">💬 Komentar</button>
                <button type="button" data-section="apikey" onclick="showSection('apikey')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">🔑 API Key</button>
                <button type="button" data-section="pengaturan-ai" onclick="showSection('pengaturan-ai')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">🤖 Pengaturan AI</button>
                <button type="button" data-section="penjadwal" onclick="showSection('penjadwal')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">⏰ Penjadwal</button>
                <button type="button" data-section="search-console" onclick="showSection('search-console')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">🔍 Search Console</button>
                <button type="button" data-section="ide-topik" onclick="showSection('ide-topik')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">💡 Ide Topik</button>
            </nav>
            <div class="p-4 border-t border-slate-800 text-xs text-slate-500">
                Blog Konektor v1.0.0<br>Multi-Channel AI Content Engine
            </div>
        </aside>

        <!-- Area utama -->
        <div class="lg:pl-64 min-h-screen flex flex-col">
        <!-- Topbar -->
        <header class="border-b border-slate-800/80 bg-slate-900/50 backdrop-blur-xl sticky top-0 z-30">
            <div class="px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                    <button onclick="toggleSidebar(true)" class="lg:hidden text-slate-300 hover:text-white text-xl leading-none px-1">☰</button>
                    <span id="topbarTitle" class="text-base font-bold text-white truncate">Dashboard</span>
                </div>

                <div class="flex items-center gap-3 flex-wrap justify-end">
                    <a href="/oauth/blogger" class="text-xs font-semibold text-orange-400 hover:text-orange-300 px-3 py-1.5 rounded-lg border border-orange-500/30 hover:bg-orange-500/10 transition flex items-center gap-1">
                        <span>🔑 Token Generator</span>
                    </a>
                    <a href="/docs" target="_blank" class="text-xs font-semibold text-slate-300 hover:text-emerald-400 px-3 py-1.5 rounded-lg border border-slate-800 hover:border-slate-700 transition flex items-center gap-1.5">
                        <svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"></path></svg>
                        API Docs (Swagger)
                    </a>
                    <a href="/logout" class="text-xs font-semibold text-red-400 hover:text-red-300 px-3 py-1.5 rounded-lg border border-red-500/20 hover:bg-red-500/10 transition">
                        Keluar
                    </a>
                </div>
            </div>
        </header>

        <!-- Main Content -->
        <main class="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <!-- Section: Dashboard (statistik + ringkasan) -->
            <section id="section-dashboard" class="nav-section space-y-6">
            <!-- Stat Cards -->
            <div class="grid grid-cols-2 lg:grid-cols-4 gap-5">
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 relative overflow-hidden">
                    <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Akun Blog Terhubung</div>
                    <div class="text-3xl font-extrabold text-white">{len(channels)}</div>
                    <div class="text-xs text-emerald-400 mt-2 flex items-center gap-1">
                        <span class="w-2 h-2 rounded-full bg-emerald-400"></span> Siap Menerima Artikel
                    </div>
                </div>

                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 relative overflow-hidden">
                    <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Artikel Published</div>
                    <div class="text-3xl font-extrabold text-white">{total_published}</div>
                    <div class="text-xs text-slate-400 mt-2">Live di blog via AI</div>
                </div>

                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 relative overflow-hidden">
                    <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Draf</div>
                    <div class="text-3xl font-extrabold text-white">{total_drafts}</div>
                    <div class="text-xs text-amber-400 mt-2">Menunggu diterbitkan</div>
                </div>

                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 relative overflow-hidden">
                    <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">AI Agent Keys</div>
                    <div class="text-3xl font-extrabold text-white">{len(api_keys)}</div>
                    <div class="text-xs text-emerald-400 mt-2">Autentikasi Aman Aktif</div>
                </div>
            </div>

            <!-- Kartu Statistik Kunjungan (Blogger pageViews, agregat per rentang) -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Total Kunjungan (30 hari)</div>
                {stats_html}
                <p class="text-[11px] text-slate-500 mt-4">Blogger API hanya memberi total agregat per rentang — tidak ada rincian kunjungan per hari.</p>
            </div>

            <!-- Ringkasan -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <h2 class="text-lg font-bold text-white mb-1">Ringkasan</h2>
                <p class="text-xs text-slate-400 mb-4">{len(channels)} blog terhubung · {total_published} artikel published · {total_drafts} draf menunggu</p>
                <div class="border-t border-slate-800 pt-4">
                    <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Artikel Terbaru</div>
                    {latest_pub_html}
                </div>
                <div class="flex flex-wrap gap-2 mt-5">
                    <button onclick="showSection('artikel')" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">✍️ Tulis Artikel</button>
                    <button onclick="showSection('channel')" class="bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold px-4 py-2 rounded-xl text-xs transition border border-slate-700">Lihat Channel</button>
                </div>
            </div>

            <!-- Ringkasan Multi-Blog -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Ringkasan Multi-Blog</h2>
                    <p class="text-xs text-slate-400">Per blog: artikel published, draf, halaman statis, dan terakhir terbit</p>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                                <th class="py-3 px-3 sm:px-4">Channel</th>
                                <th class="py-3 px-3 sm:px-4">Artikel Published</th>
                                <th class="py-3 px-3 sm:px-4">Draf</th>
                                <th class="py-3 px-3 sm:px-4">Halaman</th>
                                <th class="py-3 px-3 sm:px-4">Terakhir Terbit</th>
                            </tr>
                        </thead>
                        <tbody>
                            {summary_rows}
                        </tbody>
                    </table>
                </div>
            </div>
            </section>

            <!-- Section: Artikel (Tulis Artikel) -->
            <section id="section-artikel" class="nav-section space-y-6 hidden">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Tulis Artikel</h2>
                    <p class="text-xs text-slate-400">Tulis artikel baru lalu simpan sebagai draf atau langsung terbitkan ke blog</p>
                </div>
                <form id="articleForm" onsubmit="event.preventDefault();" class="space-y-3">
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Blog</label>
                            <select id="articleChannel" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                                {article_channel_options}
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Judul Artikel</label>
                            <input type="text" id="articleTitle" required placeholder="misal: 10 Ide Kerajinan dari Barang Bekas" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        </div>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Slug (opsional)</label>
                            <input type="text" id="articleSlug" placeholder="misal: 10-ide-kerajinan-barang-bekas" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Labels (pisah koma)</label>
                            <input type="text" id="articleLabels" placeholder="misal: diart, kerajinan, diy" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        </div>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Meta Description (SEO)</label>
                        <input type="text" id="articleMeta" maxlength="160" placeholder="Ringkasan singkat 140-160 karakter untuk SEO" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">URL Gambar Sampul (opsional)</label>
                            <input type="url" id="articleImageUrl" placeholder="https://contoh.com/gambar.jpg" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Alt Text Gambar</label>
                            <input type="text" id="articleImageAlt" placeholder="Deskripsi singkat gambar untuk SEO & aksesibilitas" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        </div>
                    </div>
                    <div class="border border-slate-800 rounded-xl p-3 space-y-2">
                        <div class="flex flex-wrap gap-2 items-end">
                            <div class="flex-1 min-w-[180px]">
                                <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Cari Foto (Image Picker)</label>
                                <input type="text" id="imageSearchQuery" placeholder="misal: menggambar digital" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                            </div>
                            <button type="button" onclick="searchImages('article', this)" class="bg-slate-800 hover:bg-slate-700 text-emerald-400 font-bold px-4 py-2 rounded-xl text-xs transition border border-slate-700">🔍 Cari Foto</button>
                        </div>
                        <p class="text-[11px] text-slate-500">Sumber utama Openverse (tanpa kunci, lisensi CC — cantumkan atribusi). Bila kunci Pexels terisi di Pengaturan AI, hasil Pexels ikut muncul (landscape 1200x675).</p>
                        <div id="imageSearchResults-article" class="grid grid-cols-2 sm:grid-cols-4 gap-2"></div>
                        <div id="imageSearchInfo-article" class="text-[11px] text-slate-500"></div>
                    </div>
                    <p class="text-[11px] text-slate-500">Gambar sampul harus berupa URL yang sudah di-host (misal di Blogger/Drive/CDN) — Blogger API tidak bisa mengunggah gambar. Gambar akan disisipkan di awal artikel.</p>
                    <div>
                        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Konten HTML</label>
                        <textarea id="articleContent" required rows="10" placeholder="Tulis konten artikel dalam HTML, misal: &lt;h2&gt;Pendahuluan&lt;/h2&gt;&lt;p&gt;...&lt;/p&gt;" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"></textarea>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Jadwal Terbit (opsional)</label>
                        <input type="datetime-local" id="articleScheduledAt" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        <p class="text-[11px] text-slate-500 mt-1">Isi tanggal & jam (WIB) untuk menjadwalkan: Blogger menerbitkan otomatis pada waktu itu. Kosongkan untuk terbit/draf biasa; jadwal di masa lalu diabaikan.</p>
                    </div>
                    <div class="flex flex-wrap gap-2">
                        <button type="button" onclick="handleWriteArticle('draft', this)" class="bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold px-4 py-2 rounded-xl text-xs transition border border-slate-700">Simpan sebagai Draf</button>
                        <button type="button" onclick="handleWriteArticle('publish', this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">Terbitkan</button>
                        <button type="button" id="checkSeoBtn" onclick="checkSeo(this)" class="bg-slate-800 hover:bg-slate-700 text-emerald-400 font-bold px-4 py-2 rounded-xl text-xs transition border border-slate-700">🔍 Cek SEO</button>
                    </div>
                    <div id="seoCheckResult" class="hidden mt-2"></div>
                </form>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Artikel Terjadwal</h2>
                    <p class="text-xs text-slate-400">Dijadwalkan lewat Blogger API — terbit otomatis pada tanggal yang dipilih</p>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                                <th class="py-3 px-3 sm:px-4">Judul Artikel</th>
                                <th class="py-3 px-3 sm:px-4">Blog</th>
                                <th class="py-3 px-3 sm:px-4">Jadwal Terbit</th>
                                <th class="py-3 px-3 sm:px-4">Status</th>
                                <th class="py-3 px-3 sm:px-4 text-right">Link</th>
                            </tr>
                        </thead>
                        <tbody>
                            {scheduled_rows}
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Optimasi SEO Draf</h2>
                    <p class="text-xs text-slate-400">Pilih draf untuk melihat saran SEO otomatis: meta description, slug, tautan internal, keterbacaan, dan alt text. Tidak ada yang berubah sampai kamu klik "Terapkan SEO". Catatan: meta description dan slug tersimpan di database konektor — untuk mengubah meta/URL live di Blogger, isi "Search Description" di editor Blogger.</p>
                </div>
                <div class="flex flex-wrap gap-3 items-end mb-4">
                    <div class="flex-1 min-w-[200px]">
                        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Draf</label>
                        <select id="seoDraftSelect" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                            {seo_draft_options}
                        </select>
                    </div>
                    <button type="button" onclick="loadSeoSuggestions(this)" class="bg-slate-800 hover:bg-slate-700 text-emerald-400 font-bold px-4 py-2 rounded-xl text-xs transition border border-slate-700">🔍 Tampilkan Saran SEO</button>
                </div>
                <div id="seoOptimizeResult" class="hidden mt-2"></div>
            </div>
            </section>

            <!-- Section: Channel -->
            <section id="section-channel" class="nav-section space-y-6 hidden">
            <!-- Channels Section -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
                    <div>
                        <h2 class="text-lg font-bold text-white">Daftar Blog (Channels)</h2>
                        <p class="text-xs text-slate-400">Hubungkan blog Blogger (Blogspot) atau WordPress Anda</p>
                    </div>
                    <button onclick="document.getElementById('addChannelModal').classList.remove('hidden')" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20 flex items-center gap-1.5 self-start sm:self-auto">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>
                        + Tambah Akun Blog
                    </button>
                </div>

                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                                <th class="py-3 px-3 sm:px-4">Blog</th>
                                <th class="py-3 px-3 sm:px-4">Platform</th>
                                <th class="py-3 px-3 sm:px-4">Alamat Blog</th>
                                <th class="py-3 px-3 sm:px-4 text-right">Aksi</th>
                            </tr>
                        </thead>
                        <tbody>
                            {channel_rows}
                        </tbody>
                    </table>
                </div>
            </div>
            </section>

            <!-- Section: Halaman -->
            <section id="section-halaman" class="nav-section space-y-6 hidden">
            <!-- Halaman Statis (Pages) -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Halaman Statis</h2>
                    <p class="text-xs text-slate-400">Halaman Tentang, Kontak, dan Kebijakan Privasi di Blogger — dibaca langsung dari Blogger</p>
                </div>

                <div class="overflow-x-auto mb-6">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                                <th class="py-3 px-3 sm:px-4">Judul</th>
                                <th class="py-3 px-3 sm:px-4">Status</th>
                                <th class="py-3 px-3 sm:px-4 text-right">Aksi</th>
                            </tr>
                        </thead>
                        <tbody>
                            {page_rows}
                        </tbody>
                    </table>
                </div>

                <form id="pageForm" onsubmit="event.preventDefault();" class="space-y-3 border-t border-slate-800 pt-5">
                    <h3 class="text-sm font-bold text-white">Tambah Halaman</h3>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Blog</label>
                            <select id="pageChannel" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                                {page_channel_options}
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Judul Halaman</label>
                            <input type="text" id="pageTitle" required placeholder="misal: Tentang" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        </div>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Konten HTML</label>
                        <textarea id="pageContent" required rows="5" placeholder="Tulis konten halaman dalam HTML, misal: &lt;h2&gt;Tentang&lt;/h2&gt;&lt;p&gt;...&lt;/p&gt;" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"></textarea>
                    </div>
                    <div class="flex flex-wrap gap-2">
                        <button type="button" id="savePageDraftBtn" onclick="handleCreatePage('draft', this)" class="bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold px-4 py-2 rounded-xl text-xs transition border border-slate-700">Simpan sebagai Draf</button>
                        <button type="button" id="publishPageBtn" onclick="handleCreatePage('publish', this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">Terbitkan</button>
                    </div>
                </form>
            </div>
            </section>

            <!-- Section: API Key -->
            <section id="section-apikey" class="nav-section space-y-6 hidden">
            <!-- AI Agent Key Management -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
                    <div>
                        <h2 class="text-lg font-bold text-white">Kunci Akses AI Agent (API Keys)</h2>
                        <p class="text-xs text-slate-400">Beri AI Agent Anda API Key ini di header <code class="bg-slate-800 text-emerald-400 px-1 py-0.5 rounded font-mono">X-API-Key</code></p>
                    </div>
                    <button onclick="document.getElementById('newKeyModal').classList.remove('hidden')" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20 self-start sm:self-auto">
                        + Buat API Key Baru
                    </button>
                </div>

                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                                <th class="py-3 px-3 sm:px-4">Nama Kunci</th>
                                <th class="py-3 px-3 sm:px-4">Prefix</th>
                                <th class="py-3 px-3 sm:px-4">Dibuat Tanggal</th>
                                <th class="py-3 px-3 sm:px-4">Terakhir Dipakai</th>
                                <th class="py-3 px-3 sm:px-4">Status</th>
                                <th class="py-3 px-3 sm:px-4 text-right">Aksi</th>
                            </tr>
                        </thead>
                        <tbody>
                            {key_rows}
                        </tbody>
                    </table>
                </div>
            </div>
            </section>

            <!-- Section: Pengaturan AI -->
            <section id="section-pengaturan-ai" class="nav-section space-y-6 hidden">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Pengaturan AI</h2>
                    <p class="text-xs text-slate-400">Kunci API untuk fitur otomatis: Gemini dipakai Auto-Rewrite dan Ide Topik, Pexels dipakai Image Picker. Kunci disimpan di database server dan tidak pernah ditampilkan lagi setelah disimpan — kosongkan kolom bila tidak ingin mengubahnya.</p>
                </div>
                <div class="space-y-4 max-w-xl">
                    <div>
                        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Gemini API Key</label>
                        <div class="flex items-center gap-2">
                            <input type="password" id="geminiKeyInput" autocomplete="off" placeholder="AI... (kosongkan bila tidak diubah)" class="flex-1 min-w-0 bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                            <span id="geminiBadge">{gemini_badge}</span>
                        </div>
                        <p class="text-[11px] text-slate-500 mt-1">Dipakai Auto-Rewrite dan Ide Topik. Dapat dibuat gratis di Google AI Studio.</p>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Pexels API Key</label>
                        <div class="flex items-center gap-2">
                            <input type="password" id="pexelsKeyInput" autocomplete="off" placeholder="Kosongkan bila tidak diubah" class="flex-1 min-w-0 bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                            <span id="pexelsBadge">{pexels_badge}</span>
                        </div>
                        <p class="text-[11px] text-slate-500 mt-1">Dipakai Image Picker untuk mencari foto gratis. Dibuat di pexels.com/api.</p>
                    </div>
                    <div class="flex flex-wrap gap-2">
                        <button type="button" onclick="saveAiSettings(this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">Simpan Pengaturan AI</button>
                    </div>
                </div>
            </div>
            </section>

            <!-- Section: Riwayat -->
            <section id="section-riwayat" class="nav-section space-y-6 hidden">
            <!-- Recent Publications -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Riwayat Publikasi Terbaru</h2>
                    <p class="text-xs text-slate-400">Artikel yang dikirimkan oleh AI ke blog-blog Anda</p>
                </div>

                <div class="flex flex-col sm:flex-row gap-3 mb-4 items-start sm:items-center">
                    <select id="bulkChannel" class="bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        {feed_channel_options}
                    </select>
                    <div class="flex flex-wrap gap-2">
                        <button type="button" onclick="bulkPublishDrafts(this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">Terbitkan Semua Draf</button>
                        <button type="button" onclick="exportBackup(this)" class="bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold px-4 py-2 rounded-xl text-xs transition border border-slate-700">⬇️ Export Backup</button>
                    </div>
                </div>

                <div class="flex flex-col sm:flex-row gap-3 mb-4">
                    <div id="pubFilters" class="flex gap-2">
                        <button type="button" data-filter="all" onclick="setPubFilter('all', this)" class="px-3 py-1.5 rounded-lg text-xs font-semibold transition bg-emerald-500 text-slate-950">Semua</button>
                        <button type="button" data-filter="draft" onclick="setPubFilter('draft', this)" class="px-3 py-1.5 rounded-lg text-xs font-semibold transition bg-slate-800 text-slate-300 hover:bg-slate-700">Draf</button>
                        <button type="button" data-filter="published" onclick="setPubFilter('published', this)" class="px-3 py-1.5 rounded-lg text-xs font-semibold transition bg-slate-800 text-slate-300 hover:bg-slate-700">Published</button>
                    </div>
                    <input id="pubSearch" type="text" placeholder="Cari judul artikel..." oninput="filterPublications()"
                        class="flex-1 bg-slate-800 border border-slate-700 rounded-xl px-3 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                </div>

                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                                <th class="py-3 px-3 sm:px-4">Judul Artikel</th>
                                <th class="py-3 px-3 sm:px-4">Channel Target</th>
                                <th class="py-3 px-3 sm:px-4">Status</th>
                                <th class="py-3 px-3 sm:px-4">Waktu</th>
                                <th class="py-3 px-3 sm:px-4">Tautan</th>
                                <th class="py-3 px-3 sm:px-4 text-right">Aksi</th>
                            </tr>
                        </thead>
                        <tbody id="pubTableBody">
                            {pub_rows}
                        </tbody>
                    </table>
                </div>

                <div class="mt-4 text-center">
                    <button id="loadMorePubs" type="button" onclick="showMorePubs()" class="text-xs font-semibold text-emerald-400 hover:text-emerald-300 px-4 py-2 rounded-xl border border-emerald-500/30 hover:bg-emerald-500/10 transition">Muat lebih banyak</button>
                </div>
            </div>
            </section>

            <!-- Section: Penjadwal (auto-publish antrean terjadwal) -->
            <section id="section-penjadwal" class="nav-section space-y-6 hidden">
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 sm:p-6">
                    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                        <div>
                            <h2 class="text-lg font-bold text-white">⏰ Penjadwal — Auto-Publish</h2>
                            <p class="text-xs text-slate-400 mt-1">Artikel terjadwal di Blogger sudah diterbitkan otomatis oleh Blogger pada waktunya (publishDate). Tick di sini menyinkronkan statusnya dan menerbitkan yang terlewat — hanya untuk channel yang toggle-nya aktif. Tick tiap jam dijalankan GitHub Actions; Cron Vercel jalan sekali sehari (08:00 WIB) sebagai pengaman, karena paket Hobby hanya mengizinkan cron harian.</p>
                        </div>
                        <button type="button" onclick="runTickNow(this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">▶ Jalankan Tick Sekarang</button>
                    </div>
                    <div id="schedulerStatus" class="text-sm text-slate-400">Memuat status scheduler…</div>
                    <div id="schedulerDue" class="mt-4"></div>
                </div>
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 sm:p-6">
                    <h3 class="text-base font-bold text-white mb-1">Auto-Publish per Channel</h3>
                    <p class="text-xs text-slate-400 mb-4">Aktifkan hanya untuk channel yang memang boleh terbit otomatis saat jadwalnya tiba.</p>
                    <div id="schedulerChannels" class="space-y-2 text-sm text-slate-400">Memuat channel…</div>
                </div>
            </section>

            <!-- Section: Search Console -->
            <section id="section-search-console" class="nav-section space-y-6 hidden">
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 sm:p-6">
                    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                        <div>
                            <h2 class="text-lg font-bold text-white">🔍 Search Console</h2>
                            <p class="text-xs text-slate-400 mt-1">Kueri teratas (28 hari terakhir) + sitemap dari Google Search Console. Butuh OAuth dengan scope Search Console — bila belum, hubungkan ulang.</p>
                        </div>
                        <div class="flex flex-wrap gap-2">
                            <select id="scChannelSelect" class="bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"></select>
                            <button type="button" onclick="loadSearchConsole(this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">Muat Data</button>
                        </div>
                    </div>
                    <div id="scContent" class="text-sm text-slate-400">Pilih blog lalu klik "Muat Data".</div>
                </div>
            </section>

            <!-- Section: Ide Topik -->
            <section id="section-ide-topik" class="nav-section space-y-6 hidden">
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 sm:p-6">
                    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                        <div>
                            <h2 class="text-lg font-bold text-white">💡 Ide Topik</h2>
                            <p class="text-xs text-slate-400 mt-1">Usulan judul dari headline feed channel + niche. Bila kunci Gemini terisi di Pengaturan AI, judul dibuat AI; kalau tidak, dipakai mode kata kunci. "Buat Draf" membuat draf kerangka (judul + H2).</p>
                        </div>
                        <div class="flex flex-wrap gap-2">
                            <select id="topicChannelSelect" class="bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"></select>
                            <button type="button" onclick="loadTopicIdeas(this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">Muat Ide</button>
                        </div>
                    </div>
                    <div id="topicIdeas" class="text-sm text-slate-400">Pilih blog lalu klik "Muat Ide".</div>
                </div>
            </section>

            <!-- Section: Ingest (feed RSS + antrean rewrite) -->
            <section id="section-ingest" class="nav-section space-y-6 hidden">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Ingest — Feed RSS & Antrean Rewrite</h2>
                    <p class="text-xs text-slate-400">Daftarkan feed RSS per blog, ambil item terbarunya, lalu jadikan bahan untuk ditulis ulang. Antrean ini hanya menyiapkan bahan — penulisan ulang dikerjakan AI agent supaya konten tetap orisinal, bukan spin mentah.</p>
                </div>

                <div class="overflow-x-auto mb-6">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                                <th class="py-3 px-3 sm:px-4">Feed</th>
                                <th class="py-3 px-3 sm:px-4">URL</th>
                                <th class="py-3 px-3 sm:px-4">Status</th>
                                <th class="py-3 px-3 sm:px-4">Terakhir Dicek</th>
                                <th class="py-3 px-3 sm:px-4 text-right">Aksi</th>
                            </tr>
                        </thead>
                        <tbody>
                            {feed_rows}
                        </tbody>
                    </table>
                </div>

                <form id="feedForm" onsubmit="event.preventDefault();" class="space-y-3 border-t border-slate-800 pt-5">
                    <h3 class="text-sm font-bold text-white">Tambah Feed</h3>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div>
                            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Blog</label>
                            <select id="feedChannel" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                                {feed_channel_options}
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">URL Feed RSS</label>
                            <input type="url" id="feedUrl" required placeholder="misal: https://contoh.com/feed.xml" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Judul Feed (opsional)</label>
                            <input type="text" id="feedTitle" placeholder="misal: Blog Diart — diisi otomatis dari feed bila kosong" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        </div>
                    </div>
                    <div class="flex flex-wrap gap-2">
                        <button type="button" onclick="handleAddFeed(this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">Tambah Feed</button>
                    </div>
                </form>
            </div>

            <!-- Antrean bahan hasil fetch -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Antrean Bahan — Hasil Fetch Terbaru</h2>
                    <p class="text-xs text-slate-400">Item terbaru dari feed yang sudah diambil. Klik "Jadikan Draf" untuk memasukkan bahan ke form Tulis Artikel dan menulis ulang sendiri, atau "Rewrite jadi Draf" untuk menulis ulang otomatis memakai Gemini — hasilnya selalu disimpan sebagai draf, lengkap dengan tautan atribusi ke sumber.</p>
                </div>
                <div class="flex flex-wrap items-end gap-3 mb-4">
                    <div>
                        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Blog untuk rewrite</label>
                        <select id="rewriteChannel" class="bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                            {article_channel_options}
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Mode rewrite</label>
                        <select id="rewriteMode" class="bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                            <option value="ringan">Ringan — susunan kalimat diubah</option>
                            <option value="sedang" selected>Sedang — struktur + contoh baru</option>
                            <option value="total">Total — sudut pandang baru</option>
                        </select>
                    </div>
                    <p class="text-[11px] text-slate-500">Rewrite memakai kunci Gemini dari Pengaturan AI dan bisa memakan waktu 1–2 menit.</p>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                                <th class="py-3 px-3 sm:px-4">Judul</th>
                                <th class="py-3 px-3 sm:px-4">Sumber</th>
                                <th class="py-3 px-3 sm:px-4">Tautan</th>
                                <th class="py-3 px-3 sm:px-4">Diambil</th>
                                <th class="py-3 px-3 sm:px-4 text-right">Aksi</th>
                            </tr>
                        </thead>
                        <tbody>
                            {source_rows}
                        </tbody>
                    </table>
                </div>
            </div>
            </section>

            <!-- Section: Komentar (moderasi komentar Blogger) -->
            <section id="section-komentar" class="nav-section space-y-6 hidden">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Komentar</h2>
                    <p class="text-xs text-slate-400">Moderasi komentar blog dari Blogger — setujui, tandai spam, atau hapus. Pilih blog lalu klik Muat.</p>
                </div>

                <div class="flex flex-col sm:flex-row gap-3 mb-4 items-start sm:items-center">
                    <select id="commentChannel" class="bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        {page_channel_options}
                    </select>
                    <button type="button" onclick="loadComments(this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">Muat Komentar</button>
                </div>

                <div id="commentList" class="space-y-3">
                    <div class="py-8 text-center text-sm text-slate-500">Pilih blog lalu klik "Muat Komentar".</div>
                </div>
            </div>
            </section>
        </main>
        </div>

        <!-- Toast notifications (pojok kanan atas) -->
        <div id="toastContainer" class="fixed top-4 right-4 z-[100] space-y-2 w-80 max-w-[calc(100vw-2rem)]"></div>

        <!-- Modal konfirmasi generik (pengganti confirm() bawaan browser) -->
        <div id="confirmModal" class="hidden fixed inset-0 z-[90] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-sm w-full shadow-2xl">
                <h3 id="confirmTitle" class="text-base font-bold text-white mb-2">Konfirmasi</h3>
                <p id="confirmMessage" class="text-sm text-slate-400 mb-5"></p>
                <div class="flex justify-end gap-2">
                    <button type="button" onclick="closeConfirm(false)" class="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:bg-slate-800">Batal</button>
                    <button type="button" onclick="closeConfirm(true)" class="px-4 py-2 rounded-xl text-xs font-bold bg-red-500 hover:bg-red-600 text-white shadow-lg shadow-red-500/20">Ya, Lanjutkan</button>
                </div>
            </div>
        </div>

        <!-- Modal Tambah Blog (Channels) -->
        <div id="addChannelModal" class="hidden fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-lg w-full shadow-2xl my-8">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-bold text-white">Hubungkan Akun Blog Baru</h3>
                    <button onclick="document.getElementById('addChannelModal').classList.add('hidden')" class="text-slate-400 hover:text-white">✕</button>
                </div>

                <!-- Platform Tabs -->
                <div class="flex rounded-xl bg-slate-800/80 p-1 mb-5">
                    <button type="button" id="tabBloggerBtn" onclick="switchPlatformTab('blogger')" class="flex-1 py-2 text-xs font-bold rounded-lg bg-emerald-500 text-slate-950 transition">
                        Google Blogger (Blogspot)
                    </button>
                    <button type="button" id="tabWpBtn" onclick="switchPlatformTab('wordpress')" class="flex-1 py-2 text-xs font-bold rounded-lg text-slate-400 hover:text-white transition">
                        WordPress
                    </button>
                </div>

                <form id="addChannelForm" onsubmit="handleAddChannel(event)" class="space-y-4 text-xs">
                    <input type="hidden" id="channelPlatform" value="blogger">

                    <div class="grid grid-cols-2 gap-3">
                        <div>
                            <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Channel ID (Unik)</label>
                            <input type="text" id="chId" required placeholder="misal: blogger-tech" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                        </div>
                        <div>
                            <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Nama Tampilan Blog</label>
                            <input type="text" id="chName" required placeholder="misal: Blog Tekno Max" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                        </div>
                    </div>

                    <div class="grid grid-cols-2 gap-3">
                        <div>
                            <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Niche Blog</label>
                            <input type="text" id="chNiche" required placeholder="misal: Gadget & AI" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                        </div>
                        <div>
                            <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Tone of Voice (Gaya)</label>
                            <input type="text" id="chTone" placeholder="misal: Santai & Informatif" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                        </div>
                    </div>

                    <!-- Blogger Specific Fields -->
                    <div id="bloggerFields" class="space-y-3 pt-2 border-t border-slate-800">
                        <div class="p-3.5 rounded-xl bg-slate-800/60 border border-slate-700 text-slate-300 space-y-2">
                            <div class="flex items-center justify-between">
                                <p class="font-semibold text-emerald-400 text-xs">✨ Cara Mudah (Tanpa Terminal):</p>
                                <a href="/oauth/blogger" target="_blank" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-3 py-1.5 rounded-lg text-xs flex items-center gap-1 shadow-md transition">
                                    <span>🌐 Dapatkan Token via Web →</span>
                                </a>
                            </div>
                            <p class="text-[11px] text-slate-300">
                                Sudah punya Client ID & Secret? Klik tombol di atas untuk login Google dan sistem akan otomatis menampilkan <b>Refresh Token & Blog ID</b> Anda langsung di halaman web!
                            </p>
                        </div>

                        <div>
                            <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Google Client ID</label>
                            <input type="text" id="bgClientId" placeholder="xxxx.apps.googleusercontent.com" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                        </div>
                        <div>
                            <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Google Client Secret</label>
                            <input type="password" id="bgClientSecret" placeholder="GOCSPX-xxxx" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                        </div>
                        <div class="grid grid-cols-2 gap-3">
                            <div>
                                <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Refresh Token</label>
                                <input type="password" id="bgRefreshToken" placeholder="1//04xxx" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                            </div>
                            <div>
                                <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Blog ID (Angka)</label>
                                <input type="text" id="bgBlogId" placeholder="misal: 819283918239" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                            </div>
                        </div>
                    </div>

                    <!-- WordPress Specific Fields (Hidden by default) -->
                    <div id="wpFields" class="hidden space-y-3 pt-2 border-t border-slate-800">
                        <div class="p-3 rounded-xl bg-slate-800/50 border border-slate-700 text-slate-300">
                            <p class="font-semibold text-blue-400">💡 Cara Konek WordPress:</p>
                            <p>Buka dashboard WP Anda > <b>Users > Profile</b> > scroll ke bawah ke <b>Application Passwords</b> > buat password baru.</p>
                        </div>
                        <div>
                            <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">WordPress URL</label>
                            <input type="url" id="wpUrl" placeholder="https://domain-anda.com" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                        </div>
                        <div class="grid grid-cols-2 gap-3">
                            <div>
                                <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Username WP</label>
                                <input type="text" id="wpUsername" placeholder="admin" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                            </div>
                            <div>
                                <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Application Password</label>
                                <input type="password" id="wpAppPassword" placeholder="xxxx xxxx xxxx xxxx" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                            </div>
                        </div>
                    </div>

                    <div class="flex justify-end gap-2 pt-3 border-t border-slate-800">
                        <button type="button" onclick="document.getElementById('addChannelModal').classList.add('hidden')" class="px-4 py-2 rounded-xl font-semibold text-slate-400 hover:bg-slate-800">Batal</button>
                        <button type="submit" id="saveChannelBtn" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-5 py-2 rounded-xl shadow-lg shadow-emerald-500/20">Simpan Akun Blog</button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Modal Pengaturan Channel (pengaturan artikel per channel) -->
        <div id="channelSettingsModal" class="hidden fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-lg w-full shadow-2xl my-8">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-bold text-white">Pengaturan Artikel — <span id="settingsChannelName" class="text-emerald-400"></span></h3>
                    <button onclick="document.getElementById('channelSettingsModal').classList.add('hidden')" class="text-slate-400 hover:text-white">✕</button>
                </div>
                <form id="channelSettingsForm" onsubmit="handleSaveChannelSettings(event)" class="space-y-4 text-xs">
                    <input type="hidden" id="settingsChannelId">
                    <div>
                        <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Niche Blog</label>
                        <input type="text" id="settingsNiche" required placeholder="misal: diart" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                    </div>
                    <div>
                        <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Tone of Voice (Gaya)</label>
                        <input type="text" id="settingsTone" placeholder="misal: Santai" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                    </div>
                    <div class="grid grid-cols-2 gap-3">
                        <div>
                            <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Target Kata</label>
                            <input type="number" id="settingsWords" min="1" placeholder="misal: 800" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                        </div>
                        <div>
                            <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Labels Default (pisah koma)</label>
                            <input type="text" id="settingsLabels" placeholder="misal: diart, catatan" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                        </div>
                    </div>
                    <div class="flex justify-end gap-2 pt-3 border-t border-slate-800">
                        <button type="button" onclick="document.getElementById('channelSettingsModal').classList.add('hidden')" class="px-4 py-2 rounded-xl font-semibold text-slate-400 hover:bg-slate-800">Batal</button>
                        <button type="submit" id="saveChannelSettingsBtn" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-5 py-2 rounded-xl shadow-lg shadow-emerald-500/20">Simpan Pengaturan</button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Modal Edit Artikel (edit draf maupun artikel published) -->
        <div id="editPubModal" class="hidden fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-2xl w-full shadow-2xl my-8">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-bold text-white">Edit Artikel</h3>
                    <button onclick="document.getElementById('editPubModal').classList.add('hidden')" class="text-slate-400 hover:text-white">✕</button>
                </div>
                <form id="editPubForm" onsubmit="handleSaveEditPublication(event)" class="space-y-4 text-xs">
                    <input type="hidden" id="editPubId">
                    <div>
                        <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Judul Artikel</label>
                        <input type="text" id="editPubTitle" placeholder="Judul artikel" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                    </div>
                    <div id="editPubNote" class="hidden text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-xl px-3 py-2">Konten artikel tidak bisa dimuat dari riwayat — isi konten baru di bawah ini.</div>
                    <div>
                        <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Konten HTML</label>
                        <textarea id="editPubContent" rows="10" placeholder="Konten artikel dalam HTML" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500"></textarea>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">URL Gambar Sampul (opsional)</label>
                            <input type="url" id="editPubImageUrl" placeholder="https://contoh.com/gambar.jpg" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                        </div>
                        <div>
                            <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1">Alt Text Gambar</label>
                            <input type="text" id="editPubImageAlt" placeholder="Deskripsi singkat gambar" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-100 focus:ring-2 focus:ring-emerald-500">
                        </div>
                    </div>
                    <div class="border border-slate-800 rounded-xl p-3 space-y-2">
                        <div class="flex flex-wrap gap-2 items-end">
                            <div class="flex-1 min-w-[180px]">
                                <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Cari Foto (Image Picker)</label>
                                <input type="text" id="editImageSearchQuery" placeholder="misal: menggambar digital" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:ring-2 focus:ring-emerald-500">
                            </div>
                            <button type="button" onclick="searchImages('edit', this)" class="bg-slate-800 hover:bg-slate-700 text-emerald-400 font-bold px-4 py-2 rounded-xl text-xs transition border border-slate-700">🔍 Cari Foto</button>
                        </div>
                        <p class="text-[11px] text-slate-500">Sumber utama Openverse (tanpa kunci, lisensi CC — cantumkan atribusi). Bila kunci Pexels terisi di Pengaturan AI, hasil Pexels ikut muncul (landscape 1200x675).</p>
                        <div id="imageSearchResults-edit" class="grid grid-cols-2 sm:grid-cols-4 gap-2"></div>
                        <div id="imageSearchInfo-edit" class="text-[11px] text-slate-500"></div>
                    </div>
                    <p class="text-[11px] text-slate-500">Gambar sampul harus berupa URL yang sudah di-host (misal di Blogger/Drive/CDN) — Blogger API tidak bisa mengunggah gambar. Gambar akan disisipkan di awal artikel, menggantikan gambar sampul lama bila ada.</p>
                    <div class="flex justify-end gap-2 pt-3 border-t border-slate-800">
                        <button type="button" onclick="document.getElementById('editPubModal').classList.add('hidden')" class="px-4 py-2 rounded-xl font-semibold text-slate-400 hover:bg-slate-800">Batal</button>
                        <button type="submit" id="saveEditPubBtn" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-5 py-2 rounded-xl shadow-lg shadow-emerald-500/20">Simpan Perubahan</button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Modal Tambah API Key -->
        <div id="newKeyModal" class="hidden fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-md w-full shadow-2xl">
                <h3 class="text-lg font-bold text-white mb-2">Buat API Key untuk AI Agent</h3>
                <p class="text-xs text-slate-400 mb-4">Beri nama pengenal agar Anda tahu agent mana yang menggunakan key ini.</p>
                <form id="createKeyForm" onsubmit="handleCreateKey(event)" class="space-y-4">
                    <div>
                        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Nama Agent</label>
                        <input type="text" id="keyNameInput" required placeholder="Contoh: AI Agent Antigravity"
                            class="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                    </div>
                    <div id="keyResultArea" class="hidden">
                        <label class="block text-xs font-semibold uppercase tracking-wider text-emerald-400 mb-1">Simpan API Key Ini Sekarang:</label>
                        <div class="flex items-center gap-2">
                            <input type="text" id="rawKeyOutput" readonly class="w-full bg-slate-950 border border-emerald-500/50 rounded-xl px-3 py-2 text-xs font-mono text-emerald-300">
                            <button type="button" onclick="copyKeyValue(this)"
                                class="bg-slate-800 hover:bg-slate-700 text-xs px-3 py-2 rounded-xl text-slate-200">Salin</button>
                        </div>
                        <p class="text-xs text-amber-400 mt-1">⚠️ Key ini hanya ditampilkan satu kali!</p>
                    </div>
                    <div class="flex justify-end gap-2 pt-2">
                        <button type="button" onclick="document.getElementById('newKeyModal').classList.add('hidden'); window.location.reload();"
                            class="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:bg-slate-800">Tutup</button>
                        <button type="submit" id="submitKeyBtn"
                            class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs">Buat Kunci</button>
                    </div>
                </form>
            </div>
        </div>

        <script>
            // --- Toast notifications (pengganti alert()) ---
            function showToast(message, type) {{
                type = type || 'success';
                const container = document.getElementById('toastContainer');
                const el = document.createElement('div');
                el.className = 'px-4 py-3 rounded-xl text-sm shadow-2xl border flex items-start gap-2 ' + (type === 'error' ? 'bg-red-950/90 border-red-500/40 text-red-200' : 'bg-slate-900 border-emerald-500/40 text-emerald-200');
                const text = document.createElement('span');
                text.className = 'flex-1 break-words';
                text.innerText = message;
                const close = document.createElement('button');
                close.type = 'button';
                close.className = 'text-slate-400 hover:text-white ml-2 shrink-0';
                close.innerText = '✕';
                close.onclick = () => el.remove();
                el.appendChild(text);
                el.appendChild(close);
                container.appendChild(el);
                setTimeout(() => {{ el.remove(); }}, 5000);
            }}

            // --- Modal konfirmasi generik (pengganti confirm()) ---
            let confirmResolve = null;
            function askConfirm(title, message) {{
                return new Promise((resolve) => {{
                    confirmResolve = resolve;
                    document.getElementById('confirmTitle').innerText = title;
                    document.getElementById('confirmMessage').innerText = message;
                    document.getElementById('confirmModal').classList.remove('hidden');
                }});
            }}
            function closeConfirm(result) {{
                document.getElementById('confirmModal').classList.add('hidden');
                if (confirmResolve) {{ confirmResolve(result); confirmResolve = null; }}
            }}

            // --- Status loading pada tombol ---
            function setBtnLoading(btn, loading, label) {{
                if (!btn) return;
                if (loading) {{
                    btn.dataset.origText = btn.innerText;
                    btn.disabled = true;
                    btn.innerText = label;
                }} else {{
                    btn.disabled = false;
                    if (btn.dataset.origText) btn.innerText = btn.dataset.origText;
                }}
            }}

            // --- Salin ke clipboard + toast ---
            async function copyToClipboard(text) {{
                try {{
                    await navigator.clipboard.writeText(text);
                    return true;
                }} catch (err) {{
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    let ok = false;
                    try {{ ok = document.execCommand('copy'); }} catch (e) {{}}
                    ta.remove();
                    return ok;
                }}
            }}
            function copyBlogUrl(btn) {{
                copyToClipboard(btn.dataset.url).then((ok) => showToast(ok ? 'Alamat blog disalin.' : 'Gagal menyalin alamat blog.', ok ? 'success' : 'error'));
            }}
            function copyKeyPrefix(btn) {{
                copyToClipboard(btn.dataset.prefix).then((ok) => showToast(ok ? 'Prefix API key disalin.' : 'Gagal menyalin prefix.', ok ? 'success' : 'error'));
            }}
            function copyKeyValue(btn) {{
                copyToClipboard(document.getElementById('rawKeyOutput').value).then((ok) => showToast(ok ? 'API Key disalin!' : 'Gagal menyalin API Key.', ok ? 'success' : 'error'));
            }}

            // --- Filter & pencarian riwayat publikasi ---
            let pubFilter = 'all';
            let pubExtraShown = false;
            function setPubFilter(filter, btn) {{
                pubFilter = filter;
                document.querySelectorAll('#pubFilters button').forEach((b) => {{
                    b.className = 'px-3 py-1.5 rounded-lg text-xs font-semibold transition ' + (b.dataset.filter === filter ? 'bg-emerald-500 text-slate-950' : 'bg-slate-800 text-slate-300 hover:bg-slate-700');
                }});
                filterPublications();
            }}
            function filterPublications() {{
                const q = (document.getElementById('pubSearch').value || '').toLowerCase();
                let visibleCount = 0;
                document.querySelectorAll('#pubTableBody .pub-row').forEach((row) => {{
                    const matchFilter = pubFilter === 'all' || row.dataset.status === pubFilter;
                    const matchSearch = !q || (row.dataset.title || '').includes(q);
                    const isExtra = row.classList.contains('pub-extra');
                    const show = matchFilter && matchSearch && (!isExtra || pubExtraShown);
                    row.classList.toggle('hidden', !show);
                    if (show) visibleCount++;
                }});
                const noMatch = document.getElementById('pubNoMatchRow');
                if (noMatch) noMatch.classList.toggle('hidden', visibleCount > 0);
                updateLoadMoreBtn();
            }}
            function showMorePubs() {{
                pubExtraShown = true;
                document.querySelectorAll('#pubTableBody .pub-extra').forEach((row) => row.classList.remove('hidden'));
                filterPublications();
            }}
            function updateLoadMoreBtn() {{
                const btn = document.getElementById('loadMorePubs');
                if (!btn) return;
                const hiddenExtra = document.querySelectorAll('#pubTableBody .pub-extra.hidden').length;
                btn.classList.toggle('hidden', hiddenExtra === 0 || pubExtraShown);
            }}

            function switchPlatformTab(platform) {{
                document.getElementById('channelPlatform').value = platform;
                if (platform === 'blogger') {{
                    document.getElementById('tabBloggerBtn').className = "flex-1 py-2 text-xs font-bold rounded-lg bg-emerald-500 text-slate-950 transition";
                    document.getElementById('tabWpBtn').className = "flex-1 py-2 text-xs font-bold rounded-lg text-slate-400 hover:text-white transition";
                    document.getElementById('bloggerFields').classList.remove('hidden');
                    document.getElementById('wpFields').classList.add('hidden');
                }} else {{
                    document.getElementById('tabWpBtn').className = "flex-1 py-2 text-xs font-bold rounded-lg bg-blue-500 text-white transition";
                    document.getElementById('tabBloggerBtn').className = "flex-1 py-2 text-xs font-bold rounded-lg text-slate-400 hover:text-white transition";
                    document.getElementById('wpFields').classList.remove('hidden');
                    document.getElementById('bloggerFields').classList.add('hidden');
                }}
            }}

            async function handleAddChannel(e) {{
                e.preventDefault();
                const platform = document.getElementById('channelPlatform').value;
                const id = document.getElementById('chId').value;
                const name = document.getElementById('chName').value;
                const niche = document.getElementById('chNiche').value;
                const tone = document.getElementById('chTone').value || 'Santai';

                let credentials = {{}};
                if (platform === 'blogger') {{
                    credentials = {{
                        client_id: document.getElementById('bgClientId').value,
                        client_secret: document.getElementById('bgClientSecret').value,
                        refresh_token: document.getElementById('bgRefreshToken').value,
                        blog_id: document.getElementById('bgBlogId').value
                    }};
                }} else {{
                    credentials = {{
                        url: document.getElementById('wpUrl').value,
                        username: document.getElementById('wpUsername').value,
                        app_password: document.getElementById('wpAppPassword').value
                    }};
                }}

                const payload = {{
                    id: id,
                    name: name,
                    platform: platform,
                    credentials: credentials,
                    niche: niche,
                    tone_of_voice: tone,
                    target_word_count: 800
                }};

                const btn = document.getElementById('saveChannelBtn');
                setBtnLoading(btn, true, 'Menyimpan…');
                try {{
                    const res = await fetch('/api/v1/channels', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(payload)
                    }});
                    if (res.ok) {{
                        showToast('Akun blog berhasil ditambahkan!');
                        setTimeout(() => window.location.reload(), 800);
                    }} else {{
                        const err = await res.json();
                        showToast('Gagal: ' + (err.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            async function testChannel(channelId, btn) {{
                setBtnLoading(btn, true, 'Mengetes…');
                try {{
                    const res = await fetch(`/api/v1/channels/${{channelId}}/test-blogger-blogs`);
                    const data = await res.json();
                    if (res.ok) {{
                        const found = (data.blogs || []).map((b) => b.name + ' (' + (b.url || b.id) + ')').join(', ');
                        showToast(data.message + (found ? ' Blog: ' + found : '') + (data.resolved_blog_url ? ' Alamat blog: ' + data.resolved_blog_url : ''));
                        setTimeout(() => window.location.reload(), 1200);
                    }} else {{
                        showToast('Gagal tes koneksi: ' + (data.detail || 'Periksa kredensial'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            async function deleteChannel(channelId, btn) {{
                const ok = await askConfirm('Hapus blog?', `Blog '${{channelId}}' akan dihapus dari konektor. Artikel yang sudah terbit di Blogger tidak ikut terhapus.`);
                if (!ok) return;
                setBtnLoading(btn, true, 'Menghapus…');
                try {{
                    const res = await fetch(`/api/v1/channels/${{channelId}}`, {{ method: 'DELETE' }});
                    if (res.ok) {{
                        showToast('Blog berhasil dihapus dari konektor.');
                        setTimeout(() => window.location.reload(), 800);
                    }} else {{
                        showToast('Gagal menghapus blog.', 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            async function publishDraft(pubId, btn) {{
                setBtnLoading(btn, true, 'Menerbitkan…');
                try {{
                    const res = await fetch(`/api/v1/publish/${{pubId}}/publish`, {{ method: 'POST' }});
                    const data = await res.json();
                    if (res.ok && data.status === 'published') {{
                        showToast('Artikel berhasil diterbitkan.' + (data.remote_url ? ' ' + data.remote_url : ''));
                        setTimeout(() => window.location.reload(), 1200);
                    }} else {{
                        showToast('Gagal menerbitkan: ' + (data.error_message || data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            async function deletePublication(pubId, btn) {{
                const ok = await askConfirm('Hapus draf?', 'Draf ini akan dihapus dari Blogger dan dari riwayat. Tindakan ini tidak bisa dibatalkan.');
                if (!ok) return;
                setBtnLoading(btn, true, 'Menghapus…');
                try {{
                    const res = await fetch(`/api/v1/publish/${{pubId}}`, {{ method: 'DELETE' }});
                    const data = await res.json();
                    if (res.ok) {{
                        showToast('Draf berhasil dihapus.' + (data.blogger_error ? ' Catatan: ' + data.blogger_error : ''));
                        setTimeout(() => window.location.reload(), 800);
                    }} else {{
                        showToast('Gagal menghapus draf: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // --- Terbitkan Semua Draf + Export Backup (Riwayat) ---
            async function bulkPublishDrafts(btn) {{
                const channelId = document.getElementById('bulkChannel').value;
                if (!channelId) {{
                    showToast('Pilih dulu blognya.', 'error');
                    return;
                }}
                const ok = await askConfirm('Terbitkan semua draf?', 'Semua draf pada blog ini akan diterbitkan ke Blogger satu per satu.');
                if (!ok) return;
                setBtnLoading(btn, true, 'Menerbitkan…');
                try {{
                    const res = await fetch('/api/v1/publish/bulk/publish', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ channel_id: channelId }})
                    }});
                    const data = await res.json();
                    if (res.ok) {{
                        showToast(`Selesai: ${{data.published}} diterbitkan, ${{data.failed}} gagal.`);
                        setTimeout(() => window.location.reload(), 1200);
                    }} else {{
                        showToast('Gagal: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            async function exportBackup(btn) {{
                setBtnLoading(btn, true, 'Mengunduh…');
                try {{
                    const res = await fetch('/api/v1/backup');
                    if (!res.ok) {{
                        showToast('Gagal mengunduh backup.', 'error');
                        return;
                    }}
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'blog-connector-backup.json';
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    URL.revokeObjectURL(url);
                    showToast('Backup berhasil diunduh.');
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // --- Moderasi Komentar (Blogger) ---
            // Isi komentar datang dari Blogger dan bisa mengandung HTML,
            // jadi selalu di-escape sebelum dimasukkan ke innerHTML.
            function escapeHtml(s) {{
                const d = document.createElement('div');
                d.innerText = s || '';
                return d.innerHTML;
            }}
            function commentStatusBadge(status) {{
                const s = (status || '').toUpperCase();
                if (s === 'LIVE') return '<span class="px-2 py-0.5 rounded text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">Live</span>';
                if (s === 'SPAM') return '<span class="px-2 py-0.5 rounded text-xs bg-red-500/10 text-red-400 border border-red-500/30">Spam</span>';
                return '<span class="px-2 py-0.5 rounded text-xs bg-amber-500/10 text-amber-400 border border-amber-500/30">Menunggu</span>';
            }}
            async function loadComments(btn) {{
                const channelId = document.getElementById('commentChannel').value;
                const box = document.getElementById('commentList');
                if (!channelId) {{
                    showToast('Pilih dulu blognya.', 'error');
                    return;
                }}
                setBtnLoading(btn, true, 'Memuat…');
                try {{
                    const res = await fetch(`/api/v1/comments?channel_id=${{encodeURIComponent(channelId)}}`);
                    const data = await res.json();
                    if (!res.ok) {{
                        showToast('Gagal memuat komentar: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                        return;
                    }}
                    if (!data.length) {{
                        box.innerHTML = '<div class="py-8 text-center text-sm text-slate-500">Belum ada komentar di blog ini.</div>';
                        return;
                    }}
                    box.innerHTML = data.map((c) => {{
                        const dateStr = c.published ? new Date(c.published).toLocaleString('id-ID') : '-';
                        // Moderasi Blogger butuh post_id (endpoint-nya
                        // per-postingan); tanpa itu tombol dimatikan.
                        const actions = c.post_id
                            ? `<div class="flex gap-1 justify-end shrink-0">
                                <button onclick="approveComment('${{c.id}}', '${{c.post_id}}', this)" class="text-xs bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 px-2 py-1 rounded border border-emerald-500/30 transition">Setujui</button>
                                <button onclick="spamComment('${{c.id}}', '${{c.post_id}}', this)" class="text-xs bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 px-2 py-1 rounded border border-amber-500/30 transition">Spam</button>
                                <button onclick="deleteComment('${{c.id}}', '${{c.post_id}}', this)" class="text-xs bg-red-950/40 hover:bg-red-900/60 text-red-400 px-2 py-1 rounded border border-red-500/30 transition">Hapus</button>
                            </div>`
                            : '<span class="text-[11px] text-slate-500 shrink-0">tanpa post — tidak bisa dimoderasi</span>';
                        return `<div class="bg-slate-800/50 border border-slate-800 rounded-xl p-4 flex gap-3 items-start">
                            <div class="flex-1 min-w-0">
                                <div class="flex flex-wrap items-center gap-2 mb-1">
                                    <span class="text-sm font-semibold text-slate-200">${{escapeHtml(c.author)}}</span>
                                    ${{commentStatusBadge(c.status)}}
                                    <span class="text-[11px] text-slate-500">${{dateStr}}</span>
                                </div>
                                <div class="text-sm text-slate-300 break-words">${{escapeHtml(c.content)}}</div>
                            </div>
                            ${{actions}}
                        </div>`;
                    }}).join('');
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}
            async function approveComment(commentId, postId, btn) {{
                const channelId = document.getElementById('commentChannel').value;
                setBtnLoading(btn, true, 'Menyetujui…');
                try {{
                    const res = await fetch(`/api/v1/comments/${{encodeURIComponent(commentId)}}/approve`, {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ channel_id: channelId, post_id: postId }})
                    }});
                    const data = await res.json();
                    if (res.ok && data.ok) {{
                        showToast('Komentar disetujui.');
                        loadComments();
                    }} else {{
                        showToast('Gagal: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}
            async function spamComment(commentId, postId, btn) {{
                const ok = await askConfirm('Tandai sebagai spam?', 'Komentar ini akan ditandai sebagai spam di Blogger.');
                if (!ok) return;
                const channelId = document.getElementById('commentChannel').value;
                setBtnLoading(btn, true, 'Menandai…');
                try {{
                    const res = await fetch(`/api/v1/comments/${{encodeURIComponent(commentId)}}/spam`, {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ channel_id: channelId, post_id: postId }})
                    }});
                    const data = await res.json();
                    if (res.ok && data.ok) {{
                        showToast('Komentar ditandai sebagai spam.');
                        loadComments();
                    }} else {{
                        showToast('Gagal: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}
            async function deleteComment(commentId, postId, btn) {{
                const ok = await askConfirm('Hapus komentar?', 'Komentar ini akan dihapus dari Blogger. Tindakan ini tidak bisa dibatalkan.');
                if (!ok) return;
                const channelId = document.getElementById('commentChannel').value;
                setBtnLoading(btn, true, 'Menghapus…');
                try {{
                    const res = await fetch(`/api/v1/comments/${{encodeURIComponent(commentId)}}?channel_id=${{encodeURIComponent(channelId)}}&post_id=${{encodeURIComponent(postId)}}`, {{ method: 'DELETE' }});
                    const data = await res.json();
                    if (res.ok && data.ok) {{
                        showToast('Komentar berhasil dihapus.');
                        loadComments();
                    }} else {{
                        showToast('Gagal: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            async function handleCreatePage(status, btn) {{
                const channelId = document.getElementById('pageChannel').value;
                const title = document.getElementById('pageTitle').value.trim();
                const content = document.getElementById('pageContent').value.trim();
                if (!channelId || !title || !content) {{
                    showToast('Isi dulu blog, judul, dan konten halamannya.', 'error');
                    return;
                }}
                setBtnLoading(btn, true, status === 'publish' ? 'Menerbitkan…' : 'Menyimpan…');
                try {{
                    const res = await fetch('/api/v1/pages', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ channel_id: channelId, title: title, content_html: content, status: status }})
                    }});
                    const data = await res.json();
                    if (res.ok && data.ok) {{
                        showToast(status === 'publish' ? 'Halaman berhasil diterbitkan.' + (data.url ? ' ' + data.url : '') : 'Halaman berhasil disimpan sebagai draf.');
                        setTimeout(() => window.location.reload(), 1000);
                    }} else {{
                        showToast('Gagal: ' + (data.error || data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            async function deletePage(channelId, pageId, btn) {{
                const ok = await askConfirm('Hapus halaman?', 'Halaman ini akan dihapus dari Blogger. Tindakan ini tidak bisa dibatalkan.');
                if (!ok) return;
                setBtnLoading(btn, true, 'Menghapus…');
                try {{
                    const res = await fetch(`/api/v1/pages/${{encodeURIComponent(pageId)}}?channel_id=${{encodeURIComponent(channelId)}}`, {{ method: 'DELETE' }});
                    const data = await res.json();
                    if (res.ok && data.ok) {{
                        showToast('Halaman berhasil dihapus.');
                        setTimeout(() => window.location.reload(), 800);
                    }} else {{
                        showToast('Gagal menghapus halaman: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            async function handleCreateKey(e) {{
                e.preventDefault();
                const name = document.getElementById('keyNameInput').value;
                const btn = document.getElementById('submitKeyBtn');
                btn.disabled = true;
                btn.innerText = 'Membuat...';
                try {{
                    const res = await fetch('/api/v1/auth/keys', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ name: name }})
                    }});
                    const data = await res.json();
                    if (res.ok) {{
                        document.getElementById('keyResultArea').classList.remove('hidden');
                        document.getElementById('rawKeyOutput').value = data.key;
                        btn.classList.add('hidden');
                        document.getElementById('keyNameInput').disabled = true;
                        showToast('API Key berhasil dibuat. Simpan sekarang, key ini hanya ditampilkan satu kali!');
                    }} else {{
                        showToast(data.detail || 'Gagal membuat API Key', 'error');
                        btn.disabled = false;
                        btn.innerText = 'Buat Kunci';
                    }}
                }} catch (err) {{
                    showToast('Terjadi kesalahan: ' + err, 'error');
                    btn.disabled = false;
                    btn.innerText = 'Buat Kunci';
                }}
            }}

            async function revokeKey(keyId, btn) {{
                const ok = await askConfirm('Cabut API Key?', 'Hak akses API Key ini akan dicabut. AI Agent yang memakainya tidak akan bisa mengakses lagi.');
                if (!ok) return;
                setBtnLoading(btn, true, 'Mencabut…');
                try {{
                    const res = await fetch(`/api/v1/auth/keys/${{keyId}}`, {{ method: 'DELETE' }});
                    if (res.ok) {{
                        showToast('API Key berhasil dicabut.');
                        setTimeout(() => window.location.reload(), 800);
                    }} else {{
                        showToast('Gagal mencabut kunci.', 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // --- Feed RSS + antrean rewrite ---
            async function handleAddFeed(btn) {{
                const channelId = document.getElementById('feedChannel').value;
                const feedUrl = document.getElementById('feedUrl').value.trim();
                const feedTitle = document.getElementById('feedTitle').value.trim();
                if (!channelId || !feedUrl) {{
                    showToast('Isi dulu blog dan URL feed RSS-nya.', 'error');
                    return;
                }}
                const payload = {{channel_id: channelId, feed_url: feedUrl}};
                if (feedTitle) payload.title = feedTitle;
                setBtnLoading(btn, true, 'Menambahkan…');
                try {{
                    const res = await fetch('/api/v1/feeds', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(payload)
                    }});
                    const data = await res.json();
                    if (res.ok) {{
                        showToast('Feed RSS berhasil ditambahkan.');
                        setTimeout(() => window.location.reload(), 800);
                    }} else {{
                        showToast('Gagal: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            async function fetchFeed(feedId, btn) {{
                setBtnLoading(btn, true, 'Mengambil…');
                try {{
                    const res = await fetch(`/api/v1/feeds/${{feedId}}/fetch`, {{ method: 'POST' }});
                    const data = await res.json();
                    if (res.ok) {{
                        showToast(`Feed diambil: ${{data.added}} bahan baru, ${{data.skipped}} dilewati (sudah ada).`);
                        setTimeout(() => window.location.reload(), 1000);
                    }} else {{
                        showToast('Gagal mengambil feed: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            async function deleteFeed(feedId, btn) {{
                const ok = await askConfirm('Hapus feed?', 'Feed ini akan dihapus dari daftar. Bahan yang sudah diambil tidak ikut terhapus.');
                if (!ok) return;
                setBtnLoading(btn, true, 'Menghapus…');
                try {{
                    const res = await fetch(`/api/v1/feeds/${{feedId}}`, {{ method: 'DELETE' }});
                    if (res.ok) {{
                        showToast('Feed berhasil dihapus.');
                        setTimeout(() => window.location.reload(), 800);
                    }} else {{
                        showToast('Gagal menghapus feed.', 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // Isi form Tulis Artikel dengan bahan dari antrean, lalu pindah ke
            // section Artikel. Bahan TIDAK diterbitkan otomatis — tulis ulang
            // dulu dengan bahasa sendiri sebelum disimpan/diterbitkan.
            async function useSourceAsDraft(sourceId, btn) {{
                setBtnLoading(btn, true, 'Memuat…');
                try {{
                    const res = await fetch(`/api/v1/ingest/${{sourceId}}`);
                    const data = await res.json();
                    if (!res.ok) {{
                        showToast('Gagal memuat bahan: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                        return;
                    }}
                    document.getElementById('articleTitle').value = data.title || '';
                    document.getElementById('articleContent').value = data.raw_content || '';
                    showToast('Bahan dimasukkan ke form Tulis Artikel — tulis ulang dengan bahasamu sendiri sebelum diterbitkan.');
                    showSection('artikel');
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // Simpan kunci API AI (Gemini / Pexels). Hanya kolom yang
            // diisi yang dikirim; kolom kosong berarti tidak diubah.
            async function saveAiSettings(btn) {{
                const gemini = document.getElementById('geminiKeyInput').value.trim();
                const pexels = document.getElementById('pexelsKeyInput').value.trim();
                if (!gemini && !pexels) {{
                    showToast('Tidak ada kunci yang diisi — kosongkan bila tidak ingin mengubah.', 'error');
                    return;
                }}
                const payload = {{}};
                if (gemini) payload.gemini_api_key = gemini;
                if (pexels) payload.pexels_api_key = pexels;
                setBtnLoading(btn, true, 'Menyimpan…');
                try {{
                    const res = await fetch('/api/v1/settings/ai', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(payload)
                    }});
                    const data = await res.json();
                    if (res.ok) {{
                        showToast('Pengaturan AI tersimpan.');
                        setTimeout(() => window.location.reload(), 800);
                    }} else {{
                        showToast('Gagal: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // Tulis ulang bahan dari antrean memakai Gemini, simpan sebagai
            // draf (tidak pernah langsung terbit). Prosesnya bisa 1-2 menit.
            async function rewriteSourceAsDraft(sourceId, btn) {{
                const channelId = document.getElementById('rewriteChannel').value;
                const mode = document.getElementById('rewriteMode').value || 'sedang';
                if (!channelId) {{
                    showToast('Pilih dulu blog untuk rewrite.', 'error');
                    return;
                }}
                setBtnLoading(btn, true, 'Merewrite…');
                try {{
                    const res = await fetch('/api/v1/rewrite', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{channel_id: channelId, source_id: sourceId, mode: mode}})
                    }});
                    const data = await res.json();
                    if (res.ok) {{
                        let msg = 'Rewrite selesai: draf "' + data.title + '" (' + data.word_count + ' kata) tersimpan.';
                        if (data.similarity_warning) msg += ' Peringatan: hasil terlalu mirip sumber (' + Math.round(data.similarity * 100) + '%).';
                        if (data.blogger_draft_error) msg += ' Draf Blogger gagal dibuat: ' + data.blogger_draft_error;
                        showToast(msg);
                        setTimeout(() => window.location.reload(), 1200);
                    }} else {{
                        showToast('Gagal rewrite: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // --- Navigasi sidebar (tampilkan satu section saja) ---
            const SECTION_TITLES = {{dashboard: 'Dashboard', channel: 'Channel', artikel: 'Artikel', halaman: 'Halaman', riwayat: 'Riwayat', ingest: 'Ingest', komentar: 'Komentar', apikey: 'API Key', 'pengaturan-ai': 'Pengaturan AI', penjadwal: 'Penjadwal', 'search-console': 'Search Console', 'ide-topik': 'Ide Topik'}};
            function showSection(name) {{
                document.querySelectorAll('.nav-section').forEach((s) => s.classList.add('hidden'));
                const target = document.getElementById('section-' + name);
                if (target) target.classList.remove('hidden');
                document.querySelectorAll('#sidebarNav .nav-item').forEach((b) => {{
                    const active = b.dataset.section === name;
                    b.className = 'nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 ' + (active ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : 'text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent');
                }});
                const title = document.getElementById('topbarTitle');
                if (title) title.innerText = SECTION_TITLES[name] || 'Dashboard';
                try {{ localStorage.setItem('bk_section', name); }} catch (e) {{}}
                if (name === 'penjadwal') {{ loadSchedulerStatus(); }}
                if (name === 'search-console') {{ loadScChannels(); }}
                if (name === 'ide-topik') {{ loadTopicChannels(); }}
                toggleSidebar(false);
                window.scrollTo(0, 0);
            }}
            function toggleSidebar(open) {{
                const sb = document.getElementById('sidebar');
                const bd = document.getElementById('sidebarBackdrop');
                if (!sb) return;
                if (open) {{
                    sb.classList.remove('-translate-x-full');
                    if (bd) bd.classList.remove('hidden');
                }} else {{
                    if (window.innerWidth < 1024) sb.classList.add('-translate-x-full');
                    if (bd) bd.classList.add('hidden');
                }}
            }}

            // --- Pengaturan artikel per channel ---
            function openChannelSettings(btn) {{
                document.getElementById('settingsChannelId').value = btn.dataset.id || '';
                document.getElementById('settingsChannelName').innerText = btn.dataset.name || btn.dataset.id || '';
                document.getElementById('settingsNiche').value = btn.dataset.niche || '';
                document.getElementById('settingsTone').value = btn.dataset.tone || '';
                document.getElementById('settingsWords').value = btn.dataset.words || '';
                document.getElementById('settingsLabels').value = btn.dataset.labels || '';
                document.getElementById('channelSettingsModal').classList.remove('hidden');
            }}
            async function handleSaveChannelSettings(e) {{
                e.preventDefault();
                const channelId = document.getElementById('settingsChannelId').value;
                const payload = {{}};
                const niche = document.getElementById('settingsNiche').value.trim();
                if (niche) payload.niche = niche;
                const tone = document.getElementById('settingsTone').value.trim();
                if (tone) payload.tone_of_voice = tone;
                const words = parseInt(document.getElementById('settingsWords').value, 10);
                if (!isNaN(words)) payload.target_word_count = words;
                const labels = document.getElementById('settingsLabels').value.trim();
                if (labels) payload.default_labels = labels;
                const btn = document.getElementById('saveChannelSettingsBtn');
                setBtnLoading(btn, true, 'Menyimpan…');
                try {{
                    const res = await fetch(`/api/v1/channels/${{encodeURIComponent(channelId)}}`, {{
                        method: 'PATCH',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(payload)
                    }});
                    const data = await res.json();
                    if (res.ok) {{
                        showToast('Pengaturan artikel berhasil disimpan.');
                        setTimeout(() => window.location.reload(), 800);
                    }} else {{
                        showToast('Gagal: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // --- Cek SEO (tanpa reload, pakai target kata channel terpilih) ---
            async function checkSeo(btn) {{
                const title = document.getElementById('articleTitle').value.trim();
                const meta = document.getElementById('articleMeta').value.trim();
                let content = document.getElementById('articleContent').value.trim();
                if (!title && !content) {{
                    showToast('Isi dulu judul atau konten artikelnya untuk dicek.', 'error');
                    return;
                }}
                // Gambar sampul ikut dihitung seperti saat publish (disisipkan di awal konten).
                const imgUrl = document.getElementById('articleImageUrl').value.trim();
                if (imgUrl) {{
                    const imgAlt = document.getElementById('articleImageAlt').value.trim();
                    content = '<img src="' + imgUrl.replace(/"/g, '&quot;') + '" alt="' + imgAlt.replace(/"/g, '&quot;') + '">' + content;
                }}
                const sel = document.getElementById('articleChannel');
                const opt = sel.options[sel.selectedIndex];
                const words = parseInt(opt ? opt.dataset.words : '', 10);
                const payload = {{title: title, meta_description: meta, content_html: content, target_word_count: isNaN(words) ? 800 : words}};
                const box = document.getElementById('seoCheckResult');
                setBtnLoading(btn, true, 'Mengecek…');
                try {{
                    const res = await fetch('/api/v1/seo-check', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(payload)
                    }});
                    const data = await res.json();
                    if (!res.ok) {{
                        showToast('Gagal cek SEO: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                        return;
                    }}
                    const rows = (data.checks || []).map((c) => {{
                        const icon = c.passed ? '✅' : '❌';
                        const cls = c.passed ? 'text-emerald-400' : 'text-red-400';
                        return '<li class="flex gap-2 text-xs ' + cls + '"><span>' + icon + '</span><span><span class="font-semibold text-slate-200">' + c.label + '</span> <span class="text-slate-400">— ' + c.detail + '</span></span></li>';
                    }}).join('');
                    const scoreCls = data.score >= 80 ? 'text-emerald-400' : (data.score >= 50 ? 'text-amber-400' : 'text-red-400');
                    box.innerHTML = '<div class="bg-slate-800 border border-slate-700 rounded-xl p-4"><div class="text-sm font-bold text-white mb-2">Skor SEO: <span class="' + scoreCls + '">' + data.score + '/100</span></div><ul class="space-y-1.5">' + rows + '</ul></div>';
                    box.classList.remove('hidden');
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            function escapeHtml(s) {{
                return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
            }}

            // Tampilkan saran SEO otomatis untuk draf yang dipilih (tanpa mengubah apa pun).
            async function loadSeoSuggestions(btn) {{
                const pubId = document.getElementById('seoDraftSelect').value;
                if (!pubId) {{
                    showToast('Belum ada draf yang bisa dioptimasi.', 'error');
                    return;
                }}
                setBtnLoading(btn, true, 'Memuat…');
                try {{
                    const res = await fetch('/api/v1/seo-optimize', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{publication_id: parseInt(pubId, 10)}})
                    }});
                    const data = await res.json();
                    if (!res.ok) {{
                        showToast('Gagal: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                        return;
                    }}
                    const box = document.getElementById('seoOptimizeResult');
                    let linksHtml = '';
                    if (data.internal_links && data.internal_links.length) {{
                        linksHtml = data.internal_links.map((l) => '<label class="flex items-start gap-2 text-xs text-slate-300 py-1"><input type="checkbox" class="seo-link-check mt-0.5" value="' + l.publication_id + '" checked> <span><a href="' + l.url + '" target="_blank" class="text-emerald-400 hover:underline">' + escapeHtml(l.anchor) + '</a> <span class="text-slate-500">(' + l.score + ' kata kunci cocok: ' + escapeHtml((l.matched_keywords || []).join(', ')) + ')</span></span></label>').join('');
                    }} else {{
                        linksHtml = '<p class="text-xs text-slate-500">Tidak ada kandidat tautan internal (butuh artikel published lain di blog yang sama dengan kata kunci yang sama).</p>';
                    }}
                    let altsHtml = '';
                    if (data.alt_suggestions && data.alt_suggestions.length) {{
                        altsHtml = '<ul class="list-disc pl-5">' + data.alt_suggestions.map((a) => '<li class="text-xs text-slate-300 py-1">Gambar: <span class="font-mono text-slate-400">' + escapeHtml(a.src) + '</span><br>Saran alt: <span class="text-emerald-400">' + escapeHtml(a.suggested_alt) + '</span></li>').join('') + '</ul>';
                    }} else {{
                        altsHtml = '<p class="text-xs text-slate-500">Semua gambar sudah punya alt text.</p>';
                    }}
                    const r = data.readability || {{}};
                    box.innerHTML = '<div class="bg-slate-800 border border-slate-700 rounded-xl p-4 space-y-3">'
                        + '<div><div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Meta description saran (' + (data.meta_description || '').length + ' karakter)</div><p class="text-xs text-slate-200">' + escapeHtml(data.meta_description || '(tidak bisa dibuat — isi terlalu pendek)') + '</p><label class="flex items-center gap-2 text-xs text-slate-300 mt-1"><input type="checkbox" id="seoApplyMeta" checked> Terapkan meta description</label></div>'
                        + '<div><div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Slug saran</div><p class="text-xs text-slate-200 font-mono">' + escapeHtml(data.slug || '-') + '</p><label class="flex items-center gap-2 text-xs text-slate-300 mt-1"><input type="checkbox" id="seoApplySlug" checked> Terapkan slug</label></div>'
                        + '<div><div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Keterbacaan: ' + escapeHtml(r.label || '-') + ' (' + (r.score == null ? '-' : r.score) + '/100)</div><p class="text-xs text-slate-400">Rata-rata ' + (r.avg_sentence_words == null ? '-' : r.avg_sentence_words) + ' kata/kalimat · ' + (r.avg_paragraph_words == null ? '-' : r.avg_paragraph_words) + ' kata/paragraf · ' + (r.sentence_count == null ? '-' : r.sentence_count) + ' kalimat</p></div>'
                        + '<div><div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Tautan internal (pilih yang mau disisipkan sebagai "Baca juga")</div>' + linksHtml + '</div>'
                        + '<div><div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Alt text gambar</div>' + altsHtml + '<label class="flex items-center gap-2 text-xs text-slate-300 mt-1"><input type="checkbox" id="seoApplyAlts" checked> Terapkan saran alt text</label></div>'
                        + '<div class="flex flex-wrap gap-2"><button type="button" onclick="applySeo(this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">Terapkan SEO</button></div>'
                        + '</div>';
                    box.classList.remove('hidden');
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // Terapkan saran SEO yang dipilih pada draf (hanya saat diklik).
            async function applySeo(btn) {{
                const pubId = document.getElementById('seoDraftSelect').value;
                if (!pubId) {{
                    showToast('Belum ada draf yang dipilih.', 'error');
                    return;
                }}
                const linkIds = Array.from(document.querySelectorAll('.seo-link-check:checked')).map((c) => parseInt(c.value, 10));
                const applyMeta = document.getElementById('seoApplyMeta') ? document.getElementById('seoApplyMeta').checked : true;
                const applySlug = document.getElementById('seoApplySlug') ? document.getElementById('seoApplySlug').checked : true;
                const applyAlts = document.getElementById('seoApplyAlts') ? document.getElementById('seoApplyAlts').checked : true;
                setBtnLoading(btn, true, 'Menerapkan…');
                try {{
                    const res = await fetch('/api/v1/seo-optimize/' + pubId + '/apply', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{link_ids: linkIds, apply_meta: applyMeta, apply_slug: applySlug, apply_alts: applyAlts}})
                    }});
                    const data = await res.json();
                    if (res.ok) {{
                        let msg = 'SEO diterapkan: ' + data.links_inserted + ' tautan disisipkan, ' + data.alts_fixed + ' alt diperbaiki.';
                        if (data.blogger_error) msg += ' Catatan: ' + data.blogger_error;
                        showToast(msg);
                        setTimeout(() => window.location.reload(), 1000);
                    }} else {{
                        showToast('Gagal menerapkan SEO: ' + (data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // --- Tulis Artikel (pakai endpoint publish yang sudah ada) ---
            async function handleWriteArticle(status, btn) {{
                const channelId = document.getElementById('articleChannel').value;
                const title = document.getElementById('articleTitle').value.trim();
                const content = document.getElementById('articleContent').value.trim();
                if (!channelId || !title || !content) {{
                    showToast('Isi dulu blog, judul, dan konten artikelnya.', 'error');
                    return;
                }}
                const slug = document.getElementById('articleSlug').value.trim();
                const meta = document.getElementById('articleMeta').value.trim();
                const labels = document.getElementById('articleLabels').value.split(',').map((s) => s.trim()).filter(Boolean);
                const item = {{channel_id: channelId, title: title, content_html: content, status: status, labels: labels}};
                if (slug) item.slug = slug;
                if (meta) item.meta_description = meta;
                const sched = document.getElementById('articleScheduledAt').value.trim();
                if (sched) item.scheduled_at = sched;
                const imgUrl = document.getElementById('articleImageUrl').value.trim();
                if (imgUrl) {{
                    item.cover_image_url = imgUrl;
                    const imgAlt = document.getElementById('articleImageAlt').value.trim();
                    if (imgAlt) item.cover_image_alt = imgAlt;
                }}
                setBtnLoading(btn, true, status === 'publish' ? 'Menerbitkan…' : 'Menyimpan…');
                try {{
                    const res = await fetch('/api/v1/publish', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{publications: [item]}})
                    }});
                    const data = await res.json();
                    const result = (data.results || [])[0];
                    if (res.ok && result && (result.status === 'draft' || result.status === 'published' || result.status === 'scheduled')) {{
                        const msg = result.status === 'scheduled'
                            ? 'Artikel berhasil dijadwalkan — Blogger menerbitkannya otomatis.'
                            : (status === 'publish' ? 'Artikel berhasil diterbitkan.' + (result.remote_url ? ' ' + result.remote_url : '') : 'Artikel berhasil disimpan sebagai draf.');
                        showToast(msg);
                        setTimeout(() => window.location.reload(), 1000);
                    }} else {{
                        showToast('Gagal: ' + ((result && result.error_message) || data.detail || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // --- Image Picker (Openverse utama, Pexels bila ada kunci) ---
            async function searchImages(target, btn) {{
                const qInput = document.getElementById(target === 'edit' ? 'editImageSearchQuery' : 'imageSearchQuery');
                const query = qInput.value.trim();
                if (!query) {{ showToast('Isi dulu kata kunci foto yang dicari.', 'error'); return; }}
                const box = document.getElementById('imageSearchResults-' + target);
                const info = document.getElementById('imageSearchInfo-' + target);
                setBtnLoading(btn, true, 'Mencari…');
                try {{
                    const res = await fetch('/api/v1/images/search?q=' + encodeURIComponent(query) + '&per_page=8');
                    const data = await res.json();
                    if (!res.ok) {{ showToast('Gagal mencari foto: ' + (data.detail || 'Terjadi kesalahan'), 'error'); return; }}
                    if (!data.results || !data.results.length) {{
                        box.innerHTML = '';
                        info.innerText = 'Tidak ada foto yang cocok — coba kata kunci lain.';
                        return;
                    }}
                    box.innerHTML = data.results.map((r) => '<button type="button" onclick="pickImage(\\'' + target + '\\', this)" data-url="' + escapeHtml(r.url || '') + '" data-alt="' + escapeHtml(r.suggested_alt || '') + '" data-attribution="' + escapeHtml(r.attribution || '') + '" class="block text-left border border-slate-700 rounded-xl overflow-hidden hover:border-emerald-500 transition"><img src="' + escapeHtml(r.thumbnail_url || r.url || '') + '" alt="' + escapeHtml(r.suggested_alt || '') + '" class="w-full h-20 object-cover"><span class="block px-2 py-1 text-[10px] text-slate-400 truncate">' + escapeHtml(r.photographer || r.source || '') + ' · ' + escapeHtml(r.license || '') + '</span></button>').join('');
                    let note = 'Sumber: ' + (data.sources || []).join(', ') + '. ';
                    if (data.pexels_error) note += 'Pexels: ' + data.pexels_error + ' ';
                    if (data.openverse_error) note += 'Openverse: ' + data.openverse_error;
                    info.innerText = note;
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            function pickImage(target, btn) {{
                const url = btn.dataset.url || '';
                const alt = btn.dataset.alt || '';
                const attribution = btn.dataset.attribution || '';
                if (target === 'edit') {{
                    document.getElementById('editPubImageUrl').value = url;
                    document.getElementById('editPubImageAlt').value = alt;
                }} else {{
                    document.getElementById('articleImageUrl').value = url;
                    document.getElementById('articleImageAlt').value = alt;
                }}
                const info = document.getElementById('imageSearchInfo-' + target);
                if (info && attribution) info.innerText = 'Atribusi (wajib dicantumkan bila lisensi CC mengharuskan): ' + attribution;
                showToast('Foto dipilih sebagai sampul — URL dan alt text sudah terisi.');
            }}

            // --- Penjadwal (auto-publish) ---
            async function loadSchedulerStatus() {{
                const statusBox = document.getElementById('schedulerStatus');
                const dueBox = document.getElementById('schedulerDue');
                const chBox = document.getElementById('schedulerChannels');
                try {{
                    const res = await fetch('/api/v1/scheduler/status');
                    const data = await res.json();
                    if (!res.ok) {{ statusBox.innerText = 'Gagal memuat status: ' + (data.detail || 'Terjadi kesalahan'); return; }}
                    const last = data.last_result;
                    let html = '<div class="grid grid-cols-2 sm:grid-cols-4 gap-3">';
                    html += '<div class="bg-slate-800 rounded-xl p-3"><div class="text-[11px] uppercase tracking-wider text-slate-400">Tick terakhir</div><div class="font-bold text-white text-xs mt-1">' + escapeHtml(data.last_tick ? data.last_tick.replace('T', ' ').slice(0, 19) : 'belum pernah') + '</div></div>';
                    html += '<div class="bg-slate-800 rounded-xl p-3"><div class="text-[11px] uppercase tracking-wider text-slate-400">Jatuh tempo</div><div class="font-bold text-white">' + (data.due_count || 0) + '</div></div>';
                    html += '<div class="bg-slate-800 rounded-xl p-3"><div class="text-[11px] uppercase tracking-wider text-slate-400">Terbit tick lalu</div><div class="font-bold text-white">' + (last ? ((last.published || 0) + (last.already_live || 0)) : '-') + '</div></div>';
                    html += '<div class="bg-slate-800 rounded-xl p-3"><div class="text-[11px] uppercase tracking-wider text-slate-400">Gagal tick lalu</div><div class="font-bold text-white">' + (last ? (last.failed || 0) : '-') + '</div></div></div>';
                    if (!data.cron_configured) html += '<p class="mt-3 text-amber-400 text-xs">⚠️ CRON_SECRET belum diatur di Vercel — cron harian Vercel tidak akan berjalan. Tick tiap jam lewat GitHub Actions dan tick manual dari tombol di atas tetap bisa dipakai.</p>';
                    statusBox.innerHTML = html;
                    if (data.due && data.due.length) {{
                        dueBox.innerHTML = '<h4 class="text-sm font-bold text-white mb-2">Antrean jatuh tempo</h4>' + data.due.map((d) => '<div class="flex flex-wrap items-center justify-between gap-2 bg-slate-800 rounded-xl px-3 py-2 mb-2 text-xs"><span class="text-slate-200">' + escapeHtml(d.title || '') + '</span><span class="text-slate-400">' + escapeHtml(d.scheduled_at ? d.scheduled_at.replace('T', ' ').slice(0, 16) : '') + ' · ' + (d.auto_publish ? 'auto-publish aktif' : 'auto-publish mati') + '</span></div>').join('');
                    }} else {{
                        dueBox.innerHTML = '<p class="text-xs text-slate-500">Tidak ada publikasi terjadwal yang jatuh tempo.</p>';
                    }}
                    const chRes = await fetch('/api/v1/channels');
                    const channels = await chRes.json();
                    if (!chRes.ok || !Array.isArray(channels)) {{ chBox.innerText = 'Gagal memuat channel.'; return; }}
                    chBox.innerHTML = channels.map((c) => '<label class="flex items-center justify-between gap-3 bg-slate-800 rounded-xl px-3 py-2.5 cursor-pointer"><span><span class="text-slate-100 font-semibold">' + escapeHtml(c.name || c.id) + '</span> <span class="text-slate-500 text-xs">(' + escapeHtml(c.id || '') + ')</span></span><input type="checkbox" data-id="' + escapeHtml(c.id || '') + '" ' + (c.auto_publish ? 'checked' : '') + ' onchange="toggleAutoPublish(this)" class="w-5 h-5 accent-emerald-500"></label>').join('');
                }} catch (err) {{
                    statusBox.innerText = 'Error: ' + err;
                }}
            }}

            async function runTickNow(btn) {{
                setBtnLoading(btn, true, 'Menjalankan…');
                try {{
                    const res = await fetch('/api/v1/scheduler/tick', {{method: 'POST'}});
                    const data = await res.json();
                    if (!res.ok) {{ showToast('Tick gagal: ' + (data.detail || 'Terjadi kesalahan'), 'error'); return; }}
                    showToast('Tick selesai: ' + (data.published || 0) + ' diterbitkan, ' + (data.already_live || 0) + ' sudah live, ' + (data.skipped || 0) + ' dilewati, ' + (data.failed || 0) + ' gagal.');
                    loadSchedulerStatus();
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            async function toggleAutoPublish(checkbox) {{
                const channelId = checkbox.dataset.id || '';
                try {{
                    const res = await fetch('/api/v1/channels/' + encodeURIComponent(channelId), {{method: 'PATCH', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{auto_publish: checkbox.checked}})}});
                    const data = await res.json();
                    if (!res.ok) {{ checkbox.checked = !checkbox.checked; showToast('Gagal mengubah toggle: ' + (data.detail || 'Terjadi kesalahan'), 'error'); return; }}
                    showToast('Auto-publish ' + (checkbox.checked ? 'diaktifkan' : 'dimatikan') + ' untuk ' + (data.name || channelId) + '.');
                    loadSchedulerStatus();
                }} catch (err) {{
                    checkbox.checked = !checkbox.checked;
                    showToast('Error: ' + err, 'error');
                }}
            }}

            // --- Search Console ---
            async function loadScChannels() {{
                const sel = document.getElementById('scChannelSelect');
                if (sel.options.length) return;
                try {{
                    const res = await fetch('/api/v1/channels');
                    const channels = await res.json();
                    if (!res.ok || !Array.isArray(channels)) return;
                    sel.innerHTML = channels.map((c) => '<option value="' + escapeHtml(c.id || '') + '">' + escapeHtml(c.name || c.id) + '</option>').join('');
                }} catch (err) {{}}
            }}

            async function loadSearchConsole(btn) {{
                const box = document.getElementById('scContent');
                const channelId = document.getElementById('scChannelSelect').value;
                if (!channelId) {{ showToast('Pilih blog dulu.', 'error'); return; }}
                if (btn) setBtnLoading(btn, true, 'Memuat…');
                try {{
                    const res = await fetch('/api/v1/search-console/overview?channel_id=' + encodeURIComponent(channelId));
                    const data = await res.json();
                    if (!res.ok) {{
                        let html = '<div class="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-xs text-amber-200">' + escapeHtml(data.detail || 'Terjadi kesalahan') + '</div>';
                        if (res.status === 403) html += '<div class="mt-3"><a href="/oauth/blogger" class="inline-block bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition">🔗 Hubungkan Ulang OAuth</a><p class="text-[11px] text-slate-500 mt-2">Di halaman OAuth, login dengan akun Google yang sama lalu salin refresh token baru ke form channel. Pastikan juga API Google Search Console sudah diaktifkan di Google Cloud.</p></div>';
                        box.innerHTML = html;
                        return;
                    }}
                    const t = data.totals || {{}};
                    let html = '<p class="text-xs text-slate-400 mb-3">Properti: <span class="text-emerald-400 font-mono">' + escapeHtml(data.site_url || '') + '</span> · ' + escapeHtml((data.date_range || {{}}).start || '') + ' s/d ' + escapeHtml((data.date_range || {{}}).end || '') + '</p>';
                    html += '<div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">';
                    html += '<div class="bg-slate-800 rounded-xl p-3"><div class="text-[11px] uppercase tracking-wider text-slate-400">Klik</div><div class="font-bold text-white text-lg">' + Math.round(t.clicks || 0) + '</div></div>';
                    html += '<div class="bg-slate-800 rounded-xl p-3"><div class="text-[11px] uppercase tracking-wider text-slate-400">Impresi</div><div class="font-bold text-white text-lg">' + Math.round(t.impressions || 0) + '</div></div>';
                    html += '<div class="bg-slate-800 rounded-xl p-3"><div class="text-[11px] uppercase tracking-wider text-slate-400">CTR rata-rata</div><div class="font-bold text-white text-lg">' + ((t.avg_ctr || 0) * 100).toFixed(2) + '%</div></div>';
                    html += '<div class="bg-slate-800 rounded-xl p-3"><div class="text-[11px] uppercase tracking-wider text-slate-400">Posisi rata-rata</div><div class="font-bold text-white text-lg">' + (t.avg_position || 0).toFixed(1) + '</div></div></div>';
                    if (data.top_queries && data.top_queries.length) {{
                        html += '<h4 class="text-sm font-bold text-white mb-2">Kueri teratas</h4><div class="overflow-x-auto mb-4"><table class="w-full text-left border-collapse text-xs"><thead><tr class="border-b border-slate-800 uppercase tracking-wider text-slate-400"><th class="py-2 px-2">Kueri</th><th class="py-2 px-2">Klik</th><th class="py-2 px-2">Impresi</th><th class="py-2 px-2">CTR</th><th class="py-2 px-2">Posisi</th></tr></thead><tbody>';
                        html += data.top_queries.map((q) => '<tr class="border-b border-slate-800/60"><td class="py-2 px-2 text-slate-100">' + escapeHtml(q.query || '') + '</td><td class="py-2 px-2">' + Math.round(q.clicks || 0) + '</td><td class="py-2 px-2">' + Math.round(q.impressions || 0) + '</td><td class="py-2 px-2">' + ((q.ctr || 0) * 100).toFixed(2) + '%</td><td class="py-2 px-2">' + (q.position || 0).toFixed(1) + '</td></tr>').join('');
                        html += '</tbody></table></div>';
                    }} else {{
                        html += '<p class="text-xs text-slate-500 mb-4">Belum ada data kueri pada periode ini (blog baru / belum terindeks — data Search Console tertinggal 2–3 hari).</p>';
                    }}
                    if (data.sitemaps && data.sitemaps.length) {{
                        html += '<h4 class="text-sm font-bold text-white mb-2">Sitemap</h4>' + data.sitemaps.map((s) => '<div class="bg-slate-800 rounded-xl px-3 py-2 mb-2 text-xs"><span class="text-slate-100 font-mono">' + escapeHtml(s.path || '') + '</span><span class="text-slate-400"> · ' + (s.isPending ? 'menunggu diproses' : 'diproses') + ' · warning ' + (s.warnings || 0) + ' · error ' + (s.errors || 0) + '</span></div>').join('');
                    }} else {{
                        html += '<p class="text-xs text-slate-500">Belum ada sitemap yang disubmit ke Search Console untuk properti ini.</p>';
                    }}
                    box.innerHTML = html;
                }} catch (err) {{
                    box.innerText = 'Error: ' + err;
                }} finally {{
                    if (btn) setBtnLoading(btn, false);
                }}
            }}

            // --- Ide Topik ---
            let topicIdeas = [];
            async function loadTopicChannels() {{
                const sel = document.getElementById('topicChannelSelect');
                if (sel.options.length) return;
                try {{
                    const res = await fetch('/api/v1/channels');
                    const channels = await res.json();
                    if (!res.ok || !Array.isArray(channels)) return;
                    sel.innerHTML = channels.map((c) => '<option value="' + escapeHtml(c.id || '') + '">' + escapeHtml(c.name || c.id) + '</option>').join('');
                }} catch (err) {{}}
            }}

            async function loadTopicIdeas(btn) {{
                const box = document.getElementById('topicIdeas');
                const channelId = document.getElementById('topicChannelSelect').value;
                if (!channelId) {{ showToast('Pilih blog dulu.', 'error'); return; }}
                if (btn) setBtnLoading(btn, true, 'Memuat…');
                try {{
                    const res = await fetch('/api/v1/topics/ideas?channel_id=' + encodeURIComponent(channelId));
                    const data = await res.json();
                    if (!res.ok) {{ box.innerHTML = '<div class="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-xs text-amber-200">' + escapeHtml(data.detail || 'Terjadi kesalahan') + '</div>'; return; }}
                    topicIdeas = data.ideas || [];
                    let html = '<p class="text-xs text-slate-400 mb-3">' + (data.ai_used ? '🤖 Judul dibuat Gemini AI' : '🔑 Judul berbasis kata kunci (tanpa AI)') + ' · ' + (data.headline_count || 0) + ' headline dipakai · niche: ' + escapeHtml(data.niche || '') + '</p>';
                    if (data.ai_error) html += '<p class="text-[11px] text-amber-400 mb-3">AI gagal (' + escapeHtml(data.ai_error) + ') — dipakai fallback kata kunci.</p>';
                    if (!topicIdeas.length) {{ box.innerHTML = html + '<p class="text-xs text-slate-500">Belum ada ide — tambahkan feed RSS di seksi Ingest dulu.</p>'; return; }}
                    html += topicIdeas.map((idea, i) => '<div class="bg-slate-800 rounded-xl p-3 mb-2"><div class="flex flex-wrap items-start justify-between gap-2"><div class="flex-1 min-w-[200px]"><p class="text-sm font-semibold text-slate-100">' + escapeHtml(idea.title || '') + '</p><p class="text-xs text-slate-400 mt-1">' + escapeHtml(idea.angle || '') + '</p><p class="text-[11px] text-slate-500 mt-1">' + (idea.keywords || []).map((k) => '#' + escapeHtml(k)).join(' ') + (idea.source_title ? ' · sumber: ' + escapeHtml(idea.source_title) : '') + '</p></div><button type="button" onclick="createTopicDraft(' + i + ', this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-3 py-1.5 rounded-xl text-xs transition whitespace-nowrap">✏️ Buat Draf</button></div></div>').join('');
                    box.innerHTML = html;
                }} catch (err) {{
                    box.innerText = 'Error: ' + err;
                }} finally {{
                    if (btn) setBtnLoading(btn, false);
                }}
            }}

            async function createTopicDraft(index, btn) {{
                const idea = topicIdeas[index];
                if (!idea) return;
                const channelId = document.getElementById('topicChannelSelect').value;
                setBtnLoading(btn, true, 'Membuat…');
                try {{
                    const res = await fetch('/api/v1/topics/draft', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{channel_id: channelId, title: idea.title, angle: idea.angle, keywords: idea.keywords, source_id: idea.source_id, source_url: idea.source_url, source_title: idea.source_title}})}});
                    const data = await res.json();
                    if (!res.ok) {{ showToast('Gagal membuat draf: ' + (data.detail || 'Terjadi kesalahan'), 'error'); return; }}
                    showToast('Draf kerangka dibuat: ' + (data.title || '') + ' (id ' + data.publication_id + '). Lengkapi di seksi Artikel.');
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // --- Edit Artikel (draf maupun published) ---
            // Pisahkan <img> gambar sampul di awal konten ke field gambar,
            // supaya textarea hanya berisi isi artikel.
            function fillEditContent(content) {{
                let body = content || '';
                const m = body.match(/^\\s*<img\\b[^>]*>/i);
                if (m) {{
                    const tag = m[0];
                    const src = tag.match(/src\\s*=\\s*["']([^"']*)["']/i);
                    const alt = tag.match(/alt\\s*=\\s*["']([^"']*)["']/i);
                    if (src) document.getElementById('editPubImageUrl').value = src[1];
                    if (alt) document.getElementById('editPubImageAlt').value = alt[1];
                    body = body.slice(m[0].length).replace(/^\\s+/, '');
                }}
                document.getElementById('editPubContent').value = body;
            }}
            function openEditPublication(btn) {{
                const pubId = btn.dataset.id;
                const title = btn.dataset.title || '';
                const content = btn.dataset.content || '';
                document.getElementById('editPubId').value = pubId;
                document.getElementById('editPubTitle').value = title;
                document.getElementById('editPubImageUrl').value = '';
                document.getElementById('editPubImageAlt').value = '';
                document.getElementById('editPubNote').classList.add('hidden');
                fillEditContent(content);
                document.getElementById('editPubModal').classList.remove('hidden');
                if (!content) {{
                    // Konten tidak tersedia di halaman — ambil dari API.
                    fetch(`/api/v1/publish/${{pubId}}`)
                        .then((r) => (r.ok ? r.json() : null))
                        .then((data) => {{
                            if (data && data.content_html) {{
                                fillEditContent(data.content_html);
                            }} else {{
                                document.getElementById('editPubNote').classList.remove('hidden');
                            }}
                        }})
                        .catch(() => {{
                            document.getElementById('editPubNote').classList.remove('hidden');
                        }});
                }}
            }}
            async function handleSaveEditPublication(e) {{
                e.preventDefault();
                const pubId = document.getElementById('editPubId').value;
                const title = document.getElementById('editPubTitle').value.trim();
                const content = document.getElementById('editPubContent').value.trim();
                if (!title && !content) {{
                    showToast('Isi minimal judul atau konten baru.', 'error');
                    return;
                }}
                const payload = {{}};
                if (title) payload.title = title;
                if (content) payload.content_html = content;
                const imgUrl = document.getElementById('editPubImageUrl').value.trim();
                if (imgUrl) {{
                    payload.cover_image_url = imgUrl;
                    payload.cover_image_alt = document.getElementById('editPubImageAlt').value.trim();
                }}
                const btn = document.getElementById('saveEditPubBtn');
                setBtnLoading(btn, true, 'Menyimpan…');
                try {{
                    const res = await fetch(`/api/v1/publish/${{pubId}}`, {{
                        method: 'PUT',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(payload)
                    }});
                    const data = await res.json();
                    if (res.ok && data && data.status !== 'failed') {{
                        showToast('Artikel berhasil diperbarui.');
                        document.getElementById('editPubModal').classList.add('hidden');
                        setTimeout(() => window.location.reload(), 800);
                    }} else {{
                        showToast('Gagal menyimpan: ' + ((data && (data.error_message || data.detail)) || 'Terjadi kesalahan'), 'error');
                    }}
                }} catch (err) {{
                    showToast('Error: ' + err, 'error');
                }} finally {{
                    setBtnLoading(btn, false);
                }}
            }}

            // Sembunyikan tombol "Muat lebih banyak" kalau tidak ada baris tersembunyi.
            updateLoadMoreBtn();
            // Buka section terakhir yang dipilih (default: dashboard).
            (function () {{
                let saved = 'dashboard';
                try {{ saved = localStorage.getItem('bk_section') || 'dashboard'; }} catch (e) {{}}
                if (!document.getElementById('section-' + saved)) saved = 'dashboard';
                showSection(saved);
            }})();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
