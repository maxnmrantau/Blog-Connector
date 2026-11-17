"""Image Picker: cari foto berlisensi bebas dari Openverse (utama) dan
Pexels (opsional, bila kunci tersedia).

Openverse (https://api.openverse.org/v1/images/) TIDAK BUTUH API key dan
mengembalikan gambar berlisensi Creative Commons beserta atribusi siap
pakai. Pexels menghentikan penerbitan API key baru sejak awal Oktober
2026, jadi Pexels hanya dipakai bila admin sudah punya kunci lama
(disimpan di Pengaturan AI). Jangan pernah scraping situs Pexels —
syarat layanan mereka melarangnya.

Batasan ukuran: Openverse mengembalikan URL file asli dari sumbernya
(Flickr, Wikimedia, dll.) dengan ukuran apa adanya — tidak ada
parameter crop seperti Pexels. Hasil Pexels selalu dipotong
landscape 1200x675 (fit=crop). Tampilan akhir di blog diatur CSS
+ wrapper max-width 640px yang sudah menjadi aturan proyek, jadi foto
Openverse tetap tampil rapi meski file aslinya lebih besar.
"""
import httpx

from app.services.settings import PEXELS_API_KEY, get_setting_value

OPENVERSE_BASE_URL = "https://api.openverse.org/v1/images/"
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"

# Batas pemakaian anonim Openverse (dari dokumentasi + header
# x-ratelimit mereka): sekitar 20 permintaan/menit dan 100-200/hari.
OPENVERSE_ANON_NOTE = "batas anonim Openverse sekitar 100-200 permintaan/hari"


class ImageSearchError(Exception):
    """Error pencarian gambar; status_code diteruskan ke HTTPException."""

    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def _pexels_crop_url(original_url):
    """Bangun URL Pexels landscape 1200x675 (fit=crop).

    Parameter w/h saja TIDAK memotong (Pexels hanya fit dalam kotak);
    fit=crop wajib agar hasil benar-benar 1200x675.
    """
    base = (original_url or "").split("?")[0]
    if not base:
        return ""
    return base + "?auto=compress&cs=tinysrgb&fit=crop&h=675&w=1200"


def search_openverse(query, per_page=8, http_client=None):
    """Cari foto di Openverse (tanpa key, lisensi komersial saja).

    Mengembalikan list dict ternormalisasi. raise ImageSearchError bila
    layanan gagal.
    """
    params = {
        "q": query,
        "license_type": "commercial",
        "size": "large",
        "aspect_ratio": "wide",
        "page_size": max(1, min(20, per_page)),
        "filter_dead": "true",
    }
    client = http_client or httpx.Client(timeout=15.0)
    own_client = http_client is None
    try:
        resp = client.get(OPENVERSE_BASE_URL, params=params)
    except httpx.RequestError as e:
        raise ImageSearchError(f"Tidak dapat menghubungi Openverse: {e}")
    finally:
        if own_client:
            client.close()
    if resp.status_code == 429:
        raise ImageSearchError(
            f"Openverse membatasi permintaan (429). Coba lagi nanti — "
            f"{OPENVERSE_ANON_NOTE}.",
            status_code=429,
        )
    if resp.status_code != 200:
        raise ImageSearchError(f"Openverse mengembalikan error [{resp.status_code}].")
    try:
        data = resp.json()
    except Exception:
        raise ImageSearchError("Respons Openverse bukan JSON yang valid.")
    results = []
    for item in data.get("results", []) or []:
        url = item.get("url") or ""
        if not url:
            continue
        title = (item.get("title") or "").strip()
        results.append(
            {
                "source": "openverse",
                "id": str(item.get("id") or ""),
                "title": title,
                "url": url,
                "thumbnail_url": item.get("thumbnail") or url,
                "width": item.get("width"),
                "height": item.get("height"),
                "suggested_alt": title or f"Foto {query}",
                "photographer": item.get("creator") or "",
                "photographer_url": item.get("creator_url") or "",
                "license": item.get("license") or "",
                "license_url": item.get("license_url") or "",
                "attribution": item.get("attribution") or "",
                "foreign_landing_url": item.get("foreign_landing_url") or "",
            }
        )
    return results


