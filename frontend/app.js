// ── Cursor glow ───────────────────────────────────────────────────────────────
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

// ── Config ────────────────────────────────────────────────────────────────────
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:5000'
  : 'https://restaurant-scraper-api-ah9e.onrender.com';

let currentJobId    = null;
let pollInterval    = null;
let jobStartTime    = null;
let currentMode     = 'delivery';   // 'delivery' | 'googlemaps' | 'websiteintel'
let wiRestaurants   = [];           // parsed CSV rows for website intel

const PLATFORM_ICONS  = { wolt: '🔵', bolt: '🟢', foodora: '🔴', glovo: '🟡' };
const PLATFORM_LABELS = { wolt: 'Wolt', bolt: 'Bolt Food', foodora: 'Foodora', glovo: 'Glovo' };

// ── Mode switching ─────────────────────────────────────────────────────────────
function switchMode(mode) {
  currentMode = mode;
  document.getElementById('formDelivery').style.display      = mode === 'delivery'     ? '' : 'none';
  document.getElementById('formGoogleMaps').style.display    = mode === 'googlemaps'   ? '' : 'none';
  document.getElementById('formWebsiteIntel').style.display  = mode === 'websiteintel' ? '' : 'none';
  document.getElementById('tabDelivery').classList.toggle('active',      mode === 'delivery');
  document.getElementById('tabGoogleMaps').classList.toggle('active',    mode === 'googlemaps');
  document.getElementById('tabWebsiteIntel').classList.toggle('active',  mode === 'websiteintel');
}

// ── Country dropdown (Google Maps) — restricted to supported markets ──────────
const COUNTRIES = [
  ['Czech Republic','CZ'],
  ['Estonia','EE'],
  ['Hungary','HU'],
  ['Latvia','LV'],
  ['Lithuania','LT'],
  ['Portugal','PT'],
  ['Romania','RO'],
  ['Slovakia','SK'],
  ['Ukraine','UA'],
];

(function buildCountryDropdown() {
  const sel = document.getElementById('gmCountry');
  COUNTRIES.forEach(([name, code]) => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.dataset.code = code;
    opt.textContent = name;
    if (name === 'Czech Republic') opt.selected = true;
    sel.appendChild(opt);
  });
})();

// ── Query count table (mirrors COUNTRY_CITIES + CITY_DISTRICTS in backend) ────
// Used for cost/time estimates. Values = total Outscraper API calls per type.
// Country totals account for per-city district expansion.
const LOCATION_QUERY_COUNT = {
  // Countries (cities × district queries per large city)
  'czech republic': 77, 'czechia': 77,  // Prague(22)+Brno(12)+Ostrava(8)+35 cities
  'estonia': 20,                          // Tallinn(8)+12 cities
  'latvia': 22,                           // Riga(12)+10 cities
  'lithuania': 25,                        // Vilnius(12)+13 cities
  'ukraine': 52,                          // Kyiv(10)+Lviv(6)+Kharkiv(9)+Odessa(4)+23 cities
  'romania': 36,                          // Bucharest(6)+30 cities
  'hungary': 44,                          // Budapest(23)+21 cities
  'slovakia': 31,                         // Bratislava(10)+21 cities
  'portugal': 50,                         // Lisbon(12)+Porto(10)+28 cities
  // Cities with district splitting
  'prague': 22, 'praha': 22,
  'brno': 12,
  'ostrava': 8,
  'tallinn': 8,
  'riga': 12,
  'vilnius': 12,
  'kyiv': 10,
  'lviv': 6,
  'kharkiv': 9,
  'odessa': 4,
  'lisbon': 12,
  'porto': 10,
  'budapest': 23,
  'bratislava': 10,
  'bucharest': 6,
};

function getQueryCount(location, numTypes) {
  const key = (location || '').trim().toLowerCase().split(',')[0].trim();
  const perType = LOCATION_QUERY_COUNT[key] || 1;
  return perType * numTypes;
}

function updateGMEstimate() {
  const locMode  = document.querySelector('input[name="gmLocMode"]:checked')?.value;
  const location = locMode === 'city'
    ? document.getElementById('gmCity').value.trim()
    : document.getElementById('gmCountry').value.trim();

  if (!location) {
    document.getElementById('gmEstimate').style.display = 'none';
    return;
  }

  const queries  = getQueryCount(location, 1);  // always 1 type: restaurants
  const minRec   = queries * 80;
  const maxRec   = queries * 400;
  const minCost  = (minRec * 0.003).toFixed(2);
  const maxCost  = (maxRec * 0.003).toFixed(2);
  const mins     = Math.ceil(queries * 35 / 60);
  const timeStr  = mins < 2 ? '~1 min' : `~${mins} min`;

  document.getElementById('estTime').textContent    = timeStr;
  document.getElementById('estCost').textContent    = `~$${minCost}–$${maxCost}`;
  document.getElementById('estQueries').textContent = `${queries} area${queries > 1 ? 's' : ''}`;
  document.getElementById('gmEstimate').style.display = '';
}

