from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import yt_dlp
import os
import uuid

app = FastAPI()

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Serve frontend
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/")
def root():
    return FileResponse("index.html")

# -----------------------
# MODEL
# -----------------------
class ConvertRequest(BaseModel):
    url: str

# -----------------------
# CONVERT
# -----------------------
@app.post("/api/convert")
def convert(req: ConvertRequest):
    file_id = str(uuid.uuid4())

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{DOWNLOAD_DIR}/{file_id}.%(ext)s",
        "noplaylist": True,  # 🔥 CRITICAL FIX
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([req.url])
    except Exception as e:
        return {"success": False, "error": str(e)}

    return {"file_id": file_id}

# -----------------------
# DOWNLOAD
# -----------------------
@app.get("/api/download/{file_id}")
def download(file_id: str):
    path = f"{DOWNLOAD_DIR}/{file_id}.mp3"

    if not os.path.exists(path):
        return {"success": False, "error": "File not found or expired"}

    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename="audio.mp3"
    )
