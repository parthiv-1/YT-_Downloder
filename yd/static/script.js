/**
 * script.js — YouTube HD Downloader Frontend Logic
 * =================================================
 * Communicates with the Flask backend via fetch API.
 * Handles: URL fetch, quality selection, SSE progress streaming,
 *          file download triggering, error display, and UI state management.
 */

"use strict";

// ─────────────────────────────────────────────────────────────
// DOM References
// ─────────────────────────────────────────────────────────────

const urlInput      = document.getElementById("url-input");
const fetchBtn      = document.getElementById("fetch-btn");
const urlError      = document.getElementById("url-error");
const loadingCard   = document.getElementById("loading-card");
const videoCard     = document.getElementById("video-card");
const progressCard  = document.getElementById("progress-card");

// Video info elements
const videoThumb    = document.getElementById("video-thumb");
const videoTitle    = document.getElementById("video-title");
const videoChannel  = document.getElementById("video-channel").querySelector("span");
const videoDuration = document.getElementById("video-duration").querySelector("span");
const videoViews    = document.getElementById("video-views").querySelector("span");
const qualityGrid   = document.getElementById("quality-grid");

// Progress elements
const progressLabel = document.getElementById("progress-label");
const progressPct   = document.getElementById("progress-pct");
const progressBar   = document.getElementById("progress-bar");
const progressTrack = document.getElementById("progress-track");
const progressMeta  = document.getElementById("progress-meta");
const downloadLink  = document.getElementById("download-link");
const cancelBtn     = document.getElementById("cancel-btn");
const progressEta   = document.getElementById("progress-eta");
const smartDownloadBtn = document.getElementById("smart-download-btn");
const mp3DownloadBtn   = document.getElementById("mp3-download-btn");
const smartDesc     = document.getElementById("smart-desc");

const toast         = document.getElementById("toast");

// ─────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────

let currentUrl     = "";          // sanitised URL from last fetch
let currentHint    = null;        // strategy hint from backend
let currentIsShort = false;       // for smart quality speed-up
let isDownloading  = false;       // prevent multiple concurrent downloads
let sseSource      = null;        // active EventSource connection
let toastTimer     = null;        // pending toast hide timer

// ─────────────────────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────────────────────

/** Format seconds into mm:ss or hh:mm:ss */
function formatDuration(seconds) {
  if (!seconds) return "Unknown";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h > 0
    ? `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`
    : `${m}:${String(s).padStart(2,"0")}`;
}

/** Format large numbers with locale-aware commas */
function formatViews(n) {
  if (!n) return "Unknown";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M views";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K views";
  return n.toLocaleString() + " views";
}

/** Show a toast notification */
function showToast(msg, type = "info", duration = 3500) {
  toast.textContent = msg;
  toast.className = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), duration);
}

/** Show inline URL error */
function showUrlError(msg) {
  urlError.innerHTML = `<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><circle cx='12' cy='12' r='10'/><line x1='12' y1='8' x2='12' y2='12'/><line x1='12' y1='16' x2='12.01' y2='16'/></svg>${msg}`;
  urlError.hidden = false;
}

/** Clear inline URL error */
function clearUrlError() {
  urlError.hidden = true;
  urlError.textContent = "";
}

/** Toggle the fetch button loading state */
function setFetchLoading(on) {
  const text = fetchBtn.querySelector(".btn-text");
  const icon = fetchBtn.querySelector(".btn-icon");
  fetchBtn.disabled = on;
  if (on) {
    text.textContent = "Fetching…";
    icon.innerHTML = `<span class="spinner"></span>`;
  } else {
    text.textContent = "Fetch Video";
    icon.innerHTML = `<i data-feather="arrow-right"></i>`;
    feather.replace();
  }
}

/** Show / hide sections */
function showSection(id) {
  [loadingCard, videoCard, progressCard].forEach(el => el.hidden = true);
  if (id) document.getElementById(id).hidden = false;
}

/** Close the active SSE connection if any */
function closeSse() {
  if (sseSource) {
    sseSource.close();
    sseSource = null;
  }
}

/** Lock all quality buttons during active download */
function setQualityBtnsDisabled(state) {
  qualityGrid.querySelectorAll(".quality-btn").forEach(btn => btn.disabled = state);
  if (smartDownloadBtn) smartDownloadBtn.disabled = state;
  if (mp3DownloadBtn) mp3DownloadBtn.disabled = state;
}

// ─────────────────────────────────────────────────────────────
// Fetch Video Info
// ─────────────────────────────────────────────────────────────

/**
 * Called when user clicks "Fetch Video".
 * Sends URL to backend, renders video info + quality options.
 */
