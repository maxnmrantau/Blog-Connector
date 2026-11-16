from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.api import routes_channels, routes_ingest, routes_publish

# Buat tabel-tabel database jika belum ada
Base.metadata.create_all(bind=engine)

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
def root():
    return {
        "system": "Blog Konektor",
        "status": "online",
        "version": "1.0.0",
        "docs_url": "/docs",
        "supported_platforms": ["blogger", "wordpress (next)"]
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}
