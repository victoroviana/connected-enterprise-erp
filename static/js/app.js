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

  // ── Modal Global de Confirmação de Exclusão ──────────────────────────────
  let activeConfirmAction = null;

  function getGlobalDeleteModal() {
    const modalEl = document.getElementById('globalConfirmDeleteModal');
    if (!modalEl) return null;
    try {
      if (window.bootstrap && window.bootstrap.Modal) {
        return window.bootstrap.Modal.getOrCreateInstance(modalEl);
      }
    } catch (e) {}
    return null;
  }

  function showConfirmDeleteModal(options = {}) {
    const {
      entityType = 'Registro',
      entityName = '',
      entityDetail = '',
      prompt = 'Deseja realmente excluir este registro?',
      warning = 'Esta ação não pode ser desfeita. Todos os dados associados a este item serão permanentemente removidos.',
      confirmButtonText = 'Sim, Excluir',
      onConfirm = null,
      formToSubmit = null
    } = options;

    const modalEl = document.getElementById('globalConfirmDeleteModal');
    if (!modalEl) {
      const msg = entityName ? `${prompt}\n\nItem: ${entityName}\n${warning}` : prompt;
      if (window.confirm(msg)) {
        if (typeof onConfirm === 'function') onConfirm();
        else if (formToSubmit) formToSubmit.submit();
      }
      return;
    }

    const typeEl = document.getElementById('globalConfirmDeleteEntityType');
    const nameEl = document.getElementById('globalConfirmDeleteEntityName');
    const detailEl = document.getElementById('globalConfirmDeleteEntityDetail');
    const promptEl = document.getElementById('globalConfirmDeletePrompt');
    const warningEl = document.getElementById('globalConfirmDeleteWarningText');
    const confirmBtn = document.getElementById('globalConfirmDeleteBtn');

    if (typeEl) typeEl.textContent = entityType;
    if (nameEl) nameEl.textContent = entityName || '-';
    if (detailEl) {
      if (entityDetail) {
        detailEl.textContent = entityDetail;
        detailEl.style.display = 'block';
      } else {
        detailEl.style.display = 'none';
      }
    }
    if (promptEl) promptEl.textContent = prompt;
    if (warningEl) warningEl.textContent = warning;
    if (confirmBtn) {
      confirmBtn.disabled = false;
      confirmBtn.innerHTML = `<i class="bi bi-trash me-1"></i>${confirmButtonText}`;
    }

    activeConfirmAction = () => {
      if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>Excluindo...`;
      }
      if (typeof onConfirm === 'function') {
        onConfirm();
      } else if (formToSubmit) {
        formToSubmit._confirmed = true;
        formToSubmit.submit();
      }
    };

    const modal = getGlobalDeleteModal();
    if (modal) {
      modal.show();
    } else {
      if (window.confirm(`${prompt} (${entityName})`)) {
        if (typeof onConfirm === 'function') onConfirm();
        else if (formToSubmit) {
          formToSubmit._confirmed = true;
          formToSubmit.submit();
        }
      }
    }
  }

  window.showConfirmDeleteModal = showConfirmDeleteModal;

  document.addEventListener('click', (event) => {
    const btn = event.target.closest('#globalConfirmDeleteBtn');
    if (btn && typeof activeConfirmAction === 'function') {
      activeConfirmAction();
      activeConfirmAction = null;
    }
  });

  // Interceptar formulários declarados com data-confirm-delete="true"
  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form._confirmed) return;

    const isExplicit = form.hasAttribute('data-confirm-delete');
    const action = form.getAttribute('action') || '';
    const hasDeleteAction = /excluir|delete|remover/i.test(action);

    if (isExplicit || (hasDeleteAction && form.hasAttribute('data-entity-name'))) {
      event.preventDefault();
      event.stopImmediatePropagation();

      const entityType = form.getAttribute('data-entity-type') || 'Registro';
      const entityName = form.getAttribute('data-entity-name') || '';
      const entityDetail = form.getAttribute('data-entity-detail') || '';
      const prompt = form.getAttribute('data-confirm-prompt') || 'Deseja realmente excluir este registro?';
      const warning = form.getAttribute('data-confirm-warning') || 'Esta ação não pode ser desfeita. Todos os dados associados a este item serão permanentemente removidos.';

      showConfirmDeleteModal({
        entityType,
        entityName,
        entityDetail,
        prompt,
        warning,
        formToSubmit: form
      });
    }
  }, true);

  // Interceptar botões ou links com data-confirm-delete="true"
  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-confirm-delete="true"]');
    if (!trigger || trigger.tagName === 'FORM') return;

    const form = trigger.closest('form');
    if (form && !form._confirmed) {
      event.preventDefault();
      event.stopImmediatePropagation();

      const entityType = trigger.getAttribute('data-entity-type') || form.getAttribute('data-entity-type') || 'Registro';
      const entityName = trigger.getAttribute('data-entity-name') || form.getAttribute('data-entity-name') || '';
      const entityDetail = trigger.getAttribute('data-entity-detail') || form.getAttribute('data-entity-detail') || '';
      const prompt = trigger.getAttribute('data-confirm-prompt') || form.getAttribute('data-confirm-prompt') || 'Deseja realmente excluir este registro?';
      const warning = trigger.getAttribute('data-confirm-warning') || form.getAttribute('data-confirm-warning') || 'Esta ação não pode ser desfeita. Todos os dados associados a este item serão permanentemente removidos.';

      showConfirmDeleteModal({
        entityType,
        entityName,
        entityDetail,
        prompt,
        warning,
        formToSubmit: form
      });
    }
  }, true);
})();
