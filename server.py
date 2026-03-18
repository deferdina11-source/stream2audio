"""
yt-mp3 API Server v2
Full-stack YouTube to MP3 with search, info, convert, download.
"""

import os
import uuid
import asyncio
import shutil
import subprocess
import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="yt-mp3")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- Config ---
DOWNLOAD_DIR = Path("/tmp/yt-mp3-downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)
MAX_DURATION = 900  # 15 minutes
CLEANUP_AGE_SECONDS = 600
COOKIE_PATH = Path("/tmp/yt_cookies.txt")
SEARCH_LIMIT = 6

def _write_cookies():
    cookie_env = os.environ.get("YT_COOKIES", "").strip()
    if cookie_env:
        COOKIE_PATH.write_text(cookie_env)
        return True
    return False

HAS_COOKIES = _write_cookies()


# --- Models ---
class SearchRequest(BaseModel):
    query: str

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


def _clean_url(url: str) -> str:
    """Strip playlist/tracking params, keep only video ID."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    if 'v' in params:
        clean_query = urlencode({'v': params['v'][0]})
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', clean_query, ''))
    if 'youtu.be' in parsed.netloc:
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
    return url


def _is_youtube_url(text: str) -> bool:
    """Check if text looks like a YouTube URL."""
    patterns = [
        r'youtube\.com/watch',
        r'youtu\.be/',
        r'youtube\.com/shorts/',
        r'youtube\.com/embed/',
        r'm\.youtube\.com/watch',
    ]
    return any(re.search(p, text) for p in patterns)


def _base_cmd() -> list[str]:
    cmd = ["yt-dlp", "--js-runtimes", "node", "--no-playlist"]
    if HAS_COOKIES:
        cmd += ["--cookies", str(COOKIE_PATH)]
    return cmd


def search_youtube(query: str) -> list[dict]:
    """Search YouTube and return list of results."""
    cmd = _base_cmd() + [
        "--ignore-no-formats-error",
        "--no-warnings",
        "--flat-playlist",
        "--dump-json",
        f"ytsearch{SEARCH_LIMIT}:{query}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    results = []
    if result.stdout.strip():
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line.startswith('{'):
                continue
            try:
                data = json.loads(line)
                vid = {
                    "id": data.get("id", ""),
                    "title": data.get("title", "Unknown"),
                    "duration": data.get("duration") or 0,
                    "thumbnail": f"https://img.youtube.com/vi/{data.get('id', '')}/mqdefault.jpg",
                }
                if vid["id"]:
                    results.append(vid)
            except json.JSONDecodeError:
                continue
    return results


def extract_info(url: str) -> dict:
    """Extract metadata for a single video."""
    url = _clean_url(url)
    cmd = _base_cmd() + [
        "--skip-download",
        "--ignore-no-formats-error",
        "--no-warnings",
        "--dump-json",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.stdout.strip():
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line.startswith('{'):
                return json.loads(line)
    raise Exception(result.stderr.strip() or "Could not fetch video info")


def download_audio(url: str, output_dir: Path, quality: int) -> Path | None:
    """Download and convert to MP3."""
    url = _clean_url(url)
    formats = ["bestaudio/best", "bestaudio*", "best"]
    last_error = ""
    for fmt in formats:
        cmd = _base_cmd() + [
            "--no-warnings",
            "--format", fmt,
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", f"{quality}K",
            "-o", str(output_dir / "%(title)s.%(ext)s"),
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        mp3_files = list(output_dir.glob("*.mp3"))
        if mp3_files:
            return mp3_files[0]
        last_error = result.stderr.strip()
        for f in output_dir.glob("*.part"):
            f.unlink(missing_ok=True)
    if last_error:
        raise Exception(last_error)
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
    ]
    for path in candidates:
        if path.exists():
            return HTMLResponse(path.read_text())
    cwd_files = os.listdir(".")
    return HTMLResponse(f"<h1>yt-mp3</h1><p>Frontend not found.</p><pre>{cwd_files}</pre>")


@app.get("/manifest.json")
async def serve_manifest():
    return {"name":"yt-mp3","short_name":"yt-mp3","description":"YouTube to MP3","start_url":"/","display":"standalone","background_color":"#0a0a0a","theme_color":"#e54d2e","icons":[{"src":"/icon.svg","sizes":"any","type":"image/svg+xml"}]}


@app.get("/icon.svg")
async def serve_icon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="96" fill="#0a0a0a"/><path d="M160 380V140l200-33v217" stroke="#e54d2e" stroke-width="32" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="120" cy="380" r="48" stroke="#e54d2e" stroke-width="32" fill="none"/><circle cx="320" cy="347" r="48" stroke="#e54d2e" stroke-width="32" fill="none"/></svg>'
    return HTMLResponse(content=svg, media_type="image/svg+xml")


@app.get("/sw.js")
async def serve_sw():
    return HTMLResponse(content="self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(clients.claim()));self.addEventListener('fetch',e=>e.respondWith(fetch(e.request)));", media_type="application/javascript")


@app.post("/api/search")
async def search(req: SearchRequest):
    """Search YouTube by query."""
    query = req.query.strip()
    if not query or len(query) < 2:
        raise HTTPException(status_code=400, detail="Query too short")
    try:
        results = await asyncio.to_thread(search_youtube, query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
    return results


@app.post("/api/info")
async def get_info(req: ConvertRequest):
    """Get video info."""
    cleanup_old_files()
    if not _is_youtube_url(req.url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    try:
        info = await asyncio.to_thread(extract_info, req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch video info: {str(e)}")
    duration = info.get("duration", 0) or 0
    if duration > MAX_DURATION:
        raise HTTPException(status_code=400, detail=f"Video too long ({duration//60}:{duration%60:02d}). Max is {MAX_DURATION//60} minutes.")
    return VideoInfo(title=info.get("title","Unknown"), duration=duration, thumbnail=info.get("thumbnail"), id=info.get("id",""))


@app.post("/api/convert")
async def convert(req: ConvertRequest):
    """Convert video to MP3."""
    cleanup_old_files()
    url = req.url
    if not _is_youtube_url(url):
        # Might be a video ID
        url = f"https://www.youtube.com/watch?v={url}"

    info = {}
    try:
        info = await asyncio.to_thread(extract_info, url)
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
        mp3_path = await asyncio.to_thread(download_audio, url, job_dir, quality)
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")

    if not mp3_path:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="MP3 not found after conversion")

    size_mb = mp3_path.stat().st_size / (1024 * 1024)
    return ConvertResponse(file_id=file_id, title=info.get("title","Unknown"), duration=duration, size_mb=round(size_mb,1))


@app.get("/api/download/{file_id}")
async def download(file_id: str):
    """Download converted MP3."""
    if not re.match(r'^[a-f0-9]+$', file_id):
        raise HTTPException(status_code=400, detail="Invalid file ID")
    job_dir = DOWNLOAD_DIR / file_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="File expired or not found")
    mp3_files = list(job_dir.glob("*.mp3"))
    if not mp3_files:
        raise HTTPException(status_code=404, detail="MP3 not found")
    return FileResponse(mp3_files[0], media_type="audio/mpeg", filename=mp3_files[0].name)


@app.get("/api/health")
async def health():
    node_v = subprocess.run(["node","--version"], capture_output=True, text=True)
    ytdlp_v = subprocess.run(["yt-dlp","--version"], capture_output=True, text=True)
    return {"status":"ok","cookies":HAS_COOKIES,"node":node_v.stdout.strip(),"ytdlp":ytdlp_v.stdout.strip()}
