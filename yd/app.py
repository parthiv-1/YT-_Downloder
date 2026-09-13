"""
YouTube HD Video Downloader - Flask Backend
==========================================
Author: Senior Python Full-Stack Developer
Description: A production-quality YouTube video downloader using yt-dlp
             with Flask as the web framework.
"""

import os
import re
import uuid
import threading
import time
import json
import shutil
import hashlib
import sys

from flask import Flask, render_template, request, jsonify, send_file, Response
import yt_dlp

# ─────────────────────────────────────────────────────────────
# App Configuration
# ─────────────────────────────────────────────────────────────


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base_path, relative_path)


app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static"),
)
app.secret_key = os.urandom(24)

# ─── FFmpeg Path Detection ───────────────────────────────────
# Absolute path to winget-installed FFmpeg (no PATH dependency)
_FFMPEG_WINGET = (
    r"C:\Users\parthiv\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
)
_FFMPEG_BIN_DIR = os.path.dirname(_FFMPEG_WINGET)

# Prefer PATH ffmpeg, fall back to winget absolute path
FFMPEG_PATH = shutil.which("ffmpeg") or (
    _FFMPEG_WINGET if os.path.isfile(_FFMPEG_WINGET) else None
)
FFMPEG_LOCATION = os.path.dirname(FFMPEG_PATH) if FFMPEG_PATH else None

HAS_FFMPEG = FFMPEG_PATH is not None
print(
    f"  [FFmpeg] {'OK: ' + FFMPEG_PATH if HAS_FFMPEG else 'NOT FOUND — 4K/2K/1080p unavailable'}"
)
_node_detect = shutil.which("node")
print(f"  [Node.js] {'OK: ' + _node_detect if _node_detect else 'NOT FOUND — YouTube signature challenge decryption might fail'}")
print(f"  [yt-dlp] Version: {yt_dlp.version.__version__}")

# Determine the directory where the executable or script is located
if getattr(sys, "frozen", False):
    # Running as a bundled executable
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Running as a normal Python script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Temporary download directory (auto-cleaned)
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# In-memory progress store: {task_id: {status, percent, filename, error}}
progress_store: dict[str, dict] = {}

# Lock to prevent multiple simultaneous downloads per session
_download_locks: dict[str, threading.Lock] = {}


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def sanitize_url(url: str) -> str:
    """Basic sanitization — strip whitespace and validate YouTube or Instagram domain."""
    url = url.strip()
    youtube_pattern = r"^(https?://)?([a-zA-Z0-9\-]+\.)?(youtube\.com|youtu\.be)/.+"
    instagram_pattern = r"^(https?://)?(www\.)?instagram\.com/(reel|p|tv|stories)/.+"
    if re.match(youtube_pattern, url) or re.match(instagram_pattern, url):
        return url
    raise ValueError("Valid YouTube URL (youtube.com/youtu.be) or Instagram Reel URL (instagram.com/reel/) enter karo.")


def detect_platform(url: str) -> str:
    """Detect whether URL is from YouTube or Instagram."""
    url_lower = url.lower()
    if "instagram.com" in url_lower:
        return "instagram"
    return "youtube"


def clean_old_files(max_age_seconds: int = 3600) -> None:
    """Remove downloaded files older than max_age_seconds (default 10 min)."""
    now = time.time()
    for fname in os.listdir(DOWNLOAD_DIR):
        fpath = os.path.join(DOWNLOAD_DIR, fname)
        try:
            if (
                os.path.isfile(fpath)
                and now - os.path.getmtime(fpath) > max_age_seconds
            ):
                os.remove(fpath)
        except OSError:
            pass


def format_size(bytes_val: int) -> str:
    """Convert bytes to human-readable string."""
    if bytes_val is None or bytes_val == 0:
        return "Unknown"
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"


# Path to manually exported cookies (most reliable method)
# We will search for common variations in the downloads folder
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")


