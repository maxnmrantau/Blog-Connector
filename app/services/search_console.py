"""Integrasi Google Search Console (read-only).

Prasyarat:
- OAuth channel harus membawa scope
  https://www.googleapis.com/auth/webmasters.readonly (ditambahkan di
  routes_oauth.py — alur OAuth meminta scope Blogger + Search Console
  sekaligus). Refresh token LAMA yang dibuat sebelum scope ditambahkan
  TIDAK membawa scope baru — admin harus menghubungkan ulang OAuth
  (prompt=consent sudah aktif di alur itu).
- Search Console API harus diaktifkan di Google Cloud project.
- Blog harus terverifikasi sebagai properti URL-prefix di Search
  Console (untuk Blogspot: https://<blog>.blogspot.com/ dengan
  trailing slash).

Sumber kebenaran siteUrl: sites().list() — dipakai verbatim, jangan
menebak dari blog_url.
"""
import datetime
import json

from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger"
SEARCH_CONSOLE_SERVICE = "searchconsole"
SEARCH_CONSOLE_VERSION = "v1"
TOP_QUERIES_LIMIT = 10
DATE_WINDOW_DAYS = 28
DATA_LAG_DAYS = 3


class SearchConsoleError(Exception):
    """Error Search Console; status_code diteruskan ke HTTPException."""

    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def build_service(credentials):
    """Bangun client searchconsole v1 dari kredensial OAuth channel."""
    creds = Credentials(
        token=None,
        refresh_token=credentials.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=credentials.get("client_id"),
        client_secret=credentials.get("client_secret"),
        scopes=[BLOGGER_SCOPE, SC_SCOPE],
    )
    return build(
        SEARCH_CONSOLE_SERVICE,
        SEARCH_CONSOLE_VERSION,
        credentials=creds,
        cache_discovery=False,
    )


def _http_error_to_sc_error(e):
    """Terjemahkan HttpError Google menjadi SearchConsoleError yang jelas."""
    status = getattr(getattr(e, "resp", None), "status", None)
    msg = ""
    try:
        raw = getattr(e, "content", None)
        body = json.loads(raw.decode("utf-8")) if raw else {}
        msg = ((body.get("error") or {}).get("message") or "")
    except Exception:
        msg = ""
    low = (msg or "").lower()
    if status == 429 or "quotaexceeded" in low or "quota exceeded" in low:
        raise SearchConsoleError(
            "Kuota Search Console terlampaui (429). Coba lagi nanti.",
            status_code=429,
        )
    if (
        status == 403
        or "insufficientpermissions" in low
        or "sufficient permission" in low
    ):
        raise SearchConsoleError(
            "Kredensial OAuth belum punya scope Search Console, atau akun "
            "ini tidak punya akses ke properti tersebut. Hubungkan ulang "
            "OAuth dengan scope Search Console (dashboard → Search "
            "Console → Hubungkan Ulang), dan pastikan Search Console API "
            "diaktifkan di Google Cloud project.",
            status_code=403,
        )
    if status == 404:
        raise SearchConsoleError(
            "Properti tidak ditemukan di Search Console. Pastikan blog "
            "sudah terverifikasi sebagai properti URL-prefix di Search "
            "Console.",
            status_code=404,
        )
    if status == 401:
        raise SearchConsoleError(
            "Refresh token tidak valid atau kedaluwarsa. Hubungkan ulang OAuth.",
            status_code=401,
        )
    raise SearchConsoleError(
        f"Search Console API error [{status}]: {msg or e}", status_code=502
    )


