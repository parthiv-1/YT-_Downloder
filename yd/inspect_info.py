import os
import yt_dlp
import shutil

# Mocking the app's logic
DOWNLOADS_DIR = r"d:\test_video.music\yd\downloads"
_NODE_PATH = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"

def get_best_cookie_file():
    variants = ["cookies.txt", "cookies (4).txt"]
    for v in variants:
        path = os.path.join(DOWNLOADS_DIR, v)
        if os.path.isfile(path): return path
    return None

url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
cookiefile = get_best_cookie_file()

opts = {
    "quiet": True,
    "skip_download": True,
    "noplaylist": True,
    "cookiefile": cookiefile,
    "extractor_args": {
        "youtube": {
            "player_client": ["tv", "web", "mweb", "ios", "android"],
            "player_skip": ["web_embedded"]
        }
    },
    "javascript_runtime": "node",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
}

with yt_dlp.YoutubeDL(opts) as ydl:
    info = ydl.extract_info(url, download=False)
    formats = info.get("formats", [])
    print(f"TOTAL FORMATS: {len(formats)}")
    for f in formats:
        h = f.get("height")
        vc = f.get("vcodec")
        ac = f.get("acodec")
        print(f"Format ID {f.get('format_id')}: height={h}, vcodec={vc}, acodec={ac}")