def get_best_cookie_file() -> str | None:
    """Find the most relevant cookie file in downloads, yd, or project root, or from environment variables."""
    # 1. Search local repository files first (cookies.txt in yd, root, or downloads)
    search_dirs = [
        BASE_DIR,
        os.path.dirname(BASE_DIR),
        DOWNLOADS_DIR,
    ]
    variants = [
        "cookies.txt",
        "instagram_cookies.txt",
        "env_cookies.txt",
        "cookies (1).txt",
        "cookies (2).txt",
    ]
    for d in search_dirs:
        if os.path.isdir(d):
            for v in variants:
                path = os.path.join(d, v)
                if os.path.isfile(path) and os.path.getsize(path) > 50:
                    return path

    # 2. Check environment variables as fallback if no local file exists
    env_cookies = os.environ.get("YOUTUBE_COOKIES") or os.environ.get("INSTAGRAM_COOKIES") or os.environ.get("COOKIES_TXT")
    if env_cookies:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        cookie_path = os.path.join(DOWNLOADS_DIR, "env_cookies.txt")
        try:
            content = env_cookies.strip()
            import base64
            try:
                clean_b64 = content.replace(" ", "").replace("\n", "").replace("\r", "")
                clean_b64 += "=" * ((4 - len(clean_b64) % 4) % 4)
                decoded = base64.b64decode(clean_b64).decode("utf-8")
                if "cookie" in decoded.lower() or "# netscape" in decoded.lower() or "\t" in decoded:
                    content = decoded
                    print("  [Cookies] Successfully decoded base64 cookies from environment")
            except Exception:
                pass

            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write(content)
            return cookie_path
        except Exception as e:
            print(f"  [Cookies] Error writing cookies from environment: {e}")

    for d in search_dirs:
        if os.path.isdir(d):
            for fname in os.listdir(d):
                if fname.endswith(".txt") and "cookie" in fname.lower():
                    return os.path.join(d, fname)
    return None


@app.route("/api/version")
def api_version():
    cf = get_best_cookie_file()
    return jsonify({
        "version": "1.4.1",
        "status": "ready",
        "cookie_file": os.path.basename(cf) if cf else None,
        "ffmpeg": HAS_FFMPEG,
        "node": bool(_NODE_PATH and os.path.isfile(_NODE_PATH)),
    })


# Initial path (can be updated dynamically)
COOKIES_TXT = get_best_cookie_file()

# We no longer probe browser databases to keep the project simple and avoid permission/DRM errors.
# Only manual cookies.txt and unauthenticated requests are used.

# JS Runtime detection
_NODE_PATH = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"

# Keywords that indicate a retryable error (auth, bot, or DRM issues)
_RETRYABLE_ERROR_KEYWORDS = (
    "cookie",
    "could not copy",
    "sign in",
    "bot",
    "dpapi",
    "decrypt",
    "failed to decrypt",
    "unable to read",
    "keyring",
    "unavailable",
    "format is not available",
    "requested format is not available",
    "sign in to confirm you're not a bot",
    "n-parameter",
    "drm protected",
    "sign in to confirm",
    "not available in your country",
    "403",
    "forbidden",
    "http error 403",
    "page needs to be reloaded",
    "the page needs to be reloaded",
    "sabr",
    "reloaded",
)


def _is_retryable_error(exc: Exception) -> bool:
    """Return True if the exception suggests we should try a different auth/client strategy."""
    msg = str(exc).lower()
    return any(kw in msg for kw in _RETRYABLE_ERROR_KEYWORDS)


def _is_low_quality(info: dict) -> bool:
    """Return True if the extraction result contains NO formats > 360p."""
    formats = info.get("formats", [])
    if not formats:
        return True

    # Check if we found ANY format with height > 360p
    has_high_quality = any((f.get("height") or 0) > 360 for f in formats)
    return not has_high_quality


