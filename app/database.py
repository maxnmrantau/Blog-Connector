import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")

# Jika di Vercel/Serverless dan belum ada DATABASE_URL cloud, gunakan /tmp (folder satu-satunya yang bisa ditulisi di Vercel)
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
            # Fallback jika filesystem berstatus read-only (seperti di Vercel / AWS Lambda)
            DATABASE_URL = "sqlite:////tmp/connector.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
