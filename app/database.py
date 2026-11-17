import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

# Session tanpa engine dulu (dikonfigurasi saat startup / init_db())
SessionLocal = sessionmaker(autocommit=False, autoflush=False)

def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "")

    # Standarisasi prefix: gunakan psycopg2 secara eksplisit agar SQLAlchemy 2.x tidak salah driver
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    if url and ("supabase.co" in url or "supabase.com" in url):
        sep = "&" if "?" in url else "?"
        if "sslmode" not in url:
            url = f"{url}{sep}sslmode=require"

    if not url:
        if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
            url = "sqlite:////tmp/connector.db"
        else:
            local_dir = "./data"
            os.makedirs(local_dir, exist_ok=True)
            url = f"sqlite:///{local_dir}/connector.db"

    return url

_engine = None

def get_engine():
    global _engine
    if _engine is None:
        url = _get_database_url()
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    return _engine

def get_db():
    """Dependency injector untuk FastAPI routes — engine sudah terikat saat startup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _ensure_channel_blog_columns(engine):
    """Tambah kolom blog_id/blog_url ke tabel channels yang sudah ada.

    create_all() tidak mengubah tabel lama, jadi tanpa ini kolom baru di
    models.Channel tidak akan pernah muncul di database production.
    """
    from sqlalchemy import inspect, text
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("channels")}
    except Exception:
        return
    missing = []
    if "blog_id" not in cols:
        missing.append(("blog_id", "VARCHAR(50)"))
    if "blog_url" not in cols:
        missing.append(("blog_url", "VARCHAR(500)"))
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE channels ADD COLUMN {name} {ddl}"))

def _ensure_feed_sources_table(engine):
    """Tambah kolom yang kurang ke tabel feed_sources yang sudah ada.

    Mengikuti pola _ensure_channel_blog_columns: create_all() tidak mengubah
    tabel lama, jadi tanpa ini kolom baru tidak akan pernah muncul di
    database production. Tabelnya sendiri dibuat oleh create_all() di
    init_db() bila belum ada.
    """
    from sqlalchemy import inspect, text
    try:
        tables = inspect(engine).get_table_names()
    except Exception:
        return
    if "feed_sources" not in tables:
        return  # create_all() sudah membuatnya
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("feed_sources")}
    except Exception:
        return
    expected = {
        "channel_id": "VARCHAR(50)",
        "feed_url": "VARCHAR(500)",
        "title": "VARCHAR(300)",
        "active": "BOOLEAN",
        "last_checked_at": "TIMESTAMP",
        "created_at": "TIMESTAMP",
    }
    missing = [(name, ddl) for name, ddl in expected.items() if name not in cols]
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE feed_sources ADD COLUMN {name} {ddl}"))

def _ensure_publication_scheduled_at(engine):
    """Tambah kolom scheduled_at ke tabel publications yang sudah ada.

    create_all() tidak mengubah tabel lama, jadi tanpa ini kolom baru di
    models.Publication tidak akan pernah muncul di database production
    dan dashboard akan 500 (OperationalError: no such column:
    publications.scheduled_at) karena query daftar terjadwal selalu
    memilih kolom tersebut.
    """
    from sqlalchemy import inspect, text
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("publications")}
    except Exception:
        return
    if "scheduled_at" in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE publications ADD COLUMN scheduled_at TIMESTAMP"))

def _ensure_channel_auto_publish(engine):
    """Tambah kolom auto_publish ke tabel channels yang sudah ada.

    create_all() tidak mengubah tabel lama, jadi tanpa ini kolom baru di
    models.Channel tidak akan pernah muncul di database production dan
    toggle auto-publish di dashboard akan gagal (OperationalError).
    """
    from sqlalchemy import inspect, text
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("channels")}
    except Exception:
        return
    if "auto_publish" in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE channels ADD COLUMN auto_publish BOOLEAN DEFAULT FALSE"))

def _ensure_settings_table(engine):
    """Buat tabel settings bila belum ada (database production lama).

    create_all() sebenarnya membuat tabel baru yang belum ada, jadi
    pemanggilan ini hanya pengaman: tabel tetap dibuat walau init_db()
    berjalan dengan metadata yang belum memuat model Setting.
    """
    from sqlalchemy import inspect, text
    try:
        tables = inspect(engine).get_table_names()
    except Exception:
        return
    if "settings" in tables:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE settings ("
            "key VARCHAR(100) NOT NULL PRIMARY KEY, "
            "value TEXT NOT NULL DEFAULT '', "
            "updated_at TIMESTAMP)"
        ))

def init_db():
    """Panggil eksplisit untuk membuat tabel dan mengikat SessionLocal ke engine."""
    engine = get_engine()
    SessionLocal.configure(bind=engine)
    Base.metadata.create_all(bind=engine)
    _ensure_channel_blog_columns(engine)
    _ensure_feed_sources_table(engine)
    _ensure_publication_scheduled_at(engine)
    _ensure_settings_table(engine)
    _ensure_channel_auto_publish(engine)
    return engine

# Untuk keperluan lokal/testing — jalankan langsung tanpa server
if __name__ == "__main__":
    init_db()
    print("Database initialized locally.")
