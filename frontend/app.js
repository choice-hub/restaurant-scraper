// Mouse-following cursor glow
const glow = document.getElementById('cursor-glow');
let mx = window.innerWidth / 2, my = window.innerHeight / 2;
let cx = mx, cy = my;
document.addEventListener('mousemove', e => { mx = e.clientX; my = e.clientY; });
(function animateGlow() {
  cx += (mx - cx) * 0.07;
  cy += (my - cy) * 0.07;
  glow.style.transform = `translate(${cx}px, ${cy}px) translate(-50%, -50%)`;
  requestAnimationFrame(animateGlow);
})();

// Backend API base URL
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:5000'
  : 'https://restaurant-scraper-api-ah9e.onrender.com';

let currentJobId = null;
let pollInterval = null;
let jobStartTime = null;

const PLATFORM_ICONS  = { wolt: '🔵', bolt: '🟢', foodora: '🔴', glovo: '🟡' };
const PLATFORM_LABELS = { wolt: 'Wolt', bolt: 'Bolt Food', foodora: 'Foodora', glovo: 'Glovo' };

// ── Autocomplete ─────────────────────────────────────────────
const locationInput = document.getElementById('location');
const acList = document.getElementById('autocompleteList');
let acTimeout = null;
let acIndex = -1;

locationInput.addEventListener('input', () => {
  clearTimeout(acTimeout);
  const q = locationInput.value.trim();
  if (q.length < 2) { closeAC(); return; }
  acTimeout = setTimeout(() => fetchSuggestions(q), 280);
});

locationInput.addEventListener('keydown', (e) => {
  const items = acList.querySelectorAll('li');
  if (e.key === 'ArrowDown') { acIndex = Math.min(acIndex + 1, items.length - 1); highlightAC(items); e.preventDefault(); }
  else if (e.key === 'ArrowUp') { acIndex = Math.max(acIndex - 1, 0); highlightAC(items); e.preventDefault(); }
  else if (e.key === 'Enter' && acIndex >= 0) { items[acIndex]?.click(); e.preventDefault(); }
  else if (e.key === 'Escape') closeAC();
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.autocomplete-wrap') && !e.target.closest('#autocompleteList')) closeAC();
});

