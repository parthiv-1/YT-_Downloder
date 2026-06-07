# 📥 YouTube HD Video Downloader

A production-quality YouTube video downloader built with **Python · Flask · yt-dlp**.

---

## 📁 Folder Structure

```
youtube-downloader/
│
├── app.py                  # Flask backend (routes, yt-dlp, SSE streaming)
├── requirements.txt        # Python dependencies
├── downloads/              # Temp download folder (auto-created, auto-cleaned)
│
├── templates/
│   └── index.html          # Jinja2 HTML template
│
└── static/
    ├── style.css           # Dark glassmorphism UI styles
    └── script.js           # Frontend logic (fetch API + SSE progress)
```

---

## ⚙️ Installation

### Prerequisites
- Python 3.10+
- `pip`
- **FFmpeg** installed and on your PATH (required to merge HD video + audio streams)

### Install FFmpeg (Windows)
```powershell
winget install --id=Gyan.FFmpeg -e
```
Or download from https://ffmpeg.org/download.html and add to PATH.

### Install Python dependencies
```bash
pip install -r requirements.txt
```

---

## ▶️ Run Locally

```bash
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

---

## 🎯 How It Works

| Step | Action |
|------|--------|
| 1 | Paste a YouTube URL and click **Fetch Video** |
| 2 | The backend fetches metadata via yt-dlp (title, thumbnail, available resolutions) |
| 3 | Available quality options (1080p, 720p, 480p, 360p) are shown as cards |
| 4 | Click a quality card to start downloading in the background |
| 5 | A real-time progress bar (via Server-Sent Events) updates as it downloads |
| 6 | When complete, a **Save File** button appears to save the MP4 to your computer |

---

## 🌐 API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `GET`  | `/` | Home page |
| `POST` | `/api/info` | Fetch video metadata and available resolutions |
| `POST` | `/api/download` | Start background download, returns `task_id` |
| `GET`  | `/api/progress/<task_id>` | SSE stream for real-time download progress |
| `GET`  | `/api/file/<task_id>` | Serve completed file as browser download |

---

## 🔒 Security Notes

- Input is validated on both client (JS regex) and server (Python regex)
- Only `youtube.com` and `youtu.be` URLs are accepted
- Files are auto-deleted after 10 minutes
- No concurrent duplicate downloads allowed per task

---

## 🛠️ Tech Stack

- **Backend:** Python 3.10+, Flask 3.x, yt-dlp
- **Frontend:** Vanilla HTML5, CSS3, JavaScript (ES2022)
- **Streaming:** Server-Sent Events (SSE) for real-time progress
- **Fonts:** Inter (Google Fonts)
- **Icons:** Feather Icons
