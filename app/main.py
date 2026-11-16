from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db, SessionLocal
from app.routes_dashboard import get_current_session

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

_db_ready = False

@app.on_event("startup")
def startup_event():
    global _db_ready
    try:
        engine = init_db()
        SessionLocal.configure(bind=engine)
        _db_ready = True
        print("✅ Database initialized successfully.")
    except Exception as e:
        print(f"⚠️ Database init warning (non-fatal): {e}")

# Registrasi Router
from app.api import routes_channels, routes_ingest, routes_publish, routes_pages, routes_auth
from app import routes_dashboard, routes_oauth

app.include_router(routes_dashboard.router)
app.include_router(routes_oauth.router)
app.include_router(routes_auth.router)
app.include_router(routes_channels.router)
app.include_router(routes_ingest.router)
app.include_router(routes_publish.router)
app.include_router(routes_pages.router)

@app.get("/")
def root(request: Request):
    # Jika diakses lewat browser (Accept: text/html), arahkan ke dashboard
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        if get_current_session(request):
            return RedirectResponse(url="/dashboard", status_code=303)
        return RedirectResponse(url="/login", status_code=303)

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
