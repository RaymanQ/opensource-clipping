/**
 * OpenSource Clipping Studio — API Client
 * 
 * Shared module for all studio pages.
 * Backend URL is stored in localStorage and configurable via the Connect modal.
 */

const StudioAPI = (() => {
  const STORAGE_KEY = 'osc_backend_url';
  const TOKEN_KEY = 'osc_backend_token';

  /** Get the saved backend URL */
  function getBackendUrl() {
    return (localStorage.getItem(STORAGE_KEY) || '').replace(/\/+$/, '');
  }

  /** Save backend URL */
  function setBackendUrl(url) {
    localStorage.setItem(STORAGE_KEY, url.replace(/\/+$/, ''));
  }

  function getAccessToken() { return sessionStorage.getItem(TOKEN_KEY) || ''; }
  function setAccessToken(token) {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  }

  /** Clear backend URL */
  function clearBackendUrl() {
    localStorage.removeItem(STORAGE_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
  }

  /** Check if connected (URL is set) */
  function isConfigured() {
    return !!getBackendUrl();
  }

  function resolveUrl(path) {
    if (!path) return '';
    if (/^https?:\/\//i.test(path)) return path;
    const base = getBackendUrl();
    return base ? new URL(path, `${base}/`).toString() : path;
  }

  function requestHeaders(headers = {}, body = null, includeAuth = true) {
    const result = new Headers(headers);
    if (!result.has('ngrok-skip-browser-warning')) {
      result.set('ngrok-skip-browser-warning', 'true');
    }
    const token = getAccessToken();
    if (includeAuth && token && !result.has('Authorization')) {
      result.set('Authorization', `Bearer ${token}`);
    }
    if (body && !(body instanceof FormData) && !result.has('Content-Type')) {
      result.set('Content-Type', 'application/json');
    }
    return result;
  }

  async function fetchFromBackend(path, options = {}) {
    const base = getBackendUrl();
    if (!base) throw new Error('Backend URL not configured. Please connect first.');

    const url = resolveUrl(path);
    const { timeout = 30000, headers: optionHeaders, signal: externalSignal, ...fetchOptions } = options;
    const isBackendOrigin = new URL(url).origin === new URL(base).origin;
    const headers = requestHeaders(optionHeaders, fetchOptions.body, isBackendOrigin);
    const controller = new AbortController();
    let timedOut = false;
    const abortFromCaller = () => controller.abort();
    if (externalSignal) {
      if (externalSignal.aborted) controller.abort();
      else externalSignal.addEventListener('abort', abortFromCaller, { once: true });
    }
    const timer = timeout ? setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeout) : null;
    let res;
    try {
      res = await fetch(url, { ...fetchOptions, headers, signal: controller.signal });
    } catch (error) {
      if (error.name === 'AbortError' && timedOut) throw new Error('Backend request timed out.');
      if (error.name === 'AbortError') throw error;
      throw new Error('Backend is offline or unreachable.');
    } finally {
      if (timer) clearTimeout(timer);
      if (externalSignal) externalSignal.removeEventListener('abort', abortFromCaller);
    }
    return res;
  }

  async function ensureResponseOk(res) {
    if (!res.ok) {
      const responseText = await res.text().catch(() => '');
      let body = {};
      try { body = responseText ? JSON.parse(responseText) : {}; }
      catch { body = {}; }
      const detail = Array.isArray(body.detail)
        ? body.detail.map(item => item.msg || JSON.stringify(item)).join('; ')
        : (body.detail && typeof body.detail === 'object' ? JSON.stringify(body.detail) : body.detail);
      const shortText = responseText && responseText.length <= 300 ? responseText : '';
      throw new Error(detail || shortText || `Request failed: ${res.status}`);
    }
    return res;
  }

  /** Generic JSON fetch wrapper with error handling. */
  async function request(path, options = {}) {
    const res = await ensureResponseOk(await fetchFromBackend(path, options));
    return res.json();
  }

  /** Fetch a protected backend resource without attempting JSON decoding. */
  async function fetchBlob(path, options = {}) {
    const res = await ensureResponseOk(await fetchFromBackend(path, options));
    return res.blob();
  }

  async function createAuthenticatedObjectUrl(path, options = {}) {
    const blob = await fetchBlob(path, { timeout: 0, ...options });
    return URL.createObjectURL(blob);
  }

  async function downloadFile(path, filename, options = {}) {
    const objectUrl = await createAuthenticatedObjectUrl(path, options);
    const safeFilename = String(filename || 'download')
      .split(/[\\/]/).pop()
      .replace(/[\u0000-\u001f\u007f]/g, '')
      .trim() || 'download';
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = safeFilename;
    anchor.style.display = 'none';
    document.body.appendChild(anchor);
    try {
      anchor.click();
    } finally {
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    }
  }

  // ---- Health ----
  async function checkHealth() {
    return request('/api/health');
  }

  async function fetchCapabilities() { return request('/api/capabilities'); }

  // ---- Jobs ----
  async function fetchJobs() {
    return request('/api/jobs');
  }

  async function fetchJob(jobId) {
    return request(`/api/jobs/${jobId}`);
  }

  async function createJob(payload) {
    return request('/api/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async function deleteJob(jobId) {
    return request(`/api/jobs/${jobId}`, { method: 'DELETE' });
  }

  async function fetchOutputs(jobId) { return request(`/api/outputs/${jobId}`); }

  // ---- Settings ----
  async function fetchSettings() {
    return request('/api/settings');
  }

  async function updateSettings(payload) {
    return request('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async function uploadVideo(file) {
    const body = new FormData();
    body.append('file', file);
    return request('/api/upload/video', { method: 'POST', body, timeout: 0 });
  }

  async function uploadAsset(file, assetType) {
    const body = new FormData();
    body.append('file', file);
    body.append('asset_type', assetType);
    return request('/api/upload/asset', { method: 'POST', body, timeout: 0 });
  }

  // ---- SSE for real-time job status ----
  function createSSE(jobId, onMessage) {
    const base = getBackendUrl();
    if (!base) return null;
    let closed = false;
    let controller = null;
    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
    (async () => {
      while (!closed) {
        controller = new AbortController();
        try {
          const res = await fetch(`${base}/api/jobs/${encodeURIComponent(jobId)}/status`, {
            headers: requestHeaders({ Accept: 'text/event-stream' }),
            signal: controller.signal,
          });
          if (!res.ok || !res.body) throw new Error(`Stream failed: ${res.status}`);
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          while (!closed) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const events = buffer.split('\n\n');
            buffer = events.pop();
            events.forEach(block => {
              const line = block.split('\n').find(row => row.startsWith('data:'));
              if (!line) return;
              try { onMessage(JSON.parse(line.slice(5).trim())); }
              catch (error) { console.error('SSE parse error:', error); }
            });
          }
        } catch (error) {
          if (!closed && error.name !== 'AbortError') await sleep(2000);
        }
      }
    })();
    return { close() { closed = true; if (controller) controller.abort(); } };
  }

  // ---- Server Shutdown ----
  async function shutdownServer() {
    return request('/api/shutdown', { method: 'POST' });
  }

  // Public API
  return {
    getBackendUrl,
    setBackendUrl,
    getAccessToken,
    setAccessToken,
    clearBackendUrl,
    isConfigured,
    checkHealth,
    fetchCapabilities,
    fetchJobs,
    fetchJob,
    createJob,
    deleteJob,
    fetchOutputs,
    fetchSettings,
    updateSettings,
    uploadVideo,
    uploadAsset,
    resolveUrl,
    fetchBlob,
    createAuthenticatedObjectUrl,
    downloadFile,
    createSSE,
    shutdownServer,
  };
})();

const JOB_PRESETS = {
  recommended: { label: 'Recommended', description: 'Balanced defaults for most clips.', values: {} },
  fast: { label: 'Fast', description: 'Small Whisper model and fast scaling.', values: { whisper_model: 'small', video_preset: 'veryfast', video_scale_algo: 'bilinear', use_broll: false } },
  balanced: { label: 'Balanced', description: 'Quality and speed for routine work.', values: { whisper_model: 'medium', video_preset: 'auto', video_cq: 23, video_crf: 20 } },
  best: { label: 'Best Quality', description: 'Slower, sharper 1080p output.', values: { whisper_model: 'large-v3', video_cq: 19, video_crf: 17, video_preset: 'slow', video_sharpen: true } },
  shorts: { label: 'YouTube Shorts', description: 'Vertical clips with bold subtitles.', values: { ratio: '9:16', font_style: 'HORMOZI', use_karaoke_effect: true } },
  reels: { label: 'Instagram Reels', description: 'Vertical, sharp social output.', values: { ratio: '9:16', video_sharpen: true, clips: 5 } },
  tiktok: { label: 'TikTok', description: 'Vertical, quick subtitles and hooks.', values: { ratio: '9:16', words_per_sub: 4, hook_v2: true } },
  podcast: { label: 'Podcast', description: 'Speaker-aware vertical reframing.', values: { ratio: '9:16', use_camera_switch: true, use_split_screen: false } },
  split_podcast: { label: 'Split-Screen Podcast', description: 'Two-speaker split screen.', values: { ratio: '9:16', use_split_screen: true, use_camera_switch: false } },
  debug: { label: 'Debug', description: 'Tracking overlays and one clip.', values: { clips: 1, dev_mode: true, box_face_detection: true, track_lines: true } },
};


// ============================================================
// Shared UI Utilities (used across all studio pages)
// ============================================================

/** Theme toggle */
function toggleTheme() {
  if (document.documentElement.classList.contains('dark')) {
    document.documentElement.classList.remove('dark');
    localStorage.setItem('theme', 'light');
  } else {
    document.documentElement.classList.add('dark');
    localStorage.setItem('theme', 'dark');
  }
}

/** Format date string to locale */
function formatDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleString('id-ID', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>\"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;',
  }[char]));
}

