// Backend API base URL — update this after deploying to Render
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:5000'
  : 'https://YOUR-RENDER-APP.onrender.com'; // <-- replace after deployment

let currentJobId = null;
let pollInterval = null;

// Platform tile selection
document.querySelectorAll('.platform-tile').forEach(tile => {
  tile.addEventListener('click', () => {
    document.querySelectorAll('.platform-tile').forEach(t => t.classList.remove('selected'));
    tile.classList.add('selected');
    tile.querySelector('input[type=radio]').checked = true;
  });
});

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
  const platform = document.querySelector('input[name=platform]:checked')?.value;
  const location = document.getElementById('location').value.trim();
  const email = document.getElementById('email').value.trim();
  const activeChip = document.querySelector('.chip.active');
  const cuisine = document.getElementById('cuisineCustom').value.trim()
    || (activeChip && activeChip.dataset.value !== '' ? activeChip.dataset.value : '');

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
      `Scraped ${job.scraped} restaurants from ${job.location}. Google Sheet is ready.`;
    document.getElementById('sheetLink').href = job.sheet_url || '#';
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