def _refresh_error_to_sc_error(e):
    """Terjemahkan RefreshError (gagal refresh token OAuth) menjadi
    SearchConsoleError yang jelas.

    invalid_scope muncul saat token REFRESH, bukan saat panggilan API —
    jadi error ini TIDAK tertangkap HttpError. Penyebabnya: refresh
    token dibuat SEBELUM scope Search Console ditambahkan; Google
    tidak mengizinkan token lama mendapat scope baru, jadi satu-satunya
    jalan adalah hubungkan ulang OAuth sekali. Status 403 dipakai
    supaya tombol "Hubungkan Ulang OAuth" di dashboard muncul.
    """
    low = str(e).lower()
    if "invalid_scope" in low:
        raise SearchConsoleError(
            "Token OAuth channel ini dibuat sebelum izin Search Console "
            "ditambahkan. Google tidak mengizinkan token lama mendapat "
            "izin baru — hubungkan ulang OAuth sekali lewat tombol "
            "\"Hubungkan Ulang OAuth\" di bawah. Token baru tersimpan "
            "otomatis ke channel ini.",
            status_code=403,
        )
    raise SearchConsoleError(
        f"Gagal memperbarui token OAuth ({e}). Hubungkan ulang OAuth "
        "lewat tombol \"Hubungkan Ulang OAuth\" di bawah.",
        status_code=401,
    )


def _normalize_site_url(url):
    if not url:
        return ""
    url = url.strip()
    if not url.endswith("/"):
        url += "/"
    return url


def _pick_site_url(entries, blog_url):
    """Pilih siteUrl dari sites().list(): cocokkan blog_url dulu, bila
    hanya ada satu properti yang bisa diakses, pakai itu. Bila tidak
    bisa diputuskan, kembalikan None (pemanggil memberi error jelas)."""
    usable = [e for e in entries if e.get("permissionLevel") != "siteUnverifiedUser"]
    wanted = _normalize_site_url(blog_url)
    if wanted:
        for e in usable:
            if _normalize_site_url(e.get("siteUrl")) == wanted:
                return e.get("siteUrl")
    if len(usable) == 1:
        return usable[0].get("siteUrl")
    return None


def _resolve_site(channel, service_factory=None):
    """Bangun service Search Console + pilih siteUrl properti channel.

    Dipakai bersama oleh get_overview() dan submit_sitemap() supaya
    validasi kredensial, pemetaan error, dan pemilihan properti
    tidak ditulis dua kali. Mengembalikan (service, site_url).
    """
    creds = channel.get_credentials()
    if not all(
        [creds.get("client_id"), creds.get("client_secret"), creds.get("refresh_token")]
    ):
        raise SearchConsoleError(
            "Channel ini belum punya kredensial OAuth Blogger. Hubungkan "
            "dulu lewat halaman OAuth Generator (/oauth/blogger).",
            status_code=400,
        )
    factory = service_factory or build_service
    try:
        service = factory(creds)
        sites = service.sites().list().execute()
    except HttpError as e:
        _http_error_to_sc_error(e)
    except RefreshError as e:
        _refresh_error_to_sc_error(e)
    except SearchConsoleError:
        raise
    except Exception as e:
        raise SearchConsoleError(f"Tidak dapat menghubungi Search Console: {e}")
    entries = (sites or {}).get("siteEntry", []) or []
    site_url = _pick_site_url(entries, channel.blog_url)
    if not site_url:
        raise SearchConsoleError(
            "Tidak ada properti Search Console yang bisa diakses akun ini. "
            "Pastikan blog terverifikasi di Search Console dan akun OAuth "
            "ditambahkan sebagai pengguna properti.",
            status_code=404,
        )
    return service, site_url


