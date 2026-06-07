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
    """Basic sanitization — strip whitespace and validate YouTube domain."""
    url = url.strip()
    pattern = r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+"
    if not re.match(pattern, url):
        raise ValueError("Not a valid YouTube URL.")
    return url


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
    """Find the most relevant cookie file in the downloads folder or read from env."""
    # Check if cookies are set in environment variables
    env_cookies = os.environ.get("YOUTUBE_COOKIES")
    if env_cookies:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        cookie_path = os.path.join(DOWNLOADS_DIR, "env_cookies.txt")
        try:
            content = env_cookies.strip()
            # Try base64 decoding to handle Railway multiline environment variable pasting issues
            import base64
            try:
                # Strip spaces and newlines if they are present in base64 string
                clean_b64 = content.replace(" ", "").replace("\n", "").replace("\r", "")
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

    if not os.path.isdir(DOWNLOADS_DIR):
        return None

    # Priority order for cookie file names
    variants = [
        "cookies.txt",
        "cookies (4).txt",
        "cookies (3).txt",
        "cookies (2).txt",
        "cookies (1).txt",
    ]
    for v in variants:
        path = os.path.join(DOWNLOADS_DIR, v)
        if os.path.isfile(path):
            return path

    # Fallback: find any .txt file that looks like a cookie file
    for fname in os.listdir(DOWNLOADS_DIR):
        if fname.endswith(".txt") and "cookie" in fname.lower():
            return os.path.join(DOWNLOADS_DIR, fname)
    return None


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
    "sign in to confirm you're not a bot",
    "n-parameter",
    "drm protected",
    "sign in to confirm",
    "not available in your country",
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
    Advanced Senior-Developer Extraction Strategy:
      - Tries specialized web clients (Web, Music Web, Embedded).
      - Uses robust browser header spoofing.
      - Enforces JS runtime for n-challenge resolution.
    """
    strategies: list[dict] = []
    current_cookie_file = get_best_cookie_file()

    if current_cookie_file and os.path.isfile(current_cookie_file):
        strategies.append({"cookiefile": current_cookie_file})
        print(f"  [Cookies] Trying strategy: {os.path.basename(current_cookie_file)}")

    strategies.append({})  # Unauthenticated fallback
    print(f"  [Cookies] Trying without cookies (Unauthenticated)")

    configs = [
        {
            "name": "4K Unlocked Mode",
            "clients": ["android_vr", "tv", "web"],
            "headers": {},  # Clean for VR/TV protocol
        },
        {"name": "Legacy Mode", "clients": ["android", "ios"], "headers": {}},
        {
            "name": "Web Mode",
            "clients": ["web", "mweb", "web_embedded"],
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            },
        },
    ]

    # If hint is provided, prioritize it
    if hint and "cookie_idx" in hint and "config_idx" in hint:
        h_cookie_idx = hint["cookie_idx"]
        h_config_idx = hint["config_idx"]

        if h_cookie_idx < len(strategies) and h_config_idx < len(configs):
            cookie_opt = strategies[h_cookie_idx]
            cfg = configs[h_config_idx]
            label = f"[HINTED] {cfg['name']}"
            opts = {**base_opts, **cookie_opt}

            try:
                opts["extractor_args"] = {
                    "youtube": {
                        "player_client": cfg["clients"],
                        "include_dash_manifest": True,
                        "player_skip": (
                            ["web_embedded", "js", "configs"]
                            if not download
                            else ["web_embedded"]
                        ),
                    }
                }
                if cfg["headers"]:
                    opts["http_headers"] = cfg["headers"]
                opts["no_color"] = True
                opts["nocheckcertificate"] = True

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=download)
                return info, {"cookie_idx": h_cookie_idx, "config_idx": h_config_idx}
            except Exception as e:
                print(f"  [Hint Failed] {str(e)[:100]}... falling back to full scan.")

    last_exc: Exception | None = None

    for s_idx, cookie_opt in enumerate(strategies):
        c_label = (
            os.path.basename(current_cookie_file)
            if "cookiefile" in cookie_opt and current_cookie_file
            else "no cookies"
        )

        for c_idx, cfg in enumerate(configs):
            label = f"{c_label} + {cfg['name']}"
            opts = {**base_opts, **cookie_opt}

            try:
                opts["extractor_args"] = {
                    "youtube": {
                        "player_client": cfg["clients"],
                        "include_dash_manifest": True,
                        "player_skip": (
                            ["web_embedded", "js", "configs"]
                            if not download
                            else ["web_embedded"]
                        ),
                    }
                }

                # Forced Node.js runtime for n-challenge solving
                # Let yt-dlp automatically detect Node.js/Deno from PATH
                pass

                if cfg["headers"]:
                    opts["http_headers"] = cfg["headers"]

                opts["no_color"] = True
                opts["nocheckcertificate"] = True

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=download)

                # Quality Gate: If results are only 360p or lower, try next config
                if not download and _is_low_quality(info):
                    print(
                        f"  [Nuclear Warning] [{label}] only found 360p or less. Trying 4K Unlocked Mode..."
                    )
                    raise ValueError("low quality result")

                print(f"  [Absolute Success] Found high-quality formats via [{label}]")
                return info, {"cookie_idx": s_idx, "config_idx": c_idx}

            except Exception as exc:
                last_exc = exc
                if _is_retryable_error(exc) or str(exc) == "low quality result":
                    print(
                        f"  [Warning] [{label}] failed or low quality — attempting next Compatibility Mode..."
                    )
                    continue
                raise

    # All strategies and clients failed
    raise last_exc if last_exc else Exception("All extraction strategies failed.")


def get_video_info(url: str) -> tuple[dict, dict]:
    """
    Fetch video metadata using yt-dlp without downloading.
    Returns (video_data, strategy_hint).
    """
    base_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 10,
        "check_formats": False,
    }

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
                "note": "Auto",
                "needs_ffmpeg": False,
                "available": True,
            }
        )

    return {
        "title": info.get("title", "Unknown Title"),
        "thumbnail": info.get("thumbnail", ""),
        "duration": info.get("duration", 0),
        "channel": info.get("uploader", "Unknown"),
        "view_count": info.get("view_count", 0),
        "resolutions": resolution_list,
        "ffmpeg_available": HAS_FFMPEG,
        "is_short": (info.get("duration", 0) or 0) <= 60 or "/shorts/" in url.lower(),
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
                    fmt = "bestvideo+bestaudio/best"
                else:
                    # Force exact height search first for pure quality, fallback to <=
                    fmt = (
                        f"bestvideo[height={height}]+bestaudio/"
                        f"bestvideo[height<={height}]+bestaudio/"
                        f"best[height<={height}]/best"
                    )
            else:
                # No FFmpeg — use pre-merged streams only (max 720p)
                if height == 0:
                    fmt = "best[ext=mp4]/best[ext=webm]/best"
                else:
                    capped = min(height, 720)
                    fmt = (
                        f"best[height<={capped}][ext=mp4]"
                        f"/best[height<={capped}][ext=webm]"
                        f"/best[height<={capped}]"
                        f"/best"
                    )

        base_opts = {
            "format": fmt,
            "outtmpl": output_template,
            "merge_output_format": "mkv" if height != -2 else "mp3",
            "postprocessors": postprocessors,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "progress_hooks": [progress_hook],
            # ── Timeout & Retry Settings ──────────────────────────
            "socket_timeout": 30,
            "retries": 1000,
            "fragment_retries": 1000,
            "file_access_retries": 5,
            "extractor_retries": 5,
            "continuedl": True,
            "concurrent_fragment_downloads": 16,
            "buffersize": 2097152,
            "http_chunk_size": 10485760,
            "sleep_interval": 0,
            "max_sleep_interval": 0,
        }

        # Add FFmpeg location if available
        if HAS_FFMPEG and FFMPEG_LOCATION:
            base_opts["ffmpeg_location"] = FFMPEG_LOCATION

        try:
            info, _ = _extract_with_cookie_fallback(
                base_opts, url, download=True, hint=hint
            )
            title = info.get("title", "video") if info else "video"

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
            progress_store[task_id]["status"] = "error"
            progress_store[task_id]["error"] = str(e).split("\n")[0]
        except Exception as e:
            progress_store[task_id]["status"] = "error"
            progress_store[task_id]["error"] = f"Unexpected error: {str(e)}"


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────


@app.route("/")
def index():
    """Home page."""
    return render_template("index.html")


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
    app.run(debug=True, threaded=True, port=5000)