// ── Location mode toggle (City / Country) ─────────────────────────────────────
document.querySelectorAll('input[name="gmLocMode"]').forEach(radio => {
  radio.addEventListener('change', () => {
    const isCity = radio.value === 'city';
    document.getElementById('gmCityInput').style.display    = isCity ? '' : 'none';
    document.getElementById('gmCountryInput').style.display = isCity ? 'none' : '';
    updateGMEstimate();
  });
});

// Trigger estimate update when country / city / types change
document.getElementById('gmCountry').addEventListener('change', updateGMEstimate);
document.getElementById('gmCity').addEventListener('input', updateGMEstimate);
document.querySelectorAll('input[name="gmType"]').forEach(cb => cb.addEventListener('change', updateGMEstimate));
// Run once on load to show estimate for default selection (Czech Republic, all types)
updateGMEstimate();

// ── Filters toggle ────────────────────────────────────────────────────────────
function toggleFilters() {
  const body  = document.getElementById('filtersBody');
  const arrow = document.getElementById('filtersArrow');
  const open  = body.style.display !== 'none';
  body.style.display  = open ? 'none' : '';
  arrow.textContent   = open ? '▼' : '▲';
}

// ── Autocomplete (Delivery mode) ──────────────────────────────────────────────
const locationInput = document.getElementById('location');
const acList = document.getElementById('autocompleteList');
let acTimeout = null;
let acIndex   = -1;

locationInput.addEventListener('input', () => {
  clearTimeout(acTimeout);
  const q = locationInput.value.trim();
  if (q.length < 2) { closeAC(); return; }
  acTimeout = setTimeout(() => fetchSuggestions(q), 280);
});
locationInput.addEventListener('keydown', (e) => {
  const items = acList.querySelectorAll('li');
  if (e.key === 'ArrowDown') { acIndex = Math.min(acIndex + 1, items.length - 1); highlightAC(items); e.preventDefault(); }
  else if (e.key === 'ArrowUp')  { acIndex = Math.max(acIndex - 1, 0); highlightAC(items); e.preventDefault(); }
  else if (e.key === 'Enter' && acIndex >= 0) { items[acIndex]?.click(); e.preventDefault(); }
  else if (e.key === 'Escape') closeAC();
});
document.addEventListener('click', (e) => {
  if (!e.target.closest('.autocomplete-wrap') && !e.target.closest('#autocompleteList')) closeAC();
});

const EUROPEAN_CC = new Set([
  'AL','AD','AT','BY','BE','BA','BG','HR','CY','CZ','DK','EE','FI','FR',
  'DE','GR','HU','IS','IE','IT','XK','LV','LI','LT','LU','MT','MD','MC',
  'ME','NL','MK','NO','PL','PT','RO','RU','SM','RS','SK','SI','ES','SE',
  'CH','UA','GB','VA','TR','AZ','AM','GE'
]);

