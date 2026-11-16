# Multi-Channel Blog Connector & AI Content Engine

Sistem jembatan (middleware & API) untuk menghubungkan **AI Agent** dengan berbagai platform blog (**WordPress REST API** & **Google Blogger API v3**). Dirancang khusus untuk mengelola banyak akun blog secara simultan dengan kemampuan adaptasi sudut pandang unik (*Multi-Angle Content Adaptation*) per niche blog.

---

## 📚 Dokumentasi Utama
1. **[docs/PROJECT_BLUEPRINT.md](file:///d:/CODING/Blog%20Konektor/docs/PROJECT_BLUEPRINT.md)**: Arsitektur lengkap sistem, matriks fitur (Fase 1-3), pilihan tech stack, dan struktur direktori.
2. **[docs/AGENT_GUIDE.md](file:///d:/CODING/Blog%20Konektor/docs/AGENT_GUIDE.md)**: Standard Operating Procedure (SOP) untuk AI Agent (aturan adaptasi niche, standar format HTML & SEO, atribusi etis, dan skema payload API).

---

## 🚀 Fitur Utama
* **Multi-Account & Multi-Platform:** Menghubungkan banyak website WordPress dan blog Blogger/Blogspot dalam satu kontrol terpusat.
* **Intelligent Source Ingestion:** Input fleksibel melalui URL web berita langsung (ekstraksi teks bersih tanpa iklan) atau pemantauan RSS feeds.
* **Multi-Angle Recontextualization:** Dari 1 topik/isu berita, AI menulis versi artikel yang berbeda sesuai karakter & niche tiap blog (bukan sekadar spin kata).
* **Ethical SEO & Source Attribution:** Mengutamakan kredibilitas E-E-A-T dengan pencantuman atribusi sumber asli dan struktur HTML semantik.
* **Drip-Feed Scheduling & Human-in-the-Loop:** Menjadwalkan publikasi secara bertahap dan opsi persetujuan draf via Telegram Bot sebelum terbit.