def get_overview(channel, service_factory=None):
    """Ambil ringkasan Search Console untuk satu channel.

    service_factory(credentials) -> service dipakai untuk menguji (mock).
    Mengembalikan dict {site_url, connected, scope_ok, date_range,
    top_queries[], totals{}, sitemaps[]}.
    """
    service, site_url = _resolve_site(channel, service_factory)
    # Data Search Console tertinggal 2-3 hari: jendela 28 hari yang
    # berakhir 3 hari lalu.
    end = datetime.date.today() - datetime.timedelta(days=DATA_LAG_DAYS)
    start = end - datetime.timedelta(days=DATE_WINDOW_DAYS - 1)
    try:
        resp = service.searchanalytics().query(
            siteUrl=site_url,
            body={
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "dimensions": ["query"],
                "rowLimit": TOP_QUERIES_LIMIT,
            },
        ).execute()
        sm = service.sitemaps().list(siteUrl=site_url).execute()
    except HttpError as e:
        _http_error_to_sc_error(e)
    except RefreshError as e:
        _refresh_error_to_sc_error(e)
    except SearchConsoleError:
        raise
    except Exception as e:
        raise SearchConsoleError(f"Tidak dapat menghubungi Search Console: {e}")
    rows = (resp or {}).get("rows", []) or []
    top_queries = [
        {
            "query": (r.get("keys") or [""])[0],
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr": r.get("ctr", 0),
            "position": r.get("position", 0),
        }
        for r in rows
    ]
    total_clicks = sum(q["clicks"] for q in top_queries)
    total_impr = sum(q["impressions"] for q in top_queries)
    avg_ctr = (total_clicks / total_impr) if total_impr else 0
    avg_pos = (
        (sum(q["position"] for q in top_queries) / len(top_queries))
        if top_queries
        else 0
    )
    sitemaps = [
        {
            "path": s.get("path"),
            "lastSubmitted": s.get("lastSubmitted"),
            "lastDownloaded": s.get("lastDownloaded"),
            "isPending": s.get("isPending", False),
            "warnings": s.get("warnings", 0),
            "errors": s.get("errors", 0),
        }
        for s in ((sm or {}).get("sitemap", []) or [])
    ]
    return {
        "site_url": site_url,
        "connected": True,
        "scope_ok": True,
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "top_queries": top_queries,
        "totals": {
            "clicks": total_clicks,
            "impressions": total_impr,
            "avg_ctr": avg_ctr,
            "avg_position": avg_pos,
        },
        "sitemaps": sitemaps,
    }


def submit_sitemap(channel, service_factory=None):
    """Kirim sitemap blog ke Search Console (sitemaps().submit).

    Sitemap Blogger (blog_url + "/sitemap.xml") diperbarui otomatis
    setiap artikel terbit, jadi submit ulang memberi tahu Google ada
    URL baru. Mengembalikan {ok, site_url, sitemap_url, submitted_at}.

    Batasan yang harus dipahami — jangan berharap lebih dari ini:
    Google TIDAK menyediakan API untuk tombol "Request Indexing" per
    URL (itu hanya ada di website Search Console). Indexing API pun
    hanya untuk halaman lowongan kerja / livestream, BUKAN artikel
    blog. Jadi pengiriman sitemap adalah satu-satunya otomatisasi
    submit yang didukung Google untuk blog.
    """
    service, site_url = _resolve_site(channel, service_factory)
    sitemap_url = site_url.rstrip("/") + "/sitemap.xml"
    try:
        service.sitemaps().submit(siteUrl=site_url, feedpath=sitemap_url).execute()
    except HttpError as e:
        _http_error_to_sc_error(e)
    except RefreshError as e:
        _refresh_error_to_sc_error(e)
    except SearchConsoleError:
        raise
    except Exception as e:
        raise SearchConsoleError(f"Tidak dapat menghubungi Search Console: {e}")
    return {
        "ok": True,
        "site_url": site_url,
        "sitemap_url": sitemap_url,
        "submitted_at": datetime.datetime.utcnow().isoformat(),
    }


def try_submit_sitemap(channel, service_factory=None):
    """Submit sitemap tanpa pernah melempar exception — dipakai
    auto-submit saat publish. Kegagalan submit TIDAK BOLEH
    menggagalkan publish, jadi hasilnya dikembalikan sebagai info:
    {"sitemap_submitted": bool, "note": str}."""
    try:
        result = submit_sitemap(channel, service_factory=service_factory)
        return {
            "sitemap_submitted": True,
            "note": f"Sitemap {result['sitemap_url']} dikirim ke Search Console.",
        }
    except SearchConsoleError as e:
        return {"sitemap_submitted": False, "note": str(e)}
    except Exception as e:
        return {"sitemap_submitted": False, "note": f"Tidak dapat mengirim sitemap: {e}"}