async function fetchSuggestions(q) {
  try {
    const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=8&addressdetails=1&featuretype=city,country&accept-language=en`;
    const res  = await fetch(url, { headers: { 'Accept-Language': 'en' } });
    const data = await res.json();
    const filtered = data.filter(r => EUROPEAN_CC.has(r.address?.country_code?.toUpperCase()));
    renderSuggestions(filtered.slice(0, 7));
  } catch { closeAC(); }
}
function renderSuggestions(items) {
  acList.innerHTML = '';
  acIndex = -1;
  if (!items.length) { closeAC(); return; }
  items.forEach(item => {
    const city    = item.address?.city || item.address?.town || item.address?.village || item.address?.county || '';
    const country = item.address?.country || '';
    const type    = item.type === 'administrative' || item.class === 'boundary' ? 'country' : 'city';
    const label   = city ? `${city}, ${country}` : country;
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

// ── Platform selection (Delivery mode) ───────────────────────────────────────
function getSelectedPlatforms() {
  return [...document.querySelectorAll('input[name="platform"]:checked')].map(el => el.value);
}

// ── Start — Delivery Platforms ────────────────────────────────────────────────
document.getElementById('btnScrape').addEventListener('click', async () => {
  const platforms = getSelectedPlatforms();
  const location  = document.getElementById('location').value.trim();
  const email     = document.getElementById('email').value.trim();

  if (!platforms.length) return alert('Please select at least one platform.');
  if (!location)         return alert('Please enter a city or country.');
  if (!email || !email.includes('@')) return alert('Please enter a valid email address.');

  jobStartTime = null;
  showPanel('progress');
  document.getElementById('progressLocation').textContent = location;
  document.getElementById('progressIcon').textContent = '🚀';
  document.getElementById('gmLiveCount').style.display = 'none';
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
    startPolling(currentJobId, 'delivery');
  } catch (err) {
    showPanel('error');
    document.getElementById('errorMsg').textContent = err.message;
  }
});

// ── Start — Google Maps ───────────────────────────────────────────────────────
document.getElementById('btnGMScrape').addEventListener('click', async () => {
  const locMode = document.querySelector('input[name="gmLocMode"]:checked').value;
  let location;
  if (locMode === 'city') {
    location = document.getElementById('gmCity').value.trim();
    if (!location) return alert('Please enter a city name.');
  } else {
    location = document.getElementById('gmCountry').value;
  }

  const email = document.getElementById('gmEmail').value.trim();
  if (!email || !email.includes('@')) return alert('Please enter a valid email address.');

  const businessTypes = ['restaurants'];

  const gm_params = {
    business_types:  businessTypes,
    min_reviews:     parseInt(document.getElementById('gmMinReviews').value) || 0,
    min_rating:      parseFloat(document.getElementById('gmMinRating').value) || 0,
    require_website: document.getElementById('gmRequireWebsite').checked,
    require_phone:   document.getElementById('gmRequirePhone').checked,
  };

  // Show ETA in progress panel header
  const totalQueries = getQueryCount(location, businessTypes.length);
  const etaMins = Math.ceil(totalQueries * 35 / 60);
  const etaText = etaMins < 2 ? '~1 min' : `~${etaMins} min`;

  jobStartTime = null;
  showPanel('progress');
  document.getElementById('progressLocation').textContent = location;
  document.getElementById('progressIcon').textContent = '🗺️';
  document.getElementById('platformRows').innerHTML = '';
  document.getElementById('gmLiveCount').style.display = '';
  document.getElementById('gmCountNum').textContent = '0';
  document.getElementById('etaText').textContent = etaText;
  document.getElementById('etaBadge').style.display = 'flex';
  setProgress(0, 'Connecting to Google Maps...');

  try {
    const res = await fetch(`${API_BASE}/api/scrape`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platforms: ['google_maps'], location, cuisine: '', email, gm_params })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to start job');
    currentJobId = data.job_id;
    startPolling(currentJobId, 'googlemaps');
  } catch (err) {
    showPanel('error');
    document.getElementById('errorMsg').textContent = err.message;
  }
});

// ── Platform rows (Delivery mode) ────────────────────────────────────────────
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
    if (countEl && info.scraped > 0) countEl.textContent = info.scraped.toLocaleString() + ' restaurants';
  });
}

// ── Polling ───────────────────────────────────────────────────────────────────
function startPolling(jobId, mode) {
  clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
      const job = await res.json();
      updateProgress(job, mode);
      if (job.status === 'done' || job.status === 'error') clearInterval(pollInterval);
    } catch { /* network blip */ }
  }, 2000);
}

function updateProgress(job, mode) {
  const pct = job.progress || 0;

  if (mode === 'googlemaps') {
    const scraped = job.scraped || 0;
    document.getElementById('gmCountNum').textContent = scraped.toLocaleString();
    // Animate bar when waiting for API (pct is low but job is running)
    const bar = document.getElementById('progressBar');
    if (job.status === 'running' && pct < 15) {
      bar.style.width = '100%';
      bar.style.animation = 'gmPulse 1.5s ease-in-out infinite';
    } else {
      bar.style.animation = '';
      bar.style.width = pct + '%';
    }
  } else {
    document.getElementById('progressBar').style.animation = '';
    updatePlatformRows(job.platforms_detail);
  }

  if (job.status === 'done') {
    showPanel('done');
    const total = job.scraped || 0;

    if (mode === 'googlemaps') {
      const stats = job.gm_stats || {};
      document.getElementById('doneMsg').textContent =
        `Google Maps scraping complete for ${job.location}.`;
      showGMStats(stats);
    } else {
      document.getElementById('doneMsg').textContent =
        `${total.toLocaleString()} restaurants scraped from ${job.location}.`;
      document.getElementById('gmStats').style.display = 'none';
    }

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

function showGMStats(stats) {
  const el = document.getElementById('gmStats');
  el.style.display = '';
  const fmt = (n, total) => total
    ? `${(n || 0).toLocaleString()} (${Math.round((n || 0) / total * 100)}%)`
    : (n || 0).toLocaleString();
  const t = stats.total || 0;
  document.getElementById('statTotal').textContent       = (t).toLocaleString();
  document.getElementById('statPhone').textContent       = fmt(stats.with_phone, t);
  document.getElementById('statWebsite').textContent     = fmt(stats.with_website, t);
  document.getElementById('statDelivery').textContent    = fmt(stats.with_delivery, t);
  document.getElementById('statReservation').textContent = fmt(stats.with_reservation, t);
}

// ── ETA ───────────────────────────────────────────────────────────────────────
function updateETA(pct) {
  if (pct < 3) { jobStartTime = Date.now(); return; }
  if (!jobStartTime || pct >= 99) return;
  const elapsed   = (Date.now() - jobStartTime) / 1000;
  const rate      = pct / elapsed;
  if (rate <= 0) return;
  const remaining = Math.round((100 - pct) / rate);
  const badge = document.getElementById('etaBadge');
  const text  = document.getElementById('etaText');
  badge.style.display = 'flex';
  if (remaining < 60)        text.textContent = `~${remaining}s left`;
  else if (remaining < 3600) text.textContent = `~${Math.round(remaining / 60)}m left`;
  else                       text.textContent = `~${Math.round(remaining / 3600)}h left`;
}

function setProgress(pct, statusText) {
  document.getElementById('progressBar').style.width   = pct + '%';
  document.getElementById('progressStatus').textContent = statusText;
  document.getElementById('progressPct').textContent   = pct + '%';
}

// ── Panel switching ───────────────────────────────────────────────────────────
function showPanel(name) {
  const isGM = currentMode === 'googlemaps';
  const isWI = currentMode === 'websiteintel';
  document.getElementById('formDelivery').style.display     = (name === 'form' && !isGM && !isWI) ? '' : 'none';
  document.getElementById('formGoogleMaps').style.display   = (name === 'form' && isGM)           ? '' : 'none';
  document.getElementById('formWebsiteIntel').style.display = (name === 'form' && isWI)           ? '' : 'none';
  document.getElementById('progressPanel').style.display    = name === 'progress' ? '' : 'none';
  document.getElementById('donePanel').style.display        = name === 'done'     ? '' : 'none';
  document.getElementById('errorPanel').style.display       = name === 'error'    ? '' : 'none';
  document.querySelector('.mode-tabs').style.display = name === 'form' ? '' : 'none';
}

document.getElementById('btnNew').addEventListener('click', () => {
  clearInterval(pollInterval);
  document.getElementById('btnDownload').style.display = 'none';
  document.getElementById('etaBadge').style.display    = 'none';
  document.getElementById('gmStats').style.display     = 'none';
  showPanel('form');
});

document.getElementById('btnRetry').addEventListener('click', () => {
  clearInterval(pollInterval);
  showPanel('form');
});

// ── Website Intelligence ──────────────────────────────────────────────────────

function parseCSV(text) {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length < 2) return [];

  // Parse a single CSV line respecting quoted fields
  function parseLine(line) {
    const fields = [];
    let cur = '', inQuote = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') { inQuote = !inQuote; }
      else if (ch === ',' && !inQuote) { fields.push(cur.trim()); cur = ''; }
      else { cur += ch; }
    }
    fields.push(cur.trim());
    return fields;
  }

  const headers = parseLine(lines[0]).map(h => h.toLowerCase().replace(/['"]/g, '').trim());

  // Find name + url column indices
  const nameIdx = headers.findIndex(h => /^(name|restaurant|restaurant[\s_-]?name|company|brand)$/i.test(h));
  const urlIdx  = headers.findIndex(h => /^(url|website|website[\s_-]?url|link|homepage|domain|web)$/i.test(h));

  if (urlIdx === -1) return null; // signal: no URL column found

  return lines.slice(1).map(line => {
    const vals = parseLine(line);
    const url  = (vals[urlIdx] || '').replace(/['"]/g, '').trim();
    const name = nameIdx >= 0 ? (vals[nameIdx] || '').replace(/['"]/g, '').trim() : url;
    return url ? { name: name || url, url } : null;
  }).filter(Boolean);
}

function clearWIFile() {
  wiRestaurants = [];
  document.getElementById('wiFileInput').value = '';
  document.getElementById('wiPreview').style.display = 'none';
  document.getElementById('wiUploadArea').style.display = '';
  document.getElementById('wiUploadText').textContent = 'Drop CSV here or click to upload';
  document.getElementById('btnWIScrape').disabled = true;
}

function handleWIFile(file) {
  if (!file || !file.name.endsWith('.csv')) {
    return alert('Please upload a .csv file.');
  }
  const reader = new FileReader();
  reader.onload = e => {
    const parsed = parseCSV(e.target.result);
    if (parsed === null) {
      return alert('No URL column found. Make sure your CSV has a column named "url" or "website".');
    }
    if (!parsed.length) {
      return alert('No restaurant rows found in the CSV.');
    }
    wiRestaurants = parsed;

    // Show preview
    document.getElementById('wiUploadArea').style.display = 'none';
    document.getElementById('wiPreview').style.display = '';
    document.getElementById('wiPreviewCount').textContent =
      `${parsed.length} restaurant${parsed.length !== 1 ? 's' : ''} loaded`;

    const rows = document.getElementById('wiPreviewRows');
    rows.innerHTML = '';
    parsed.slice(0, 5).forEach(r => {
      const div = document.createElement('div');
      div.className = 'wi-preview-row';
      div.innerHTML = `<span class="wi-row-name">${r.name}</span><span class="wi-row-url">${r.url}</span>`;
      rows.appendChild(div);
    });
    if (parsed.length > 5) {
      const more = document.createElement('div');
      more.className = 'wi-preview-more';
      more.textContent = `+${parsed.length - 5} more…`;
      rows.appendChild(more);
    }

    document.getElementById('btnWIScrape').disabled = false;
  };
  reader.readAsText(file);
}

// File input click + drag-drop
const wiUploadArea = document.getElementById('wiUploadArea');
const wiFileInput  = document.getElementById('wiFileInput');

wiUploadArea.addEventListener('click', () => wiFileInput.click());
wiFileInput.addEventListener('change', e => handleWIFile(e.target.files[0]));

wiUploadArea.addEventListener('dragover', e => { e.preventDefault(); wiUploadArea.classList.add('drag-over'); });
wiUploadArea.addEventListener('dragleave', () => wiUploadArea.classList.remove('drag-over'));
wiUploadArea.addEventListener('drop', e => {
  e.preventDefault();
  wiUploadArea.classList.remove('drag-over');
  handleWIFile(e.dataTransfer.files[0]);
});

// ── Start — Website Intel ─────────────────────────────────────────────────────
document.getElementById('btnWIScrape').addEventListener('click', async () => {
  if (!wiRestaurants.length) return alert('Please upload a CSV file first.');
  const email = document.getElementById('wiEmail').value.trim();

  jobStartTime = null;
  showPanel('progress');
  document.getElementById('progressLocation').textContent = `${wiRestaurants.length} restaurants`;
  document.getElementById('progressIcon').textContent = '🔍';
  document.getElementById('platformRows').innerHTML = '';
  document.getElementById('gmLiveCount').style.display = '';
  document.getElementById('gmCountNum').textContent = '0';
  document.getElementById('etaBadge').style.display = 'none';
  setProgress(0, 'Starting analysis...');

  try {
    const res = await fetch(`${API_BASE}/api/website-intel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ restaurants: wiRestaurants, email }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to start job');
    currentJobId = data.job_id;
    startPolling(currentJobId, 'websiteintel');
  } catch (err) {
    showPanel('error');
    document.getElementById('errorMsg').textContent = err.message;
  }
});

// Patch updateProgress to handle websiteintel mode
const _origUpdateProgress = updateProgress;
function updateProgress(job, mode) {
  if (mode === 'websiteintel') {
    const scraped = job.scraped || 0;
    document.getElementById('gmCountNum').textContent = scraped.toLocaleString();
    const bar = document.getElementById('progressBar');
    bar.style.animation = '';
    bar.style.width = (job.progress || 0) + '%';

    if (job.status === 'done') {
      showPanel('done');
      document.getElementById('doneMsg').textContent =
        `Analyzed ${scraped.toLocaleString()} restaurants.`;
      document.getElementById('gmStats').style.display = 'none';
      if (job.has_file) {
        const btn = document.getElementById('btnDownload');
        btn.href = `${API_BASE}/api/jobs/${job.id}/download`;
        btn.style.display = 'inline-flex';
      }
      return;
    }
    if (job.status === 'error') {
      showPanel('error');
      document.getElementById('errorMsg').textContent = job.message || 'Analysis failed.';
      return;
    }
    setProgress(job.progress || 0, job.message || 'Analyzing...');
    return;
  }
  _origUpdateProgress(job, mode);
}
