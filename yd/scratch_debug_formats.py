import os
import yt_dlp

COOKIES_TXT = r"d:\test_video.music\yd\downloads\cookies (4).txt"
url = "https://www.youtube.com/watch?v=0_uNoI-F_M8" # Using a known music video

base_opts = {
    "quiet": False,
    "no_warnings": False,
    "skip_download": True,
    "noplaylist": True,
}

# Emulate the app's robust options
opts = {**base_opts}
opts["extractor_args"] = {
    "youtube": {
        "player_client": ["ios", "android", "tv", "web", "mweb"],
        "player_skip": ["web_embedded"]
    }
}
opts["javascript_runtime"] = "node"
opts["nocheckcertificate"] = True
if os.path.isfile(COOKIES_TXT):
    opts["cookiefile"] = COOKIES_TXT

try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        print(f"TITLE: {info.get('title')}")
        formats = info.get("formats", [])
        print(f"FOUND {len(formats)} formats")
        
        resolutions = set()
        for f in formats:
            h = f.get("height")
            if h:
                resolutions.add(h)
        
        print(f"RESOLUTIONS: {sorted(list(resolutions))}")
except Exception as e:
    print(f"ERROR: {e}")