/** Status labels */
const STATUS_LABELS = {
  queued: 'Queued',
  downloading: 'Downloading',
  transcribing: 'Transcribing',
  analyzing: 'Analyzing',
  rendering: 'Rendering',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

/** Mobile sidebar toggle */
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('mobile-overlay');
  sidebar.classList.toggle('open');
  if (sidebar.classList.contains('open')) {
    overlay.style.display = 'block';
  } else {
    overlay.style.display = 'none';
  }
}

function closeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('mobile-overlay');
  sidebar.classList.remove('open');
  overlay.style.display = 'none';
}

/** Update sidebar connection indicator */
function updateConnectIndicator() {
  const dot = document.getElementById('connect-dot');
  const label = document.getElementById('connect-label');
  const btn = document.getElementById('connect-btn');
  const stopBtn = document.getElementById('sidebar-stop-btn');
  if (!dot || !label) return;

  if (StudioAPI.isConfigured()) {
    dot.className = 'connect-dot online';
    const url = StudioAPI.getBackendUrl();
    try {
      label.textContent = new URL(url).hostname;
    } catch {
      label.textContent = 'Connected';
    }
    if (btn) btn.textContent = 'Change';
    if (stopBtn) stopBtn.classList.remove('hidden');
  } else {
    dot.className = 'connect-dot offline';
    label.textContent = 'Not connected';
    if (btn) btn.textContent = 'Connect';
    if (stopBtn) stopBtn.classList.add('hidden');
  }
}