def _extract_with_cookie_fallback(
    base_opts: dict, url: str, download: bool, hint: dict = None
) -> tuple[dict, dict]:
    """
    Fast, highly-reliable extraction strategy:
      1. Primary: Cookie-authenticated default client extraction
         - Yields all resolutions up to 4K (2160p) and 2K (1440p) in 2-3 seconds.
         - Returns immediately once formats are extracted without sequential scanning.
      2. Fallback: Android/TV client extraction
         - Bypasses cloud/datacenter IP bot blocks if cookies expire or fail.
    """
    current_cookie_file = get_best_cookie_file()
    has_cookies = bool(current_cookie_file and os.path.isfile(current_cookie_file))

    # Fast strategies:
    # 1) Primary: VisionOS client without cookies (instant 2-3s, unthrottled, up to 4K, bypasses datacenter bot blocks)
    #    Note: yt-dlp explicitly skips visionos if a cookiefile is present, so visionos must run cookie-free.
    # 2) Fallback: Authenticated extraction using cookies (if available, for 18+ or private videos)
    strategies = [
        {
            "name": "Primary (VisionOS Cloud-Bypass)",
            "opts": {
                **base_opts,
                "socket_timeout": 12,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["visionos"],
                        "include_dash_manifest": True,
                    }
                },
                "js_runtimes": {"node": {}},
                "no_color": True,
                "nocheckcertificate": True,
            },
            "hint": {"cookie_idx": 0, "config_idx": 0},
        }
    ]

    if has_cookies:
        strategies.append({
            "name": "Fallback (Authenticated with Cookies)",
            "opts": {
                **base_opts,
                "cookiefile": current_cookie_file,
                "socket_timeout": 12,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["tv", "mweb", "web"],
                        "include_dash_manifest": True,
                    }
                },
                "js_runtimes": {"node": {}},
                "no_color": True,
                "nocheckcertificate": True,
            },
            "hint": {"cookie_idx": 1, "config_idx": 0},
        })

    last_exc: Exception | None = None
    for s in strategies:
        print(f"  [Extraction] Attempting strategy: {s['name']}")
        try:
            with yt_dlp.YoutubeDL(s["opts"]) as ydl:
                info = ydl.extract_info(url, download=download)

            if download:
                print(f"  [Extraction Success] Download completed via {s['name']}")
                return info, s["hint"]

            formats = info.get("formats", [])
            if formats:
                max_height = max([f.get("height") or 0 for f in formats] or [0])
                print(f"  [Extraction Success] Found {len(formats)} formats (max: {max_height}p) via {s['name']}")
                return info, s["hint"]

        except Exception as exc:
            last_exc = exc
            print(f"  [Extraction Warn] {s['name']} failed ({str(exc)[:100]}) — falling back...")
            continue

    if last_exc:
        raise last_exc
    raise Exception("All extraction strategies failed.")


@app.route("/api/test-clients")
def api_test_clients():
    import time
    url = request.args.get("url") or "https://youtu.be/eQOqpctSNs8"
    use_cookies = request.args.get("cookies", "false").lower() == "true"
    client_param = request.args.get("client")
    cf = get_best_cookie_file() if use_cookies else None
    results = {}
    clients = [client_param] if client_param else ["android", "tv", "ios", "mweb", "android_vr", "web"]
    for c in clients:
        t0 = time.time()
        try:
            opts = {
                "quiet": True,
                "skip_download": True,
                "socket_timeout": 4,
                "extractor_args": {"youtube": {"player_client": [c]}},
                "no_color": True,
                "nocheckcertificate": True,
            }
            if cf:
                opts["cookiefile"] = cf
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            results[c] = {
                "status": "success",
                "time": round(time.time() - t0, 2),
                "formats": len(info.get("formats", [])),
                "heights": sorted(set(f.get("height") for f in info.get("formats", []) if f.get("height"))),
            }
        except Exception as e:
            results[c] = {
                "status": "error",
                "time": round(time.time() - t0, 2),
                "error": str(e)[:100],
            }
    return jsonify({"use_cookies": use_cookies, "cookie_file": bool(cf), "results": results})


