from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.api import routes_channels, routes_ingest, routes_publish

# Inisialisasi tabel database dengan penanganan error aman (agar serverless tidak crash saat cold-start)
db_init_status = "connected"
db_init_error = None

try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    db_init_status = "error"
    db_init_error = str(e)
    print(f"⚠️ Warning Database Connection Failed: {e}")

app = FastAPI(
    title="Blog Konektor - Multi-Channel AI Content Engine",
    description="Middleware API yang menghubungkan AI Agent dengan WordPress dan Google Blogger (Blogspot)",
    version="1.0.0"
)

# CORS middleware agar bisa diakses dari dashboard web lokal mana saja
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrasi Router
app.include_router(routes_channels.router)
app.include_router(routes_ingest.router)
app.include_router(routes_publish.router)

@app.get("/")
@app.get("/api/index.py")
def root():
    return {
        "system": "Blog Konektor",
        "status": "online",
        "version": "1.0.0",
        "docs_url": "/docs",
        "database": {
            "status": db_init_status,
            "error": db_init_error
        },
        "supported_platforms": ["blogger", "wordpress (next)"]
    }

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database": db_init_status
    }
