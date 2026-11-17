"""Auto-Rewrite: tulis ulang artikel sumber menjadi artikel baru yang
orisinal memakai provider AI aktif (Gemini atau OpenAI, REST, httpx).

Keamanan & kualitas:
- Kunci AI diambil dari tabel settings (Pengaturan AI), TIDAK PERNAH
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
        raise GeminiError(
            f"Tidak dapat menghubungi Gemini API: {type(e).__name__}: {e}"
        )
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


OPENAI_BASE_URL = "https://api.openai.com"
# Model OpenAI default: gpt-4o-mini ($0,15/1 jt token input, $0,60/1 jt
# output). TIDAK ADA model "gpt-4o-nano" — yang ada gpt-4.1-nano
# ($0,10/$0,40) dan gpt-5-nano ($0,05/$0,40). Bisa diubah lewat
# setting "openai_model" di Pengaturan AI. OpenAI BERBAYAR dari token
# pertama (tidak ada free tier) — butuh saldo/billing di platform.openai.com.
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class OpenAIError(Exception):
    """Kegagalan memanggil OpenAI API (jaringan, kunci salah, saldo, dll)."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _is_reasoning_model(model):
    """True untuk model reasoning OpenAI (keluarga gpt-5, o1, o3).

    Model reasoning tidak menerima temperature selain 1 dan tidak
    menerima parameter max_tokens (pakai max_completion_tokens).
    """
    m = (model or "").strip().lower()
    return m.startswith("gpt-5") or m.startswith("o1") or m.startswith("o3")


def generate_text_openai(api_key, prompt, model=DEFAULT_OPENAI_MODEL,
                         temperature=0.7, max_output_tokens=8192,
                         http_client=None):
    """Panggil OpenAI Chat Completions (REST) dan kembalikan teks hasilnya.

    http_client hanya dipakai tes (mock) — bila None, dibuatkan
    httpx.Client baru dengan timeout 120 detik. Kunci TIDAK PERNAH
    ditulis ke log (hanya dikirim di header Authorization).
    """
    url = f"{OPENAI_BASE_URL}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if _is_reasoning_model(model):
        # Model reasoning: temperature hanya boleh 1 (default) dan
        # batas output memakai max_completion_tokens.
        payload["max_completion_tokens"] = max_output_tokens
    else:
        payload["temperature"] = temperature
        payload["max_tokens"] = max_output_tokens
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    own_client = http_client is None
    client = http_client or httpx.Client(timeout=120.0)
    try:
        resp = client.post(url, headers=headers, json=payload)
    except httpx.RequestError as e:
        raise OpenAIError(
            f"Tidak dapat menghubungi OpenAI API: {type(e).__name__}: {e}"
        )
    finally:
        if own_client:
            client.close()
    if resp.status_code != 200:
        try:
            err = resp.json().get("error", {}) or {}
            msg = err.get("message") or resp.text
            code = err.get("code") or ""
        except Exception:
            msg = resp.text
            code = ""
        raise OpenAIError(
            f"OpenAI API error [{resp.status_code}]: {msg}"
            + (f" (code: {code})" if code else ""),
            status_code=resp.status_code,
        )
    try:
        data = resp.json()
        choices = data.get("choices", []) or []
        text = (choices[0].get("message", {}) or {}).get("content") or ""
    except Exception:
        raise OpenAIError("Respons OpenAI bukan JSON yang valid.")
    text = (text or "").strip()
    if not text:
        raise OpenAIError("OpenAI mengembalikan respons kosong (tidak ada teks).")
    return text


def generate_with_provider(db, prompt, temperature=0.7,
                           max_output_tokens=8192, http_client=None):
    """Panggil provider AI aktif dari settings (Gemini/OpenAI).

    Mengembalikan (teks, provider, model). Provider dibaca dari setting
    "ai_provider" ("gemini" default bila kosong/tidak dikenal). Bila
    provider OpenAI dipilih tapi kuncinya belum dikonfigurasi, raise
    OpenAIError dengan pesan yang jelas (begitu pula Gemini).
    """
    from app.services.settings import (
        AI_PROVIDER,
        GEMINI_API_KEY,
        OPENAI_API_KEY,
        OPENAI_MODEL,
        get_setting_value,
    )

    provider = (get_setting_value(db, AI_PROVIDER) or "gemini").strip().lower()
    if provider not in ("gemini", "openai"):
        provider = "gemini"
    if provider == "openai":
        api_key = get_setting_value(db, OPENAI_API_KEY)
        if not api_key:
            raise OpenAIError(
                "Kunci OpenAI belum dikonfigurasi di Pengaturan AI. "
                "Tempel kunci OpenAI dulu, simpan, lalu coba lagi."
            )
        model = get_setting_value(db, OPENAI_MODEL) or DEFAULT_OPENAI_MODEL
        return (
            generate_text_openai(
                api_key, prompt, model=model, temperature=temperature,
                max_output_tokens=max_output_tokens, http_client=http_client,
            ),
            "openai",
            model,
        )
    api_key = get_setting_value(db, GEMINI_API_KEY)
    if not api_key:
        raise GeminiError(
            "Kunci Gemini belum dikonfigurasi di Pengaturan AI. "
            "Tempel kunci Gemini dulu, simpan, lalu coba lagi."
        )
    model = get_setting_value(db, "gemini_model") or DEFAULT_MODEL
    return (
        generate_text(
            api_key, prompt, model=model, temperature=temperature,
            max_output_tokens=max_output_tokens, http_client=http_client,
        ),
        "gemini",
        model,
    )


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
