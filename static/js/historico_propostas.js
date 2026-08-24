(() => {
  const bootstrapLib = window.bootstrap;
  const csrfTokenMeta = document.querySelector('meta[name="csrf-token"]');
  const fallbackFetch = (resource, options = {}) => {
    const opts = { ...options };
    const headers = new Headers(opts.headers || {});
    if (csrfTokenMeta) {
      const method = (opts.method || 'GET').toUpperCase();
      if (method !== 'GET' && !headers.has('X-CSRFToken')) {
        headers.set('X-CSRFToken', csrfTokenMeta.getAttribute('content'));
      }
    }
    if (!headers.has('X-Requested-With')) {
      headers.set('X-Requested-With', 'XMLHttpRequest');
    }
    opts.headers = headers;
    if (!opts.credentials) {
      opts.credentials = 'same-origin';
    }
    return fetch(resource, opts);
  };
  const secureFetch = typeof window.csrfFetch === 'function'
    ? window.csrfFetch
    : fallbackFetch;
  const secureFormCsrf = typeof window.ensureFormCsrf === 'function'
    ? window.ensureFormCsrf
    : () => {};

  const selectSearchMap = new Map();

  function normalizeText(value) {
    return (value || '')
      .toString()
      .trim()
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '');
  }

  function buildOptions(selectEl) {
    return Array.from(selectEl.options)
      .map((opt) => ({
        value: opt.value,
        text: opt.textContent || '',
        normalized: normalizeText(opt.textContent || ''),
      }))
      .filter((opt) => opt.text);
  }

  function syncSearchInput(selectEl) {
    const entry = selectSearchMap.get(selectEl);
    if (!entry) return;
    const { inputEl } = entry;
    const selectedOption = selectEl.options[selectEl.selectedIndex];
    inputEl.value = selectedOption && selectedOption.value ? selectedOption.text : '';
  }

  function setupSelectSearch(inputEl) {
    const selectId = inputEl.dataset.selectTarget;
    const selectEl = document.getElementById(selectId);
    if (!selectEl) return;
    const wrapper = inputEl.closest('[data-search-select]') || inputEl.parentElement;
    if (!wrapper) return;
    const menuEl = wrapper.querySelector('[data-select-menu]');
    if (!menuEl) return;

    const options = buildOptions(selectEl);
    const entry = { inputEl, selectEl, wrapper, menuEl, options };
    selectSearchMap.set(selectEl, entry);
    syncSearchInput(selectEl);

    function renderMenu(term) {
      const filter = normalizeText(term);
      const matches = options.filter((opt) => !filter || opt.normalized.includes(filter));
      const visible = matches.filter((opt) => opt.value || !inputEl.required);

      menuEl.innerHTML = '';
      if (!visible.length) {
        const empty = document.createElement('div');
        empty.className = 'search-select-empty';
        empty.textContent = 'Nenhum resultado.';
        menuEl.appendChild(empty);
        return;
      }
      visible.forEach((opt) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'search-select-item';
        btn.textContent = opt.text;
        btn.dataset.value = opt.value;
        btn.dataset.text = opt.text;
        menuEl.appendChild(btn);
      });
    }

    function selectOption(opt) {
      if (!opt || (!opt.value && inputEl.required)) {
        return;
      }
      selectEl.value = opt.value || '';
      inputEl.value = opt.text;
      inputEl.setCustomValidity('');
      selectEl.dispatchEvent(new Event('change', { bubbles: true }));
      wrapper.classList.remove('is-open');
    }

    function applyInputValue() {
      const raw = normalizeText(inputEl.value);
      if (!raw) {
        selectEl.value = '';
        selectEl.dispatchEvent(new Event('change', { bubbles: true }));
        inputEl.setCustomValidity(inputEl.required ? 'Selecione uma opcao valida.' : '');
        return;
      }

      let match = options.find(
        (opt) => opt.normalized === raw && (opt.value || !inputEl.required),
      );
      if (!match) {
        const matches = options.filter(
          (opt) => opt.normalized.includes(raw) && (opt.value || !inputEl.required),
        );
        if (matches.length === 1) {
          match = matches[0];
        }
      }

      if (match) {
        selectOption(match);
      } else {
        selectEl.value = '';
        inputEl.setCustomValidity(inputEl.required ? 'Selecione uma opcao valida.' : '');
      }
    }

    inputEl.addEventListener('input', () => {
      selectEl.value = '';
      inputEl.setCustomValidity('');
      renderMenu(inputEl.value);
      wrapper.classList.add('is-open');
    });
    inputEl.addEventListener('focus', () => {
      renderMenu(inputEl.value);
      wrapper.classList.add('is-open');
    });
    inputEl.addEventListener('click', () => {
      renderMenu(inputEl.value);
      wrapper.classList.add('is-open');
    });
    inputEl.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        wrapper.classList.remove('is-open');
        return;
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        applyInputValue();
        wrapper.classList.remove('is-open');
      }
    });
    inputEl.addEventListener('blur', () => {
      setTimeout(() => {
        if (!wrapper.contains(document.activeElement)) {
          applyInputValue();
          wrapper.classList.remove('is-open');
        }
      }, 120);
    });

    menuEl.addEventListener('mousedown', (event) => {
      event.preventDefault();
    });
    menuEl.addEventListener('click', (event) => {
      const btn = event.target.closest('.search-select-item');
      if (!btn) return;
      const opt = options.find(
        (item) => item.text === btn.dataset.text && item.value === btn.dataset.value,
      );
      selectOption(opt);
    });

    selectEl.addEventListener('change', () => syncSearchInput(selectEl));

    const form = inputEl.closest('form');
    if (form) {
      form.addEventListener('submit', (event) => {
        if (inputEl.required && !selectEl.value) {
          inputEl.setCustomValidity('Selecione uma opcao valida.');
          inputEl.reportValidity();
          event.preventDefault();
        } else {
          inputEl.setCustomValidity('');
        }
      });
    }
  }

  document.addEventListener('click', (event) => {
    selectSearchMap.forEach(({ wrapper }) => {
      if (!wrapper.contains(event.target)) {
        wrapper.classList.remove('is-open');
      }
    });
  });

  const historyPdfModalEl = document.getElementById('historyPdfModal');
  let historyPdfModalInstance = null;
  const historyPdfFrame = document.getElementById('historyPdfFrame');
  const historyPdfLoading = document.getElementById('historyPdfLoading');
  const historyPdfDownloadBtn = document.getElementById('historyPdfDownload');
  const historyPdfDownloadLabel = document.getElementById('historyPdfDownloadLabel');
  const historyPdfMeta = document.getElementById('historyPdfMeta');
  let historyPdfTimer = null;
  let historyPdfObjectUrl = null;
  const approveModalEl = document.getElementById('approveVersionModal');
  const approveLabelEl = document.getElementById('approveVersionLabel');
  const approveConfirmBtn = document.getElementById('approveVersionConfirm');
  let approveTargetId = null;

  function ensureHistoryPdfModal() {
    if (!historyPdfModalEl || !bootstrapLib || !bootstrapLib.Modal) {
      return null;
    }
    if (!historyPdfModalInstance) {
      historyPdfModalInstance = bootstrapLib.Modal.getOrCreateInstance(historyPdfModalEl);
    }
    return historyPdfModalInstance;
  }

  function historyFlash(message, category = 'info') {
    if (typeof window.showFlash === 'function') {
      window.showFlash(message, category);
      return;
    }
    const flashStack = document.querySelector('.flash-stack');
    if (flashStack) {
      const alertDiv = document.createElement('div');
      const cat = category === 'message' ? 'warning' : category;
      alertDiv.className = `alert alert-${cat} alert-dismissible fade show shadow-sm mb-2`;
      alertDiv.setAttribute('role', 'alert');
      alertDiv.innerHTML = `${message}<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Fechar"></button>`;
      flashStack.appendChild(alertDiv);
      setTimeout(() => {
        alertDiv.classList.remove('show');
        alertDiv.classList.add('hide');
        setTimeout(() => alertDiv.remove(), 300);
      }, 6000);
      return;
    }
    if (category === 'danger') {
      alert(message);
      return;
    }
    console.log(message);
  }

  function resetHistoryPdfModal() {
    if (historyPdfFrame) {
      historyPdfFrame.classList.add('d-none');
      historyPdfFrame.removeAttribute('src');
      historyPdfFrame.onload = null;
    }
    if (historyPdfDownloadBtn) {
      historyPdfDownloadBtn.href = '#';
      historyPdfDownloadBtn.classList.add('disabled');
      historyPdfDownloadBtn.setAttribute('aria-disabled', 'true');
      historyPdfDownloadBtn.removeAttribute('download');
      const defaultLabel = historyPdfDownloadBtn.dataset.labelDefault || 'Baixar PDF';
      if (historyPdfDownloadLabel) {
        historyPdfDownloadLabel.textContent = defaultLabel;
      }
    }
    if (historyPdfMeta) {
      historyPdfMeta.textContent = '';
    }
    if (historyPdfLoading) {
      historyPdfLoading.classList.remove('d-none');
    }
    if (historyPdfObjectUrl) {
      URL.revokeObjectURL(historyPdfObjectUrl);
      historyPdfObjectUrl = null;
    }
  }

  function updateHistoryPdfMeta(payload) {
    if (historyPdfDownloadBtn && historyPdfDownloadLabel) {
      const defaultLabel = historyPdfDownloadBtn.dataset.labelDefault || 'Baixar PDF';
      historyPdfDownloadBtn.dataset.labelDefault = defaultLabel;
      if (payload?.download_name) {
        historyPdfDownloadLabel.textContent = payload.download_name;
      } else {
        historyPdfDownloadLabel.textContent = defaultLabel;
      }
    }
    if (historyPdfMeta) {
      const parts = [];
      if (payload?.generated_at) {
        const date = new Date(payload.generated_at);
        parts.push(!Number.isNaN(date.getTime()) ? date.toLocaleString('pt-BR') : payload.generated_at);
      }
      if (payload?.file_size_readable) {
        parts.push(payload.file_size_readable);
      }
      historyPdfMeta.textContent = parts.length ? parts.join('  ') : '';
    }
  }

  function loadHistoryPdfIntoFrame(viewUrl) {
    if (!viewUrl) {
      throw new Error('Endereo invlido do PDF.');
    }
    if (historyPdfLoading) {
      historyPdfLoading.classList.remove('d-none');
    }
    if (historyPdfFrame) {
      historyPdfFrame.classList.add('d-none');
      historyPdfFrame.onload = null;
    }
    return secureFetch(viewUrl, {
      method: 'GET',
      headers: { Accept: 'application/pdf' },
    })
      .then((resp) => {
        if (!resp.ok) {
          throw new Error(`Falha ao carregar o PDF (status ${resp.status}).`);
        }
        return resp.blob();
      })
      .then((blob) => {
        if (historyPdfObjectUrl) {
          URL.revokeObjectURL(historyPdfObjectUrl);
        }
        historyPdfObjectUrl = URL.createObjectURL(blob);
        if (historyPdfFrame) {
          historyPdfFrame.onload = () => {
            if (historyPdfLoading) {
              historyPdfLoading.classList.add('d-none');
            }
            historyPdfFrame.classList.remove('d-none');
          };
          historyPdfFrame.src = historyPdfObjectUrl;
        } else {
          window.open(viewUrl, '_blank', 'noopener');
        }
      });
  }

  function fmt(value) {
    return value.toFixed(2).replace('.', ',').replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }

  function br2f(text) {
    const raw = String(text || '').trim();
    if (!raw) return 0;
    const cleaned = raw.replace(/[^\d,.-]/g, '');
    if (!cleaned) return 0;
    if (cleaned.includes(',')) {
      return parseFloat(cleaned.replace(/\./g, '').replace(',', '.')) || 0;
    }
    return parseFloat(cleaned) || 0;
  }

  function toIsoDate(value) {
    const raw = (value || '').trim();
    if (!raw) return '';
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
    const parts = raw.split('/');
    if (parts.length !== 3) return '';
    const [day, month, year] = parts.map((part) => part.trim());
    if (!day || !month || !year) return '';
    return `${year.padStart(4, '0')}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
  }

  function getPreco(id) {
    return secureFetch(`/equipamentos/${id}`)
      .then((res) => res.json())
      .then((data) => parseFloat(data.preco));
  }

  function requestHistoryPdf(button) {
    const proposalId = button?.dataset?.proposalId || button?.dataset?.propostaId || button?.getAttribute('data-proposal-id');
    if (!proposalId) {
      historyFlash('Proposta invlida.', 'danger');
      return;
    }
    const proposalName = button.dataset.proposalName || button.dataset.nome || button.getAttribute('data-proposal-name') || 'proposta';

    resetHistoryPdfModal();
    const modal = ensureHistoryPdfModal();
    modal?.show();

    secureFetch(`/api/propostas/${proposalId}/pdf`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
      .then(async (resp) => {
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok || !payload?.ok) {
          throw new Error(payload?.message || `Falha ao preparar o PDF (status ${resp.status}).`);
        }
        pollHistoryPdfJob(payload, proposalName);
      })
      .catch((error) => {
        console.error(error);
        historyFlash(error?.message || 'Falha ao preparar o PDF.', 'danger');
        const modalFallback = ensureHistoryPdfModal();
        modalFallback?.hide();
      });
  }

  function pollHistoryPdfJob(state, proposalName) {
    const jobId = state?.job_id;
    if (!jobId) {
      historyFlash('Tarefa invlida.', 'danger');
      const modal = ensureHistoryPdfModal();
      modal?.hide();
      return;
    }
    let attempts = 0;
    clearInterval(historyPdfTimer);
    const tick = async () => {
      attempts += 1;
      try {
        const resp = await secureFetch(`/api/jobs/${jobId}`);
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok || !payload?.ok) {
          throw new Error(payload?.message || `Falha ao consultar tarefa (status ${resp.status}).`);
        }
        if (payload.status === 'done') {
          if (historyPdfTimer) {
            clearInterval(historyPdfTimer);
            historyPdfTimer = null;
          }
          updateHistoryPdfMeta(payload);
          const modal = ensureHistoryPdfModal();
          if (!modal) {
            historyFlash('PDF pronto.', 'success');
            return;
          }
          const viewUrl = payload.inline_url || payload.download_url;
          if (viewUrl) {
            loadHistoryPdfIntoFrame(viewUrl).catch((error) => {
              historyFlash(error?.message || 'Falha ao carregar o PDF.', 'danger');
              modal.hide();
              window.open(viewUrl, '_blank', 'noopener');
            });
          }
          if (historyPdfDownloadBtn) {
            const downloadUrl = payload.download_url || viewUrl;
            if (downloadUrl) {
              historyPdfDownloadBtn.href = downloadUrl;
              historyPdfDownloadBtn.download = payload.download_name || `${proposalName}.pdf`;
              historyPdfDownloadBtn.classList.remove('disabled');
              historyPdfDownloadBtn.setAttribute('aria-disabled', 'false');
            }
          }
          historyFlash('PDF pronto.', 'success');
          return;
        }
        if (payload.status === 'error') {
          throw new Error(payload.message || 'Falha ao gerar o PDF.');
        }
        if (attempts >= 60) {
          throw new Error('Tempo excedido ao gerar o PDF.');
        }
      } catch (error) {
        if (historyPdfTimer) {
          clearInterval(historyPdfTimer);
          historyPdfTimer = null;
        }
        const modal = ensureHistoryPdfModal();
        modal?.hide();
        historyFlash(error?.message || 'Falha ao gerar o PDF.', 'danger');
      }
    };

    historyPdfTimer = setInterval(tick, 1000);
    tick();
  }

  function triggerDownload(url, name) {
    if (!url) return;
    const link = document.createElement('a');
    link.href = url;
    if (name) {
      link.download = name;
    }
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function pollHistoryPdfDownload(state, proposalName, button) {
    const jobId = state?.job_id;
    if (!jobId) {
      historyFlash('Tarefa invalida.', 'danger');
      if (button) button.disabled = false;
      return;
    }
    let attempts = 0;
    const tick = async () => {
      attempts += 1;
      try {
        const resp = await secureFetch(`/api/jobs/${jobId}`);
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok || !payload?.ok) {
          throw new Error(payload?.message || `Falha ao consultar tarefa (status ${resp.status}).`);
        }
        if (payload.status === 'done') {
          const downloadUrl = payload.download_url || payload.inline_url;
          triggerDownload(downloadUrl, payload.download_name || `${proposalName}.pdf`);
          historyFlash('Download pronto.', 'success');
          if (button) button.disabled = false;
          return;
        }
        if (payload.status === 'error') {
          throw new Error(payload.message || 'Falha ao gerar o PDF.');
        }
        if (attempts >= 60) {
          throw new Error('Tempo excedido ao gerar o PDF.');
        }
        setTimeout(tick, 1000);
      } catch (error) {
        if (button) button.disabled = false;
        historyFlash(error?.message || 'Falha ao gerar o PDF.', 'danger');
      }
    };
    tick();
  }

  function requestHistoryPdfDownload(button) {
    const proposalId = button?.dataset?.proposalId || button?.dataset?.propostaId || button?.getAttribute('data-proposal-id');
    if (!proposalId) {
      historyFlash('Proposta invalida.', 'danger');
      return;
    }
    const proposalName = button.dataset.proposalName || button.dataset.nome || button.getAttribute('data-proposal-name') || 'proposta';
    button.disabled = true;
    secureFetch(`/api/propostas/${proposalId}/pdf`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'baixar' }),
    })
      .then(async (resp) => {
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok || !payload?.ok) {
          throw new Error(payload?.message || `Falha ao preparar o PDF (status ${resp.status}).`);
        }
        pollHistoryPdfDownload(payload, proposalName, button);
      })
      .catch((error) => {
        console.error(error);
        historyFlash(error?.message || 'Falha ao preparar o PDF.', 'danger');
        button.disabled = false;
      });
  }

  function toggleVersionRow(button) {
    if (!button || button.disabled) return;
    const targetId = button.dataset.target;
    if (!targetId) return;
    const row = document.getElementById(targetId);
    if (!row) return;
    row.classList.toggle('d-none');
    button.classList.toggle('is-open');
  }

  function openApproveModal(button) {
    if (!button) return;
    approveTargetId = button.dataset.proposalId || button.getAttribute('data-proposal-id');
    if (approveLabelEl) {
      approveLabelEl.textContent = button.dataset.versionLabel || 'esta versao';
    }
    if (approveModalEl && bootstrapLib && bootstrapLib.Modal) {
      bootstrapLib.Modal.getOrCreateInstance(approveModalEl).show();
    }
  }

  function submitApprove() {
    if (!approveTargetId) {
      return;
    }
    if (approveConfirmBtn) {
      approveConfirmBtn.disabled = true;
    }
    secureFetch(`/aprovar_proposta/${approveTargetId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
      .then(async (resp) => {
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok || !payload?.ok) {
          throw new Error(payload?.message || `Falha ao aprovar (status ${resp.status}).`);
        }
        historyFlash(payload?.message || 'Versao aprovada.', 'success');
        const modalInstance = approveModalEl && bootstrapLib && bootstrapLib.Modal
          ? bootstrapLib.Modal.getInstance(approveModalEl) || bootstrapLib.Modal.getOrCreateInstance(approveModalEl)
          : null;
        modalInstance?.hide();
        setTimeout(() => location.reload(), 200);
      })
      .catch((error) => {
        console.error(error);
        historyFlash(error?.message || 'Falha ao aprovar a versao.', 'danger');
      })
      .finally(() => {
        if (approveConfirmBtn) {
          approveConfirmBtn.disabled = false;
        }
      });
  }

  function viewVersionChanges(button) {
    const proposalId = button.dataset.proposalId;
    const versionLabel = button.dataset.versionLabel || 'esta versão';
    
    // Show a loading indicator if possible, or just open the modal with loading state
    const modalEl = document.getElementById('auditJsonModal');
    if (!modalEl || !window.AuditDiff) return;
    
    const modal = bootstrapLib ? bootstrapLib.Modal.getOrCreateInstance(modalEl) : null;
    const titleEl = modalEl.querySelector('.audit-json-modal-title');
    const contextEl = modalEl.querySelector('#auditJsonModalContext');
    const beforePre = modalEl.querySelector('#auditJsonModalBefore');
    const afterPre = modalEl.querySelector('#auditJsonModalAfter');
    const diffSummary = modalEl.querySelector('#auditJsonDiffSummary');
    
    if (titleEl) titleEl.textContent = `Alterações: ${versionLabel}`;
    if (contextEl) contextEl.textContent = `Proposta #${proposalId}`;
    if (beforePre) beforePre.textContent = 'Carregando...';
    if (afterPre) afterPre.textContent = 'Carregando...';
    if (diffSummary) diffSummary.classList.add('d-none');
    
    modal?.show();

    // Fetch from Audit API
    secureFetch(`/audit/api?entity_type=Proposal&entity_id=${proposalId}&action=version&limit=1`)
      .then(res => res.json())
      .then(data => {
        if (!data || !data.length) {
          if (beforePre) beforePre.textContent = 'Nenhum log de alteração encontrado para esta versão.';
          if (afterPre) afterPre.textContent = '';
          return;
        }
        
        const log = data[0];
        const beforeData = window.AuditDiff.extractData({ dataset: { json: JSON.stringify(log.before) } }, 'payload');
        const afterData = window.AuditDiff.extractData({ dataset: { json: JSON.stringify(log.after) } }, 'payload');

        if (beforePre) beforePre.textContent = beforeData.text;
        if (afterPre) afterPre.textContent = afterData.text;

        const blocks = {
          before: modalEl.querySelector('#auditJsonBeforeBlock'),
          after: modalEl.querySelector('#auditJsonAfterBlock')
        };
        
        window.AuditDiff.setFocusBlock('after', blocks);
        window.AuditDiff.renderDiff(beforeData, afterData, {
          diffSummary: modalEl.querySelector('#auditJsonDiffSummary'),
          diffListEl: modalEl.querySelector('#auditJsonDiffList'),
          diffCountEl: modalEl.querySelector('#auditJsonDiffCount'),
          diffEmptyEl: modalEl.querySelector('#auditJsonDiffEmpty')
        });
      })
      .catch(err => {
        console.error('Erro ao buscar auditoria:', err);
        if (beforePre) beforePre.textContent = 'Erro ao carregar dados de alteração.';
      });
  }

  const docTypeSelect = document.getElementById('document_type_edit');
  const documentInput = document.getElementById('document_edit');
  const documentLabelEdit = document.getElementById('document_label_edit');
  const companyWrapper = document.getElementById('divCompanyEdit');
  const companyInput = document.getElementById('company');
  const issuerSelect = document.getElementById('issuer_company_code_edit');
  const usarOutroSelect = document.getElementById('usar_outro_usuario_edit');
  const outroWrapper = document.getElementById('outro_usuario_wrapper_edit');
  const outroUsuarioSelect = document.getElementById('outro_usuario_edit');
  const usarSistemaSwitch = document.getElementById('usar_sistema_edit');
  const sistemaWrapper = document.getElementById('sistema_edit_wrapper');
  const sistemaSelect = document.getElementById('sistema_opcao_edit');
  const sistemaQuantidade = document.getElementById('sistema_quantidade_edit');
  const sistemaPreco = document.getElementById('sistema_preco_unitario_edit');
  const sistemaTotalInput = document.getElementById('sistema_preco_total_edit');
  const sistemaPreview = document.getElementById('sistema_preview_edit');

  const enviarEmailSwitch = document.getElementById('enviar_email_edit');
  const emailOptionsWrapper = document.getElementById('email_options_edit');
  const emailBodyInput = document.getElementById('email_corpo_edit');
  const enviarCopiaSwitch = document.getElementById('enviar_copia_edit');
  const emailCcWrapper = document.getElementById('email_cc_edit_wrapper');
  const emailCcInput = document.getElementById('email_cc_edit');
  const modalEdicaoEl = document.getElementById('modalEdicao');

  function maskCNPJ(value) {
    let digits = (value || '').replace(/\D/g, '').slice(0, 14);
    digits = digits.replace(/(\d{2})(\d)/, '$1.$2');
    digits = digits.replace(/(\d{2}\.\d{3})(\d)/, '$1.$2');
    digits = digits.replace(/(\d{2}\.\d{3}\.\d{3})(\d)/, '$1/$2');
    digits = digits.replace(/(\d{2}\.\d{3}\.\d{3}\/\d{4})(\d)/, '$1-$2');
    return digits;
  }

  function maskCPF(value) {
    let digits = (value || '').replace(/\D/g, '').slice(0, 11);
    digits = digits.replace(/(\d{3})(\d)/, '$1.$2');
    digits = digits.replace(/(\d{3}\.\d{3})(\d)/, '$1.$2');
    digits = digits.replace(/(\d{3}\.\d{3}\.\d{3})(\d)/, '$1-$2');
    return digits;
  }

  function getDocTypeValue(type) {
    if (type) {
      return type.toLowerCase();
    }
    if (docTypeSelect && docTypeSelect.value) {
      return docTypeSelect.value.toLowerCase();
    }
    return 'cnpj';
  }

  function updateDocumentInputFormatting() {
    if (!documentInput) return;
    const docType = getDocTypeValue();
    const raw = documentInput.value || '';
    documentInput.value = docType === 'cpf' ? maskCPF(raw) : maskCNPJ(raw);
  }

  function applyDocTypeUI(type) {
    const docType = getDocTypeValue(type);
    const isCpf = docType === 'cpf';
    if (documentLabelEdit) {
      documentLabelEdit.textContent = isCpf ? 'CPF do Cliente' : 'CNPJ do Cliente';
    }
    if (documentInput) {
      documentInput.placeholder = isCpf ? '000.000.000-00' : '00.000.000/0000-00';
      updateDocumentInputFormatting();
    }
    if (companyWrapper) {
      companyWrapper.classList.toggle('d-none', isCpf);
    }
    if (companyInput && isCpf) {
      companyInput.value = '';
    }
  }

  function handleDocumentBlur() {
    if (!documentInput || getDocTypeValue() !== 'cnpj') return;
    const digits = documentInput.value.replace(/\D/g, '');
    if (digits.length !== 14) return;
    fetch(`/api/cnpj/${digits}`)
      .then((response) => response.json())
      .then((data) => {
        if (!data) return;
        if (data.company && companyInput) {
          companyInput.value = data.company;
          if (companyWrapper) {
            companyWrapper.classList.remove('d-none');
          }
        }
        if (data.email) {
          const emailInput = document.getElementById('email');
          if (emailInput && !emailInput.value) {
            emailInput.value = data.email;
          }
        }
        if (data.telefone) {
          const telInput = document.getElementById('telefone');
          if (telInput && !telInput.value) {
            telInput.value = data.telefone;
          }
        }
      })
      .catch(() => {});
  }

  function toggleOutroUsuario(force) {
    if (!usarOutroSelect || !outroWrapper) {
      return;
    }
    const shouldShow = typeof force === 'boolean'
      ? force
      : (usarOutroSelect.value || '').toLowerCase() === 'sim';
    outroWrapper.classList.toggle('d-none', !shouldShow);
    if (!shouldShow && outroUsuarioSelect) {
      outroUsuarioSelect.value = '';
    }
  }

  function formatCurrency(value) {
    const numeric = Number.isFinite(value) ? value : 0;
    return `R$ ${fmt(numeric)}`;
  }

  function maskCurrencyInput(inputEl) {
    if (!inputEl) return;
    const applyMask = () => {
      const digits = (inputEl.value || '').replace(/\D/g, '');
      if (!digits) {
        inputEl.value = '';
        return;
      }
      const value = parseInt(digits, 10) / 100;
      inputEl.value = formatCurrency(value);
    };
    inputEl.addEventListener('input', applyMask);
    inputEl.addEventListener('blur', applyMask);
  }

  function toggleSistemaEdit(force) {
    if (!usarSistemaSwitch || !sistemaWrapper) {
      return;
    }
    const active = typeof force === 'boolean' ? force : usarSistemaSwitch.checked;
    sistemaWrapper.classList.toggle('d-none', !active);
    if (!active) {
      if (sistemaSelect) {
        sistemaSelect.selectedIndex = 0;
      }
      if (sistemaQuantidade) {
        sistemaQuantidade.value = '1';
      }
      if (sistemaPreco) {
        sistemaPreco.value = '';
      }
      if (sistemaTotalInput) {
        sistemaTotalInput.value = '0';
      }
      if (sistemaPreview) {
        sistemaPreview.innerHTML = '';
      }
    } else {
      updateSistemaPreview();
    }
  }

  function updateSistemaPreview() {
    if (!sistemaTotalInput) {
      return;
    }
    if (!usarSistemaSwitch || !usarSistemaSwitch.checked) {
      sistemaTotalInput.value = '0';
      if (sistemaPreview) {
        sistemaPreview.innerHTML = '';
      }
      return;
    }
    const opt = sistemaSelect ? sistemaSelect.options[sistemaSelect.selectedIndex] : null;
    let quantity = parseInt(sistemaQuantidade ? sistemaQuantidade.value : '1', 10);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      quantity = 1;
      if (sistemaQuantidade) {
        sistemaQuantidade.value = '1';
      }
    }
    const unit = sistemaPreco ? br2f(sistemaPreco.value) : 0;
    const saneUnit = Number.isFinite(unit) ? unit : 0;
    const isFixo = document.getElementById('sistema_preco_manual_edit')?.checked;
    const total = isFixo ? saneUnit : (quantity * saneUnit);
    sistemaTotalInput.value = Number.isFinite(total) ? total.toFixed(2) : '0';
    if (sistemaPreview) {
      const pieces = [];
      const customDesc = document.getElementById('sistema_descricao_custom_edit');
      const descVal = customDesc ? customDesc.value : '';
      if (opt && opt.value) {
        const label = (opt.textContent || '').trim();
        if (label) {
          pieces.push(`<strong>${label}</strong>`);
        }
        pieces.push(`<div>${descVal || opt.dataset.description || ''}</div>`);
      }
      const isFixo = document.getElementById('sistema_preco_manual_edit')?.checked;
      pieces.push(`<div>Qtd: ${quantity}</div>`);
      const unitLabel = isFixo ? (saneUnit > 0 ? formatCurrency(saneUnit) : '-') : formatCurrency(saneUnit) + ' mensais';
      pieces.push(`<div>Unitário: ${unitLabel}</div>`);
      sistemaPreview.innerHTML = pieces.join('');
    }
  }

  // Attach event listeners for dynamic preview updates
  if (sistemaPreco) {
    sistemaPreco.addEventListener('input', updateSistemaPreview);
    sistemaPreco.addEventListener('blur', updateSistemaPreview);
  }
  if (sistemaQuantidade) {
    sistemaQuantidade.addEventListener('input', updateSistemaPreview);
    sistemaQuantidade.addEventListener('change', updateSistemaPreview);
  }
  if (sistemaSelect) {
    sistemaSelect.addEventListener('change', () => {
      // Ao trocar o sistema, resetar a descrição para a padrão da opção selecionada
      const customDesc = document.getElementById('sistema_descricao_custom_edit');
      if (customDesc) {
        const selectedOpt = sistemaSelect.options[sistemaSelect.selectedIndex];
        customDesc.value = (selectedOpt && selectedOpt.dataset.description) ? selectedOpt.dataset.description : '';
      }
      updateSistemaPreview();
    });
  }
  const sistemaFixoCheckEdit = document.getElementById('sistema_preco_manual_edit');
  if (sistemaFixoCheckEdit) {
    sistemaFixoCheckEdit.addEventListener('change', updateSistemaPreview);
  }

  function toggleEmailOptions(force) {
    if (!emailOptionsWrapper || !enviarEmailSwitch) {
      return;
    }
    const shouldShow = typeof force === 'boolean' ? force : enviarEmailSwitch.checked;
    emailOptionsWrapper.classList.toggle('d-none', !shouldShow);
    if (!shouldShow) {
      toggleEmailCc(false);
    }
  }

  function toggleEmailCc(force) {
    if (!emailCcWrapper || !enviarCopiaSwitch) {
      return;
    }
    const shouldShow = typeof force === 'boolean' ? force : enviarCopiaSwitch.checked;
    emailCcWrapper.classList.toggle('d-none', !shouldShow);
    if (!shouldShow && emailCcInput) {
      emailCcInput.value = '';
    }
  }

  const selEquipEdit = document.getElementById('equipamento-edit-select');
  const containerEdit = document.getElementById('equipamentos-edit-selecionados');
  const formEdicao = document.getElementById('formEdicao');
  const locacaoFieldsEdit = document.getElementById('locacaoFieldsEdit');
  const locacaoVigenciaInput = document.getElementById('locacao_vigencia_edit');
  const locacaoModeloInput = document.getElementById('locacao_modelo_edit');
  const locacaoCnpjsInput = document.getElementById('locacao_qtd_cnpjs_edit');
  const modalidadeSelectEdit = document.getElementById('modalidade_type_edit');
  const repPWrapperEdit = document.getElementById('repPWrapperEdit');
  const repCategoriaEdit = document.getElementById('rep_categoria_programa_edit');
  const repMobileWrapperEdit = document.getElementById('repMobileWrapperEdit');
  const repTemMobileEdit = document.getElementById('rep_tem_mobile_edit');
  const repMobileQtdWrapperEdit = document.getElementById('repMobileQtdWrapperEdit');
  const repMobileQtdEdit = document.getElementById('rep_qtd_mobile_edit');
  const repMobileValorEdit = document.getElementById('rep_mobile_valor_mensal_edit');
  const observacaoComercialEdit = document.getElementById('observacao_comercial_edit');
  const ambienteFotosEdit = document.getElementById('ambiente_fotos_edit');
  const ambienteIncluirEdit = document.getElementById('ambiente_incluir_edit');
  const ambienteWrapperEdit = document.getElementById('ambienteFotosWrapperEdit');
  const servicoSelectEdit = document.getElementById('servico_type_edit');
  let ambienteFilesEdit = [];
  let ambienteTitleMapEdit = new Map();
  function buildAmbienteKeyEdit(file) {
    return `${file.name}_${file.size}_${file.lastModified}`;
  }
  function syncAmbienteInputEdit() {
    if (!ambienteFotosEdit) return;
    const dt = new DataTransfer();
    ambienteFilesEdit.forEach((file) => dt.items.add(file));
    ambienteFotosEdit.files = dt.files;
  }

  function toggleLocacaoEdit(value) {
    if (!locacaoFieldsEdit) return;
    const modalidade = (value || (modalidadeSelectEdit?.value || '')).toUpperCase();
    const isLocacao = modalidade === 'LOCACAO';
    locacaoFieldsEdit.classList.toggle('d-none', !isLocacao);
    document.querySelectorAll('.equip-acquisition-edit').forEach((wrapper) => {
      wrapper.classList.toggle('d-none', !isLocacao);
      if (!isLocacao) {
        const checkbox = wrapper.querySelector('input[type="checkbox"]');
        if (checkbox) checkbox.checked = false;
      }
    });
  }
  if (modalidadeSelectEdit) {
    modalidadeSelectEdit.addEventListener('change', (event) => {
      toggleLocacaoEdit(event.target.value);
    });
    toggleLocacaoEdit(modalidadeSelectEdit.value);
  }

  function isServicoPontoEdit() {
    return (servicoSelectEdit?.value || '').toUpperCase() === 'PONTO';
  }

  function toggleRepMobileEdit() {
    const repActive = !!(repCategoriaEdit && repCategoriaEdit.checked && isServicoPontoEdit());
    if (repMobileWrapperEdit) {
      repMobileWrapperEdit.classList.toggle('d-none', !repActive);
    }
    if (!repActive) {
      if (repTemMobileEdit) repTemMobileEdit.checked = false;
      if (repMobileQtdEdit) repMobileQtdEdit.value = '';
      if (repMobileValorEdit) repMobileValorEdit.value = '';
    }
    const showQtd = repActive && repTemMobileEdit && repTemMobileEdit.checked;
    if (repMobileQtdWrapperEdit) {
      repMobileQtdWrapperEdit.classList.toggle('d-none', !showQtd);
    }
    if (!showQtd) {
      if (repMobileQtdEdit) repMobileQtdEdit.value = '';
      if (repMobileValorEdit) repMobileValorEdit.value = '';
    }
  }

  function toggleRepPEdit() {
    const isPonto = isServicoPontoEdit();
    if (repPWrapperEdit) {
      repPWrapperEdit.classList.toggle('d-none', !isPonto);
    }
    if (!isPonto && repCategoriaEdit) {
      repCategoriaEdit.checked = false;
    }
    toggleRepMobileEdit();
  }

  if (servicoSelectEdit) {
    servicoSelectEdit.addEventListener('change', toggleRepPEdit);
    toggleRepPEdit();
  }
  if (repCategoriaEdit) {
    repCategoriaEdit.addEventListener('change', toggleRepMobileEdit);
  }
  if (repTemMobileEdit) {
    repTemMobileEdit.addEventListener('change', toggleRepMobileEdit);
  }

  function renderAmbientePreviewEdit() {
    const preview = document.getElementById('ambienteFotosPreviewEdit');
    if (!preview || !ambienteFotosEdit) return;
    preview.innerHTML = '';
    const list = ambienteFilesEdit.length ? ambienteFilesEdit : Array.from(ambienteFotosEdit.files || []);
    const files = list.filter((file) => file && file.type && file.type.startsWith('image/'));
    if (!files.length) {
      preview.classList.add('d-none');
      return;
    }
    preview.classList.remove('d-none');
    files.forEach((file) => {
      const reader = new FileReader();
      reader.onload = () => {
        const key = buildAmbienteKeyEdit(file);
        if (!ambienteTitleMapEdit.has(key)) {
          ambienteTitleMapEdit.set(key, '');
        }
        const wrap = document.createElement('div');
        wrap.className = 'ambiente-preview-item';
        const thumb = document.createElement('div');
        thumb.className = 'ambiente-preview-thumb';
        const img = document.createElement('img');
        img.src = reader.result;
        img.alt = file.name || 'Ambiente';
        thumb.appendChild(img);
        const titleInput = document.createElement('input');
        titleInput.type = 'text';
        titleInput.name = 'ambiente_titulos';
        titleInput.className = 'form-control form-control-sm ambiente-title-input';
        titleInput.placeholder = 'Titulo da foto';
        titleInput.value = ambienteTitleMapEdit.get(key) || '';
        titleInput.addEventListener('input', () => {
          ambienteTitleMapEdit.set(key, titleInput.value);
        });
        wrap.appendChild(thumb);
        wrap.appendChild(titleInput);
        preview.appendChild(wrap);
      };
      reader.readAsDataURL(file);
    });
  }
  function mergeAmbienteFilesEdit() {
    if (!ambienteFotosEdit) return;
    const incoming = Array.from(ambienteFotosEdit.files || [])
      .filter((file) => file && file.type && file.type.startsWith('image/'));
    if (!incoming.length) return;
    const map = new Map(ambienteFilesEdit.map((file) => [buildAmbienteKeyEdit(file), file]));
    incoming.forEach((file) => map.set(buildAmbienteKeyEdit(file), file));
    ambienteFilesEdit = Array.from(map.values());
    ambienteFilesEdit.forEach((file) => {
      const key = buildAmbienteKeyEdit(file);
      if (!ambienteTitleMapEdit.has(key)) {
        ambienteTitleMapEdit.set(key, '');
      }
    });
    syncAmbienteInputEdit();
    renderAmbientePreviewEdit();
  }
  function toggleAmbienteEdit(force) {
    const show = typeof force === 'boolean'
      ? force
      : !!(ambienteIncluirEdit && ambienteIncluirEdit.checked);
    if (ambienteWrapperEdit) {
      ambienteWrapperEdit.classList.toggle('d-none', !show);
    }
    const preview = document.getElementById('ambienteFotosPreviewEdit');
    if (!show) {
      ambienteFilesEdit = [];
      ambienteTitleMapEdit = new Map();
      if (ambienteFotosEdit) ambienteFotosEdit.value = '';
      if (preview) {
        preview.innerHTML = '';
        preview.classList.add('d-none');
      }
      return;
    }
    mergeAmbienteFilesEdit();
  }
  if (ambienteIncluirEdit) {
    ambienteIncluirEdit.addEventListener('change', () => toggleAmbienteEdit());
  }
  if (ambienteFotosEdit) {
    ambienteFotosEdit.addEventListener('change', mergeAmbienteFilesEdit);
  }
  maskCurrencyInput(repMobileValorEdit);

  function recalcularEdit(uid) {
    const row = document.getElementById(`equip_edit_${uid}`);
    if (!row) return;
    const qtd = parseFloat(row.querySelector(`[name="quantity_${uid}"]`).value) || 1;
    let preco = parseFloat(row.dataset.preco || 0);
    if (document.getElementById(`chk_preco_edit_${uid}`).checked) {
      preco = br2f(document.getElementById(`manual_edit_${uid}`).value);
    }
    const pct = document.getElementById(`chk_desc_edit_${uid}`).checked
      ? (parseFloat(document.getElementById(`pct_edit_${uid}`)?.value) || 0)
      : 0;
    const precoDesc = preco * (1 - pct / 100);

    const fullPriceEl = document.getElementById(`p_cheio_edit_${uid}`);
    const descPriceEl = document.getElementById(`p_desc_edit_${uid}`);
    if (fullPriceEl) fullPriceEl.textContent = fmt(preco * qtd);
    if (descPriceEl) descPriceEl.textContent = fmt(precoDesc * qtd);
  }

  function togglePctEdit(uid) {
    const wrap = document.getElementById(`wrap_pct_edit_${uid}`);
    const chk = document.getElementById(`chk_desc_edit_${uid}`);
    const pctInput = document.getElementById(`pct_edit_${uid}`);
    if (wrap && chk) {
      wrap.classList.toggle('d-none', !chk.checked);
      if (!chk.checked && pctInput) {
        pctInput.value = '';
      }
    }
    recalcularEdit(uid);
  }

  function togglePrecoEdit(uid) {
    const wrap = document.getElementById(`wrap_manual_edit_${uid}`);
    const chk = document.getElementById(`chk_preco_edit_${uid}`);
    const manual = document.getElementById(`manual_edit_${uid}`);
    if (wrap && chk) {
      wrap.classList.toggle('d-none', !chk.checked);
      if (!chk.checked && manual) {
        manual.value = '';
      }
    }
    recalcularEdit(uid);
  }

  function toggleOutroEdit(select) {
    const id = select.id.replace('_edit', '');
    const wrapper = document.getElementById(`${id}_other_edit_wrapper`);
    if (!wrapper) return;
    if (select.value === 'outros') {
      wrapper.classList.remove('d-none');
    } else {
      wrapper.classList.add('d-none');
      const other = document.getElementById(`${id}_other_edit`);
      if (other) {
        other.value = '';
      }
    }
  }

  function normalizeTelefone(inputEl) {
    if (!inputEl) return;
    let raw = (inputEl.value || '').trim();
    if (!raw) return;

    const digits = raw.replace(/\D/g, '');
    if (raw.startsWith('+') && digits.startsWith('55')) return;
    if (digits.startsWith('55') && digits.length >= 12) {
      inputEl.value = `+${digits}`;
      return;
    }
    let d = digits.replace(/^0+/, '');
    if (d.length === 10 || d.length === 11) {
      inputEl.value = `+55${d}`;
      return;
    }
    if (digits.length >= 12 && !raw.startsWith('+')) {
      inputEl.value = `+${digits}`;
    }
  }

  function populateParamSelect(baseId, value) {
    const select = document.getElementById(`${baseId}_edit`);
    const other = document.getElementById(`${baseId}_other_edit`);
    if (!select) return;
    const normalized = (value || '').trim();
    if (!normalized) {
      select.value = '';
      toggleOutroEdit(select);
      if (other) other.value = '';
      return;
    }
    const hasOption = Array.from(select.options).some((opt) => opt.value === normalized);
    if (hasOption) {
      select.value = normalized;
      toggleOutroEdit(select);
      if (other) other.value = '';
      return;
    }
    select.value = 'outros';
    toggleOutroEdit(select);
    if (other) other.value = normalized;
  }

  function normalizeParamValues(formData) {
    const mappings = [
      { select: 'pagto_equip', other: 'pagto_equip_other', target: 'pagamento' },
      { select: 'prazo_entrega', other: 'prazo_entrega_other', target: 'prazo_entrega' },
      { select: 'frete', other: 'frete_other', target: 'frete' },
      { select: 'garantia_eq', other: 'garantia_eq_other', target: 'garantia' },
      { select: 'garantia_sys', other: 'garantia_sys_other', target: 'garantia_sistema' },
    ];

    mappings.forEach(({ select, other, target }) => {
      const value = (formData.get(select) || '').trim();
      const otherValue = (formData.get(other) || '').trim();
      if (value === 'outros') {
        formData.set(target, otherValue);
      } else if (value) {
        formData.set(target, value);
      } else if (otherValue) {
        formData.set(target, otherValue);
      }
      if (select !== target) {
        formData.delete(select);
      }
      formData.delete(other);
    });

    if (enviarCopiaSwitch && !enviarCopiaSwitch.checked) {
      formData.delete('email_cc');
    }
  }

  function buildFormData(form) {
    const formData = new FormData(form);
    normalizeParamValues(formData);
    return formData;
  }

  function abrirModalEdicao(id) {
    const erroDiv = document.getElementById('erro-edicao-modal');
    if (erroDiv) erroDiv.classList.add('d-none');

    secureFetch(`/editar_proposta/${id}`)
      .then((response) => response.json())
      .then((data) => {
        if (data.error) {
          alert(data.error);
          return;
        }

        const docType = (data.client_document_type || data.document_type || 'cnpj').toLowerCase();
        if (docTypeSelect) {
          docTypeSelect.value = docType;
          applyDocTypeUI(docType);
        }
        if (documentInput) {
          documentInput.value = data.document || '';
          updateDocumentInputFormatting();
        }
        if (issuerSelect && data.issuer_company_code) {
          issuerSelect.value = data.issuer_company_code;
        }

        if (usarOutroSelect) {
          const usarOutroValor = (data.usar_outro_usuario || 'nao').toLowerCase();
          usarOutroSelect.value = usarOutroValor;
          toggleOutroUsuario(usarOutroValor === 'sim');
        }
        if (outroUsuarioSelect) {
          if (data.outro_usuario_id) {
            outroUsuarioSelect.value = String(data.outro_usuario_id);
          } else if (!usarOutroSelect || usarOutroSelect.value !== 'sim') {
            outroUsuarioSelect.value = '';
          }
        }

        if (usarSistemaSwitch) {
          const hasSystem = Boolean(data.sistema_ativo);
          usarSistemaSwitch.checked = hasSystem;
          toggleSistemaEdit(hasSystem);
        }
        const sistemaFixoCheck = document.getElementById('sistema_preco_manual_edit');
        if (sistemaFixoCheck) {
          sistemaFixoCheck.checked = Boolean(data.sistema_preco_manual);
        }
        if (sistemaSelect) {
          let matched = false;
          if (data.sistema_key) {
            const exact = Array.from(sistemaSelect.options).find((opt) => opt.value === data.sistema_key);
            if (exact) {
              exact.selected = true;
              matched = true;
            }
          }
          if (!matched && data.sistema_nome) {
            const byLabel = Array.from(sistemaSelect.options).find((opt) => (opt.textContent || '').trim().toLowerCase() === data.sistema_nome.trim().toLowerCase());
            if (byLabel) {
              byLabel.selected = true;
              matched = true;
            }
          }
          if (!matched) {
            sistemaSelect.selectedIndex = 0;
          }
        }
        if (sistemaQuantidade) {
          if (data.sistema_quantidade) {
            sistemaQuantidade.value = data.sistema_quantidade;
          } else if (!sistemaQuantidade.value) {
            sistemaQuantidade.value = '1';
          }
        }
        if (sistemaPreco) {
          if (typeof data.sistema_preco_unitario === 'number' && !Number.isNaN(data.sistema_preco_unitario) && data.sistema_preco_unitario > 0) {
            sistemaPreco.value = formatCurrency(data.sistema_preco_unitario);
          } else {
            sistemaPreco.value = '';
          }
        }
        if (sistemaTotalInput) {
          if (typeof data.sistema_preco_total === 'number' && !Number.isNaN(data.sistema_preco_total)) {
            sistemaTotalInput.value = data.sistema_preco_total.toFixed(2);
          } else {
            sistemaTotalInput.value = '0';
          }
        }
        const customDescInput = document.getElementById('sistema_descricao_custom_edit');
        if (customDescInput) {
          customDescInput.value = data.sistema_descricao || '';
        }

        if (usarSistemaSwitch && usarSistemaSwitch.checked) {
          updateSistemaPreview();
        } else if (sistemaPreview) {
          sistemaPreview.innerHTML = '';
        }

        const camposSimples = ['proposta_id', 'company', 'client_name', 'email', 'telefone'];
        camposSimples.forEach((campo) => {
          const el = document.getElementById(campo === 'proposta_id' ? 'proposta_id' : campo);
          if (!el) return;
          el.value = campo === 'proposta_id' ? (data.proposta_id || id) : (data[campo] || '');
        });
        if (observacaoComercialEdit) {
          observacaoComercialEdit.value = data.observacao_comercial || '';
        }
        if (ambienteIncluirEdit) {
          ambienteIncluirEdit.checked = !!data.ambiente_incluir;
          toggleAmbienteEdit(ambienteIncluirEdit.checked);
        }
        if (ambienteFotosEdit) {
          ambienteFotosEdit.value = '';
        }
        ambienteFilesEdit = [];
        ambienteTitleMapEdit = new Map();
        renderAmbientePreviewEdit();

        const tel = document.getElementById('telefone');
        if (tel) {
          tel.removeEventListener?.('__blur_norm__', tel.__blur_norm_handler);
          tel.__blur_norm_handler = () => normalizeTelefone(tel);
          tel.addEventListener('blur', tel.__blur_norm_handler);
          tel.__blur_norm__ = true;
        }

        const servicoSelect = document.getElementById('servico_type_edit');
        if (servicoSelect && data.servico_type) {
          servicoSelect.value = data.servico_type;
        }
        const modalidadeSelect = document.getElementById('modalidade_type_edit');
        if (modalidadeSelect && data.modalidade_type) {
          modalidadeSelect.value = data.modalidade_type;
        }
        toggleLocacaoEdit(modalidadeSelect?.value);
        if (locacaoVigenciaInput) {
          locacaoVigenciaInput.value = data.locacao_vigencia || '';
        }
        if (locacaoModeloInput) {
          const modeloRaw = (data.locacao_modelo || '').toString().toLowerCase();
          locacaoModeloInput.value = (modeloRaw === 'analitico' || modeloRaw === 'sintetico')
            ? modeloRaw
            : 'sintetico';
        }
        if (locacaoCnpjsInput) {
          locacaoCnpjsInput.value = data.locacao_qtd_cnpjs || '';
        }

        if (repCategoriaEdit) {
          repCategoriaEdit.checked = Boolean(data.rep_categoria_programa);
        }
        if (repTemMobileEdit) {
          repTemMobileEdit.checked = Boolean(data.rep_tem_mobile);
        }
        if (repMobileQtdEdit) {
          repMobileQtdEdit.value = data.rep_qtd_mobile || '';
        }
        if (repMobileValorEdit) {
          if (typeof data.rep_mobile_valor_mensal === 'number' && !Number.isNaN(data.rep_mobile_valor_mensal)) {
            repMobileValorEdit.value = formatCurrency(data.rep_mobile_valor_mensal);
          } else {
            repMobileValorEdit.value = data.rep_mobile_valor_mensal || '';
          }
        }
        toggleRepPEdit();

        const paramValues = {
          pagto_equip: data.pagamento,
          prazo_entrega: data.prazo_entrega,
          frete: data.frete,
          garantia_eq: data.garantia,
          garantia_sys: data.garantia_sistema,
        };
        Object.entries(paramValues).forEach(([base, value]) => {
          populateParamSelect(base, value);
        });
        const validadeEdit = document.getElementById('validade_edit');
        if (validadeEdit) {
          validadeEdit.value = toIsoDate(data.validade);
        }
        containerEdit.innerHTML = '';
        (data.equipamentos || []).forEach((eq) => {
          const uid = `edit_${eq.id}_${Math.floor(Math.random() * 100000)}`;
          const row = document.createElement('div');
          const stockQty = typeof eq.stock_quantity === 'number' ? eq.stock_quantity : (eq.stock_quantity || 0);
          row.id = `equip_edit_${uid}`;
          row.className = 'equip-card mb-3 p-3 border rounded shadow-sm bg-white';

          const catalogPrice = typeof eq.catalog_price === 'number' ? eq.catalog_price : 0.0;
          const overrideUnit = typeof eq.unit_price === 'number' ? eq.unit_price : 0.0;
          const hasCustomPrice = overrideUnit > 0 && Math.abs(overrideUnit - catalogPrice) > 0.005;
          row.dataset.preco = catalogPrice;

          row.innerHTML = `
            <input type="hidden" name="item_uids" value="${uid}">
            <input type="hidden" name="equip_id_${uid}" value="${eq.id}">
            <div class="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">
              <div>
                <strong>${eq.name}</strong>
                <span class="equip-stock-tag ms-2">Estoque: ${stockQty}</span>
              </div>
              <div class="d-flex align-items-center gap-2">
                Qtd:
                <input type="number" name="quantity_${uid}" value="${eq.quantity}" min="1"
                       class="form-control d-inline-block" style="width:80px"
                       onchange="recalcularEdit('${uid}')">
                <label class="ms-2 me-1"><input type="checkbox" id="chk_desc_edit_${uid}"
                       onchange="togglePctEdit('${uid}')" ${eq.discount_percent > 0 ? 'checked' : ''}> Desconto?</label>
                <span id="wrap_pct_edit_${uid}" class="${eq.discount_percent > 0 ? '' : 'd-none'}">
                  <input type="number" id="pct_edit_${uid}" name="discount_${uid}" placeholder="%"
                         class="form-control d-inline-block" style="width:90px"
                         min="0" max="100" step="0.01" oninput="recalcularEdit('${uid}')" value="${eq.discount_percent}"> %
                </span>
                <label class="ms-2 me-1"><input type="checkbox" id="chk_preco_edit_${uid}"
                       onchange="togglePrecoEdit('${uid}')" ${hasCustomPrice ? 'checked' : ''}> Preço?</label>
                <span id="wrap_manual_edit_${uid}" class="${hasCustomPrice ? '' : 'd-none'}">
                  <input type="text" id="manual_edit_${uid}" name="price_${uid}"
                         class="form-control d-inline-block" style="width:110px"
                         placeholder="R$ 0,00" value="${hasCustomPrice ? formatCurrency(overrideUnit) : ''}">
                </span>
                <label class="ms-2 me-1 equip-acquisition-edit d-none">
                  <input type="checkbox" name="acquisition_${uid}" value="1" ${eq.is_acquisition ? 'checked' : ''}> Aquisição?
                </label>
                <label class="ms-2 me-1">
                  <input type="checkbox" name="include_in_total_${uid}" value="1" ${eq.include_in_total !== false ? 'checked' : ''}> Somar no Total?
                </label>
                <small class="ms-3">
                  Preço: R$ <span id="p_cheio_edit_${uid}">0,00</span> |
                  c/ desc.: R$ <span id="p_desc_edit_${uid}">0,00</span>
                </small>
                <button type="button" class="btn btn-sm btn-danger ms-2"
                        onclick="this.closest('.equip-card').remove()">Remover</button>
              </div>
            </div>
            <div class="mt-2">
              <textarea name="description_${uid}" class="form-control form-control-sm" rows="2" placeholder="Descrição do equipamento para esta proposta (opcional)"></textarea>
            </div>
          `;
          containerEdit.appendChild(row);
          const taEdit = row.querySelector(`[name='description_${uid}']`);
          if (taEdit) {
            taEdit.value = eq.description || '';
          }
          recalcularEdit(uid);
          const mEdit = document.getElementById(`manual_edit_${uid}`);
          if (mEdit) {
            maskCurrencyInput(mEdit);
            mEdit.addEventListener('input', () => recalcularEdit(uid));
            mEdit.addEventListener('blur', () => recalcularEdit(uid));
          }
        });
        toggleLocacaoEdit(modalidadeSelect?.value);

        if (enviarEmailSwitch) {
          enviarEmailSwitch.checked = !!data.enviar_email;
          toggleEmailOptions(enviarEmailSwitch.checked);
        }
        if (emailBodyInput) {
          emailBodyInput.value = data.email_corpo || '';
        }
        if (enviarCopiaSwitch) {
          const hasCc = !!(data.email_cc && data.email_cc.trim());
          enviarCopiaSwitch.checked = hasCc;
          toggleEmailCc(hasCc);
        }
        if (emailCcInput) {
          emailCcInput.value = data.email_cc || '';
        }

        const modal = bootstrapLib ? bootstrapLib.Modal.getOrCreateInstance(document.getElementById('modalEdicao')) : null;
        modal?.show();
      });
  }

  if (formEdicao) {
    secureFormCsrf(formEdicao);
    formEdicao.addEventListener('submit', (event) => {
      event.preventDefault();
      const id = document.getElementById('proposta_id').value;
      const erroDiv = document.getElementById('erro-edicao-modal');
      if (erroDiv) erroDiv.classList.add('d-none');
      if (usarSistemaSwitch) {
        if (usarSistemaSwitch.checked) {
          updateSistemaPreview();
        } else if (sistemaTotalInput) {
          sistemaTotalInput.value = '0';
        }
      }
      const params = buildFormData(formEdicao);
      secureFetch(`/editar_proposta/${id}`, {
        method: 'POST',
        body: params,
      })
        .then((response) => response.json())
        .then((data) => {
          if (data.success) {
            const successMessage = data.message || 'Proposta atualizada com sucesso.';
            try {
              sessionStorage.setItem('history-edit-success', successMessage);
            } catch (error) {
              console.warn('Não foi possível armazenar a mensagem de sucesso', error);
            }
            const modalInstance = bootstrapLib && modalEdicaoEl
              ? bootstrapLib.Modal.getInstance(modalEdicaoEl)
                || bootstrapLib.Modal.getOrCreateInstance(modalEdicaoEl)
              : null;
            modalInstance?.hide();
            setTimeout(() => location.reload(), 200);
          } else if (data.error) {
            if (erroDiv) {
              erroDiv.innerText = data.error;
              erroDiv.classList.remove('d-none');
            } else {
              alert(data.error);
            }
          } else {
            alert('Erro ao salvar alterações.');
          }
        })
        .catch((error) => {
          console.error(error);
          if (erroDiv) {
            erroDiv.innerText = 'Erro ao salvar alterações.';
            erroDiv.classList.remove('d-none');
          } else {
            historyFlash('Erro ao salvar alterações.', 'danger');
          }
        });
    });
  }

  if (selEquipEdit) {
    selEquipEdit.addEventListener('change', () => {
      const opt = selEquipEdit.options[selEquipEdit.selectedIndex];
      const id = opt.value;
      const nome = opt.dataset.nome;
      const stock = opt.dataset.quantity || '0';
      if (!id) return;

      const uid = `new_${id}_${Date.now()}_${Math.floor(Math.random() * 1000)}`;
      const row = document.createElement('div');
      row.id = `equip_edit_${uid}`;
      row.className = 'equip-card mb-3 p-3 border rounded shadow-sm bg-white';
      row.innerHTML = `
        <input type="hidden" name="item_uids" value="${uid}">
        <input type="hidden" name="equip_id_${uid}" value="${id}">
        <div class="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">
          <div>
            <strong>${nome}</strong>
            <span class="equip-stock-tag ms-2">Estoque: ${stock}</span>
          </div>
          <div class="d-flex align-items-center gap-2">
            Qtd:
            <input type="number" name="quantity_${uid}" value="1" min="1"
                   class="form-control d-inline-block" style="width:80px"
                   onchange="recalcularEdit('${uid}')">
            <label class="ms-2 me-1"><input type="checkbox" id="chk_desc_edit_${uid}"
                   onchange="togglePctEdit('${uid}')"> Desconto?</label>
            <span id="wrap_pct_edit_${uid}" class="d-none">
              <input type="number" id="pct_edit_${uid}" name="discount_${uid}" placeholder="%"
                     class="form-control d-inline-block" style="width:90px"
                     min="0" max="100" step="0.01" oninput="recalcularEdit('${uid}')"> %
            </span>
            <label class="ms-2 me-1"><input type="checkbox" id="chk_preco_edit_${uid}"
                   onchange="togglePrecoEdit('${uid}')"> Preço?</label>
            <span id="wrap_manual_edit_${uid}" class="d-none">
              <input type="text" id="manual_edit_${uid}" name="price_${uid}"
                     class="form-control d-inline-block" style="width:110px"
                     placeholder="R$ 0,00">
            </span>
            <label class="ms-2 me-1 equip-acquisition-edit d-none">
              <input type="checkbox" name="acquisition_${uid}" value="1"> Aquisição?
            </label>
            <label class="ms-2 me-1">
              <input type="checkbox" name="include_in_total_${uid}" value="1" checked> Somar no Total?
            </label>
            <small class="ms-3">
              Preço: R$ <span id="p_cheio_edit_${uid}">0,00</span> |
              c/ desc.: R$ <span id="p_desc_edit_${uid}">0,00</span>
            </small>
            <button type="button" class="btn btn-sm btn-danger ms-2"
                    onclick="this.closest('.equip-card').remove()">Remover</button>
          </div>
        </div>
        <div class="mt-2">
          <textarea name="description_${uid}" class="form-control form-control-sm" rows="2" placeholder="Descrição do equipamento para esta proposta (opcional)"></textarea>
        </div>
      `;
      containerEdit.appendChild(row);
      selEquipEdit.selectedIndex = 0;
      selEquipEdit.value = '';
      const _srch = document.getElementById('equip-edit-search');
      if (_srch) { _srch.value = ''; const _dd = document.getElementById('equip-edit-dropdown'); if (_dd) _dd.style.display = 'none'; }
      toggleLocacaoEdit(modalidadeSelectEdit?.value);
      secureFetch(`/equipamentos/${id}`).then(r => r.json()).then((data) => {
        const p = parseFloat(data.preco) || 0;
        row.dataset.preco = p;
        const fullPriceEl = document.getElementById(`p_cheio_edit_${uid}`);
        if (fullPriceEl) fullPriceEl.textContent = fmt(p);
        const ta = row.querySelector(`[name='description_${uid}']`);
        if (ta && data.descricao) ta.value = data.descricao;
        recalcularEdit(uid);
        const mEdit = document.getElementById(`manual_edit_${uid}`);
        if (mEdit) {
          maskCurrencyInput(mEdit);
          mEdit.addEventListener('input', () => recalcularEdit(uid));
          mEdit.addEventListener('blur', () => recalcularEdit(uid));
        }
      });
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    ensureHistoryPdfModal();
    document.querySelectorAll('[data-select-target]').forEach(setupSelectSearch);

    document.querySelectorAll('.param-select-edit')
      .forEach((select) => select.addEventListener('change', () => toggleOutroEdit(select)));

    document.querySelectorAll('.js-history-pdf')
      .forEach((btn) => btn.addEventListener('click', (event) => {
        event.preventDefault();
        requestHistoryPdf(btn);
      }));
    document.querySelectorAll('.js-history-pdf-download')
      .forEach((btn) => btn.addEventListener('click', (event) => {
        event.preventDefault();
        requestHistoryPdfDownload(btn);
      }));
    document.querySelectorAll('.js-toggle-versions')
      .forEach((btn) => btn.addEventListener('click', (event) => {
        event.preventDefault();
        toggleVersionRow(btn);
      }));
    document.querySelectorAll('.js-approve-version')
      .forEach((btn) => btn.addEventListener('click', (event) => {
        event.preventDefault();
        openApproveModal(btn);
      }));

    document.querySelectorAll('.js-view-changes')
      .forEach((btn) => btn.addEventListener('click', (event) => {
        event.preventDefault();
        viewVersionChanges(btn);
      }));

    if (approveConfirmBtn) {
      approveConfirmBtn.addEventListener('click', (event) => {
        event.preventDefault();
        submitApprove();
      });
    }

    if (docTypeSelect) {
      applyDocTypeUI(docTypeSelect.value);
    }
    if (usarOutroSelect) {
      toggleOutroUsuario((usarOutroSelect.value || '').toLowerCase() === 'sim');
    }
    if (usarSistemaSwitch) {
      toggleSistemaEdit(usarSistemaSwitch.checked);
    }
    if (enviarEmailSwitch) {
      toggleEmailOptions(enviarEmailSwitch.checked);
    }
    if (enviarCopiaSwitch) {
      toggleEmailCc(enviarCopiaSwitch.checked);
    }

    try {
      const storedMessage = sessionStorage.getItem('history-edit-success');
      if (storedMessage) {
        historyFlash(storedMessage, 'success');
        sessionStorage.removeItem('history-edit-success');
      }
    } catch (error) {
      console.warn('Não foi possível recuperar a mensagem de sucesso.', error);
    }
  });

  if (docTypeSelect) {
    docTypeSelect.addEventListener('change', () => applyDocTypeUI(docTypeSelect.value));
  }

  if (documentInput) {
    documentInput.addEventListener('input', updateDocumentInputFormatting);
    documentInput.addEventListener('blur', handleDocumentBlur);
  }

  if (usarOutroSelect) {
    usarOutroSelect.addEventListener('change', () => toggleOutroUsuario());
  }

  if (usarSistemaSwitch) {
    usarSistemaSwitch.addEventListener('change', () => {
      toggleSistemaEdit();
    });
  }

  if (sistemaQuantidade) {
    sistemaQuantidade.addEventListener('input', () => updateSistemaPreview());
    sistemaQuantidade.addEventListener('change', () => updateSistemaPreview());
  }

  if (sistemaPreco) {
    maskCurrencyInput(sistemaPreco);
    sistemaPreco.addEventListener('input', () => updateSistemaPreview());
    sistemaPreco.addEventListener('change', () => updateSistemaPreview());
    sistemaPreco.addEventListener('blur', () => updateSistemaPreview());
  }

  if (sistemaSelect) {
    sistemaSelect.addEventListener('change', () => {
      const opt = sistemaSelect.options[sistemaSelect.selectedIndex];
      if (opt) {
        const defaultQty = parseInt(opt.dataset.defaultQuantity || '1', 10);
        if (sistemaQuantidade && (!sistemaQuantidade.value || parseInt(sistemaQuantidade.value, 10) <= 0)) {
          sistemaQuantidade.value = Number.isFinite(defaultQty) && defaultQty > 0 ? String(defaultQty) : '1';
        }
        const defaultUnit = parseFloat(opt.dataset.unitPrice || '0');
        if (sistemaPreco && (!sistemaPreco.value || br2f(sistemaPreco.value) === 0) && defaultUnit > 0) {
          sistemaPreco.value = formatCurrency(defaultUnit);
        }
      }
      updateSistemaPreview();
    });
  }

  if (historyPdfModalEl) {
    historyPdfModalEl.addEventListener('hidden.bs.modal', () => {
      clearInterval(historyPdfTimer);
      resetHistoryPdfModal();
    });
  }

  if (modalEdicaoEl) {
    modalEdicaoEl.addEventListener('shown.bs.modal', () => {
      setupEquipEditAutocomplete();
    });
  }

  if (approveModalEl) {
    approveModalEl.addEventListener('hidden.bs.modal', () => {
      approveTargetId = null;
      if (approveConfirmBtn) {
        approveConfirmBtn.disabled = false;
      }
    });
  }

  if (enviarEmailSwitch) {
    enviarEmailSwitch.addEventListener('change', () => toggleEmailOptions(enviarEmailSwitch.checked));
  }
  if (enviarCopiaSwitch) {
    enviarCopiaSwitch.addEventListener('change', () => toggleEmailCc(enviarCopiaSwitch.checked));
  }

  // ── Vanilla autocomplete for equipment search ──────────────────────────────
  function setupEquipEditAutocomplete() {
    const searchInput = document.getElementById('equip-edit-search');
    const dropdown   = document.getElementById('equip-edit-dropdown');
    const hiddenSel  = document.getElementById('equipamento-edit-select');
    if (!searchInput || !dropdown || !hiddenSel) return;
    if (searchInput._autocompleteReady) return; // only attach once per element
    searchInput._autocompleteReady = true;

    const allOptions = Array.from(hiddenSel.options).filter(o => o.value !== '');

    function showDropdown(filter) {
      const q = (filter || '').toLowerCase().trim();
      const matches = q ? allOptions.filter(o => o.text.toLowerCase().includes(q)) : allOptions;
      if (!matches.length) { dropdown.style.display = 'none'; return; }
      dropdown.innerHTML = matches.map(o =>
        `<div class="equip-ac-item" data-value="${o.value}" data-nome="${o.dataset.nome || o.text}" data-quantity="${o.dataset.quantity || '0'}"
              style="padding:0.5rem 0.9rem;cursor:pointer;color:var(--text,#000);transition:background .15s;"
              onmouseenter="this.style.background='rgba(14,93,198,.12)'" onmouseleave="this.style.background=''">
          ${o.text}
        </div>`
      ).join('');
      dropdown.style.display = 'block';
    }

    function pickItem(value, nome, quantity) {
      hiddenSel.value = value;
      hiddenSel.dispatchEvent(new Event('change'));
      searchInput.value = '';
      dropdown.style.display = 'none';
    }

    searchInput.addEventListener('input', () => showDropdown(searchInput.value));
    searchInput.addEventListener('focus', () => showDropdown(searchInput.value));

    dropdown.addEventListener('mousedown', (e) => {
      const item = e.target.closest('.equip-ac-item');
      if (!item) return;
      e.preventDefault();
      pickItem(item.dataset.value, item.dataset.nome, item.dataset.quantity);
    });

    document.addEventListener('click', (e) => {
      if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.style.display = 'none';
      }
    }, { capture: true });
  }

  window.setupEquipEditAutocomplete = setupEquipEditAutocomplete;
  window.toggleOutroEdit = toggleOutroEdit;
  window.recalcularEdit = recalcularEdit;
  window.togglePctEdit = togglePctEdit;
  window.togglePrecoEdit = togglePrecoEdit;
  window.abrirModalEdicao = abrirModalEdicao;
})();

