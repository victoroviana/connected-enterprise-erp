(function () {
  const form = document.getElementById('photoCutterForm');
  const fileInput = document.getElementById('photoCutterFiles');
  const resultsEl = document.getElementById('photoCutterResults');
  const emptyEl = document.getElementById('photoCutterEmpty');
  const errorsEl = document.getElementById('photoCutterErrors');
  const summaryEl = document.getElementById('photoCutterSummary');
  const downloadBtn = document.getElementById('photoDownloadZip');
  const selectAllBtn = document.getElementById('photoSelectAll');
  const secureFetch = typeof window.csrfFetch === 'function' ? window.csrfFetch : fetch;

  let batchId = '';
  let processedImages = [];

  if (!form || !fileInput || !resultsEl) {
    return;
  }

  function setBusy(isBusy) {
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) {
      submitBtn.disabled = isBusy;
      submitBtn.innerHTML = isBusy
        ? '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span> Processando'
        : '<i class="fa-solid fa-wand-magic-sparkles me-1"></i> Cortar fotos';
    }
  }

  function showErrors(errors, fallbackMessage) {
    const items = Array.isArray(errors) ? errors : [];
    if (!items.length && !fallbackMessage) {
      errorsEl.style.display = 'none';
      errorsEl.innerHTML = '';
      return;
    }
    const html = items.length
      ? items.map((item) => `<div><strong>${item.name || 'Arquivo'}:</strong> ${item.error || 'Erro ao processar.'}</div>`).join('')
      : fallbackMessage;
    errorsEl.innerHTML = html;
    errorsEl.style.display = 'block';
  }

  function selectedNames() {
    return Array.from(resultsEl.querySelectorAll('input[type="checkbox"]:checked'))
      .map((input) => input.value);
  }

  function refreshActions() {
    const hasImages = processedImages.length > 0;
    const hasSelection = selectedNames().length > 0;
    downloadBtn.disabled = !hasSelection;
    selectAllBtn.disabled = !hasImages;
    summaryEl.textContent = hasImages
      ? `${processedImages.length} foto(s) processada(s).`
      : 'Nenhuma foto processada.';
  }

  function renderResults(images) {
    processedImages = images || [];
    resultsEl.innerHTML = '';
    emptyEl.style.display = processedImages.length ? 'none' : 'block';

    processedImages.forEach((image, index) => {
      const card = document.createElement('div');
      card.className = 'photo-result';
      card.innerHTML = `
        <img src="${image.url}" alt="${image.name}">
        <div class="d-flex align-items-start justify-content-between gap-2 mt-2">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" value="${image.name}" id="photo-cut-${index}" checked>
            <label class="form-check-label fw-semibold small" for="photo-cut-${index}">${image.name}</label>
          </div>
        </div>
        <div class="mt-2">
          <span class="photo-status ${image.detected ? 'photo-status--ok' : 'photo-status--fallback'}">
            <i class="fa-solid ${image.detected ? 'fa-face-smile' : 'fa-image'}"></i>
            ${image.detected ? 'Rosto detectado' : 'Imagem inteira'}
          </span>
        </div>
      `;
      resultsEl.appendChild(card);
    });

    resultsEl.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.addEventListener('change', refreshActions);
    });
    refreshActions();
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    showErrors([]);
    const files = Array.from(fileInput.files || []);
    if (!files.length) {
      showErrors([], 'Selecione pelo menos uma imagem.');
      return;
    }

    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    const token = window.csrfToken || document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
    if (token) {
      formData.append('csrf_token', token);
    }

    setBusy(true);
    try {
      const response = await secureFetch('/cracha/cortador-fotos/processar', {
        method: 'POST',
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw payload;
      }
      batchId = payload.batch_id;
      renderResults(payload.images || []);
      showErrors(payload.errors || []);
    } catch (error) {
      showErrors(error.errors || [], error.message || 'Não foi possível processar as fotos.');
    } finally {
      setBusy(false);
    }
  });

  form.addEventListener('reset', () => {
    batchId = '';
    renderResults([]);
    showErrors([]);
  });

  ['dragenter', 'dragover'].forEach((eventName) => {
    form.addEventListener(eventName, (event) => {
      event.preventDefault();
      form.classList.add('is-dragover');
    });
  });

  ['dragleave', 'drop'].forEach((eventName) => {
    form.addEventListener(eventName, (event) => {
      event.preventDefault();
      form.classList.remove('is-dragover');
    });
  });

  form.addEventListener('drop', (event) => {
    if (event.dataTransfer && event.dataTransfer.files.length) {
      fileInput.files = event.dataTransfer.files;
    }
  });

  selectAllBtn.addEventListener('click', () => {
    const checks = Array.from(resultsEl.querySelectorAll('input[type="checkbox"]'));
    const shouldCheck = checks.some((input) => !input.checked);
    checks.forEach((input) => {
      input.checked = shouldCheck;
    });
    refreshActions();
  });

  downloadBtn.addEventListener('click', async () => {
    const names = selectedNames();
    if (!batchId || !names.length) {
      refreshActions();
      return;
    }
    downloadBtn.disabled = true;
    try {
      const response = await secureFetch('/cracha/cortador-fotos/download', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({batch_id: batchId, names}),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw payload;
      }
      window.location.href = payload.download_url;
    } catch (error) {
      showErrors([], error.message || 'Não foi possível gerar o ZIP.');
    } finally {
      refreshActions();
    }
  });
})();