def get_video_info(url: str) -> tuple[dict, dict]:
    """
    Fetch video metadata using yt-dlp without downloading.
    Returns (video_data, strategy_hint).
    Supports YouTube and Instagram URLs.
    """
    platform = detect_platform(url)
    is_story = "stories" in url.lower()
    base_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": not is_story,
        "socket_timeout": 15,
        "check_formats": False,
    }

    # Instagram: use simple direct extraction with cookie fallback
    if platform == "instagram":
        # Strategy 1: If cookies are provided, prioritize them (essential for Stories & 18+ Reels)
        ig_strategies = []
        current_cookie = get_best_cookie_file()
        if current_cookie:
            ig_strategies.append({**base_opts, "cookiefile": current_cookie})

        # Strategy 2: Standard browser request
        ig_strategies.append(
            {
                **base_opts,
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Sec-Fetch-Mode": "navigate",
                },
            }
        )

        last_ig_exc = None
        info = None
        for ig_opts in ig_strategies:
            try:
                with yt_dlp.YoutubeDL(ig_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                print(f"  [Instagram] Successfully extracted info.")
                break
            except Exception as e:
                err_str = str(e)
                print(f"  [Instagram] Strategy failed: {err_str[:80]}, trying next...")
                # Filter out missing local browser database errors so the user sees the real Instagram reason
                if "could not find" not in err_str.lower() and "database" not in err_str.lower():
                    last_ig_exc = e
                elif last_ig_exc is None:
                    last_ig_exc = e
                continue

        if info is None:
            if last_ig_exc:
                err_msg = str(last_ig_exc)
                if "can't be seen by certain audiences" in err_msg or "isn't available to everyone" in err_msg or "login" in err_msg.lower():
                    raise ValueError("This Instagram Reel or Story requires Instagram login. Please update Instagram cookies.")
                raise last_ig_exc
            raise Exception("Failed to fetch Instagram reel/story info.")

        # Unpack Instagram Story or Highlight playlist into target single story item
        if info and "entries" in info:
            entries = [e for e in info.get("entries", []) if e]
            if entries:
                m = re.search(r"/stories/[^/]+/(\d+)", url)
                target_entry = None
                if m:
                    target_id = m.group(1)
                    for e in entries:
                        if str(e.get("id")) == target_id or str(e.get("pk")) == target_id:
                            target_entry = e
                            break
                info = target_entry or entries[0]

        hint = {"cookie_idx": 0, "config_idx": 0}
    else:
        info, hint = _extract_with_cookie_fallback(base_opts, url, download=False)

    # Build resolution options from available formats
    resolutions_seen = set()
    resolution_list = []

    # All resolutions we support (4K, 2K, HD, SD)
    # FFmpeg required for 1080p+; lower quality works without it
    TARGET_HEIGHTS = [
        (2160, "4K Ultra HD", True),
        (1440, "2K QHD", True),
        (1080, "Full HD", True),
        (720, "HD", False),
        (480, "SD", False),
        (360, "Low", False),
    ]
    target_map = {h: (label, needs_ffmpeg) for h, label, needs_ffmpeg in TARGET_HEIGHTS}

    for fmt in info.get("formats", []):
        height = fmt.get("height")
        vcodec = fmt.get("vcodec", "none")

        if vcodec in (None, "none"):
            continue
        if height is None:
            continue
        if height not in target_map:
            continue
        if height in resolutions_seen:
            continue

        label, needs_ffmpeg = target_map[height]
        resolutions_seen.add(height)
        resolution_list.append(
            {
                "label": f"{height}p",
                "height": height,
                "note": label,
                "needs_ffmpeg": needs_ffmpeg,
                "available": True if not needs_ffmpeg else HAS_FFMPEG,
            }
        )

    # Sort highest quality first
    resolution_list.sort(key=lambda x: x["height"], reverse=True)

    # If no standard resolutions found, show best available
    if not resolution_list:
        resolution_list.append(
            {
                "label": "Best",
                "height": 0,
                "note": "Best Available",
                "needs_ffmpeg": False,
                "available": True,
            }
        )

    duration = info.get("duration", 0) or 0
    return {
        "title": info.get("title") or info.get("description", "Instagram Reel") or "Unknown Title",
        "thumbnail": info.get("thumbnail", ""),
        "duration": duration,
        "channel": info.get("uploader") or info.get("channel", "Unknown"),
        "view_count": info.get("view_count", 0),
        "resolutions": resolution_list,
        "ffmpeg_available": HAS_FFMPEG,
        "is_short": duration <= 60 or "/shorts/" in url.lower() or "/reel/" in url.lower(),
        "platform": platform,
    }, hint


# ─────────────────────────────────────────────────────────────
# Background Download Worker
# ─────────────────────────────────────────────────────────────


def _download_worker(
    task_id: str, url: str, height: int, hint: dict = None, is_short_hint: bool = None
) -> None:
    """
    Runs in a background thread.
    Downloads the video + merges audio, updating progress_store as it goes.
    """
    """
    Runs in a background thread.
    Downloads the video + merges audio, updating progress_store as it goes.
    """
    # Generate a stable resume key based on URL and Height
    # This allows yt-dlp to find previous .part files and resume.
    resume_key = hashlib.md5(f"{url}_{height}".encode()).hexdigest()
    progress_store[task_id]["resume_key"] = resume_key

    # Concurrency lock: prevent multiple threads from writing to the same file
    if resume_key not in _download_locks:
        _download_locks[resume_key] = threading.Lock()

    with _download_locks[resume_key]:
        output_template = os.path.join(DOWNLOAD_DIR, f"{resume_key}.%(ext)s")

        def progress_hook(d):
            """Called by yt-dlp during download with progress info."""
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                pct = int(downloaded / total * 100) if total else 0
                speed = d.get("speed", 0) or 0
                eta = d.get("eta", 0)
                progress_store[task_id]["percent"] = pct
                progress_store[task_id]["speed"] = format_size(int(speed)) + "/s"
                progress_store[task_id]["eta"] = eta
                progress_store[task_id]["status"] = "downloading"

            elif d["status"] == "finished":
                progress_store[task_id]["status"] = "merging"
                progress_store[task_id]["percent"] = 99

        # ── Format Selector ──────────────────────────────────────
        postprocessors = []

        if height == -2:
            # Audio Only (MP3)
            postprocessors.append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            )
            # Audio-specific optimizations
            fmt = "bestaudio/best"
        else:
            # Video Download Logic (Smart or specific resolution)
            if height == -1:
                # Use hint from frontend if available to skip extraction
                if is_short_hint is not None:
                    height = 1440 if is_short_hint else 2160
                    print(f"  [Smart Quality] Using cached hint — Targeting {height}p")
                else:
                    # Smart Quality fallback (only if frontend hint missing)
                    temp_opts = {
                        "quiet": True,
                        "no_warnings": True,
                        "skip_download": True,
                    }
                    try:
                        info, _ = _extract_with_cookie_fallback(
                            temp_opts, url, download=False, hint=hint
                        )
                        is_short = (
                            info.get("duration", 0) or 0
                        ) <= 60 or "/shorts/" in url.lower()
                        height = 1440 if is_short else 2160
                        print(
                            f"  [Smart Quality] Detected {'Short' if is_short else 'Long video'} — Targeting {height}p"
                        )
                    except:
                        height = 2160  # Fallback to 4K

            # With FFmpeg: download best separate video+audio → merge (4K/2K/1080p)
            # Without FFmpeg: download best pre-merged stream (≤720p)
            if HAS_FFMPEG:
                if height == 0:
                    # Best quality: prefer DASH separate streams, fallback to combined
                    fmt = "bestvideo+bestaudio/best"
                else:
                    # DASH-only format (no codec restriction so web/tv_embedded clients work).
                    # Tries exact height first, then nearest lower resolution.
                    # No bare 'best' fallback — that would silently give a pre-merged 480p stream.
                    fmt = (
                        f"bestvideo[height={height}]+bestaudio/"
                        f"bestvideo[height<={height}]+bestaudio"
                    )
                    print(f"  [Format] DASH format for {height}p: {fmt}")
            else:
                # No FFmpeg — use pre-merged streams only (max 720p)
                if height == 0:
                    fmt = "best[ext=mp4]/best[ext=webm]/best"
                else:
                    # Try exact height first, then fallback to nearest lower quality
                    capped = min(height, 720)
                    fmt = (
                        f"best[height={capped}][ext=mp4]/"
                        f"best[height<={capped}][ext=mp4]/"
                        f"best[height<={capped}][ext=webm]/"
                        f"best[height<={capped}]/best"
                    )

        base_opts = {
            "format": fmt,
            "outtmpl": output_template,
            "merge_output_format": "mkv" if height != -2 else "mp3",
            "postprocessors": postprocessors,
            "quiet": False,
            "no_warnings": False,
            "verbose": False,  # Flip to True for deep debugging
            "noplaylist": not ("stories" in url.lower()),
            "progress_hooks": [progress_hook],
            # ── Timeout & Retry Settings ──────────────────────────
            "socket_timeout": 30,
            "retries": 15,
            "fragment_retries": 15,
            "file_access_retries": 5,
            "extractor_retries": 5,
            # Enable resume to continue from where we left off after a 403
            "continuedl": True,
            # CRITICAL: 1 fragment at a time avoids YouTube rate-limiting (403)
            # More than 1 triggers YouTube's bot detection on large DASH files
            "concurrent_fragment_downloads": 1,
            "buffersize": 1024 * 1024,       # 1 MB buffer
            "http_chunk_size": 10 * 1024 * 1024,  # 10 MB chunks
            # Small sleep between requests to appear more human-like
            "sleep_interval_requests": 0.5,
            "sleep_interval": 0,
            "max_sleep_interval": 2,
            "legacyserverconnect": True,
        }

        # Add FFmpeg location if available
        if HAS_FFMPEG and FFMPEG_LOCATION:
            base_opts["ffmpeg_location"] = FFMPEG_LOCATION

        try:
            platform = detect_platform(url)

            if platform == "instagram":
                # Instagram download: try with cookies first (essential for Stories & 18+ Reels)
                ig_dl_strategies = []
                current_cookie = get_best_cookie_file()
                if current_cookie:
                    ig_dl_strategies.append({**base_opts, "cookiefile": current_cookie})

                ig_dl_strategies.append(
                    {
                        **base_opts,
                        "http_headers": {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                            "Accept-Language": "en-US,en;q=0.9",
                            "Sec-Fetch-Mode": "navigate",
                        },
                    }
                )

                last_dl_exc = None
                info = None
                for ig_dl_opts in ig_dl_strategies:
                    try:
                        with yt_dlp.YoutubeDL(ig_dl_opts) as ydl:
                            info = ydl.extract_info(url, download=True)
                        print(f"  [Instagram Download] Success.")
                        break
                    except Exception as e:
                        err_str = str(e)
                        print(f"  [Instagram Download] Strategy failed: {err_str[:80]}, trying next...")
                        if "could not find" not in err_str.lower() and "database" not in err_str.lower():
                            last_dl_exc = e
                        elif last_dl_exc is None:
                            last_dl_exc = e
                        continue

                if info is None:
                    if last_dl_exc:
                        err_msg = str(last_dl_exc)
                        if "can't be seen by certain audiences" in err_msg or "isn't available to everyone" in err_msg:
                            raise ValueError("This Instagram Reel is restricted (Age 18+ or requires Instagram login).")
                        raise last_dl_exc
                    raise Exception("Instagram download failed.")
            else:
                info, _ = _extract_with_cookie_fallback(
                    base_opts, url, download=True, hint=hint
                )
            title = info.get("title", "video") if info else "video"

            # Log the actual format chosen by yt-dlp for debugging
            if info:
                chosen_height = info.get("height") or info.get("resolution", "?")
                chosen_format = info.get("format", "?")
                chosen_ext = info.get("ext", "?")
                print(f"  [Download] Chosen format: {chosen_format} | height={chosen_height} | ext={chosen_ext}")

                # Quality validation: warn if we got much lower quality than requested
                if height > 0 and isinstance(chosen_height, int) and chosen_height < height * 0.75:
                    print(
                        f"  [Quality Warn] Requested {height}p but got {chosen_height}p! "
                        f"YouTube may have throttled DASH streams — try again or use a cookies.txt."
                    )

            # Find the resulting file
            result_file = None
            for fname in os.listdir(DOWNLOAD_DIR):
                if fname.startswith(resume_key):
                    result_file = os.path.join(DOWNLOAD_DIR, fname)
                    break

            if result_file and os.path.isfile(result_file):
                progress_store[task_id]["status"] = "done"
                progress_store[task_id]["percent"] = 100
                progress_store[task_id]["filename"] = os.path.basename(result_file)
                progress_store[task_id]["title"] = title
            else:
                progress_store[task_id]["status"] = "error"
                progress_store[task_id]["error"] = "Downloaded file not found."

        except yt_dlp.utils.DownloadError as e:
            raw = str(e).split("\n")[0]
            # Clean ANSI escape codes
            clean = re.sub(r"\x1B\[[0-9;]*[mK]", "", raw).strip()
            clean = re.sub(r"^ERROR:\s*", "", clean)
            print(f"  [DownloadError] {clean}")
            progress_store[task_id]["status"] = "error"
            progress_store[task_id]["error"] = clean
        except Exception as e:
            print(f"  [UnexpectedError] {str(e)}")
            progress_store[task_id]["status"] = "error"
            progress_store[task_id]["error"] = f"Unexpected error: {str(e)}"


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────


