(function(){
  'use strict';

  /* ================= THEME ================= */
  const themeBtn = document.getElementById('themeToggle');

  function syncLogos(){
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    document.querySelectorAll('.logo-dark').forEach(el => { el.style.display = isLight ? 'none' : 'inline-block'; });
    document.querySelectorAll('.logo-light').forEach(el => { el.style.display = isLight ? 'inline-block' : 'none'; });
  }

  const applyTheme = (t) => {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('theme', t); } catch(e){}
    if (themeBtn) themeBtn.textContent = (t === 'light' ? '' : '');
    syncLogos();
  };

  (function initTheme(){
    const t = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(t);
    if (themeBtn) {
      themeBtn.addEventListener('click', () => {
        const next = (document.documentElement.getAttribute('data-theme') === 'dark') ? 'light' : 'dark';
        applyTheme(next);
      });
    }
  })();

  /* ================ CSRF (helpers p/ AJAX e auto-injeo no form) ================ */
  function getCsrfToken(){
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  window.getCsrfToken = getCsrfToken; // disponvel globalmente

  // Auto-injeta o token em TODO form POST que no tenha o campo
  document.addEventListener('DOMContentLoaded', () => {
    const token = getCsrfToken();
    document.querySelectorAll('form[method="post"]').forEach(form => {
      if (!form.querySelector('input[name="csrf_token"]')) {
        const i = document.createElement('input');
        i.type = 'hidden'; i.name = 'csrf_token'; i.value = token;
        form.prepend(i);
      }
    });
  });

  /* ================ DROPZONE opcional ================ */
  const dz = document.getElementById('dropzone');
  const input = document.getElementById('fileInputMulti');
  if (dz && input) {
    const prevent = e => { e.preventDefault(); e.stopPropagation(); };
    ['dragenter','dragover','dragleave','drop'].forEach(evt => dz.addEventListener(evt, prevent, false));
    ['dragenter','dragover'].forEach(evt => dz.addEventListener(evt, () => dz.classList.add('dragover'), false));
    ['dragleave','drop'].forEach(evt => dz.addEventListener(evt, () => dz.classList.remove('dragover'), false));
    dz.addEventListener('drop', (e) => {
      const files = e.dataTransfer.files;
      if (files && files.length) { input.files = files; }
    });
    dz.addEventListener('click', () => input.click());
  }

  /* ================ SIDEBAR ================ */
  const body = document.body;
  const sidebar = document.getElementById('sidebar');
  const menuBtn  = document.getElementById('sidebarMenuBtn');
  const backdrop = document.getElementById('sidebarBackdrop');
  const isDesktop = () => window.innerWidth > 900;

  (function initSidebar(){
    try {
      const pinned = localStorage.getItem('sidebarPinned') === '1';
      if (pinned && isDesktop()) body.classList.add('sidebar-pinned');
    } catch(e){}
  })();

  if (sidebar) {
    sidebar.addEventListener('mouseenter', () => {
      if (!isDesktop()) return;
      if (!body.classList.contains('sidebar-pinned')) body.classList.add('sidebar-hover');
    });
    sidebar.addEventListener('mouseleave', () => {
      if (!isDesktop()) return;
      if (!body.classList.contains('sidebar-pinned')) body.classList.remove('sidebar-hover');
    });
  }

  const handleMenuBtn = () => {
    if (isDesktop()) {
      body.classList.toggle('sidebar-pinned');
      body.classList.remove('sidebar-hover');
      try {
        localStorage.setItem('sidebarPinned', body.classList.contains('sidebar-pinned') ? '1' : '0');
      } catch(e){}
    } else {
      body.classList.toggle('sidebar-open');
    }
  };
  if (menuBtn) menuBtn.addEventListener('click', handleMenuBtn);

  if (backdrop) backdrop.addEventListener('click', () => body.classList.remove('sidebar-open'));

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') body.classList.remove('sidebar-open');
  });

  if (sidebar) {
    sidebar.addEventListener('click', (e) => {
      const a = e.target.closest('a');
      if (!a) return;
      if (!isDesktop()) body.classList.remove('sidebar-open');
    });
  }

  window.addEventListener('resize', () => {
    if (isDesktop()) {
      body.classList.remove('sidebar-open');
      try {
        const pinned = localStorage.getItem('sidebarPinned') === '1';
        body.classList.toggle('sidebar-pinned', pinned);
      } catch(e){}
    } else {
      body.classList.remove('sidebar-pinned', 'sidebar-hover');
    }
  });
})();
