"""Auto-Rewrite: tulis ulang artikel sumber menjadi artikel baru yang
orisinal memakai Google Gemini API (REST, httpx).

Keamanan & kualitas:
- Kunci Gemini diambil dari tabel settings (Pengaturan AI), TIDAK PERNAH
  ditulis ke log dan tidak pernah dikirim ke klien.
- Hasil rewrite SELALU disimpan sebagai draf — tidak pernah auto-publish.
- Rasio kemiripan dengan sumber dihitung (difflib); bila terlalu mirip,
  respons membawa flag peringatan tapi draf tetap disimpan supaya admin
  bisa menilai sendiri.
- Tautan atribusi ke sumber selalu disisipkan di akhir artikel.
"""
import difflib
import re

import httpx

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
# Model default: gemini-3.8-flash (Stable, pilihan Google untuk proyek
# baru per Nov 2026). JANGAN pakai gemini-2.0-flash lagi — Google
# mematikannya 1 Juni 2026 (request ke sana gagal 404). Bisa diubah
# lewat setting "gemini_model" di Pengaturan AI.
DEFAULT_MODEL = "gemini-3.8-flash"

# Mode rewrite: seberapa jauh hasil boleh menyimpang dari sumber.
REWRITE_MODES = {
    "ringan": {
        "temperature": 0.5,
        "label": "Ringan",
        "instruction": (
            "Ubah susunan kalimat dan paragraf dengan tetap mengikuti alur "
            "sumber; ganti contoh yang mudah diganti."
        ),
    },
    "sedang": {
        "temperature": 0.7,
        "label": "Sedang",
        "instruction": (
            "Rombak struktur bagian dan ganti sebagian besar contoh; sudut "
            "pandang boleh diubah selama faktanya sama."
        ),
    },
    "total": {
        "temperature": 0.9,
        "label": "Total",
        "instruction": (
            "Tulis dari sudut pandang yang benar-benar baru dengan struktur "
            "yang berbeda total; hanya fakta inti dari sumber yang dipertahankan."
        ),
    },
}


class GeminiError(Exception):
    """Kegagalan memanggil Gemini API (jaringan, kunci salah, kuota, dll)."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def generate_text(api_key, prompt, model=DEFAULT_MODEL,
                  temperature=0.7, max_output_tokens=8192,
                  http_client=None):
    """Panggil Gemini generateContent (REST) dan kembalikan teks hasilnya.

    http_client hanya dipakai tes (mock) — bila None, dibuatkan
    httpx.Client baru dengan timeout 120 detik.
    """
    url = f"{GEMINI_BASE_URL}/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    own_client = http_client is None
    client = http_client or httpx.Client(timeout=120.0)
    try:
        resp = client.post(url, headers=headers, json=payload)
    except httpx.RequestError as e:
        raise GeminiError(f"Tidak dapat menghubungi Gemini API: {e}")
    finally:
        if own_client:
            client.close()
    if resp.status_code != 200:
        try:
            err = resp.json().get("error", {}) or {}
            msg = err.get("message") or resp.text
        except Exception:
            msg = resp.text
        raise GeminiError(
            f"Gemini API error [{resp.status_code}]: {msg}",
            status_code=resp.status_code,
        )
    try:
        data = resp.json()
    except Exception:
        raise GeminiError("Respons Gemini bukan JSON yang valid.")
    parts = []
    for cand in data.get("candidates", []) or []:
        content = cand.get("content", {}) or {}
        for part in content.get("parts", []) or []:
            if part.get("text"):
                parts.append(part["text"])
    text = "".join(parts).strip()
    if not text:
        raise GeminiError("Gemini mengembalikan respons kosong (tidak ada teks).")
    return text


def build_rewrite_prompt(channel, source_title, source_text, mode,
                         source_url=None):
    """Susun prompt rewrite dari profil channel + aturan rewrite."""
    mode_info = REWRITE_MODES.get(mode) or REWRITE_MODES["sedang"]
    niche = channel.niche or "umum"
    tone = channel.tone_of_voice or "Informatif & Santai"
    audience = channel.target_audience or "Umum"
    try:
        target_words = int(channel.target_word_count or 800)
    except (TypeError, ValueError):
        target_words = 800
    return (
        f'Kamu adalah penulis blog berbahasa Indonesia untuk blog "{channel.name}" '
        f"(niche: {niche}).\n"
        "Tulis ulang artikel sumber di bawah ini menjadi artikel BARU yang "
        "orisinal, bukan salinan.\n\n"
        "Aturan:\n"
        f"- Bahasa: Bahasa Indonesia, gaya {tone}.\n"
        f"- Target: sekitar {target_words} kata, untuk pembaca {audience}.\n"
        "- Restrukturisasi: ubah urutan dan judul bagian (H2/H3) supaya berbeda "
        "dari sumber; jangan mempertahankan struktur sumber apa adanya.\n"
        "- Ganti semua contoh dengan contoh baru yang relevan; pertahankan fakta, "
        "angka, dan nama yang benar dari sumber.\n"
        "- Jangan menyalin kalimat sumber kata demi kata.\n"
        "- Keluaran HARUS berupa HTML saja: baris pertama \"JUDUL: <judul baru>\", "
        "lalu isi artikel memakai <h2>, <h3>, <p> (tanpa <html>, <body>, atau "
        "blok kode markdown).\n"
        "- Jangan menambahkan pendahuluan tentang proses penulisan; langsung ke "
        "judul dan isi.\n\n"
        f"Mode rewrite: {mode_info['label']} — {mode_info['instruction']}\n\n"
        f"Judul sumber: {source_title or 'Tanpa Judul'}\n"
        f"Teks sumber:\n{source_text}"
    )


def clean_model_html(text):
    """Bersihkan keluaran model: buang pagar kode markdown, rapikan spasi."""
    text = (text or "").strip()
    # Buang blok ```html ... ``` atau ``` ... ```
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_model_output(text):
    """Pisahkan judul dan isi dari keluaran model.

    Baris pertama "JUDUL: ..." menjadi judul; sisanya menjadi HTML isi.
    Bila tidak ada baris JUDUL, judul = None (pemanggil memakai judul
    sumber). Bila isi tidak mengandung tag HTML sama sekali, paragraf
    dibungkus <p> dan baris "# ..." dijadikan <h2>.
    """
    cleaned = clean_model_html(text)
    title = None
    body = cleaned
    lines = cleaned.splitlines()
    if lines and lines[0].strip().upper().startswith("JUDUL:"):
        title = lines[0].split(":", 1)[1].strip() or None
        body = "\n".join(lines[1:]).strip()
    if "<" not in body:
        out = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("## "):
                out.append(f"<h2>{line[3:].strip()}</h2>")
            elif line.startswith("# "):
                out.append(f"<h2>{line[2:].strip()}</h2>")
            else:
                out.append(f"<p>{line}</p>")
        body = "\n".join(out)
    return title, body


def plain_text(content_html):
    """Teks polos dari HTML (untuk hitung kata & kemiripan)."""
    text = re.sub(r"<[^>]+>", " ", content_html or "")
    return re.sub(r"\s+", " ", text).strip()


def count_words(content_html):
    """Jumlah kata dalam konten HTML."""
    text = plain_text(content_html)
    return len([w for w in text.split(" ") if w]) if text else 0


def similarity_ratio(source_text, rewritten_html):
    """Rasio kemiripan 0..1 antara teks sumber dan hasil rewrite
    (difflib atas teks polos)."""
    a = plain_text(source_text)
    b = plain_text(rewritten_html)
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 3)