@app.route("/api/debug")
def api_debug():
    import subprocess
    try:
        node_ver = subprocess.check_output(["node", "--version"], stderr=subprocess.STDOUT).decode().strip()
    except Exception as e:
        node_ver = f"Error: {e}"
        
    try:
        # Check ffmpeg from path or FFMPEG_PATH
        path_to_use = FFMPEG_PATH or "ffmpeg"
        ffmpeg_ver = subprocess.check_output([path_to_use, "-version"], stderr=subprocess.STDOUT).decode().split('\n')[0].strip()
    except Exception as e:
        ffmpeg_ver = f"Error: {e}"
        
    return jsonify({
        "node": node_ver,
        "ffmpeg": ffmpeg_ver,
        "yt_dlp_version": yt_dlp.version.__version__,
        "cookies_env_exists": "YOUTUBE_COOKIES" in os.environ,
        "cookies_env_length": len(os.environ.get("YOUTUBE_COOKIES", "")),
        "cookies_file_exists": os.path.isfile(get_best_cookie_file() or ""),
    })


@app.route("/")
def index():
    """Home page."""
    return render_template("index.html")


def _parse_cookie_lines_to_dict(text: str) -> dict[str, str]:
    """Parse Netscape cookie format lines into {domain::name: full_line} for seamless merging."""
    cookie_map = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            domain = parts[0]
            name = parts[5]
            cookie_map[f"{domain}::{name}"] = line
    return cookie_map