/** Show connect modal */
function showConnectModal() {
  const existing = document.getElementById('connect-modal-backdrop');
  if (existing) existing.remove();

  const currentUrl = StudioAPI.getBackendUrl();
  const hasToken = !!StudioAPI.getAccessToken();

  const backdrop = document.createElement('div');
  backdrop.id = 'connect-modal-backdrop';
  backdrop.className = 'connect-modal-backdrop';
  backdrop.innerHTML = `
    <div class="connect-modal">
      <div class="flex items-center justify-between mb-4">
        <h3 class="font-display font-bold text-lg text-slate-900 dark:text-white">Connect to Backend</h3>
        <button onclick="closeConnectModal()" class="p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
          <i data-lucide="x" class="w-5 h-5 text-slate-400"></i>
        </button>
      </div>
      <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">
        Paste the tunnel URL from your Kaggle/Colab notebook. Run the notebook first to get the URL.
      </p>
      <div class="mb-4">
        <input id="connect-url-input" type="url" value="${currentUrl}" 
          placeholder="https://xxxx-xx-xx.ngrok-free.app"
          class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 text-slate-900 dark:text-white placeholder-slate-400 font-mono"
        />
      </div>
      <div class="mb-4">
        <label class="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1.5">Backend Access Token <span class="font-normal text-slate-400">(optional)</span></label>
        <input id="connect-token-input" type="password" value=""
          placeholder="${hasToken ? 'Token already stored for this tab' : 'OSC_API_TOKEN'}"
          class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/50 text-slate-900 dark:text-white placeholder-slate-400 font-mono"
        />
        <p class="text-xs text-slate-400 mt-1">Stored only in sessionStorage and cleared when this browser session ends.</p>
      </div>
      <div id="connect-status-msg" class="text-sm mb-4 hidden"></div>
      <div class="flex gap-3">
        <button id="connect-test-btn" onclick="testAndConnect()" class="flex-1 px-4 py-2.5 rounded-xl bg-brand-600 text-white font-medium hover:bg-brand-700 transition-colors text-sm">
          Test & Connect
        </button>
        ${currentUrl ? `
          <button onclick="disconnectBackend()" title="Disconnect UI from backend" class="px-3 py-2.5 rounded-xl border border-red-200 dark:border-red-900/50 text-red-600 dark:text-red-400 font-medium hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors text-sm">
            Disconnect
          </button>
          <button id="stop-server-btn" onclick="stopBackendServer()" title="Shut down the backend process" class="px-3 py-2.5 rounded-xl border border-red-500 bg-red-600 text-white font-medium hover:bg-red-700 transition-colors text-sm">
            Stop Server
          </button>
        ` : ''}
      </div>
    </div>
  `;

  document.body.appendChild(backdrop);
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) closeConnectModal();
  });
  lucide.createIcons();
  document.getElementById('connect-url-input').focus();
}