async function fetchVideoInfo() {
  const url = urlInput.value.trim();
  clearUrlError();

  // Client-side basic validation
  if (!url) {
    showUrlError("Please enter a YouTube URL.");
    return;
  }
  if (!/^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/.+/.test(url)) {
    showUrlError("Please enter a valid YouTube URL.");
    return;
  }

  // Reset UI
  showSection("loading-card");
  setFetchLoading(true);
  qualityGrid.innerHTML = "";
  closeSse();
  isDownloading = false;

  try {
    const res = await fetch("/api/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    const data = await res.json();

    if (!res.ok) {
      showSection(null);
      showUrlError(data.error || "Failed to fetch video info.");
      return;
    }

    // Save URL and hint for download requests
    currentUrl = url;
    currentHint = data.hint;
    currentIsShort = data.is_short;

    // Populate video metadata
    videoThumb.src    = data.thumbnail || "";
    videoThumb.alt    = data.title || "Video thumbnail";
    videoTitle.textContent  = data.title || "Unknown Title";
    videoChannel.textContent = data.channel || "Unknown";
    videoDuration.textContent = formatDuration(data.duration);
    videoViews.textContent    = formatViews(data.view_count);

    // Set Smart Download description
    if (data.is_short) {
      smartDesc.textContent = "Short detected — Targeting 2K (1440p)";
    } else {
      smartDesc.textContent = "Long video — Targeting 4K (2160p)";
    }

    // Build quality buttons
    buildQualityGrid(data.resolutions || []);

    showSection("video-card");
    videoCard.classList.add("fade-in");
    // Re-render feather icons injected in quality grid
    feather.replace();

  } catch (err) {
    showSection(null);
    showUrlError("Network error. Is the server running?");
    console.error(err);
  } finally {
    setFetchLoading(false);
  }
}

// ─────────────────────────────────────────────────────────────
// Build Quality Grid
// ─────────────────────────────────────────────────────────────

/**
 * Renders a button card for each available resolution.
 * @param {Array} resolutions - [{label, height, note}]
 */
function buildQualityGrid(resolutions) {
  if (resolutions.length === 0) {
    qualityGrid.innerHTML = `<p style="color:var(--text-muted);font-size:.88rem;">No formats available.</p>`;
    return;
  }

  qualityGrid.innerHTML = resolutions.map(r => {
    const isHD = r.height >= 720;
    const noteClass = isHD ? "" : "sd";
    return `
      <button
        class="quality-btn"
        role="listitem"
        data-height="${r.height}"
        aria-label="Download in ${r.label}"
        title="Download ${r.label} (${r.note})"
      >
        <div class="quality-icon"><i data-feather="${isHD ? 'film' : 'video'}"></i></div>
        <span class="quality-label">${r.label}</span>
        <span class="quality-note ${noteClass}">${r.note}</span>
      </button>`;
  }).join("");

  // Wire click handlers
  qualityGrid.querySelectorAll(".quality-btn").forEach(btn => {
    btn.addEventListener("click", () => startDownload(Number(btn.dataset.height)));
  });
}

// ─────────────────────────────────────────────────────────────
// Start Download
// ─────────────────────────────────────────────────────────────

/**
 * Initiates a download for the selected quality.
 * @param {number} height - Resolution height (e.g. 720, 1080, 0 for best)
 */
async function startDownload(height) {
  if (isDownloading) {
    showToast("⚠️ A download is already in progress.", "error");
    return;
  }

  isDownloading = true;
  setQualityBtnsDisabled(true);

  // Switch to progress card
  showSection("progress-card");
  progressCard.classList.add("fade-in");
  progressBar.style.width = "0%";
  progressPct.textContent = "0%";
  progressTrack.setAttribute("aria-valuenow", 0);
  progressMeta.textContent = "";
  progressEta.hidden = true;
  progressEta.textContent = "";
  downloadLink.hidden = true;
  cancelBtn.hidden = false;

  setProgressLabel("pending", 0);

  try {
    // Request backend to start download
    const res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 
        url: currentUrl, 
        height, 
        hint: currentHint,
        is_short: currentIsShort 
      }),
    });

    const data = await res.json();

    if (!res.ok || !data.task_id) {
      throw new Error(data.error || "Failed to start download.");
    }

    // Begin polling via SSE with a tiny handshake delay for stability
    setTimeout(() => streamProgress(data.task_id), 150);

  } catch (err) {
    isDownloading = false;
    setQualityBtnsDisabled(false);
    showToast("❌ " + err.message, "error");
    showSection("video-card");
  }
}

// ─────────────────────────────────────────────────────────────
// SSE Progress Streaming
// ─────────────────────────────────────────────────────────────