def search_pexels(api_key, query, per_page=8, http_client=None):
    """Cari foto di Pexels (butuh kunci; header Authorization = kunci mentah).

    Mengembalikan list dict ternormalisasi dengan URL landscape 1200x675.
    raise ImageSearchError bila layanan gagal atau kunci tidak valid.
    """
    params = {
        "query": query,
        "orientation": "landscape",
        "per_page": max(1, min(80, per_page)),
        "page": 1,
    }
    headers = {"Authorization": api_key}
    client = http_client or httpx.Client(timeout=15.0)
    own_client = http_client is None
    try:
        resp = client.get(PEXELS_SEARCH_URL, headers=headers, params=params)
    except httpx.RequestError as e:
        raise ImageSearchError(f"Tidak dapat menghubungi Pexels: {e}")
    finally:
        if own_client:
            client.close()
    if resp.status_code == 401:
        raise ImageSearchError(
            "Kunci Pexels tidak valid (401). Periksa kunci di Pengaturan AI.",
            status_code=401,
        )
    if resp.status_code == 429:
        raise ImageSearchError(
            "Pexels membatasi permintaan (429). Coba lagi nanti.", status_code=429
        )
    if resp.status_code != 200:
        raise ImageSearchError(f"Pexels mengembalikan error [{resp.status_code}].")
    try:
        data = resp.json()
    except Exception:
        raise ImageSearchError("Respons Pexels bukan JSON yang valid.")
    results = []
    for photo in data.get("photos", []) or []:
        src = photo.get("src", {}) or {}
        original = src.get("original") or ""
        if not original:
            continue
        alt = (photo.get("alt") or "").strip()
        photographer = photo.get("photographer") or ""
        results.append(
            {
                "source": "pexels",
                "id": str(photo.get("id") or ""),
                "title": alt,
                "url": _pexels_crop_url(original),
                "thumbnail_url": src.get("small") or src.get("medium") or original,
                "width": 1200,
                "height": 675,
                "suggested_alt": alt or f"Foto {query}",
                "photographer": photographer,
                "photographer_url": photo.get("photographer_url") or "",
                "license": "Pexels License",
                "license_url": "https://www.pexels.com/license/",
                "attribution": (
                    f"Photo by {photographer} on Pexels"
                    if photographer
                    else "Photo from Pexels"
                ),
                "foreign_landing_url": photo.get("url") or "",
            }
        )
    return results


def search_images(query, per_page=8, db=None, http_client=None):
    """Cari foto: Openverse selalu; Pexels bila kunci tersedia.

    Kegagalan satu sumber tidak menggagalkan sumber lain — error tiap
    sumber dilaporkan di respons. Bila semua sumber gagal (atau tidak
    ada hasil), raise ImageSearchError.
    """
    per_page = max(1, min(20, per_page or 8))
    results = []
    sources = []
    errors = {}
    try:
        results.extend(
            search_openverse(query, per_page=per_page, http_client=http_client)
        )
        sources.append("openverse")
    except ImageSearchError as e:
        errors["openverse_error"] = str(e)
    pexels_key = get_setting_value(db, PEXELS_API_KEY) if db is not None else None
    if pexels_key:
        try:
            results.extend(
                search_pexels(
                    pexels_key, query, per_page=per_page, http_client=http_client
                )
            )
            sources.append("pexels")
        except ImageSearchError as e:
            errors["pexels_error"] = str(e)
    if not results:
        msg = (
            errors.get("openverse_error")
            or errors.get("pexels_error")
            or "Tidak ada hasil."
        )
        raise ImageSearchError(msg)
    out = {"query": query, "results": results, "sources": sources}
    out.update(errors)
    return out
