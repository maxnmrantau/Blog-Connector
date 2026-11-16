"""
Script Pembantu Setup Autentikasi Google Blogger OAuth 2.0

Cara Penggunaan:
1. Buat Project di Google Cloud Console (https://console.cloud.google.com/)
2. Aktifkan 'Blogger API v3' di API Library.
3. Buka 'APIs & Services > Credentials' -> 'Create Credentials' -> 'OAuth client ID'.
4. Pilih Application type: 'Desktop app' (atau 'Web application').
5. Download JSON kredensial atau catat Client ID dan Client Secret.
6. Jalankan script ini:
   .venv\\Scripts\\python.exe scripts\\setup_blogger_auth.py
"""

import sys
import os

# Tambahkan path root proyek
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/blogger"]

def authenticate_blogger():
    print("=" * 60)
    print("🤖 SETUP AUTENTIKASI GOOGLE BLOGGER (BLOGSPOT)")
    print("=" * 60)

    client_id = input("Masukkan Google Client ID: ").strip()
    client_secret = input("Masukkan Google Client Secret: ").strip()

    if not client_id or not client_secret:
        print("❌ Client ID dan Client Secret tidak boleh kosong.")
        return

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080/"]
        }
    }

    try:
        print("\n🌐 Membuka browser untuk login Google dan memberikan izin akses Blogger...")
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = flow.run_local_server(port=8080, prompt="consent")

        print("\n✅ Autentikasi Berhasil!")
        print("-" * 60)
        print("🔑 SIMPAN REFRESH TOKEN INI:")
        print(f"Refresh Token: {creds.refresh_token}")
        print("-" * 60)

        # Ambil daftar blog yang bisa diakses
        service = build("blogger", "v3", credentials=creds)
        blogs_res = service.blogs().listByUser(userId="self").execute()
        blogs = blogs_res.get("items", [])

        print(f"\n📚 Ditemukan {len(blogs)} Blog di akun Anda:")
        for idx, b in enumerate(blogs, 1):
            print(f"  {idx}. Nama Blog: {b.get('name')}")
            print(f"     Blog ID  : {b.get('id')}")
            print(f"     URL      : {b.get('url')}")
            print()

        print("💡 Salin 'Blog ID' di atas untuk didaftarkan ke channel Blog Konektor!")

    except Exception as e:
        print(f"\n❌ Terjadi kesalahan saat autentikasi: {str(e)}")

if __name__ == "__main__":
    authenticate_blogger()
