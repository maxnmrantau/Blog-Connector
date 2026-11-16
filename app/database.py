import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")

# Standarisasi URI jika Supabase memberikan format 'postgres://' (SQLAlchemy 2.0+ butuh 'postgresql://')
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Jika di Vercel/Serverless dan belum ada DATABASE_URL cloud, gunakan fallback /tmp
if not DATABASE_URL:
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        DATABASE_URL = "sqlite:////tmp/connector.db"
    else:
        DATABASE_URL = "sqlite:///./data/connector.db"

# Pastikan folder lokal ada jika menggunakan SQLite di luar /tmp
if DATABASE_URL.startswith("sqlite") and not DATABASE_URL.startswith("sqlite:////tmp"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except OSError:
            DATABASE_URL = "sqlite:////tmp/connector.db"

# Koneksi engine (check_same_thread hanya untuk SQLite)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True  # Otomatis me-reconnect jika koneksi pooler sempat terputus
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
