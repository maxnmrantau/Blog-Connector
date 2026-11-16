import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

# Session tanpa engine dulu (dikonfigurasi saat startup / init_db())
SessionLocal = sessionmaker(autocommit=False, autoflush=False)

def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "")

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

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

def init_db():
    """Panggil eksplisit untuk membuat tabel dan mengikat SessionLocal ke engine."""
    engine = get_engine()
    SessionLocal.configure(bind=engine)
    Base.metadata.create_all(bind=engine)
    return engine

# Untuk keperluan lokal/testing — jalankan langsung tanpa server
if __name__ == "__main__":
    init_db()
    print("Database initialized locally.")