function closeConnectModal() {
  const backdrop = document.getElementById('connect-modal-backdrop');
  if (backdrop) backdrop.remove();
}

async function testAndConnect() {
  const input = document.getElementById('connect-url-input');
  const msg = document.getElementById('connect-status-msg');
  const btn = document.getElementById('connect-test-btn');
  const url = input.value.trim();
  const tokenInput = document.getElementById('connect-token-input');

  if (!url) {
    msg.className = 'text-sm mb-4 text-red-500';
    msg.textContent = '⚠️ Please enter a URL';
    msg.classList.remove('hidden');
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner spinner-dark"></span> Testing...';
  msg.className = 'text-sm mb-4 text-slate-500 dark:text-slate-400';
  msg.textContent = '⏳ Connecting...';
  msg.classList.remove('hidden');

  try {
    StudioAPI.setBackendUrl(url);
    if (tokenInput.value) StudioAPI.setAccessToken(tokenInput.value);
    const health = await StudioAPI.checkHealth();
    await StudioAPI.fetchJobs();
    msg.className = 'text-sm mb-4 text-emerald-600 dark:text-emerald-400';
    msg.textContent = `✅ Connected! GPU: ${health.gpu_available ? '✅' : '❌'} | FFmpeg: ${health.ffmpeg_available ? '✅' : '❌'}`;
    updateConnectIndicator();

    setTimeout(() => closeConnectModal(), 1200);
  } catch (err) {
    StudioAPI.clearBackendUrl();
    msg.className = 'text-sm mb-4 text-red-500';
    msg.textContent = `❌ Connection failed: ${err.message}`;
    updateConnectIndicator();
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Test & Connect';
  }
}

function disconnectBackend() {
  StudioAPI.clearBackendUrl();
  updateConnectIndicator();
  closeConnectModal();
}

async function stopBackendServer() {
  const btn = document.getElementById('stop-server-btn');
  const msg = document.getElementById('connect-status-msg');

  if (!confirm('Are you sure you want to STOP the Kaggle backend server? You will have to restart the notebook cell manually.')) {
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner spinner-light"></span> Stopping...';
  }

  if (msg) {
    msg.className = 'text-sm mb-4 text-slate-500 dark:text-slate-400';
    msg.textContent = '⏳ Sending shutdown signal...';
    msg.classList.remove('hidden');
  }

  try {
    await StudioAPI.shutdownServer();
    if (msg) {
      msg.className = 'text-sm mb-4 text-emerald-600 dark:text-emerald-400';
      msg.textContent = '✅ Server stopped successfully.';
    }
  } catch (err) {
    // A fetch error is expected if the server dies immediately
    console.log('Server disconnected during shutdown:', err);
  } finally {
    setTimeout(() => {
      StudioAPI.clearBackendUrl();
      updateConnectIndicator();
      closeConnectModal();
    }, 1500);
  }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  updateConnectIndicator();
});
