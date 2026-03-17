# yt→mp3

A self-hosted YouTube to MP3 converter with a mobile-friendly PWA interface.
Deploy once, then add to your phone's home screen — it works like a native app.

## Quick Deploy (Pick One)

### Option A: Railway (Easiest — free trial)

1. Create an account at [railway.app](https://railway.app)
2. Click **New Project → Deploy from GitHub Repo**
3. Push this folder to a GitHub repo first, or use Railway CLI:
   ```bash
   npm i -g @railway/cli
   railway login
   cd yt-mp3-app
   railway init
   railway up
   ```
4. Railway auto-detects the Dockerfile and deploys
5. Go to **Settings → Networking → Generate Domain** to get your public URL

### Option B: Render (Free tier available)

1. Create an account at [render.com](https://render.com)
2. New → **Web Service** → connect your GitHub repo
3. Settings:
   - **Runtime**: Docker
   - **Instance Type**: Free (or Starter for reliability)
4. Deploy — Render gives you a `.onrender.com` URL

### Option C: Fly.io (Free tier available)

1. Install the CLI: `curl -L https://fly.io/install.sh | sh`
2. ```bash
   cd yt-mp3-app
   fly auth signup   # or fly auth login
   fly launch         # auto-detects Dockerfile
   fly deploy
   ```
3. Your app is live at `https://your-app.fly.dev`

---

## Add to Your Phone

Once deployed, open the URL on your phone:

### iPhone (Safari)
1. Open your app URL in **Safari**
2. Tap the **Share** button (square with arrow)
3. Scroll down → **Add to Home Screen**
4. Tap **Add**

### Android (Chrome)
1. Open your app URL in **Chrome**
2. Tap the **⋮** menu
3. Tap **Add to Home Screen** (or "Install App")
4. Tap **Add**

The app will launch fullscreen without browser chrome — just like a native app.

---

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Also need ffmpeg
# macOS: brew install ffmpeg
# Ubuntu: sudo apt install ffmpeg

# Run the server
uvicorn server:app --reload --port 8000

# Open http://localhost:8000
```

## Project Structure

```
yt-mp3-app/
├── server.py          # FastAPI backend (API + serves frontend)
├── static/
│   └── index.html     # PWA frontend (single file)
├── requirements.txt
├── Dockerfile
└── README.md
```

## Notes

- **Max video length**: 20 minutes (configurable in `server.py`)
- **Auto-cleanup**: Downloaded files are deleted after 10 minutes
- **Quality options**: 128, 192, 256, 320 kbps
- Only download content you have the rights to use
