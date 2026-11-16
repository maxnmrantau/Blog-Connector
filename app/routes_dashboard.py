import datetime
from html import escape as html_escape
import os
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Channel, Publication, ApiKey
from app.services.platforms.blogger import BloggerPlatform
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
    # Hitung dari database, bukan dari daftar yang dibatasi 50 baris,
    # supaya angka di kartu statistik selalu benar.
    total_published = db.query(Publication).filter(Publication.status == "published").count()
    total_drafts = db.query(Publication).filter(Publication.status == "draft").count()

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
    page_rows = ""
    for ch in blogger_channels:
        try:
            page_driver = BloggerPlatform(channel_id=ch.id, credentials=ch.get_credentials())
            pages = page_driver.list_pages()
        except Exception:
            pages = None
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

    # Opsi dropdown channel untuk form tambah halaman
    page_channel_options = "".join(
        f'<option value="{html_escape(ch.id, quote=True)}">{html_escape(ch.name)} ({html_escape(ch.id)})</option>'
        for ch in blogger_channels
    )

    # Opsi dropdown channel untuk form Tulis Artikel (semua channel;
    # channel blogger pertama terpilih sebagai default).
    first_blogger_id = blogger_channels[0].id if blogger_channels else None
    article_channel_options = ""
    for ch in channels:
        sel = " selected" if ch.id == first_blogger_id else ""
        article_channel_options += (
            f'<option value="{html_escape(ch.id, quote=True)}"{sel}>'
            f'{html_escape(ch.name)} ({html_escape(ch.id)})</option>'
        )
    if not channels:
        article_channel_options = '<option value="">Belum ada channel — tambahkan dulu</option>'

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
        status_badge = '<span class="px-2 py-0.5 rounded text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">Published</span>' if p.status == 'published' else '<span class="px-2 py-0.5 rounded text-xs bg-amber-500/10 text-amber-400 border border-amber-500/30">Draft</span>'
        link_btn = f'<a href="{p.remote_url}" target="_blank" class="text-xs text-emerald-400 hover:underline">Buka Link →</a>' if p.remote_url else '<span class="text-xs text-slate-500">-</span>'
        date_str = p.created_at.strftime('%d/%m/%Y %H:%M') if p.created_at else '-'
        rel = _rel_time(p.created_at)
        time_cell = f'{date_str}<div class="text-[11px] text-slate-500">{rel}</div>' if rel else date_str
        if p.status == 'draft':
            actions = f"""
            <div class="flex gap-1 justify-end">
                <button onclick="publishDraft({p.id}, this)" class="text-xs bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 px-2 py-1 rounded border border-emerald-500/30 transition">Terbitkan</button>
                <button onclick="deletePublication({p.id}, this)" class="text-xs bg-red-950/40 hover:bg-red-900/60 text-red-400 px-2 py-1 rounded border border-red-500/30 transition">Hapus</button>
            </div>
            """
        else:
            actions = '<span class="text-xs text-slate-600">—</span>'
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
                <button type="button" data-section="apikey" onclick="showSection('apikey')" class="nav-item w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition flex items-center gap-2.5 text-slate-300 hover:bg-slate-800 hover:text-white border border-transparent">🔑 API Key</button>
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
                    <div>
                        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Konten HTML</label>
                        <textarea id="articleContent" required rows="10" placeholder="Tulis konten artikel dalam HTML, misal: &lt;h2&gt;Pendahuluan&lt;/h2&gt;&lt;p&gt;...&lt;/p&gt;" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"></textarea>
                    </div>
                    <div class="flex flex-wrap gap-2">
                        <button type="button" onclick="handleWriteArticle('draft', this)" class="bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold px-4 py-2 rounded-xl text-xs transition border border-slate-700">Simpan sebagai Draf</button>
                        <button type="button" onclick="handleWriteArticle('publish', this)" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">Terbitkan</button>
                    </div>
                </form>
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

            <!-- Section: Riwayat -->
            <section id="section-riwayat" class="nav-section space-y-6 hidden">
            <!-- Recent Publications -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Riwayat Publikasi Terbaru</h2>
                    <p class="text-xs text-slate-400">Artikel yang dikirimkan oleh AI ke blog-blog Anda</p>
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

            <!-- Section: Ingest (placeholder — UI ingest menyusul) -->
            <section id="section-ingest" class="nav-section space-y-6 hidden">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Ingest — Ambil Artikel dari Web / RSS</h2>
                    <p class="text-xs text-slate-400">Fitur ingest tersedia lewat API; UI ingest menyusul.</p>
                </div>
                <div class="p-4 rounded-xl bg-slate-800/60 border border-slate-700 text-sm text-slate-300 space-y-2">
                    <p>Ambil isi artikel dari URL web atau teks mentah lewat endpoint:</p>
                    <p><code class="bg-slate-800 text-emerald-400 px-1.5 py-0.5 rounded font-mono text-xs">POST /api/v1/ingest</code> — body <code class="bg-slate-800 text-emerald-400 px-1.5 py-0.5 rounded font-mono text-xs">{{"url": "..."}}</code> atau <code class="bg-slate-800 text-emerald-400 px-1.5 py-0.5 rounded font-mono text-xs">{{"raw_text": "..."}}</code></p>
                    <p><code class="bg-slate-800 text-emerald-400 px-1.5 py-0.5 rounded font-mono text-xs">GET /api/v1/ingest/{{source_id}}</code> — ambil teks hasil ekstraksi berdasarkan ID sumber</p>
                    <p class="text-xs text-slate-500">Dukungan RSS feed dan form ingest di dashboard akan ditambahkan pada tahap berikutnya.</p>
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

            // --- Navigasi sidebar (tampilkan satu section saja) ---
            const SECTION_TITLES = {{dashboard: 'Dashboard', channel: 'Channel', artikel: 'Artikel', halaman: 'Halaman', riwayat: 'Riwayat', ingest: 'Ingest', apikey: 'API Key'}};
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
                setBtnLoading(btn, true, status === 'publish' ? 'Menerbitkan…' : 'Menyimpan…');
                try {{
                    const res = await fetch('/api/v1/publish', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{publications: [item]}})
                    }});
                    const data = await res.json();
                    const result = (data.results || [])[0];
                    if (res.ok && result && (result.status === 'draft' || result.status === 'published')) {{
                        showToast(status === 'publish' ? 'Artikel berhasil diterbitkan.' + (result.remote_url ? ' ' + result.remote_url : '') : 'Artikel berhasil disimpan sebagai draf.');
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