@app.route("/api/set-cookies", methods=["POST"])
def api_set_cookies():
    """
    POST /api/set-cookies
    Body: { "cookies": "<sessionid or cookies string or netscape text>", "platform": "youtube" | "instagram" }
    Saves and merges cookies to enable 18+ Reels and YouTube 4K/2K downloads.
    """
    data = request.get_json(silent=True) or {}
    raw_val = data.get("cookies", "").strip()
    platform = (data.get("platform") or "").lower().strip()

    if not raw_val:
        return jsonify({"error": "Please provide cookie data."}), 400

    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    cookie_path = os.path.join(DOWNLOADS_DIR, "env_cookies.txt")

    # Read existing cookies if available to merge
    existing_text = ""
    current_best = get_best_cookie_file()
    if current_best and os.path.isfile(current_best):
        try:
            with open(current_best, "r", encoding="utf-8") as f:
                existing_text = f.read()
        except Exception:
            pass

    cookie_dict = _parse_cookie_lines_to_dict(existing_text)

    # Detect platform
    is_youtube = platform == "youtube" or any(
        k in raw_val for k in ["LOGIN_INFO", "SAPISID", "SID=", "SSID=", "__Secure", "VISITOR_INFO"]
    )

    if raw_val.startswith("# Netscape") or "\t" in raw_val:
        # Full Netscape file pasted
        for line in raw_val.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookie_dict[f"{parts[0]}::{parts[5]}"] = line
    else:
        # Header string or single token
        if is_youtube:
            # Semicolon-delimited cookies from YouTube / Google Login
            for p in raw_val.split(";"):
                if "=" in p:
                    k, v = p.strip().split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k and v:
                        for domain in [".youtube.com", ".google.com"]:
                            line = f"{domain}\tTRUE\t/\tTRUE\t2147483647\t{k}\t{v}"
                            cookie_dict[f"{domain}::{k}"] = line
        else:
            # Instagram cookies
            if ";" in raw_val:
                for p in raw_val.split(";"):
                    if "=" in p:
                        k, v = p.strip().split("=", 1)
                        k, v = k.strip(), v.strip()
                        if k and v:
                            line = f".instagram.com\tTRUE\t/\tTRUE\t2147483647\t{k}\t{v}"
                            cookie_dict[f".instagram.com::{k}"] = line
            else:
                clean_sid = raw_val.replace("sessionid=", "").strip().strip(";").strip()
                line = f".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\t{clean_sid}"
                cookie_dict[".instagram.com::sessionid"] = line

    # Assemble unified Netscape cookie file
    final_lines = [
        "# Netscape HTTP Cookie File",
        "# This file is generated by yt-dlp. Do not edit.",
        "",
    ]
    final_lines.extend(cookie_dict.values())
    cookie_content = "\n".join(final_lines) + "\n"

    try:
        with open(cookie_path, "w", encoding="utf-8") as f:
            f.write(cookie_content)
        # Mirror to BASE_DIR and project root
        try:
            with open(os.path.join(BASE_DIR, "cookies.txt"), "w", encoding="utf-8") as f:
                f.write(cookie_content)
            root_cookie = os.path.join(os.path.dirname(BASE_DIR), "cookies.txt")
            with open(root_cookie, "w", encoding="utf-8") as f:
                f.write(cookie_content)
        except Exception:
            pass

        global COOKIES_TXT
        COOKIES_TXT = cookie_path

        msg = (
            "YouTube cookies saved! 4K & 2K downloads unlocked."
            if is_youtube
            else "Instagram cookies saved! 18+ Reels unlocked."
        )
        return jsonify({
            "success": True,
            "message": msg,
            "total_cookies": len(cookie_dict),
            "is_youtube": is_youtube
        })
    except Exception as e:
        return jsonify({"error": f"Failed to save cookies: {str(e)}"}), 500


