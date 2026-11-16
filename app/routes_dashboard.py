import os
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Channel, Publication, ApiKey
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
                    class="w-full bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold py-3 px-4 rounded-xl shadow-lg shadow-emerald-500/20 hover:shadow-emerald-500/30 transition transform active:scale-95">
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
    publications = db.query(Publication).order_by(Publication.created_at.desc()).limit(15).all()
    api_keys = db.query(ApiKey).all()

    # Buat baris tabel channel
    channel_rows = ""
    for ch in channels:
        creds = ch.get_credentials()
        blog_url = ch.blog_url or creds.get("blog_url") or creds.get("url") or None
        blog_id = ch.blog_id or creds.get("blog_id") or None
        blog_cell = f'<a href="{blog_url}" target="_blank" class="text-xs text-emerald-400 hover:underline break-all">{blog_url}</a>' if blog_url else '<span class="text-xs text-slate-500">Belum diketahui — klik Test</span>'
        if blog_id:
            blog_cell += f'<div class="text-[11px] text-slate-500 font-mono mt-0.5">ID: {blog_id}</div>'
        test_btn = f"""
        <button onclick="testChannel('{ch.id}')" class="text-xs bg-slate-800 hover:bg-slate-700 text-emerald-400 px-2 py-1 rounded border border-slate-700 transition">Test</button>
        <button onclick="deleteChannel('{ch.id}')" class="text-xs bg-red-950/40 hover:bg-red-900/60 text-red-400 px-2 py-1 rounded border border-red-500/30 transition ml-1">Hapus</button>
        """ if ch.platform == 'blogger' else f"""
        <button onclick="deleteChannel('{ch.id}')" class="text-xs bg-red-950/40 hover:bg-red-900/60 text-red-400 px-2 py-1 rounded border border-red-500/30 transition">Hapus</button>
        """
        channel_rows += f"""
        <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 transition">
            <td class="py-3 px-4 font-mono text-xs text-emerald-400">{ch.id}</td>
            <td class="py-3 px-4 font-medium text-slate-200">{ch.name}</td>
            <td class="py-3 px-4"><span class="px-2 py-1 rounded text-xs font-semibold {'bg-orange-500/10 text-orange-400 border border-orange-500/30' if ch.platform == 'blogger' else 'bg-blue-500/10 text-blue-400 border border-blue-500/30'}">{ch.platform.upper()}</span></td>
            <td class="py-3 px-4 text-sm text-slate-300">{ch.niche}</td>
            <td class="py-3 px-4">{blog_cell}</td>
            <td class="py-3 px-4 text-xs text-slate-400">{ch.tone_of_voice or '-'}</td>
            <td class="py-3 px-4 text-xs text-slate-400">{ch.target_word_count} kata</td>
            <td class="py-3 px-4 text-right">{test_btn}</td>
        </tr>
        """
    if not channels:
        channel_rows = """<tr><td colspan="8" class="py-8 text-center text-slate-500">Belum ada akun blog yang didaftarkan. Klik tombol "+ Tambah Akun Blog" di atas untuk menghubungkan!</td></tr>"""

    # Buat baris tabel publikasi
    pub_rows = ""
    for p in publications:
        status_badge = '<span class="px-2 py-0.5 rounded text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">Published</span>' if p.status == 'published' else '<span class="px-2 py-0.5 rounded text-xs bg-amber-500/10 text-amber-400 border border-amber-500/30">Draft</span>'
        link_btn = f'<a href="{p.remote_url}" target="_blank" class="text-xs text-emerald-400 hover:underline">Buka Link →</a>' if p.remote_url else '<span class="text-xs text-slate-500">-</span>'
        pub_rows += f"""
        <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 transition">
            <td class="py-3 px-4 text-sm font-medium text-slate-200 max-w-xs truncate">{p.title}</td>
            <td class="py-3 px-4 text-xs font-mono text-slate-400">{p.channel_id}</td>
            <td class="py-3 px-4">{status_badge}</td>
            <td class="py-3 px-4 text-xs text-slate-400">{p.created_at.strftime('%d/%m/%Y %H:%M') if p.created_at else '-'}</td>
            <td class="py-3 px-4">{link_btn}</td>
        </tr>
        """
    if not publications:
        pub_rows = """<tr><td colspan="5" class="py-8 text-center text-slate-500">Belum ada riwayat posting artikel.</td></tr>"""

    # Buat baris API keys
    key_rows = ""
    for k in api_keys:
        key_rows += f"""
        <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 transition">
            <td class="py-3 px-4 text-sm font-medium text-slate-200">{k.name}</td>
            <td class="py-3 px-4 font-mono text-xs text-slate-400">{k.key_prefix}</td>
            <td class="py-3 px-4 text-xs text-slate-400">{k.created_at.strftime('%d/%m/%Y')}</td>
            <td class="py-3 px-4 text-xs text-slate-400">{k.last_used_at.strftime('%d/%m/%Y %H:%M') if k.last_used_at else 'Belum pernah'}</td>
            <td class="py-3 px-4"><span class="px-2 py-0.5 rounded text-xs bg-emerald-500/10 text-emerald-400">Aktif</span></td>
            <td class="py-3 px-4 text-right">
                <button onclick="revokeKey({k.id})" class="text-xs text-red-400 hover:text-red-300">Cabut</button>
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
        <!-- Top Navbar -->
        <header class="border-b border-slate-800/80 bg-slate-900/50 backdrop-blur-xl sticky top-0 z-50">
            <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 flex items-center justify-center shadow-lg shadow-emerald-500/20">
                        <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z"></path></svg>
                    </div>
                    <div>
                        <span class="text-base font-bold text-white">Blog Konektor</span>
                        <span class="text-xs text-slate-400 block -mt-0.5">Control Panel</span>
                    </div>
                </div>

                <div class="flex items-center gap-3">
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
        <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
            <!-- Stat Cards -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 relative overflow-hidden">
                    <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Akun Blog Terhubung</div>
                    <div class="text-3xl font-extrabold text-white">{len(channels)}</div>
                    <div class="text-xs text-emerald-400 mt-2 flex items-center gap-1">
                        <span class="w-2 h-2 rounded-full bg-emerald-400"></span> Siap Menerima Artikel
                    </div>
                </div>

                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 relative overflow-hidden">
                    <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Total Riwayat Artikel</div>
                    <div class="text-3xl font-extrabold text-white">{len(publications)}</div>
                    <div class="text-xs text-slate-400 mt-2">Draf & Published via AI</div>
                </div>

                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 relative overflow-hidden">
                    <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">AI Agent Keys</div>
                    <div class="text-3xl font-extrabold text-white">{len(api_keys)}</div>
                    <div class="text-xs text-emerald-400 mt-2">Autentikasi Aman Aktif</div>
                </div>
            </div>

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
                                <th class="py-3 px-4">Channel ID</th>
                                <th class="py-3 px-4">Nama Blog</th>
                                <th class="py-3 px-4">Platform</th>
                                <th class="py-3 px-4">Niche</th>
                                <th class="py-3 px-4">Alamat Blog</th>
                                <th class="py-3 px-4">Tone of Voice</th>
                                <th class="py-3 px-4">Target Kata</th>
                                <th class="py-3 px-4 text-right">Aksi</th>
                            </tr>
                        </thead>
                        <tbody>
                            {channel_rows}
                        </tbody>
                    </table>
                </div>
            </div>

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
                                <th class="py-3 px-4">Nama Kunci</th>
                                <th class="py-3 px-4">Prefix</th>
                                <th class="py-3 px-4">Dibuat Tanggal</th>
                                <th class="py-3 px-4">Terakhir Dipakai</th>
                                <th class="py-3 px-4">Status</th>
                                <th class="py-3 px-4 text-right">Aksi</th>
                            </tr>
                        </thead>
                        <tbody>
                            {key_rows}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Recent Publications -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div class="mb-4">
                    <h2 class="text-lg font-bold text-white">Riwayat Publikasi Terbaru</h2>
                    <p class="text-xs text-slate-400">Artikel yang dikirimkan oleh AI ke blog-blog Anda</p>
                </div>

                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                                <th class="py-3 px-4">Judul Artikel</th>
                                <th class="py-3 px-4">Channel Target</th>
                                <th class="py-3 px-4">Status</th>
                                <th class="py-3 px-4">Waktu</th>
                                <th class="py-3 px-4">Tautan</th>
                            </tr>
                        </thead>
                        <tbody>
                            {pub_rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </main>

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
                            <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('rawKeyOutput').value); alert('API Key disalin!');"
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

                try {{
                    const res = await fetch('/api/v1/channels', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(payload)
                    }});
                    if (res.ok) {{
                        alert('Akun blog berhasil ditambahkan!');
                        window.location.reload();
                    }} else {{
                        const err = await res.json();
                        alert('Gagal: ' + (err.detail || 'Terjadi kesalahan'));
                    }}
                }} catch (err) {{
                    alert('Error: ' + err);
                }}
            }}

            async function testChannel(channelId) {{
                try {{
                    const res = await fetch(`/api/v1/channels/${{channelId}}/test-blogger-blogs`);
                    const data = await res.json();
                    if (res.ok) {{
                        alert(data.message + '\\nBlog yang ditemukan: ' + data.blogs.map(b => b.name + ' (' + b.id + ') - ' + (b.url || '-')).join(', ') + (data.resolved_blog_url ? '\\nAlamat blog channel ini: ' + data.resolved_blog_url : ''));
                    }} else {{
                        alert('Gagal tes koneksi: ' + (data.detail || 'Periksa kredensial'));
                    }}
                }} catch (err) {{
                    alert('Error: ' + err);
                }}
            }}

            async function deleteChannel(channelId) {{
                if (!confirm(`Hapus blog '${{channelId}}' dari konektor?`)) return;
                try {{
                    const res = await fetch(`/api/v1/channels/${{channelId}}`, {{ method: 'DELETE' }});
                    if (res.ok) {{
                        window.location.reload();
                    }} else {{
                        alert('Gagal menghapus');
                    }}
                }} catch (err) {{
                    alert('Error: ' + err);
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
                    }} else {{
                        alert(data.detail || 'Gagal membuat API Key');
                        btn.disabled = false;
                        btn.innerText = 'Buat Kunci';
                    }}
                }} catch (err) {{
                    alert('Terjadi kesalahan: ' + err);
                    btn.disabled = false;
                    btn.innerText = 'Buat Kunci';
                }}
            }}

            async function revokeKey(keyId) {{
                if (!confirm('Cabut hak akses API Key ini? AI Agent yang memakainya tidak akan bisa mengakses lagi.')) return;
                try {{
                    const res = await fetch(`/api/v1/auth/keys/${{keyId}}`, {{ method: 'DELETE' }});
                    if (res.ok) {{
                        window.location.reload();
                    }} else {{
                        alert('Gagal mencabut kunci');
                    }}
                }} catch (err) {{
                    alert('Error: ' + err);
                }}
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