/**
 * Opens an SSE connection to /api/progress/<task_id> and
 * updates the progress UI in real-time.
 * @param {string} taskId
 */
function streamProgress(taskId) {
  closeSse();

  sseSource = new EventSource(`/api/progress/${taskId}`);

  sseSource.onmessage = (event) => {
    let state;
    try {
      state = JSON.parse(event.data);
    } catch {
      return;
    }

    const { status, percent, speed, eta, filename, title, error } = state;

    // Update progress bar
    const pct = Math.min(percent || 0, 100);
    progressBar.style.width   = `${pct}%`;
    progressPct.textContent   = `${pct}%`;
    progressTrack.setAttribute("aria-valuenow", pct);

    setProgressLabel(status, pct);

    if (speed) progressMeta.textContent = `⚡ ${speed}`;
    
    if (eta && status === "downloading") {
      progressEta.innerHTML = `<i data-feather="clock" style="width:13px;height:13px;"></i> ${formatDuration(eta)}`;
      progressEta.hidden = false;
      feather.replace();
    } else {
      progressEta.hidden = true;
    }

    if (status === "done") {
      closeSse();
      isDownloading = false;
      setQualityBtnsDisabled(false);

      // Show the save button
      downloadLink.href    = `/api/file/${taskId}`;
      downloadLink.hidden  = false;
      cancelBtn.hidden     = true;
      cancelBtn.hidden     = false;

      progressPct.textContent = "100%";
      progressBar.style.width = "100%";
      progressMeta.textContent = title ? `✅ Ready: ${title}` : "✅ Download ready!";

      showToast("🎉 Download complete! Click 'Save File'.", "success", 5000);
      feather.replace();
    }

    if (status === "error") {
      closeSse();
      isDownloading = false;
      setQualityBtnsDisabled(false);

      progressMeta.textContent = `❌ ${error || "Unknown error occurred."}`;
      showToast("❌ " + (error || "Download failed."), "error", 6000);
      cancelBtn.hidden = false;
      downloadLink.hidden = true;
    }
  };

  sseSource.onerror = (e) => {
    console.error("SSE Connection Error:", e);
    closeSse();
    if (isDownloading) {
      isDownloading = false;
      setQualityBtnsDisabled(false);
      progressMeta.textContent = "❌ Connection lost. Please try again.";
      showToast("Connection to server lost.", "error");
    }
  };
}

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

/** Update the progress label text for a given status */
function setProgressLabel(status, pct) {
  const labels = {
    pending:     `<span class="spinner"></span> Preparing download…`,
    downloading: `<span class="spinner"></span> Downloading… ${pct}%`,
    merging:     `<span class="spinner"></span> Merging audio & video…`,
    done:        `✅ Done!`,
    error:       `❌ Failed`,
  };
  progressLabel.innerHTML = labels[status] || `<span class="spinner"></span> Working…`;
}

// ─────────────────────────────────────────────────────────────
// Event Listeners
// ─────────────────────────────────────────────────────────────

// Fetch button click
fetchBtn.addEventListener("click", fetchVideoInfo);

// Allow Enter key in URL input
urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") fetchVideoInfo();
});

// Clear error on input change
urlInput.addEventListener("input", () => {
  clearUrlError();
  // Persistence: Save to session storage (persists on refresh, clears on tab close)
  sessionStorage.setItem("yt_downloader_last_url", urlInput.value.trim());
});

// Cancel / back button
cancelBtn.addEventListener("click", () => {
  closeSse();
  isDownloading = false;
  setQualityBtnsDisabled(false);
  showSection("video-card");
  showToast("Download cancelled.", "info");
});

// Paste shortcut: Ctrl+V into input auto-focuses
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "v") {
    urlInput.focus();
  }
});

// Internet Connection Status Listeners
window.addEventListener("online", () => {
    showToast("🌐 You are online and your downloading will started", "success", 5000);
});

window.addEventListener("offline", () => {
    showToast("⚠️ You are ofline", "error", 5000);
});

// Smart Download button click
smartDownloadBtn.addEventListener("click", () => {
  startDownload(-1); // -1 triggers backend smart logic
});

// MP3 Download button click
mp3DownloadBtn.addEventListener("click", () => {
  startDownload(-2); // -2 triggers backend MP3 logic
});

// ─────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────

// Persistence: Restore last URL from sessionStorage
const savedUrl = sessionStorage.getItem("yt_downloader_last_url");
if (savedUrl) {
  urlInput.value = savedUrl;
  fetchVideoInfo(); // Auto-fetch video info on page load
}

urlInput.focus();