@app.route("/api/info", methods=["POST"])
def api_info():
    """
    POST /api/info
    Body: { "url": "<youtube_url>" }
    Returns video metadata and available resolutions.
    """
    data = request.get_json(silent=True) or {}
    raw_url = data.get("url", "").strip()

    if not raw_url:
        return jsonify({"error": "URL is required."}), 400

    try:
        url = sanitize_url(raw_url)
        data_info, hint = get_video_info(url)
        data_info["hint"] = hint
        return jsonify(data_info)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except yt_dlp.utils.DownloadError as e:
        msg = str(e).split("\n")[0]
        # Strip ANSI escape codes (e.g., [0;31mERROR:[0m)
        clean_msg = re.sub(r"\x1B\[[0-9;]*[mK]", "", msg).strip()
        # Remove redundant "ERROR: " prefix if present
        clean_msg = re.sub(r"^ERROR:\s*", "", clean_msg)
        return jsonify({"error": f"Could not fetch video: {clean_msg}"}), 422
    except Exception as e:
        return jsonify({"error": f"Internal error: {str(e)}"}), 500


@app.route("/api/download", methods=["POST"])
def api_download():
    """
    POST /api/download
    Body: { "url": "<youtube_url>", "height": 720 }
    Starts background download, returns { "task_id": "..." }
    """
    data = request.get_json(silent=True) or {}
    raw_url = data.get("url", "").strip()
    height = int(data.get("height", 720))
    hint = data.get("hint")
    is_short_hint = data.get("is_short")

    if not raw_url:
        return jsonify({"error": "URL is required."}), 400

    try:
        url = sanitize_url(raw_url)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Clean old files before starting
    clean_old_files()

    # Create a unique task ID
    task_id = str(uuid.uuid4())
    progress_store[task_id] = {
        "status": "pending",
        "percent": 0,
        "speed": "",
        "eta": 0,
        "filename": None,
        "title": None,
        "error": None,
    }

    # Kick off download in a daemon thread
    t = threading.Thread(
        target=_download_worker,
        args=(task_id, url, height, hint, is_short_hint),
        daemon=True,
    )
    t.start()

    return jsonify({"task_id": task_id})


