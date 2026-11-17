import os
import urllib.parse
import httpx
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.security import serializer, is_session_valid, COOKIE_NAME

router = APIRouter(include_in_schema=False)

def get_redirect_uri(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", "https" if "vercel" in request.headers.get("host", "") else request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", "localhost:8000"))
    return f"{scheme}://{host}/oauth/blogger/callback"

@router.get("/oauth/blogger", response_class=HTMLResponse)
def oauth_blogger_page(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not is_session_valid(token):
        return RedirectResponse(url="/login", status_code=303)

    redirect_uri = get_redirect_uri(request)

    html = f"""
    <!DOCTYPE html>
    <html lang="id" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dapatkan Refresh Token Blogger</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script>
            tailwind.config = {{
                darkMode: 'class',
                theme: {{ extend: {{ colors: {{ brand: {{ 500: '#10b981', 600: '#059669' }} }} }} }}
            }}
        </script>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen flex items-center justify-center p-4 antialiased">
        <div class="max-w-xl w-full bg-slate-900 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl backdrop-blur-xl">
            <div class="flex items-center justify-between mb-6">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-xl bg-orange-500/20 border border-orange-500/30 flex items-center justify-center text-orange-400 font-bold">
                        B
                    </div>
                    <div>
                        <h1 class="text-xl font-bold text-white">OAuth Generator Blogger</h1>
                        <p class="text-xs text-slate-400">Dapatkan Refresh Token (Blogger + Search Console) & Blog ID tanpa buka terminal</p>
                    </div>
                </div>
                <a href="/dashboard" class="text-xs text-slate-400 hover:text-white px-3 py-1.5 rounded-lg border border-slate-800 hover:bg-slate-800 transition">
                    ← Kembali
                </a>
            </div>

            <!-- Notice Box: Redirect URI -->
            <div class="mb-6 p-4 rounded-xl bg-slate-800/60 border border-slate-700/80 text-xs space-y-2">
                <p class="font-semibold text-amber-400 flex items-center gap-1.5">
                    <span>⚠️</span> Langkah Wajib di Google Cloud Console:
                </p>
                <p class="text-slate-300">
                    Pastikan di <b>Google Cloud > Credentials > OAuth Client ID (Web application)</b> Anda sudah memasukkan URL ini pada bagian <b>Authorized redirect URIs</b>:
                </p>
                <p class="text-slate-300">
                    Aktifkan juga API <b>Google Search Console API</b> di Google Cloud &gt; APIs &amp; Services &gt; Library, supaya dashboard bisa menampilkan data Search Console.
                </p>
                <div class="flex items-center gap-2 mt-2">
                    <input type="text" readonly id="redirectUriInput" value="{redirect_uri}" 
                        class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 font-mono text-[11px] text-emerald-400 select-all">
                    <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('redirectUriInput').value); alert('Redirect URI disalin!');"
                        class="bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded-lg text-slate-200 font-medium whitespace-nowrap">
                        Salin
                    </button>
                </div>
            </div>

            <form action="/oauth/blogger/start" method="POST" class="space-y-4 text-xs">
                <div>
                    <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1.5">Google Client ID</label>
                    <input type="text" name="client_id" required placeholder="Contoh: 123456789-xxx.apps.googleusercontent.com"
                        class="w-full bg-slate-800/80 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                </div>

                <div>
                    <label class="block font-semibold uppercase tracking-wider text-slate-400 mb-1.5">Google Client Secret</label>
                    <input type="password" name="client_secret" required placeholder="Contoh: GOCSPX-xxxxxxxxx"
                        class="w-full bg-slate-800/80 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                </div>

                <div class="pt-3">
                    <button type="submit"
                        class="w-full bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold py-3 px-4 rounded-xl shadow-lg shadow-emerald-500/20 transition transform active:scale-95 flex items-center justify-center gap-2 text-sm">
                        <span>Lanjut Login dengan Akun Google</span>
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
                    </button>
                </div>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@router.post("/oauth/blogger/start")
def oauth_blogger_start(request: Request, client_id: str = Form(...), client_secret: str = Form(...)):
    token = request.cookies.get(COOKIE_NAME)
    if not is_session_valid(token):
        return RedirectResponse(url="/login", status_code=303)

    redirect_uri = get_redirect_uri(request)
    state = serializer.dumps({"client_id": client_id.strip(), "client_secret": client_secret.strip()})

    params = {
        "client_id": client_id.strip(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        # Blogger + Search Console (read-only). Refresh token LAMA yang
        # dibuat sebelum scope Search Console ditambahkan TIDAK membawa
        # scope baru — admin harus mengulang alur ini (prompt=consent
        # sudah aktif) agar token baru membawa kedua scope.
        "scope": "https://www.googleapis.com/auth/blogger https://www.googleapis.com/auth/webmasters.readonly",
        "access_type": "offline",
        "prompt": "consent",
        "state": state
    }
    google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=google_auth_url, status_code=303)

@router.get("/oauth/blogger/callback", response_class=HTMLResponse)
async def oauth_blogger_callback(request: Request, code: str = None, state: str = None, error: str = None):
    if error or not code or not state:
        err_msg = error or "Otorisasi dibatalkan atau kode otorisasi tidak ditemukan."
        return HTMLResponse(content=f"""
        <body style="background:#020617;color:#f87171;font-family:sans-serif;padding:40px;text-align:center;">
            <h2>❌ Otorisasi Gagal</h2>
            <p>{err_msg}</p>
            <br>
            <a href="/oauth/blogger" style="color:#38bdf8;">← Coba Lagi</a>
        </body>
        """)

    try:
        data = serializer.loads(state, max_age=1800)
        client_id = data.get("client_id")
        client_secret = data.get("client_secret")
    except Exception:
        return HTMLResponse(content="<h3>Sesi state kedaluwarsa. Silakan ulangi dari awal di <a href='/oauth/blogger'>sini</a>.</h3>")

    redirect_uri = get_redirect_uri(request)

    # Tukar code menjadi token ke Google
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code"
            }
        )
        token_data = token_res.json()

    refresh_token = token_data.get("refresh_token", "")
    access_token = token_data.get("access_token", "")

    if not refresh_token:
        # Jika refresh_token tidak ada (misal karena consent screen sebelumnya tidak dicentang ulang)
        return HTMLResponse(content=f"""
        <body style="background:#020617;color:#f87171;font-family:sans-serif;padding:40px;text-align:center;">
            <h2>⚠️ Refresh Token Tidak Ditemukan</h2>
            <p>Google tidak mengembalikan refresh token. Pastikan saat otorisasi Anda menyetujui akses offline, atau cabut izin app di Google Account lalu ulangi.</p>
            <pre style="background:#0f172a;padding:15px;color:#cbd5e1;text-align:left;display:inline-block;border-radius:8px;">{token_data}</pre>
            <br><br>
            <a href="/oauth/blogger" style="color:#38bdf8;">← Ulangi Otorisasi</a>
        </body>
        """)

    # Ambil daftar blog user via Blogger API
    blogs = []
    if access_token:
        async with httpx.AsyncClient() as client:
            blog_res = await client.get(
                "https://www.googleapis.com/blogger/v3/users/self/blogs",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if blog_res.status_code == 200:
                blog_json = blog_res.json()
                blogs = blog_json.get("items", [])

    blogs_html = ""
    for idx, b in enumerate(blogs, 1):
        blogs_html += f"""
        <div class="p-3 bg-slate-950 border border-slate-800 rounded-xl flex items-center justify-between text-xs">
            <div>
                <p class="font-bold text-slate-100">{b.get('name')}</p>
                <p class="text-[11px] text-slate-400 font-mono mt-0.5">Blog ID: <span id="blogId_{idx}" class="text-emerald-400 font-bold">{b.get('id')}</span></p>
                <a href="{b.get('url')}" target="_blank" class="text-[10px] text-slate-500 hover:text-emerald-400">{b.get('url')}</a>
            </div>
            <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('blogId_{idx}').innerText); alert('Blog ID disalin!');"
                class="bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-1.5 rounded-lg border border-slate-700">
                Salin ID
            </button>
        </div>
        """

    if not blogs_html:
        blogs_html = "<p class='text-xs text-slate-400'>Tidak ditemukan blog di akun Google ini atau API Blogger belum diaktifkan.</p>"

    html = f"""
    <!DOCTYPE html>
    <html lang="id" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Berhasil Terhubung - Blogger</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen flex items-center justify-center p-4 antialiased">
        <div class="max-w-xl w-full bg-slate-900 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl backdrop-blur-xl space-y-6">
            <div class="text-center">
                <div class="w-12 h-12 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center mx-auto mb-3 text-xl font-bold">
                    ✓
                </div>
                <h1 class="text-xl font-bold text-white">Autentikasi Berhasil!</h1>
                <p class="text-xs text-slate-400 mt-1">Salin Refresh Token & Blog ID Anda untuk dimasukkan ke form Tambah Blog</p>
            </div>

            <!-- Refresh Token Box -->
            <div class="p-4 bg-slate-800/60 border border-slate-700 rounded-xl space-y-1.5">
                <label class="block text-xs font-semibold uppercase tracking-wider text-emerald-400">Refresh Token Anda:</label>
                <div class="flex items-center gap-2">
                    <input type="text" readonly id="refreshTokenInput" value="{refresh_token}"
                        class="w-full bg-slate-950 border border-emerald-500/40 rounded-lg px-3 py-2 font-mono text-xs text-emerald-300 select-all">
                    <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('refreshTokenInput').value); alert('Refresh Token disalin!');"
                        class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-3 py-2 rounded-lg text-xs whitespace-nowrap">
                        Salin Token
                    </button>
                </div>
            </div>

            <!-- List Blogs Box -->
            <div class="space-y-2">
                <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400">Daftar Blogspot di Akun Anda ({len(blogs)} ditemukan):</label>
                <div class="space-y-2">
                    {blogs_html}
                </div>
            </div>

            <div class="pt-2">
                <a href="/dashboard"
                    class="block w-full text-center bg-slate-800 hover:bg-slate-700 text-white font-bold py-3 px-4 rounded-xl border border-slate-700 transition text-sm">
                    Kembali ke Dashboard & Masukkan ke Form
                </a>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
