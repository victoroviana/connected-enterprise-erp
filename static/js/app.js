(() => {
  const meta = document.querySelector('meta[name="csrf-token"]');
  const token = meta ? meta.getAttribute('content') || '' : '';

  function ensureHeaders(headers = {}) {
    if (headers instanceof Headers) {
      if (token && !headers.has('X-CSRFToken')) {
        headers.set('X-CSRFToken', token);
      }
      if (!headers.has('X-Requested-With')) {
        headers.set('X-Requested-With', 'XMLHttpRequest');
      }
      return headers;
    }
    const normalized = new Headers(headers || {});
    if (token && !normalized.has('X-CSRFToken')) {
      normalized.set('X-CSRFToken', token);
    }
    if (!normalized.has('X-Requested-With')) {
      normalized.set('X-Requested-With', 'XMLHttpRequest');
    }
    return normalized;
  }

  function injectFormToken(form) {
    if (!form || !token) {
      return;
    }
    let input = form.querySelector('input[name="csrf_token"]');
    if (!input) {
      input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'csrf_token';
      form.appendChild(input);
    }
    input.value = token;
  }

  async function csrfFetch(resource, options = {}) {
    const opts = { ...options };
    const method = (opts.method || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') {
      opts.headers = ensureHeaders(opts.headers);
    }
    if (!opts.credentials) {
      opts.credentials = 'same-origin';
    }
    return fetch(resource, opts);
  }

  window.csrfToken = token;
  window.csrfFetch = csrfFetch;
  window.ensureFormCsrf = injectFormToken;

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (form instanceof HTMLFormElement) {
      injectFormToken(form);
    }
  }, true);
})();
