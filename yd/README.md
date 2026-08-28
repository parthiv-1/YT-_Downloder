# 📥 YouTube HD Video Downloader

A production-quality YouTube video downloader built with **Python · Flask · yt-dlp**.

---

## 📁 Folder Structure

```
test_video.music/          ← Project Root
│
├── venv/                  # Python virtual environment
├── yd/                    # Main application folder  ← app.py is HERE
│   ├── app.py             # Flask backend (routes, yt-dlp, SSE)
│   ├── requirements.txt   # Python dependencies
│   ├── downloads/         # Temp download folder (auto-created)
│   ├── templates/
│   │   └── index.html     # HTML template
│   └── static/
│       ├── style.css      # Dark glassmorphism UI
│       └── script.js      # Frontend logic
│
├── Dockerfile
├── gunicorn.conf.py
├── nixpacks.toml
└── requirements.txt
```

---

## ⚙️ Installation

### Step 1 — Install FFmpeg (Windows, required for HD/4K)
```powershell
winget install --id=Gyan.FFmpeg -e
```

### Step 2 — Create virtual environment
```powershell
python -m venv venv
```

### Step 3 — Install dependencies
```powershell
venv\Scripts\pip install -r yd\requirements.txt
```

---

## ▶️ How to Run

> ⚠️ **`app.py` is inside the `yd/` folder — NOT the project root!**

### ✅ Correct way (from project root):
```powershell
venv\Scripts\python.exe yd\app.py
```

### Or go into the yd folder first:
```powershell
cd yd
..\venv\Scripts\python.exe app.py
```

Then open 👉 **http://127.0.0.1:5000**

---

## ❌ Common Mistake

```powershell
# WRONG — app.py is NOT in the root!
python app.py
# Error: can't open file 'app.py': No such file or directory

# CORRECT
venv\Scripts\python.exe yd\app.py
```

---

## 🎯 How It Works

| Step | Action |
|------|--------|
| 1 | Paste a YouTube URL → click **Fetch Video** |
| 2 | Backend fetches metadata (title, thumbnail, resolutions) |
| 3 | Quality cards: 4K, 2K, 1080p, 720p, 480p, 360p |
| 4 | Click quality → background download starts |
| 5 | Real-time progress bar via Server-Sent Events |
| 6 | **Save File** button appears when done |

---

## 🌐 API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `GET`  | `/` | Home page |
| `POST` | `/api/info` | Fetch video metadata |
| `POST` | `/api/download` | Start background download |
| `GET`  | `/api/progress/<task_id>` | SSE real-time progress |
| `GET`  | `/api/file/<task_id>` | Download completed file |
| `GET`  | `/api/debug` | Debug info (ffmpeg, node, yt-dlp) |

---

## 🛠️ Tech Stack

- **Backend:** Python 3.10+, Flask 3.x, yt-dlp 2026.08.19+
- **Frontend:** Vanilla HTML5, CSS3, JavaScript ES2022
- **Streaming:** Server-Sent Events (SSE)
- **Fonts:** Inter (Google Fonts) · **Icons:** Feather Icons
