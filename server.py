from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

APP_TITLE = "stream2audio"
DOWNLOAD_DIR = Path("/tmp/stream2audio-downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_DURATION_SECONDS = 15 * 60
CLEANUP_AGE_SECONDS = 10 * 60
SEARCH_LIMIT = 8
COOKIE_PATH = Path("/tmp/yt_cookies.txt")


def write_cookies() -> bool:
    cookie_env = os.environ.get("YT_COOKIES", "").strip()
    if cookie_env:
        COOKIE_PATH.write_text(cookie_env, encoding="utf-8")
        return True
    return False


HAS_COOKIES = write_cookies()

app = FastAPI(title=APP_TITLE)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class InfoRequest(BaseModel):
    url: str = Field(min_length=1)


class ConvertRequest(BaseModel):
    url: str = Field(min_length=1)
    quality: int = 192


def json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return json_error(exc.status_code, detail)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_, exc: Exception):
    return json_error(500, f"Internal server error: {str(exc)}")


def cleanup_old_files() -> None:
    now = time.time()
    for item in DOWNLOAD_DIR.iterdir():
        try:
            if item.is_dir() and (now - item.stat().st_mtime) > CLEANUP_AGE_SECONDS:
                shutil.rmtree(item, ignore_errors=True)
        except FileNotFoundError:
            continue


def is_youtube_url(value: str) -> bool:
    value = value.strip().lower()
    return any(
        token in value
        for token in (
            "youtube.com/watch",
            "m.youtube.com/watch",
            "youtu.be/",
            "youtube.com/shorts/",
            "youtube.com/embed/",
        )
    )


def normalize_youtube_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    params = parse_qs(parsed.query)

    if "youtu.be" in host:
        return urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path, "", "", ""))

    if "youtube.com" in host:
        if parsed.path.startswith("/watch") and "v" in params:
            clean_query = urlencode({"v": params["v"][0]})
            return urlunparse((parsed.scheme or "https", parsed.netloc, "/watch", "", clean_query, ""))

        if parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]
            return f"https://www.youtube.com/watch?v={video_id}"

        if parsed.path.startswith("/embed/"):
            video_id = parsed.path.split("/embed/", 1)[1].split("/", 1)[0]
            return f"https://www.youtube.com/watch?v={video_id}"

    return url


