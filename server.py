"""
yt-mp3 API Server
FastAPI backend with yt-dlp for YouTube to MP3 conversion.
"""

import os
import uuid
import asyncio
import shutil
import subprocess
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="yt-mp3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Config ---
DOWNLOAD_DIR = Path("/tmp/yt-mp3-downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)
MAX_DURATION = 1200
CLEANUP_AGE_SECONDS = 600
COOKIE_PATH = Path("/tmp/yt_cookies.txt")

def _write_cookies():
    cookie_env = os.environ.get("YT_COOKIES", "").strip()
    if cookie_env:
        COOKIE_PATH.write_text(cookie_env)
        return True
    return False

HAS_COOKIES = _write_cookies()


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
    import time
    now = time.time()
    if DOWNLOAD_DIR.exists():
        for item in DOWNLOAD_DIR.iterdir():
            if item.is_dir() and (now - item.stat().st_mtime) > CLEANUP_AGE_SECONDS:
                shutil.rmtree(item, ignore_errors=True)


def _run_ytdlp(args: list[str]) -> subprocess.CompletedProcess:
    """Run yt-dlp as a subprocess with Node.js runtime enabled."""
    cmd = [
        "yt-dlp",
        "--no-js-runtimes",        # clear defaults
        "--js-runtimes", "node",   # enable Node.js
        "--quiet",
        "--no-warnings",
    ]
    if HAS_COOKIES:
        cmd += ["--cookies", str(COOKIE_PATH)]
    cmd += args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def extract_info(url: str) -> dict:
    """Extract metadata using yt-dlp CLI."""
    import json
    result = _run_ytdlp([
        "--skip-download",
        "--print-json",
        url,
    ])
    if result.stdout.strip():
        return json.loads(result.stdout.strip().split('\n')[0])
    # If JSON output failed, try with --dump-json
    result2 = _run_ytdlp([
        "--skip-download",
        "--dump-json",
        url,
    ])
    if result2.stdout.strip():
        return json.loads(result2.stdout.strip().split('\n')[0])
    raise Exception(result.stderr or result2.stderr or "Could not fetch video info")


def download_audio(url: str, output_dir: Path, quality: int) -> Path | None:
    """Download and convert to MP3 using yt-dlp CLI."""
    formats_to_try = [
        "bestaudio/best",
        "bestaudio*",
        "best",
    ]

    last_error = ""
    for fmt in formats_to_try:
        result = _run_ytdlp([
            "-f", fmt,
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", str(quality) + "K",
            "-o", str(output_dir / "%(title)s.%(ext)s"),
            url,
        ])

        mp3_files = list(output_dir.glob("*.mp3"))
        if mp3_files:
            return mp3_files[0]

        last_error = result.stderr
        # Clean partial files
        for f in output_dir.glob("*.part"):
            f.unlink(missing_ok=True)

    if last_error:
        raise Exception(last_error.strip())
    return None


# --- Routes ---
@app.get("/")
async def serve_frontend():
    candidates = [
        Path(__file__).parent / "static" / "index.html",
        Path("/app/static/index.html"),
        Path("/app/static /index.html"),
        Path("static/index.html"),
        Path("static /index.html"),
        Path(__file__).parent / "index.html",
        Path("/app/index.html"),
        Path("index.html"),
    ]
    for path in candidates:
        if path.exists():
            return HTMLResponse(path.read_text())
    tried = [str(p) + (" EXISTS" if p.exists() else " MISSING") for p in candidates]
    cwd_files = os.listdir(".")
    return HTMLResponse(
        f"<h1>yt-mp3</h1><p>Frontend not found.</p>"
        f"<pre>CWD: {os.getcwd()}\nFiles: {cwd_files}\nTried: {tried}</pre>"
    )


@app.get("/manifest.json")
async def serve_manifest():
    return {
        "name": "yt-mp3", "short_name": "yt-mp3",
        "description": "YouTube to MP3 converter",
        "start_url": "/", "display": "standalone",
        "background_color": "#0e0e0e", "theme_color": "#FF4B2B",
        "icons": [
            {"src": "/icon-192.svg", "sizes": "192x192", "type": "image/svg+xml"},
            {"src": "/icon-512.svg", "sizes": "512x512", "type": "image/svg+xml"},
        ],
    }

@app.get("/icon-192.svg")
@app.get("/icon-512.svg")
async def serve_icon():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
        <rect width="512" height="512" rx="96" fill="#0e0e0e"/>
        <path d="M160 380V140l200-33v217" stroke="#FF4B2B" stroke-width="32" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        <circle cx="120" cy="380" r="48" stroke="#FF4B2B" stroke-width="32" fill="none"/>
        <circle cx="320" cy="347" r="48" stroke="#FF4B2B" stroke-width="32" fill="none"/>
    </svg>'''
    return HTMLResponse(content=svg, media_type="image/svg+xml")

@app.get("/sw.js")
async def serve_sw():
    js = "self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(clients.claim()));self.addEventListener('fetch',e=>e.respondWith(fetch(e.request)));"
    return HTMLResponse(content=js, media_type="application/javascript")


@app.post("/api/info")
async def get_info(req: ConvertRequest):
    cleanup_old_files()
    try:
        info = await asyncio.to_thread(extract_info, req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch video info: {str(e)}")
    duration = info.get("duration", 0) or 0
    if duration > MAX_DURATION:
        raise HTTPException(status_code=400, detail=f"Video too long ({duration//60}min). Max {MAX_DURATION//60}min.")
    return VideoInfo(
        title=info.get("title", "Unknown"),
        duration=duration,
        thumbnail=info.get("thumbnail"),
        id=info.get("id", ""),
    )


@app.post("/api/convert")
async def convert(req: ConvertRequest):
    cleanup_old_files()
    info = {}
    try:
        info = await asyncio.to_thread(extract_info, req.url)
    except Exception:
        pass

    duration = info.get("duration", 0) or 0
    if duration > MAX_DURATION and duration > 0:
        raise HTTPException(status_code=400, detail="Video too long")

    quality = max(128, min(320, req.quality))
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
    job_dir = DOWNLOAD_DIR / file_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="File expired or not found")
    mp3_files = list(job_dir.glob("*.mp3"))
    if not mp3_files:
        raise HTTPException(status_code=404, detail="MP3 not found")
    return FileResponse(mp3_files[0], media_type="audio/mpeg", filename=mp3_files[0].name)


@app.get("/api/health")
async def health():
    node_check = subprocess.run(["node", "--version"], capture_output=True, text=True)
    ytdlp_check = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
    return {
        "status": "ok",
        "cookies": HAS_COOKIES,
        "node": node_check.stdout.strip(),
        "ytdlp": ytdlp_check.stdout.strip(),
    }
