from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db, get_engine, SessionLocal

app = FastAPI(
    title="Blog Konektor - Multi-Channel AI Content Engine",
    description="Middleware API yang menghubungkan AI Agent dengan WordPress dan Google Blogger (Blogspot)",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inisialisasi DB saat startup — aman untuk serverless cold-start
_db_ready = False

@app.on_event("startup")
def startup_event():
    global _db_ready
    try:
        engine = init_db()
        # Ikat SessionLocal ke engine yang sudah siap
        SessionLocal.configure(bind=engine)
        _db_ready = True
        print("✅ Database initialized successfully.")
    except Exception as e:
        print(f"⚠️ Database init warning (non-fatal): {e}")

from app.api import routes_channels, routes_ingest, routes_publish  # noqa: E402

app.include_router(routes_channels.router)
app.include_router(routes_ingest.router)
app.include_router(routes_publish.router)

@app.get("/")
def root():
    return {
        "system": "Blog Konektor",
        "status": "online",
        "version": "1.0.0",
        "docs_url": "/docs",
        "database_ready": _db_ready,
        "supported_platforms": ["blogger", "wordpress (next)"]
    }

@app.get("/health")
def health_check():
    return {"status": "healthy", "database_ready": _db_ready}
