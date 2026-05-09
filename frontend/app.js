// Backend API base URL — update this after deploying to Render
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:5000'
  : 'https://restaurant-scraper-api-ah9e.onrender.com';

let currentJobId = null;
let pollInterval = null;

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

    // Filter to Europe only
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
    li.addEventListener('click', () => {
      locationInput.value = label;
      closeAC();
    });
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


// Cuisine chip selection
document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    document.getElementById('cuisineCustom').value = '';
  });
});

document.getElementById('cuisineCustom').addEventListener('input', () => {
  document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
});

// Start scraping
document.getElementById('btnScrape').addEventListener('click', async () => {
  const platform = 'wolt';
  const location = document.getElementById('location').value.trim();
  const email = document.getElementById('email').value.trim();
  const cuisine = '';

  if (!location) return alert('Please enter a city or country.');
  if (!email || !email.includes('@')) return alert('Please enter a valid email address.');

  showPanel('progress');
  setProgress(0, 'Connecting to scraper...');
  document.getElementById('progressStats').style.display = 'none';

  try {
    const res = await fetch(`${API_BASE}/api/scrape`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform, location, cuisine, email })
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

function startPolling(jobId) {
  clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
      const job = await res.json();
      updateProgress(job);
      if (job.status === 'done' || job.status === 'error') {
        clearInterval(pollInterval);
      }
    } catch (e) {
      // network blip — keep polling
    }
  }, 2500);
}

function updateProgress(job) {
  const pct = job.total > 0 ? Math.round((job.scraped / job.total) * 100) : (job.progress || 0);

  if (job.status === 'done') {
    showPanel('done');
    document.getElementById('doneMsg').textContent =
      `Scraped ${job.scraped} restaurants from ${job.location}. Excel file sent to your email.`;
    return;
  }

  if (job.status === 'error') {
    showPanel('error');
    document.getElementById('errorMsg').textContent = job.message || 'Scraping failed.';
    return;
  }

  setProgress(pct, job.message || 'Scraping...');
  document.getElementById('progressStats').style.display = 'flex';
  document.getElementById('statFound').textContent = job.total || 0;
  document.getElementById('statScraped').textContent = job.scraped || 0;
  document.getElementById('statFailed').textContent = job.failed || 0;
}

function setProgress(pct, statusText) {
  document.getElementById('progressBar').style.width = pct + '%';
  document.getElementById('progressStatus').textContent = statusText;
}

function showPanel(name) {
  document.querySelector('main.card').style.display = name === 'form' ? '' : 'none';
  document.getElementById('progressPanel').style.display = name === 'progress' ? '' : 'none';
  document.getElementById('donePanel').style.display = name === 'done' ? '' : 'none';
  document.getElementById('errorPanel').style.display = name === 'error' ? '' : 'none';
}

document.getElementById('btnNew').addEventListener('click', () => {
  clearInterval(pollInterval);
  showPanel('form');
});

document.getElementById('btnRetry').addEventListener('click', () => {
  clearInterval(pollInterval);
  showPanel('form');
});