def sanitize_filename(value: str) -> str:
    value = re.sub(r'[\\/*?:"<>|]+', "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:180] or "audio"


def base_cmd() -> list[str]:
    cmd = ["yt-dlp", "--no-playlist", "--no-warnings", "--js-runtimes", "node"]
    if HAS_COOKIES:
        cmd += ["--cookies", str(COOKIE_PATH)]
    return cmd


def run_cmd(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def parse_json_lines(stdout: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def normalize_item(info: dict[str, Any]) -> dict[str, Any]:
    vid = info.get("id", "") or ""
    webpage_url = info.get("webpage_url") or info.get("original_url")
    if not webpage_url and vid:
        webpage_url = f"https://www.youtube.com/watch?v={vid}"

    thumb = info.get("thumbnail")
    if not thumb and vid:
        thumb = f"https://img.youtube.com/vi/{vid}/mqdefault.jpg"

    return {
        "id": vid,
        "title": info.get("title", "Unknown") or "Unknown",
        "duration": int(info.get("duration") or 0),
        "thumbnail": thumb,
        "webpage_url": webpage_url,
    }


def search_youtube(query: str, limit: int = SEARCH_LIMIT) -> list[dict[str, Any]]:
    cmd = base_cmd() + [
        "--skip-download",
        "--dump-json",
        f"ytsearch{limit}:{query}",
    ]
    result = run_cmd(cmd, timeout=120)
    rows = parse_json_lines(result.stdout)
    if not rows:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "Search returned no results")

    items = [normalize_item(row) for row in rows]
    return [item for item in items if item["id"] and item["webpage_url"]]


def extract_info(url: str) -> dict[str, Any]:
    url = normalize_youtube_url(url)
    cmd = base_cmd() + [
        "--skip-download",
        "--dump-json",
        url,
    ]
    result = run_cmd(cmd, timeout=120)
    rows = parse_json_lines(result.stdout)
    if rows:
        return normalize_item(rows[0])

    stderr = (result.stderr or "").strip()
    raise RuntimeError(stderr or "Could not fetch video info")


def download_audio(url: str, output_dir: Path, quality: int) -> Path:
    url = normalize_youtube_url(url)
    quality = max(128, min(320, int(quality)))
    formats = ["bestaudio/best", "bestaudio*", "best"]
    last_error = ""

    for fmt in formats:
        cmd = base_cmd() + [
            "--format",
            fmt,
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            f"{quality}K",
            "--output",
            str(output_dir / "%(title)s.%(ext)s"),
            url,
        ]
        result = run_cmd(cmd, timeout=300)

        mp3_files = sorted(output_dir.glob("*.mp3"))
        if mp3_files:
            chosen = mp3_files[0]
            clean_name = sanitize_filename(chosen.stem) + ".mp3"
            final_path = chosen.with_name(clean_name)
            if chosen != final_path:
                chosen.rename(final_path)
            return final_path

        last_error = (result.stderr or "").strip()
        for part_file in output_dir.glob("*.part"):
            part_file.unlink(missing_ok=True)

    raise RuntimeError(last_error or "Conversion failed")


@app.get("/")
async def serve_frontend():
    candidates = [
        Path(__file__).parent / "index.html",
        Path(__file__).parent / "static" / "index.html",
        Path("/app/index.html"),
        Path("/app/static/index.html"),
        Path("index.html"),
        Path("static/index.html"),
    ]
    for path in candidates:
        if path.exists():
            return HTMLResponse(path.read_text(encoding="utf-8"))

    return HTMLResponse("<h1>stream2audio</h1><p>Frontend not found.</p>", status_code=500)


@app.get("/manifest.json")
async def serve_manifest():
    return {
        "name": "stream2audio",
        "short_name": "stream2audio",
        "description": "Search and convert YouTube audio to MP3",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0e0e0e",
        "theme_color": "#ff4b2b",
        "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}],
    }


@app.get("/icon.svg")
async def serve_icon():
    svg = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
      <rect width="512" height="512" rx="96" fill="#0e0e0e"/>
      <path d="M160 380V140l200-33v217" stroke="#ff4b2b" stroke-width="32" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
      <circle cx="120" cy="380" r="48" stroke="#ff4b2b" stroke-width="32" fill="none"/>
      <circle cx="320" cy="347" r="48" stroke="#ff4b2b" stroke-width="32" fill="none"/>
    </svg>
    """
    return HTMLResponse(content=svg.strip(), media_type="image/svg+xml")


@app.get("/sw.js")
async def serve_sw():
    script = """
self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(clients.claim()));
self.addEventListener('fetch', (e) => e.respondWith(fetch(e.request)));
    """
    return HTMLResponse(content=script.strip(), media_type="application/javascript")


@app.post("/api/search")
async def api_search(req: SearchRequest):
    cleanup_old_files()
    query = req.query.strip()

    if len(query) < 2:
        raise HTTPException(status_code=400, detail="Query too short")

    if is_youtube_url(query):
        item = await asyncio.to_thread(extract_info, query)
        if item["duration"] > MAX_DURATION_SECONDS:
            raise HTTPException(status_code=400, detail="Video too long")
        return {"success": True, "items": [item]}

    items = await asyncio.to_thread(search_youtube, query, SEARCH_LIMIT)
    items = [item for item in items if item["duration"] <= MAX_DURATION_SECONDS]
    return {"success": True, "items": items}


@app.post("/api/info")
async def api_info(req: InfoRequest):
    cleanup_old_files()
    raw = req.url.strip()

    if not is_youtube_url(raw):
        raise HTTPException(status_code=400, detail="Enter a valid YouTube URL")

    item = await asyncio.to_thread(extract_info, raw)
    if item["duration"] > MAX_DURATION_SECONDS:
        raise HTTPException(status_code=400, detail=f"Video too long. Max is {MAX_DURATION_SECONDS // 60} minutes.")

    return {"success": True, "item": item}


@app.post("/api/convert")
async def api_convert(req: ConvertRequest):
    cleanup_old_files()
    raw = req.url.strip()

    if not is_youtube_url(raw):
        raise HTTPException(status_code=400, detail="Enter a valid YouTube URL")

    item = await asyncio.to_thread(extract_info, raw)
    if item["duration"] > MAX_DURATION_SECONDS:
        raise HTTPException(status_code=400, detail="Video too long")

    file_id = uuid.uuid4().hex[:12]
    job_dir = DOWNLOAD_DIR / file_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        mp3_path = await asyncio.to_thread(download_audio, raw, job_dir, req.quality)
        size_mb = round(mp3_path.stat().st_size / (1024 * 1024), 1)
        return {
            "success": True,
            "file_id": file_id,
            "title": item["title"],
            "duration": item["duration"],
            "size_mb": size_mb,
        }
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(exc)}") from exc


@app.get("/api/download/{file_id}")
async def api_download(file_id: str):
    if not re.fullmatch(r"[a-f0-9]{12}", file_id):
        raise HTTPException(status_code=400, detail="Invalid file ID")

    job_dir = DOWNLOAD_DIR / file_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="File expired or not found")

    mp3_files = sorted(job_dir.glob("*.mp3"))
    if not mp3_files:
        raise HTTPException(status_code=404, detail="MP3 not found")

    file_path = mp3_files[0]
    return FileResponse(
        file_path,
        media_type="audio/mpeg",
        filename=file_path.name,
    )


@app.get("/api/health")
async def api_health():
    node_v = run_cmd(["node", "--version"], timeout=10).stdout.strip()
    ytdlp_v = run_cmd(["yt-dlp", "--version"], timeout=10).stdout.strip()
    return {
        "success": True,
        "status": "ok",
        "cookies": HAS_COOKIES,
        "node": node_v,
        "ytdlp": ytdlp_v,
        "max_duration_seconds": MAX_DURATION_SECONDS,
        "cleanup_age_seconds": CLEANUP_AGE_SECONDS,
                   }
