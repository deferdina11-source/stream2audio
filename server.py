import os
import uuid
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp

app = FastAPI()

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

files = {}  # in-memory storage


class ConvertRequest(BaseModel):
    url: str
    quality: int = 192


class SearchRequest(BaseModel):
    query: str


# --- SEARCH ---
@app.post("/api/search")
def search(req: SearchRequest):

    ydl_opts = {
        "quiet": True,
        "skip_download": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"ytsearch5:{req.query}", download=False)["entries"]

    return [
        {
            "title": v["title"],
            "webpage_url": v["webpage_url"],
            "thumbnail": v.get("thumbnail")
        }
        for v in results
    ]


# --- INFO ---
@app.post("/api/info")
def info(req: ConvertRequest):

    ydl_opts = {
        "quiet": True,
        "skip_download": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        data = ydl.extract_info(req.url, download=False)

    return {
        "title": data["title"],
        "thumbnail": data.get("thumbnail")
    }


# --- CONVERT ---
@app.post("/api/convert")
def convert(req: ConvertRequest):

    file_id = str(uuid.uuid4())
    output = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp3")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": str(req.quality)
        }]
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(req.url, download=True)

    # 🔥 SAVE metadata (THIS WAS YOUR BUG)
    files[file_id] = {
        "path": output,
        "title": info["title"]
    }

    return {"file_id": file_id, "title": info["title"]}


# --- DOWNLOAD ---
@app.get("/api/download/{file_id}")
def download(file_id: str):

    if file_id not in files:
        return {"success": False, "error": "Invalid file ID"}

    file = files[file_id]

    return FileResponse(
        file["path"],
        filename=f"{file['title']}.mp3",
        media_type="audio/mpeg"
    )
