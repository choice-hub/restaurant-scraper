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

let currentJobId  = null;
let pollInterval  = null;
let jobStartTime  = null;
let currentMode   = 'delivery';   // 'delivery' | 'googlemaps'

const PLATFORM_ICONS  = { wolt: '🔵', bolt: '🟢', foodora: '🔴', glovo: '🟡' };
const PLATFORM_LABELS = { wolt: 'Wolt', bolt: 'Bolt Food', foodora: 'Foodora', glovo: 'Glovo' };

// ── Mode switching ─────────────────────────────────────────────────────────────
function switchMode(mode) {
  currentMode = mode;
  document.getElementById('formDelivery').style.display   = mode === 'delivery'    ? '' : 'none';
  document.getElementById('formGoogleMaps').style.display = mode === 'googlemaps'  ? '' : 'none';
  document.getElementById('tabDelivery').classList.toggle('active',   mode === 'delivery');
  document.getElementById('tabGoogleMaps').classList.toggle('active', mode === 'googlemaps');
}

// ── Country dropdown (Google Maps) ────────────────────────────────────────────
const COUNTRIES = [
  ['Afghanistan','AF'],['Albania','AL'],['Algeria','DZ'],['Argentina','AR'],
  ['Armenia','AM'],['Australia','AU'],['Austria','AT'],['Azerbaijan','AZ'],
  ['Bahrain','BH'],['Bangladesh','BD'],['Belarus','BY'],['Belgium','BE'],
  ['Bolivia','BO'],['Bosnia and Herzegovina','BA'],['Brazil','BR'],['Bulgaria','BG'],
  ['Cambodia','KH'],['Canada','CA'],['Chile','CL'],['China','CN'],
  ['Colombia','CO'],['Croatia','HR'],['Cyprus','CY'],['Czech Republic','CZ'],
  ['Denmark','DK'],['Ecuador','EC'],['Egypt','EG'],['Estonia','EE'],
  ['Ethiopia','ET'],['Finland','FI'],['France','FR'],['Georgia','GE'],
  ['Germany','DE'],['Ghana','GH'],['Greece','GR'],['Guatemala','GT'],
  ['Honduras','HN'],['Hungary','HU'],['Iceland','IS'],['India','IN'],
  ['Indonesia','ID'],['Ireland','IE'],['Israel','IL'],['Italy','IT'],
  ['Japan','JP'],['Jordan','JO'],['Kazakhstan','KZ'],['Kenya','KE'],
  ['Kosovo','XK'],['Kuwait','KW'],['Latvia','LV'],['Lebanon','LB'],
  ['Lithuania','LT'],['Luxembourg','LU'],['Malaysia','MY'],['Malta','MT'],
  ['Mexico','MX'],['Moldova','MD'],['Morocco','MA'],['Netherlands','NL'],
  ['New Zealand','NZ'],['Nigeria','NG'],['North Macedonia','MK'],['Norway','NO'],
  ['Pakistan','PK'],['Paraguay','PY'],['Peru','PE'],['Philippines','PH'],
  ['Poland','PL'],['Portugal','PT'],['Qatar','QA'],['Romania','RO'],
  ['Saudi Arabia','SA'],['Senegal','SN'],['Serbia','RS'],['Singapore','SG'],
  ['Slovakia','SK'],['Slovenia','SI'],['South Africa','ZA'],['South Korea','KR'],
  ['Spain','ES'],['Sweden','SE'],['Switzerland','CH'],['Taiwan','TW'],
  ['Thailand','TH'],['Tunisia','TN'],['Turkey','TR'],['Ukraine','UA'],
  ['United Arab Emirates','AE'],['United Kingdom','GB'],['United States','US'],
  ['Uruguay','UY'],['Uzbekistan','UZ'],['Venezuela','VE'],['Vietnam','VN'],
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

// ── Location mode toggle (City / Country) ─────────────────────────────────────
document.querySelectorAll('input[name="gmLocMode"]').forEach(radio => {
  radio.addEventListener('change', () => {
    const isCity = radio.value === 'city';
    document.getElementById('gmCityInput').style.display    = isCity ? '' : 'none';
    document.getElementById('gmCountryInput').style.display = isCity ? 'none' : '';
  });
});

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

  const businessTypes = [...document.querySelectorAll('input[name="gmType"]:checked')].map(el => el.value);
  if (!businessTypes.length) return alert('Please select at least one business type.');

  const gm_params = {
    business_types:  businessTypes,
    min_reviews:     parseInt(document.getElementById('gmMinReviews').value) || 0,
    min_rating:      parseFloat(document.getElementById('gmMinRating').value) || 0,
    require_website: document.getElementById('gmRequireWebsite').checked,
    require_phone:   document.getElementById('gmRequirePhone').checked,
  };

  jobStartTime = null;
  showPanel('progress');
  document.getElementById('progressLocation').textContent = location;
  document.getElementById('progressIcon').textContent = '🗺️';
  document.getElementById('platformRows').innerHTML = '';
  document.getElementById('gmLiveCount').style.display = '';
  document.getElementById('gmCountNum').textContent = '0';
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
  document.getElementById('formDelivery').style.display   = (name === 'form' && !isGM) ? '' : 'none';
  document.getElementById('formGoogleMaps').style.display = (name === 'form' && isGM)  ? '' : 'none';
  document.getElementById('progressPanel').style.display  = name === 'progress' ? '' : 'none';
  document.getElementById('donePanel').style.display      = name === 'done'     ? '' : 'none';
  document.getElementById('errorPanel').style.display     = name === 'error'    ? '' : 'none';
  // Always show tabs unless in progress/done/error
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
