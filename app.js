/* ============================================
   PIXELVERSE DOWNLOADER — APP LOGIC
   ============================================ */

let currentVideoUrl = '';
let currentDownloadId = null;
let pollInterval = null;

// ── Fetch Video Info ──
async function fetchVideoInfo() {
  const url = document.getElementById('videoUrl').value.trim();
  if (!url) {
    showError('Por favor pega un enlace de video.');
    return;
  }

  currentVideoUrl = url;

  // Show loading, hide others
  hideAll();
  document.getElementById('loadingSection').classList.add('visible');

  try {
    const response = await fetch(`/api/info?url=${encodeURIComponent(url)}`);
    const data = await response.json();

    document.getElementById('loadingSection').classList.remove('visible');

    if (data.error) {
      showError(data.error);
      return;
    }

    displayVideoInfo(data);
  } catch (err) {
    document.getElementById('loadingSection').classList.remove('visible');
    showError('Error de conexión. ¿Está corriendo el servidor?');
  }
}

// ── Display Video Info ──
function displayVideoInfo(info) {
  document.getElementById('videoThumbnail').src = info.thumbnail || '';
  document.getElementById('videoTitle').textContent = info.title;
  document.getElementById('videoUploader').textContent = info.uploader;
  document.getElementById('videoDuration').textContent = formatDuration(info.duration);
  document.getElementById('videoDescription').textContent = info.description || '';

  const views = info.view_count ? info.view_count.toLocaleString('es-MX') : '—';
  document.getElementById('videoViews').innerHTML = `<span class="stat-icon">👁️</span> ${views} vistas`;

  const link = document.getElementById('videoLink');
  link.href = info.webpage_url || currentVideoUrl;

  // Show result section
  document.getElementById('resultSection').classList.add('visible');

  // Reset progress and complete sections
  document.getElementById('progressSection').classList.remove('visible');
  document.getElementById('completeSection').classList.remove('visible');
  document.getElementById('downloadBtn').disabled = false;

  // Load history
  refreshHistory();
}

// ── Quality Selection ──
document.querySelectorAll('.quality-option').forEach(option => {
  option.addEventListener('click', () => {
    document.querySelectorAll('.quality-option').forEach(o => o.classList.remove('selected'));
    option.classList.add('selected');
  });
});

// ── Start Download ──
async function startDownload() {
  if (!currentVideoUrl) return;

  const quality = document.querySelector('input[name="quality"]:checked').value;
  const downloadBtn = document.getElementById('downloadBtn');

  downloadBtn.disabled = true;
  downloadBtn.innerHTML = '<span class="btn-icon">⏳</span><span class="btn-text">Iniciando descarga...</span>';

  // Show progress
  document.getElementById('progressSection').classList.add('visible');
  document.getElementById('completeSection').classList.remove('visible');
  document.getElementById('progressFill').style.width = '0%';
  document.getElementById('progressPercent').textContent = '0%';
  document.getElementById('progressLabel').textContent = 'Iniciando descarga...';

  try {
    const response = await fetch(`/api/download?url=${encodeURIComponent(currentVideoUrl)}&quality=${quality}`);
    const data = await response.json();

    if (data.error) {
      showError(data.error);
      downloadBtn.disabled = false;
      downloadBtn.innerHTML = '<span class="btn-icon">⬇️</span><span class="btn-text">Descargar Video</span>';
      return;
    }

    currentDownloadId = data.download_id;

    // Start polling status
    document.getElementById('progressLabel').textContent = 'Descargando...';
    pollDownloadStatus();
  } catch (err) {
    showError('Error al iniciar la descarga.');
    downloadBtn.disabled = false;
    downloadBtn.innerHTML = '<span class="btn-icon">⬇️</span><span class="btn-text">Descargar Video</span>';
  }
}

// ── Poll Download Status ──
function pollDownloadStatus() {
  if (pollInterval) clearInterval(pollInterval);

  pollInterval = setInterval(async () => {
    try {
      const response = await fetch(`/api/status?id=${currentDownloadId}`);
      const data = await response.json();

      if (data.status === 'downloading') {
        const percent = data.progress || '0%';
        document.getElementById('progressPercent').textContent = percent;
        document.getElementById('progressFill').style.width = percent;
        document.getElementById('progressLabel').textContent = 'Descargando...';
      } else if (data.status === 'complete') {
        clearInterval(pollInterval);
        pollInterval = null;
        downloadComplete(data.filename);
      } else if (data.status === 'error') {
        clearInterval(pollInterval);
        pollInterval = null;
        showError(data.error || 'Error durante la descarga.');
        resetDownloadButton();
      }
    } catch (err) {
      // Silently retry
    }
  }, 1000);
}

// ── Download Complete ──
function downloadComplete(filename) {
  // Update progress to 100%
  document.getElementById('progressPercent').textContent = '100%';
  document.getElementById('progressFill').style.width = '100%';
  document.getElementById('progressLabel').textContent = '¡Completado!';

  // Show complete section
  document.getElementById('completeSection').classList.add('visible');
  document.getElementById('completedFilename').textContent = filename;

  const downloadLink = document.getElementById('downloadLink');
  downloadLink.href = `/api/file/${encodeURIComponent(filename)}`;

  // Reset button
  resetDownloadButton();

  // Refresh history
  setTimeout(refreshHistory, 500);
}

// ── History ──
async function refreshHistory() {
  try {
    const response = await fetch('/api/list');
    const data = await response.json();

    const list = document.getElementById('historyList');

    if (!data.files || data.files.length === 0) {
      list.innerHTML = '<p class="history-empty">No hay descargas aún.</p>';
      return;
    }

    list.innerHTML = data.files.map(file => {
      const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
      const ext = file.name.split('.').pop().toUpperCase();
      const icon = ext === 'MP3' ? '🎵' : '🎬';

      return `
        <div class="history-item">
          <span class="history-item-icon">${icon}</span>
          <div class="history-item-info">
            <div class="history-item-name" title="${file.name}">${file.name}</div>
            <div class="history-item-size">${sizeMB} MB · ${ext}</div>
          </div>
          <a class="history-item-download" href="/api/file/${encodeURIComponent(file.name)}" download title="Descargar">⬇️</a>
        </div>
      `;
    }).join('');

    document.getElementById('historySection').style.display = 'block';
  } catch (err) {
    // Silently fail
  }
}

// ── Helpers ──
function formatDuration(seconds) {
  if (!seconds) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function hideAll() {
  document.getElementById('loadingSection').classList.remove('visible');
  document.getElementById('errorSection').classList.remove('visible');
  document.getElementById('resultSection').classList.remove('visible');
  document.getElementById('progressSection').classList.remove('visible');
  document.getElementById('completeSection').classList.remove('visible');
}

function showError(message) {
  hideAll();
  document.getElementById('errorMessage').textContent = message;
  document.getElementById('errorSection').classList.add('visible');
}

function hideError() {
  document.getElementById('errorSection').classList.remove('visible');
}

function clearInput() {
  document.getElementById('videoUrl').value = '';
  document.getElementById('videoUrl').focus();
  hideAll();
}

function resetDownloadButton() {
  const btn = document.getElementById('downloadBtn');
  btn.disabled = false;
  btn.innerHTML = '<span class="btn-icon">⬇️</span><span class="btn-text">Descargar Video</span>';
}

// ── Enter Key Support ──
document.getElementById('videoUrl').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') fetchVideoInfo();
});

// ── Init: Load History ──
refreshHistory();

console.log('⬇️ PixelVerse Downloader loaded');
