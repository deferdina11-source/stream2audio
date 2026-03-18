"""
yt→mp3 API Server
FastAPI backend with yt-dlp for YouTube to MP3 conversion.
Serves the PWA frontend and handles conversion requests.
"""

import os
import uuid
import asyncio
import shutil
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp

app = FastAPI(title="yt→mp3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Config ---
DOWNLOAD_DIR = Path("/tmp/yt-mp3-downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)
MAX_DURATION = 1200  # 20 minutes max
CLEANUP_AGE_SECONDS = 600  # Delete files after 10 minutes


# --- Models ---
class ConvertRequest(BaseModel):
    url: str
    quality: int = 192


class VideoInfo(BaseModel):
    title: str
    duration: int
    thumbnail: str | None
    id: str


class ConvertResponse(BaseModel):
    file_id: str
    title: str
    duration: int
    size_mb: float


# --- Helpers ---
def cleanup_old_files():
    """Remove downloads older than CLEANUP_AGE_SECONDS."""
    import time
    now = time.time()
    for item in DOWNLOAD_DIR.iterdir():
        if item.is_dir() and (now - item.stat().st_mtime) > CLEANUP_AGE_SECONDS:
            shutil.rmtree(item, ignore_errors=True)


def _get_base_opts() -> dict:
    """Common yt-dlp options to avoid bot detection."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
            "Sec-Fetch-Mode": "navigate",
        },
        "extractor_args": {"youtube": {"player_client": ["web"]}},
        "socket_timeout": 30,
    }

    # Support cookies via environment variable
    cookie_env = os.environ.get("YT_COOKIES", "").strip()
    if cookie_env:
        cookie_path = Path("/tmp/yt_cookies.txt")
        cookie_path.write_text(cookie_env)
        opts["cookiefile"] = str(cookie_path)

    return opts


def extract_info(url: str) -> dict:
    """Extract video metadata without downloading."""
    ydl_opts = {
        **_get_base_opts(),
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def download_audio(url: str, output_dir: Path, quality: int) -> Path | None:
    """Download and convert to MP3."""
    ydl_opts = {
        **_get_base_opts(),
        "format": "bestaudio*",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(quality),
            }
        ],
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Find the resulting MP3
    mp3_files = list(output_dir.glob("*.mp3"))
    return mp3_files[0] if mp3_files else None


# --- Routes ---
@app.get("/")
async def serve_frontend():
    """Serve the PWA frontend."""
    # Try multiple possible locations
    candidates = [
        Path(__file__).parent / "static" / "index.html",
        Path("/app/static /index.html"),
        Path("static/index.html"),
        Path(__file__).parent / "index.html",
        Path("/app/index.html"),
        Path("index.html"),
    ]
    for path in candidates:
        if path.exists():
            return HTMLResponse(path.read_text())
    # Debug: show what paths were tried
    tried = [str(p) + (" EXISTS" if p.exists() else " MISSING") for p in candidates]
    import os
    cwd_files = os.listdir(".")
    return HTMLResponse(
        f"<h1>yt→mp3</h1><p>Frontend not found.</p>"
        f"<pre>CWD: {os.getcwd()}\nFiles: {cwd_files}\nTried: {tried}</pre>"
    )


@app.get("/manifest.json")
async def serve_manifest():
    """PWA manifest."""
    return {
        "name": "yt→mp3",
        "short_name": "yt→mp3",
        "description": "YouTube to MP3 converter",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0e0e0e",
        "theme_color": "#FF4B2B",
        "icons": [
            {
                "src": "/icon-192.svg",
                "sizes": "192x192",
                "type": "image/svg+xml",
            },
            {
                "src": "/icon-512.svg",
                "sizes": "512x512",
                "type": "image/svg+xml",
            },
        ],
    }


@app.get("/icon-192.svg")
@app.get("/icon-512.svg")
async def serve_icon():
    """App icon as SVG."""
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
        <rect width="512" height="512" rx="96" fill="#0e0e0e"/>
        <path d="M160 380V140l200-33v217" stroke="#FF4B2B" stroke-width="32" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        <circle cx="120" cy="380" r="48" stroke="#FF4B2B" stroke-width="32" fill="none"/>
        <circle cx="320" cy="347" r="48" stroke="#FF4B2B" stroke-width="32" fill="none"/>
    </svg>'''
    return HTMLResponse(content=svg, media_type="image/svg+xml")


@app.get("/sw.js")
async def serve_sw():
    """Minimal service worker for PWA install."""
    js = """
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));
self.addEventListener('fetch', e => e.respondWith(fetch(e.request)));
"""
    return HTMLResponse(content=js, media_type="application/javascript")


@app.post("/api/info")
async def get_info(req: ConvertRequest):
    """Get video info before converting."""
    cleanup_old_files()
    try:
        info = await asyncio.to_thread(extract_info, req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch video info: {str(e)}")

    duration = info.get("duration", 0) or 0
    if duration > MAX_DURATION:
        raise HTTPException(
            status_code=400,
            detail=f"Video too long ({duration // 60}min). Max is {MAX_DURATION // 60}min.",
        )

    return VideoInfo(
        title=info.get("title", "Unknown"),
        duration=duration,
        thumbnail=info.get("thumbnail"),
        id=info.get("id", ""),
    )


@app.post("/api/convert")
async def convert(req: ConvertRequest):
    """Convert YouTube video to MP3 and return download info."""
    cleanup_old_files()

    # Validate
    try:
        info = await asyncio.to_thread(extract_info, req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    duration = info.get("duration", 0) or 0
    if duration > MAX_DURATION:
        raise HTTPException(status_code=400, detail="Video too long")

    quality = max(128, min(320, req.quality))

    # Download
    file_id = uuid.uuid4().hex[:12]
    job_dir = DOWNLOAD_DIR / file_id
    job_dir.mkdir(exist_ok=True)

    try:
        mp3_path = await asyncio.to_thread(download_audio, req.url, job_dir, quality)
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")

    if not mp3_path:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="MP3 file not found after conversion")

    size_mb = mp3_path.stat().st_size / (1024 * 1024)

    return ConvertResponse(
        file_id=file_id,
        title=info.get("title", "Unknown"),
        duration=duration,
        size_mb=round(size_mb, 1),
    )


@app.get("/api/download/{file_id}")
async def download(file_id: str):
    """Download the converted MP3."""
    job_dir = DOWNLOAD_DIR / file_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="File expired or not found")

    mp3_files = list(job_dir.glob("*.mp3"))
    if not mp3_files:
        raise HTTPException(status_code=404, detail="MP3 not found")

    return FileResponse(
        mp3_files[0],
        media_type="audio/mpeg",
        filename=mp3_files[0].name,
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}
