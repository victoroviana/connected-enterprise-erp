(function(){
  const tipoSelect = document.getElementById('orcamento-tipo');
  if (!tipoSelect) {
    return;
  }
  const osSelect = document.getElementById('orcamento-os');
  const itemSections = document.querySelectorAll('[data-orcamento-section]');
  const conditionSections = document.querySelectorAll('[data-orcamento-conditions]');
  const osDetails = document.getElementById('os-details');
  const configModal = document.getElementById('orcamentoConfigModal');
  const applyConfigBtn = document.getElementById('orcamentoConfigApply');
  const orcamentoIdInput = document.getElementById('orcamento_id');
  const submitLabel = document.querySelector('[data-orcamento-submit-label]');
  const formEl = tipoSelect.closest('form');
  const loadingModalEl = document.getElementById('orcamentoGerandoModal');
  const loadingProgress = document.getElementById('orcamentoGerandoProgress');
  const loadingModal = loadingModalEl && window.bootstrap
    ? window.bootstrap.Modal.getOrCreateInstance(loadingModalEl)
    : null;
  const pdfModalEl = document.getElementById('orcamentoPdfPreviewModal');
  const pdfModal = pdfModalEl && window.bootstrap
    ? window.bootstrap.Modal.getOrCreateInstance(pdfModalEl)
    : null;
  const pdfFrame = document.getElementById('orcamentoPdfPreviewFrame');
  const pdfDownloadBtn = document.getElementById('orcamentoPdfDownloadBtn');
  const pdfPrintBtn = document.getElementById('orcamentoPdfPrintBtn');
  const pdfHistoryBtn = document.getElementById('orcamentoPdfHistoryBtn');
  const pdfOpenBtn = document.getElementById('orcamentoPdfOpenBtn');
  let loadingTimer = null;

  const docTypeInputs = Array.from(document.querySelectorAll('input[name="manual_document_type"]'));
  const documentInput = document.getElementById('manual_cnpj');
  const documentLabel = document.getElementById('manualDocumentLabel');
  const divCompany = document.getElementById('divManualCompany');
  const companyInput = document.getElementById('manual_empresa');
  const emailInput = document.getElementById('manual_email');
  const phoneInput = document.getElementById('manual_telefone');
  const manualUnidadeSelect = document.getElementById('manual_unidade');
  const numOrcamentoInput = document.getElementById('numero_orcamento');
  let activeFetchController = null;

  async function fetchBudgetNumber(unidade) {
    if (!numOrcamentoInput) return;
    
    // Se estiver editando um orçamento existente, não sobrescrever
    if (orcamentoIdInput && orcamentoIdInput.value) {
      return;
    }

    if (!unidade) {
      numOrcamentoInput.value = '';
      numOrcamentoInput.placeholder = 'Aguardando filial...';
      return;
    }

    if (activeFetchController) {
      activeFetchController.abort();
    }
    activeFetchController = new AbortController();

    numOrcamentoInput.placeholder = 'Buscando número...';
    try {
      const resp = await fetch(`/assistencia/orcamentos/api/next-number?unidade=${encodeURIComponent(unidade)}`, {
        signal: activeFetchController.signal
      });
      const data = await resp.json();
      if (data && data.ok && data.formatted) {
        numOrcamentoInput.value = data.formatted;
      } else {
        numOrcamentoInput.value = '';
        numOrcamentoInput.placeholder = 'Erro ao obter número';
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('Error fetching budget number:', err);
        numOrcamentoInput.value = '';
        numOrcamentoInput.placeholder = 'Erro ao obter número';
      }
    }
  }

  function updateBudgetNumberFromManualFilial() {
    if (manualUnidadeSelect) {
      fetchBudgetNumber(manualUnidadeSelect.value);
    }
  }

  function getDocType() {
    const checked = docTypeInputs.find(r => r.checked);
    return checked ? checked.value : 'cnpj';
  }

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

  function maskPhone(value) {
    let digits = (value || '').replace(/\D/g, '').slice(0, 11);
    if (digits.length <= 2) {
      return digits.length > 0 ? `(${digits}` : '';
    }
    if (digits.length <= 6) {
      return `(${digits.slice(0, 2)}) ${digits.slice(2)}`;
    }
    if (digits.length <= 10) {
      return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
    }
    return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
  }

  function updateDocumentInputFormatting() {
    if (!documentInput) return;
    const type = getDocType();
    const raw = documentInput.value || '';
    documentInput.value = type === 'cnpj' ? maskCNPJ(raw) : maskCPF(raw);
  }

  function updatePhoneInputFormatting() {
    if (!phoneInput) return;
    const raw = phoneInput.value || '';
    phoneInput.value = maskPhone(raw);
  }

  function updateDocumentUI() {
    const type = getDocType();
    if (documentLabel) {
      documentLabel.textContent = type === 'cnpj' ? 'CNPJ do Cliente' : 'CPF do Cliente';
    }
    if (documentInput) {
      documentInput.placeholder = type === 'cnpj' ? '00.000.000/0000-00' : '000.000.000-00';
      updateDocumentInputFormatting();
    }
    if (divCompany) {
      divCompany.style.display = type === 'cnpj' ? 'block' : 'none';
    }
    if (companyInput && type !== 'cnpj') {
      companyInput.value = '';
    }
  }

  function handleDocumentBlur() {
    if (!documentInput || getDocType() !== 'cnpj') return;
    const digits = documentInput.value.replace(/\D/g, '');
    if (digits.length !== 14) return;
    fetch('/api/cnpj/' + digits)
      .then(r => r.json())
      .then(d => {
        if (d && d.company && companyInput) {
          companyInput.value = d.company;
          if (divCompany) divCompany.style.display = 'block';
        }
        if (d && d.email && emailInput && !emailInput.value) {
          emailInput.value = d.email;
        }
        if (d && d.telefone && phoneInput && !phoneInput.value) {
          phoneInput.value = maskPhone(d.telefone);
        }
      })
      .catch(() => {});
  }

  if (documentInput) {
    documentInput.addEventListener('input', updateDocumentInputFormatting);
    documentInput.addEventListener('blur', handleDocumentBlur);
  }
  if (phoneInput) {
    phoneInput.addEventListener('input', updatePhoneInputFormatting);
  }
  if (docTypeInputs.length) {
    docTypeInputs.forEach(radio => {
      radio.addEventListener('change', () => {
        docTypeInputs.forEach(btn => {
          const label = btn.nextElementSibling;
          if (label) {
            label.classList.toggle('active', btn.checked);
          }
        });
        updateDocumentUI();
      });
    });
    updateDocumentUI();
  }

  function parseCurrency(value) {
    if (!value) { return 0; }
    const raw = String(value).trim();
    if (!raw) { return 0; }
    const cleaned = raw.replace(/[^\d.,-]/g, '');
    if (cleaned.includes(',')) {
      return parseFloat(cleaned.replace(/\./g, '').replace(',', '.')) || 0;
    }
    return parseFloat(cleaned) || 0;
  }

  function parsePercent(value) {
    if (!value) { return 0; }
    const cleaned = String(value).replace('%','').replace(/\s/g,'').replace(',', '.');
    return parseFloat(cleaned) || 0;
  }

  function formatCurrency(value) {
    try {
      return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value || 0);
    } catch (e) {
      return `R$ ${(value || 0).toFixed(2).replace('.', ',')}`;
    }
  }

  function formatPercent(value) {
    const num = Number.isFinite(value) ? value : 0;
    return `${num.toFixed(2)}`;
  }

  function startLoadingProgress() {
    if (!loadingProgress) { return; }
    let value = 12;
    loadingProgress.style.width = `${value}%`;
    if (loadingTimer) {
      clearInterval(loadingTimer);
    }
    loadingTimer = setInterval(() => {
      value = Math.min(94, value + Math.max(2, Math.round((94 - value) * 0.16)));
      loadingProgress.style.width = `${value}%`;
      if (value >= 94 && loadingTimer) {
        clearInterval(loadingTimer);
        loadingTimer = null;
      }
    }, 450);
  }

  function showLoadingModal() {
    if (loadingModal) {
      loadingModal.show();
    }
    startLoadingProgress();
  }

  function hideLoadingModal() {
    return new Promise((resolve) => {
      if (loadingTimer) {
        clearInterval(loadingTimer);
        loadingTimer = null;
      }
      if (loadingProgress) {
        loadingProgress.style.width = '100%';
      }
      if (loadingModal && loadingModalEl) {
        setTimeout(() => {
          let resolved = false;
          const handler = () => {
            if (resolved) return;
            resolved = true;
            loadingModalEl.removeEventListener('hidden.bs.modal', handler);
            resolve();
          };
          loadingModalEl.addEventListener('hidden.bs.modal', handler);
          loadingModal.hide();
          setTimeout(handler, 800); // Fallback
        }, 400); // Time for progress bar to hit 100%
      } else {
        resolve();
      }
    });
  }

  function showPdfModal(viewUrl, downloadUrl, downloadName, historyUrl, openUrl) {
    if (!viewUrl) {
      hideLoadingModal();
      return;
    }
    if (pdfDownloadBtn) {
      pdfDownloadBtn.href = downloadUrl || viewUrl;
      if (downloadName) {
        pdfDownloadBtn.setAttribute('download', downloadName);
      }
    }
    if (pdfHistoryBtn && historyUrl) {
      pdfHistoryBtn.href = historyUrl;
    }
    if (pdfOpenBtn && openUrl) {
      pdfOpenBtn.href = openUrl;
    }
    const openPreview = async () => {
      if (openPreview.done) return;
      openPreview.done = true;
      await hideLoadingModal();
      if (pdfModal) {
        pdfModal.show();
      } else {
        window.open(viewUrl, '_blank', 'noopener');
      }
    };
    if (pdfFrame) {
      pdfFrame.addEventListener('load', openPreview, { once: true });
      pdfFrame.src = viewUrl;
      setTimeout(openPreview, 20000);
    } else {
      openPreview();
    }
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function updateTotals(section) {
    if (!section) { return; }
    const table = section.querySelector('table');
    if (!table) { return; }
    let total = 0;
    table.querySelectorAll('[data-item-row]').forEach(row => {
      const qtyInput = row.querySelector('[data-qty]');
      const unitInput = row.querySelector('[data-unit]');
      const discInput = row.querySelector('[data-discount]');
      const qty = parseInt(qtyInput ? qtyInput.value : '0', 10) || 0;
      const unit = parseCurrency(unitInput ? unitInput.value : '0');
      const disc = parsePercent(discInput ? discInput.value : '0');
      const lineTotal = qty * unit * (1 - (disc / 100));
      total += lineTotal;
      const lineEl = row.querySelector('[data-line-total]');
      if (lineEl) {
        lineEl.textContent = formatCurrency(lineTotal);
      }
    });
    const totalLabel = section.querySelector('[data-total-label]');
    if (totalLabel) {
      totalLabel.textContent = formatCurrency(total);
    }
  }

  function addRow(section) {
    const table = section.querySelector('table');
    if (!table) { return; }
    const select = section.querySelector('[data-equip-select]');
    const option = select ? select.options[select.selectedIndex] : null;
    if (!option || !option.value) {
      alert('Selecione um item do estoque primeiro.');
      return;
    }
    const tipo = section.getAttribute('data-tipo');
    const tbody = table.querySelector('tbody');
    const nextIndex = parseInt(table.dataset.nextIndex || '0', 10);
    const equipId = option.value;
    if (tbody.querySelector(`[data-equip-id="${equipId}"]`)) {
      alert('Este item já foi adicionado.');
      return;
    }
    const equipName = option.dataset.name || option.textContent || 'Item';
    const equipDesc = option.dataset.description || '';
    const stockQty = option.dataset.quantity || '0';
    const unitPrice = parseFloat(option.dataset.price || '0') || 0;
    const row = document.createElement('tr');
    row.dataset.itemRow = 'true';
    row.dataset.equipId = equipId;
    row.innerHTML = `
      <td>
        <div class="fw-semibold">${escapeHtml(equipName)}</div>
        ${equipDesc ? `<div class="small text-muted">${escapeHtml(equipDesc)}</div>` : ''}
        <div class="small text-muted"><span class="equip-stock-tag">Estoque: ${escapeHtml(stockQty)}</span></div>
        <input type="hidden" name="equip_${tipo}_${nextIndex}" value="${escapeHtml(equipId)}">
        <input type="hidden" name="desc_${tipo}_${nextIndex}" value="${escapeHtml(equipDesc)}">
      </td>
      <td class="text-center">
        <input type="number" min="0" step="1" class="form-control form-control-sm" name="qty_${tipo}_${nextIndex}" value="1" data-qty>
      </td>
      <td class="text-center">
        <input type="text" class="form-control form-control-sm" name="unit_${tipo}_${nextIndex}" value="${formatCurrency(unitPrice)}" data-unit>
      </td>
      <td class="text-center">
        <input type="number" min="0" step="0.01" class="form-control form-control-sm" name="disc_${tipo}_${nextIndex}" value="0" data-discount>
      </td>
      <td class="text-center">
        <span class="fw-semibold" data-line-total>R$ 0,00</span>
      </td>
      <td class="text-center">
        <button type="button" class="btn btn-link text-danger p-0" data-remove-row>Remover</button>
      </td>
    `;
    tbody.appendChild(row);
    table.dataset.nextIndex = nextIndex + 1;
    if (select) {
      select.value = '';
    }
    updateTotals(section);
  }

  function addRowWithData(section, item) {
    if (!section || !item) { return; }
    const table = section.querySelector('table');
    if (!table) { return; }
    const tbody = table.querySelector('tbody');
    if (!tbody) { return; }
    const tipo = section.getAttribute('data-tipo');
    const nextIndex = parseInt(table.dataset.nextIndex || '0', 10);
    const select = section.querySelector('[data-equip-select]');
    const equipId = String(item.equipment_id || item.equip_id || '');
    if (!equipId) { return; }
    if (tbody.querySelector(`[data-equip-id="${equipId}"]`)) { return; }
    const option = select ? select.querySelector(`option[value="${equipId}"]`) : null;
    const equipName = (option && (option.dataset.name || option.textContent)) || item.description || 'Item';
    const equipDesc = item.description || (option ? option.dataset.description : '') || '';
    const stockQty = option ? (option.dataset.quantity || '0') : '0';
    const unitPrice = Number(item.unit_price) || parseFloat(option?.dataset?.price || '0') || 0;
    const discount = Number(item.discount_percent) || 0;
    const quantity = Number(item.quantity) || 0;
    const row = document.createElement('tr');
    row.dataset.itemRow = 'true';
    row.dataset.equipId = equipId;
    row.innerHTML = `
      <td>
        <div class="fw-semibold">${escapeHtml(equipName)}</div>
        ${equipDesc ? `<div class="small text-muted">${escapeHtml(equipDesc)}</div>` : ''}
        <div class="small text-muted"><span class="equip-stock-tag">Estoque: ${escapeHtml(stockQty)}</span></div>
        <input type="hidden" name="equip_${tipo}_${nextIndex}" value="${escapeHtml(equipId)}">
        <input type="hidden" name="desc_${tipo}_${nextIndex}" value="${escapeHtml(equipDesc)}">
      </td>
      <td class="text-center">
        <input type="number" min="0" step="1" class="form-control form-control-sm" name="qty_${tipo}_${nextIndex}" value="${quantity}" data-qty>
      </td>
      <td class="text-center">
        <input type="text" class="form-control form-control-sm" name="unit_${tipo}_${nextIndex}" value="${formatCurrency(unitPrice)}" data-unit>
      </td>
      <td class="text-center">
        <input type="number" min="0" step="0.01" class="form-control form-control-sm" name="disc_${tipo}_${nextIndex}" value="${formatPercent(discount)}" data-discount>
      </td>
      <td class="text-center">
        <span class="fw-semibold" data-line-total>R$ 0,00</span>
      </td>
      <td class="text-center">
        <button type="button" class="btn btn-link text-danger p-0" data-remove-row>Remover</button>
      </td>
    `;
    tbody.appendChild(row);
    table.dataset.nextIndex = nextIndex + 1;
    updateTotals(section);
  }

  function applySnapshotToSections(tipo, snapshot) {
    if (!tipo || !snapshot) { return; }
    const conditionsSection = document.querySelector(`[data-orcamento-conditions][data-tipo="${tipo}"]`);
    const modalSection = configModal ? configModal.querySelector(`.orc-modal-fields[data-tipo="${tipo}"]`) : null;
    const condicoes = Array.isArray(snapshot.condicoes) ? snapshot.condicoes : [];
    condicoes.forEach((pair, idx) => {
      const value = Array.isArray(pair) ? pair[1] : (pair?.value || pair);
      if (conditionsSection) {
        const target = conditionsSection.querySelector(`[data-cond-index="${idx}"]`);
        if (target) target.textContent = value || '-';
      }
      if (modalSection) {
        const input = modalSection.querySelector(`[data-cond-index="${idx}"]`);
        if (input) input.value = value || '';
      }
    });
    const observacao = snapshot.observacao || '';
    if (conditionsSection) {
      const obsTarget = conditionsSection.querySelector('[data-observacao]');
      if (obsTarget) obsTarget.textContent = observacao || '-';
    }
    if (modalSection) {
      const obsInput = modalSection.querySelector(`textarea[name="observacao_${tipo}"]`);
      if (obsInput) obsInput.value = observacao || '';
    }
    const aceite = Array.isArray(snapshot.aceite) ? snapshot.aceite : [];
    if (conditionsSection) {
      const aceiteTarget = conditionsSection.querySelector('[data-aceite]');
      if (aceiteTarget) {
        aceiteTarget.innerHTML = '';
        if (aceite.length) {
          aceite.forEach(line => {
            const span = document.createElement('span');
            span.textContent = `- ${line}`;
            aceiteTarget.appendChild(span);
          });
        } else {
          const span = document.createElement('span');
          span.textContent = '-';
          aceiteTarget.appendChild(span);
        }
      }
    }
    if (modalSection) {
      const aceiteInput = modalSection.querySelector(`textarea[name="aceite_${tipo}"]`);
      if (aceiteInput) {
        aceiteInput.value = aceite.join('\\n');
      }
    }
  }

  function updateSubmitLabel(hasEdit) {
    if (!submitLabel) { return; }
    submitLabel.textContent = hasEdit ? 'Salvar alterações' : 'Gerar orçamento';
  }

  function clearAllRows() {
    itemSections.forEach((section) => {
      const table = section.querySelector('table');
      const tbody = table ? table.querySelector('tbody') : null;
      if (tbody) {
        tbody.innerHTML = '';
      }
      if (table) {
        table.dataset.nextIndex = '0';
      }
    });
  }

  function bindSection(section) {
    if (!section || section.dataset.bound === 'true') { return; }
    section.dataset.bound = 'true';
    const table = section.querySelector('table');
    const addBtn = section.querySelector('[data-add-row]');
    if (table) {
      table.addEventListener('input', evt => {
        if (evt.target && (evt.target.matches('[data-qty]') || evt.target.matches('[data-unit]') || evt.target.matches('[data-discount]'))) {
          updateTotals(section);
        }
      });
      table.addEventListener('blur', evt => {
        if (!evt.target) { return; }
        if (evt.target.matches('[data-unit]')) {
          const value = parseCurrency(evt.target.value);
          evt.target.value = formatCurrency(value);
        }
        if (evt.target.matches('[data-discount]')) {
          const value = parsePercent(evt.target.value);
          evt.target.value = formatPercent(value);
        }
      }, true);
      table.addEventListener('click', evt => {
        const btn = evt.target.closest('[data-remove-row]');
        if (!btn) { return; }
        const row = btn.closest('[data-item-row]');
        if (row) {
          row.remove();
          updateTotals(section);
        }
      });
    }
    if (addBtn) {
      addBtn.addEventListener('click', () => addRow(section));
    }
    updateTotals(section);
  }

  function updateModalFields(selected) {
    if (!configModal) { return; }
    configModal.querySelectorAll('.orc-modal-fields').forEach(section => {
      const isActive = section.getAttribute('data-tipo') === selected;
      section.classList.toggle('active', isActive);
    });
  }

  function updateSummaryFromModal(selected) {
    if (!configModal || !selected) { return; }
    const modalSection = configModal.querySelector(`.orc-modal-fields[data-tipo="${selected}"]`);
    const conditionsSection = document.querySelector(`[data-orcamento-conditions][data-tipo="${selected}"]`);
    if (!modalSection || !conditionsSection) { return; }

    modalSection.querySelectorAll('[data-cond-index]').forEach(input => {
      const idx = input.getAttribute('data-cond-index');
      const target = conditionsSection.querySelector(`[data-cond-index="${idx}"]`);
      if (target) {
        target.textContent = input.value || '-';
      }
    });

    const obsInput = modalSection.querySelector(`textarea[name="observacao_${selected}"]`);
    const obsTarget = conditionsSection.querySelector('[data-observacao]');
    if (obsTarget) {
      obsTarget.textContent = (obsInput && obsInput.value.trim()) ? obsInput.value.trim() : '-';
    }

    const aceiteInput = modalSection.querySelector(`textarea[name="aceite_${selected}"]`);
    const aceiteTarget = conditionsSection.querySelector('[data-aceite]');
    if (aceiteTarget) {
      const lines = (aceiteInput ? aceiteInput.value.split('\\n') : []).map(line => line.trim()).filter(Boolean);
      aceiteTarget.innerHTML = '';
      if (lines.length) {
        lines.forEach(line => {
          const span = document.createElement('span');
          span.textContent = `- ${line}`;
          aceiteTarget.appendChild(span);
        });
      } else {
        const span = document.createElement('span');
        span.textContent = '-';
        aceiteTarget.appendChild(span);
      }
    }

  }

  function updateVisible() {
    const selected = tipoSelect ? tipoSelect.value : '';
    itemSections.forEach(section => {
      const isActive = section.getAttribute('data-tipo') === selected;
      section.classList.toggle('active', isActive);
      if (isActive) {
        bindSection(section);
        updateTotals(section);
      }
    });
    conditionSections.forEach(section => {
      const isActive = section.getAttribute('data-tipo') === selected;
      section.classList.toggle('active', isActive);
    });
    updateModalFields(selected);
  }

  function updateOsDetails() {
    if (!osSelect || !osDetails) { return; }
    const selectedOption = osSelect.options[osSelect.selectedIndex];
    const manualDetails = document.getElementById('manual-details');
    if (!selectedOption || !selectedOption.value) {
      osDetails.style.display = 'none';
      if (manualDetails) {
        manualDetails.style.display = 'block';
      }
      osDetails.querySelectorAll('[data-field]').forEach(el => { el.textContent = '-'; });
      updateBudgetNumberFromManualFilial();
      return;
    }
    if (manualDetails) {
      manualDetails.style.display = 'none';
    }
    osDetails.style.display = 'block';
    const fields = ['empresa','cnpj','os','unidade','departamento','tecnico','data','descricao'];
    fields.forEach(field => {
      const target = osDetails.querySelector(`[data-field="${field}"]`);
      if (!target) { return; }
      target.textContent = selectedOption.dataset[field] || '-';
    });

    const osUnidade = selectedOption.dataset.unidade || '';
    fetchBudgetNumber(osUnidade);
  }

  if (tipoSelect) {
    tipoSelect.addEventListener('change', updateVisible);
  }
  if (configModal) {
    configModal.addEventListener('show.bs.modal', () => {
      const selected = tipoSelect ? tipoSelect.value : '';
      updateModalFields(selected);
    });
  }
  if (applyConfigBtn) {
    applyConfigBtn.addEventListener('click', () => {
      const selected = tipoSelect ? tipoSelect.value : '';
      updateSummaryFromModal(selected);
    });
  }
  if (osSelect) {
    osSelect.addEventListener('change', updateOsDetails);
  }
  if (manualUnidadeSelect) {
    manualUnidadeSelect.addEventListener('change', () => {
      fetchBudgetNumber(manualUnidadeSelect.value);
    });
  }
  if (formEl) {
    formEl.addEventListener('submit', async (event) => {
      event.preventDefault();
      showLoadingModal();
      try {
        const response = await fetch(formEl.action || window.location.href, {
          method: 'POST',
          body: new FormData(formEl),
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
          credentials: 'same-origin',
        });
        let payload = null;
        try {
          payload = await response.json();
        } catch (jsonError) {
          payload = null;
        }
        if (!response.ok || !payload || !payload.ok) {
          await hideLoadingModal();
          alert((payload && payload.message) || 'Falha ao gerar o orçamento.');
          return;
        }
        showPdfModal(
          payload.view_url || payload.download_url,
          payload.download_url || payload.view_url,
          payload.download_name || 'orcamento.pdf',
          payload.history_url,
          payload.open_url
        );
      } catch (error) {
        console.error(error);
        await hideLoadingModal();
        alert('Falha ao gerar o orçamento.');
      }
    });
  }
  if (pdfPrintBtn) {
    pdfPrintBtn.addEventListener('click', () => {
      const targetWindow = pdfFrame && pdfFrame.contentWindow;
      if (targetWindow) {
        targetWindow.focus();
        targetWindow.print();
      }
    });
  }

  // --- PDF Download interceptor ("Salvar Como") ---
  if (pdfDownloadBtn) {
    pdfDownloadBtn.addEventListener('click', async (event) => {
      if (window.showSaveFilePicker) {
        event.preventDefault();
        const downloadUrl = pdfDownloadBtn.href;
        const downloadName = pdfDownloadBtn.getAttribute('download') || 'orcamento.pdf';

        const originalHtml = pdfDownloadBtn.innerHTML;
        pdfDownloadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Preparando...';
        pdfDownloadBtn.classList.add('disabled');

        try {
          const response = await fetch(downloadUrl);
          if (!response.ok) throw new Error('Falha ao baixar o arquivo PDF.');
          const blob = await response.blob();

          const handle = await window.showSaveFilePicker({
            suggestedName: downloadName,
            types: [{
              description: 'Documento PDF',
              accept: {
                'application/pdf': ['.pdf'],
              },
            }],
          });
          const writable = await handle.createWritable();
          await writable.write(blob);
          await writable.close();
        } catch (err) {
          console.error(err);
          // If the user cancelled, err.name is 'AbortError'. We only fallback if it's NOT an AbortError.
          if (err.name !== 'AbortError') {
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = downloadName;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
          }
        } finally {
          pdfDownloadBtn.innerHTML = originalHtml;
          pdfDownloadBtn.classList.remove('disabled');
        }
      }
    });
  }

  // --- OS Search Modal logic ---
  const modalPesquisaOS = document.getElementById('modalPesquisaOS');
  const inputBuscaOS = document.getElementById('inputBuscaOS');
  const tabelaBuscaOSBody = document.querySelector('#tabelaBuscaOS tbody');
  let osList = [];

  function buildOSList() {
    if (!osSelect) return;
    osList = [];
    Array.from(osSelect.options).forEach(opt => {
      if (!opt.value) return; // skip placeholder
      osList.push({
        id: opt.value,
        os: opt.dataset.os || '',
        empresa: opt.dataset.empresa || '',
        unidade: opt.dataset.unidade || '',
        tecnico: opt.dataset.tecnico || '',
        data: opt.dataset.data || '',
        text: opt.textContent
      });
    });
  }

  function renderOSList(filterText = '') {
    if (!tabelaBuscaOSBody) return;
    tabelaBuscaOSBody.innerHTML = '';
    const cleanFilter = filterText.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

    const filtered = osList.filter(item => {
      if (!cleanFilter) return true;
      const osMatch = item.os.toLowerCase().includes(cleanFilter);
      const empresaMatch = item.empresa.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').includes(cleanFilter);
      const unidadeMatch = item.unidade.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').includes(cleanFilter);
      return osMatch || empresaMatch || unidadeMatch;
    });

    if (filtered.length === 0) {
      tabelaBuscaOSBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">Nenhuma OS encontrada.</td></tr>`;
      return;
    }

    filtered.forEach(item => {
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.innerHTML = `
        <td class="fw-bold text-primary">OS ${item.os}</td>
        <td>${escapeHtml(item.empresa)}</td>
        <td>${escapeHtml(item.unidade)}</td>
        <td>${escapeHtml(item.tecnico || '-')}</td>
        <td>${escapeHtml(item.data || '-')}</td>
        <td class="text-end">
          <button type="button" class="btn btn-primary btn-sm py-1 px-3">Selecionar</button>
        </td>
      `;
      tr.addEventListener('click', () => {
        osSelect.value = item.id;
        osSelect.dispatchEvent(new Event('change'));
        if (window.bootstrap && modalPesquisaOS) {
          const m = window.bootstrap.Modal.getInstance(modalPesquisaOS);
          if (m) m.hide();
        }
      });
      tabelaBuscaOSBody.appendChild(tr);
    });
  }

  if (modalPesquisaOS) {
    modalPesquisaOS.addEventListener('show.bs.modal', () => {
      buildOSList();
      if (inputBuscaOS) inputBuscaOS.value = '';
      renderOSList();
    });
  }

  if (inputBuscaOS) {
    inputBuscaOS.addEventListener('input', (e) => {
      renderOSList(e.target.value);
    });
  }

  // --- Items Search Modal logic ---
  const modalPesquisaItem = document.getElementById('modalPesquisaItem');
  const inputBuscaItem = document.getElementById('inputBuscaItem');
  const tabelaBuscaItemBody = document.querySelector('#tabelaBuscaItem tbody');
  let itemList = [];
  let currentActiveSelect = null;
  let currentActiveSection = null;

  function buildItemList(selectEl) {
    itemList = [];
    currentActiveSelect = selectEl;
    if (!selectEl) return;
    Array.from(selectEl.options).forEach(opt => {
      if (!opt.value) return; // skip placeholder
      itemList.push({
        id: opt.value,
        name: opt.dataset.name || '',
        description: opt.dataset.description || '',
        price: parseFloat(opt.dataset.price) || 0,
        quantity: parseInt(opt.dataset.quantity, 10) || 0,
        text: opt.textContent
      });
    });
  }

  function renderItemList(filterText = '') {
    if (!tabelaBuscaItemBody) return;
    tabelaBuscaItemBody.innerHTML = '';
    const cleanFilter = filterText.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

    const filtered = itemList.filter(item => {
      if (!cleanFilter) return true;
      const nameMatch = item.name.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').includes(cleanFilter);
      const descMatch = item.description.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').includes(cleanFilter);
      return nameMatch || descMatch;
    });

    if (filtered.length === 0) {
      tabelaBuscaItemBody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-3">Nenhum item encontrado.</td></tr>`;
      return;
    }

    filtered.forEach(item => {
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.innerHTML = `
        <td class="fw-semibold">${escapeHtml(item.name)}</td>
        <td class="text-muted small">${escapeHtml(item.description)}</td>
        <td class="text-center"><span class="badge bg-light text-dark border">${item.quantity}</span></td>
        <td class="text-center fw-medium">${formatCurrency(item.price)}</td>
        <td class="text-end">
          <button type="button" class="btn btn-primary btn-sm py-1 px-3">Adicionar</button>
        </td>
      `;
      tr.addEventListener('click', () => {
        if (currentActiveSelect && currentActiveSection) {
          currentActiveSelect.value = item.id;
          addRow(currentActiveSection);
        }
        if (window.bootstrap && modalPesquisaItem) {
          const m = window.bootstrap.Modal.getInstance(modalPesquisaItem);
          if (m) m.hide();
        }
      });
      tabelaBuscaItemBody.appendChild(tr);
    });
  }

  if (modalPesquisaItem) {
    modalPesquisaItem.addEventListener('show.bs.modal', (event) => {
      const btn = event.relatedTarget;
      if (!btn) return;
      const section = btn.closest('[data-orcamento-section]');
      if (!section) return;
      const select = section.querySelector('[data-equip-select]');
      currentActiveSection = section;
      buildItemList(select);
      if (inputBuscaItem) inputBuscaItem.value = '';
      renderItemList();
    });
  }

  if (inputBuscaItem) {
    inputBuscaItem.addEventListener('input', (e) => {
      renderItemList(e.target.value);
    });
  }

  updateVisible();
  updateOsDetails();

  function applyOrcamentoData(data) {
    if (!data) { return; }
    if (orcamentoIdInput) {
      orcamentoIdInput.value = data.id ? String(data.id) : '';
    }
    if (numOrcamentoInput && data.snapshot && data.snapshot.numero_proposta) {
      numOrcamentoInput.value = data.snapshot.numero_proposta;
    }
    updateSubmitLabel(!!data.id);
    if (tipoSelect && data.tipo) {
      tipoSelect.value = data.tipo;
    }
    if (osSelect && data.tarefa_id) {
      osSelect.value = String(data.tarefa_id);
    } else if (osSelect) {
      osSelect.value = '';
    }
    clearAllRows();
    updateVisible();
    updateOsDetails();

    // Populate manual details fields if there is no tarefa_id and we have a snapshot
    if (!data.tarefa_id && data.snapshot) {
      const snap = data.snapshot;
      const mEmpresa = document.getElementById('manual_empresa');
      const mCnpj = document.getElementById('manual_cnpj');
      const mEmail = document.getElementById('manual_email');
      const mOs = document.getElementById('manual_os');
      const mUnidade = document.getElementById('manual_unidade');
      const mTecnico = document.getElementById('manual_tecnico');
      const mDept = document.getElementById('manual_departamento');
      const mDesc = document.getElementById('manual_descricao');
      const mClientName = document.getElementById('manual_client_name');
      const mTelefone = document.getElementById('manual_telefone');

      // Resolve document type radio checking based on the stored CNPJ/CPF digits length
      const cleanDoc = (snap.cnpj || '').replace(/\D/g, '');
      const docType = cleanDoc.length === 11 ? 'cpf' : 'cnpj';
      docTypeInputs.forEach(radio => {
        radio.checked = radio.value === docType;
        const label = radio.nextElementSibling;
        if (label) {
          label.classList.toggle('active', radio.checked);
        }
      });
      updateDocumentUI();

      if (mEmpresa) mEmpresa.value = snap.empresa || '';
      if (mCnpj) mCnpj.value = docType === 'cnpj' ? maskCNPJ(snap.cnpj || '') : maskCPF(snap.cnpj || '');
      if (mClientName) mClientName.value = snap.client_name || '';
      if (mEmail) mEmail.value = snap.email || '';
      if (mTelefone) mTelefone.value = maskPhone(snap.telefone || '');
      if (mOs) mOs.value = snap.os || '';
      if (mUnidade) mUnidade.value = snap.unidade || '';
      if (mTecnico) {
        const techVal = (snap.tecnico === 'Sem técnico' || snap.tecnico === 'N/A' || !snap.tecnico) ? '' : snap.tecnico;
        mTecnico.value = techVal;
      }
      if (mDept) {
        const deptVal = (snap.departamento === 'N/A' || !snap.departamento) ? 'ASSISTENCIA TECNICA' : snap.departamento;
        mDept.value = deptVal;
      }
      if (mDesc) mDesc.value = snap.descricao || '';
    }

    const activeSection = document.querySelector(`[data-orcamento-section][data-tipo="${data.tipo}"]`);
    const items = Array.isArray(data.itens) ? data.itens : [];
    if (activeSection) {
      items.forEach((item) => addRowWithData(activeSection, item));
    }
    applySnapshotToSections(data.tipo, data.snapshot || {});
  }

  window.applyOrcamentoData = applyOrcamentoData;

  const initialOrcamento = window.initialOrcamento || null;
  if (initialOrcamento) {
    applyOrcamentoData(initialOrcamento);
  } else {
    updateSubmitLabel(false);
  }
})();