async function fetchSuggestions(q) {
  try {
    const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=8&addressdetails=1&featuretype=city,country&accept-language=en`;
    const res = await fetch(url, { headers: { 'Accept-Language': 'en' } });
    const data = await res.json();
    const european = data.filter(r => {
      const cc = r.address?.country_code?.toUpperCase();
      return EUROPEAN_CC.has(cc);
    });
    renderSuggestions(european.slice(0, 7));
  } catch { closeAC(); }
}

function renderSuggestions(items) {
  acList.innerHTML = '';
  acIndex = -1;
  if (!items.length) { closeAC(); return; }
  items.forEach(item => {
    const city = item.address?.city || item.address?.town || item.address?.village || item.address?.county || '';
    const country = item.address?.country || '';
    const type = item.type === 'administrative' || item.class === 'boundary' ? 'country' : 'city';
    const label = city ? `${city}, ${country}` : country;
    const li = document.createElement('li');
    li.innerHTML = `<span>📍</span><span>${label}</span><span class="ac-type">${type}</span>`;
    li.addEventListener('click', () => { locationInput.value = label; closeAC(); });
    acList.appendChild(li);
  });
  acList.classList.add('open');
}

function highlightAC(items) {
  items.forEach((li, i) => li.classList.toggle('active', i === acIndex));
  items[acIndex]?.scrollIntoView({ block: 'nearest' });
}

function closeAC() {
  acList.innerHTML = '';
  acList.classList.remove('open');
  acIndex = -1;
}

const EUROPEAN_CC = new Set([
  'AL','AD','AT','BY','BE','BA','BG','HR','CY','CZ','DK','EE','FI','FR',
  'DE','GR','HU','IS','IE','IT','XK','LV','LI','LT','LU','MT','MD','MC',
  'ME','NL','MK','NO','PL','PT','RO','RU','SM','RS','SK','SI','ES','SE',
  'CH','UA','GB','VA','TR','AZ','AM','GE'
]);

// ── Platform selection ────────────────────────────────────────
function getSelectedPlatforms() {
  return [...document.querySelectorAll('input[name="platform"]:checked')].map(el => el.value);
}

// ── Start scraping ────────────────────────────────────────────
document.getElementById('btnScrape').addEventListener('click', async () => {
  const platforms = getSelectedPlatforms();
  const location  = document.getElementById('location').value.trim();
  const email     = document.getElementById('email').value.trim();

  if (!platforms.length) return alert('Please select at least one platform.');
  if (!location) return alert('Please enter a city or country.');
  if (!email || !email.includes('@')) return alert('Please enter a valid email address.');

  jobStartTime = null;
  showPanel('progress');
  document.getElementById('progressLocation').textContent = location;
  renderPlatformRows(platforms);
  setProgress(0, 'Connecting...');

  try {
    const res = await fetch(`${API_BASE}/api/scrape`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platforms, location, cuisine: '', email })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to start job');
    currentJobId = data.job_id;
    startPolling(currentJobId);
  } catch (err) {
    showPanel('error');
    document.getElementById('errorMsg').textContent = err.message;
  }
});

// ── Per-platform rows ─────────────────────────────────────────
function renderPlatformRows(platforms) {
  const container = document.getElementById('platformRows');
  container.innerHTML = '';
  platforms.forEach(plat => {
    const row = document.createElement('div');
    row.className = 'platform-row';
    row.id = `row-${plat}`;
    row.innerHTML = `
      <span class="plat-icon">${PLATFORM_ICONS[plat] || '⚪'}</span>
      <span class="plat-name">${PLATFORM_LABELS[plat] || plat}</span>
      <span class="plat-status pending" id="status-${plat}">Queued</span>
      <span class="plat-count" id="count-${plat}"></span>
    `;
    container.appendChild(row);
  });
}

function updatePlatformRows(detail) {
  if (!detail) return;
  Object.entries(detail).forEach(([plat, info]) => {
    const statusEl = document.getElementById(`status-${plat}`);
    const countEl  = document.getElementById(`count-${plat}`);
    if (!statusEl) return;

    const s = info.status;
    statusEl.className = `plat-status ${s}`;
    statusEl.textContent = s === 'running' ? 'Scraping...' : s === 'done' ? 'Done ✓' : 'Queued';

    if (countEl && info.scraped > 0) {
      countEl.textContent = info.scraped.toLocaleString() + ' restaurants';
    }
  });
}

// ── Polling ───────────────────────────────────────────────────
function startPolling(jobId) {
  clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
      const job = await res.json();
      updateProgress(job);
      if (job.status === 'done' || job.status === 'error') clearInterval(pollInterval);
    } catch {
      // network blip — keep polling
    }
  }, 2000);
}

function updateProgress(job) {
  const pct = job.progress || 0;

  updatePlatformRows(job.platforms_detail);

  if (job.status === 'done') {
    showPanel('done');
    const total = job.scraped || 0;
    document.getElementById('doneMsg').textContent =
      `${total.toLocaleString()} restaurants scraped from ${job.location}.`;
    if (job.has_file) {
      const btn = document.getElementById('btnDownload');
      btn.href = `${API_BASE}/api/jobs/${job.id}/download`;
      btn.style.display = 'inline-flex';
    }
    return;
  }

  if (job.status === 'error') {
    showPanel('error');
    document.getElementById('errorMsg').textContent = job.message || 'Scraping failed.';
    return;
  }

  setProgress(pct, job.message || 'Scraping...');
  updateETA(pct);
}

// ── ETA ───────────────────────────────────────────────────────
function updateETA(pct) {
  if (pct < 3) { jobStartTime = Date.now(); return; }
  if (!jobStartTime || pct >= 99) return;

  const elapsed = (Date.now() - jobStartTime) / 1000;
  const rate = pct / elapsed; // % per second
  if (rate <= 0) return;

  const remaining = Math.round((100 - pct) / rate);
  const badge = document.getElementById('etaBadge');
  const text  = document.getElementById('etaText');
  badge.style.display = 'flex';

  if (remaining < 60)       text.textContent = `~${remaining}s left`;
  else if (remaining < 3600) text.textContent = `~${Math.round(remaining / 60)}m left`;
  else                       text.textContent = `~${Math.round(remaining / 3600)}h left`;
}

function setProgress(pct, statusText) {
  document.getElementById('progressBar').style.width = pct + '%';
  document.getElementById('progressStatus').textContent = statusText;
  document.getElementById('progressPct').textContent = pct + '%';
}

// ── Panel switching ───────────────────────────────────────────
function showPanel(name) {
  document.querySelector('main.card').style.display       = name === 'form'     ? '' : 'none';
  document.getElementById('progressPanel').style.display  = name === 'progress' ? '' : 'none';
  document.getElementById('donePanel').style.display      = name === 'done'     ? '' : 'none';
  document.getElementById('errorPanel').style.display     = name === 'error'    ? '' : 'none';
}

document.getElementById('btnNew').addEventListener('click', () => {
  clearInterval(pollInterval);
  document.getElementById('btnDownload').style.display = 'none';
  document.getElementById('etaBadge').style.display = 'none';
  showPanel('form');
});

document.getElementById('btnRetry').addEventListener('click', () => {
  clearInterval(pollInterval);
  showPanel('form');
});