@app.route("/api/progress/<task_id>")
def api_progress(task_id: str):
    """
    GET /api/progress/<task_id>
    Returns current download status for the given task.
    Uses Server-Sent Events (SSE) for real-time streaming.
    """

    def generate():
        while True:
            state = progress_store.get(task_id)
            if state is None:
                yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
                break

            yield f"data: {json.dumps(state)}\n\n"

            if state["status"] in ("done", "error"):
                break

            time.sleep(0.5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/file/<task_id>")
def api_file(task_id: str):
    """
    GET /api/file/<task_id>
    Serves the downloaded file for browser download.
    Deletes the file after sending.
    """
    state = progress_store.get(task_id)
    if not state or state["status"] != "done":
        return jsonify({"error": "File not ready or task not found."}), 404

    resume_key = state.get("resume_key")
    if not resume_key:
        return jsonify({"error": "Resume key missing."}), 404

    # Find the resulting file by resume_key
    fpath = None
    for fname in os.listdir(DOWNLOAD_DIR):
        if fname.startswith(resume_key) and not fname.endswith(".part"):
            fpath = os.path.join(DOWNLOAD_DIR, fname)
            break

    if not fpath or not os.path.isfile(fpath):
        return jsonify({"error": "File not found on disk."}), 404

    title = state.get("title", "video")
    # Sanitize title for use as download filename
    safe_title = re.sub(r"[^\w\s\-]", "", title).strip()[:80] or "video"
    ext = os.path.splitext(fpath)[1]
    download_name = f"{safe_title}{ext}"

    # Determine mimetype based on extension
    mime_type = "video/x-matroska" if ext == ".mkv" else "video/mp4"
    if ext == ".mp3":
        mime_type = "audio/mpeg"

    return send_file(
        fpath,
        as_attachment=True,
        download_name=download_name,
        mimetype=mime_type,
    )


# ─────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  YouTube HD Downloader  |  http://127.0.0.1:5000")
    print("=" * 55)
    app.run(host="0.0.0.0", debug=True, threaded=True, port=5000)
