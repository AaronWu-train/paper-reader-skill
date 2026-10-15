(() => {
  const root = document.documentElement;
  const toc = document.getElementById('toc');
  const toggle = document.getElementById('toc-toggle');
  let savedMode, savedTheme;
  try { savedMode = localStorage.getItem('paper-reader-mode'); savedTheme = localStorage.getItem('paper-reader-theme'); } catch (_) {}
  if (['zh', 'en', 'both'].includes(savedMode)) root.dataset.mode = savedMode;
  if (['light', 'dark'].includes(savedTheme)) root.dataset.theme = savedTheme;
  document.querySelectorAll('input[name="mode"]').forEach(input => {
    input.checked = input.value === root.dataset.mode;
    input.addEventListener('change', () => {
      root.dataset.mode = input.value;
      try { localStorage.setItem('paper-reader-mode', input.value); } catch (_) {}
    });
  });
  toggle.addEventListener('click', () => { const open = toc.classList.toggle('open'); toggle.setAttribute('aria-expanded', String(open)); });
  toc.addEventListener('click', e => { if (e.target.closest('a')) { toc.classList.remove('open'); toggle.setAttribute('aria-expanded', 'false'); } });
  document.getElementById('theme-toggle').addEventListener('click', () => {
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme:dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('paper-reader-theme', root.dataset.theme); } catch (_) {}
  });
})();
