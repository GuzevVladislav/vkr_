// ─── Theme ───────────────────────────────────
const html = document.documentElement;
const saved = localStorage.getItem('theme') || 'dark';
html.setAttribute('data-theme', saved);

const toggleBtn = document.getElementById('themeToggle');
if (toggleBtn) {
  toggleBtn.addEventListener('click', () => {
    const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
  });
}

// ─── XSS-safe helper ─────────────────────────
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
