(() => {
  const modalEl = document.getElementById('modalEditarRecibo');
  const modalInstance = modalEl && window.bootstrap ? window.bootstrap.Modal.getOrCreateInstance(modalEl) : null;
  const loadingModalEl = document.getElementById('reciboGerandoModal');
  const loadingModal = loadingModalEl && window.bootstrap
    ? window.bootstrap.Modal.getOrCreateInstance(loadingModalEl)
    : null;
  const progressBar = document.getElementById('reciboGerandoProgress');
  const pdfModalEl = document.getElementById('reciboPdfModal');
  const pdfModal = pdfModalEl && window.bootstrap ? window.bootstrap.Modal.getOrCreateInstance(pdfModalEl) : null;
  const pdfFrame = document.getElementById('reciboPdfFrame');
  const pdfDownloadBtn = document.getElementById('reciboPdfDownloadBtn');
  const pdfPrintBtn = document.getElementById('reciboPdfPrintBtn');
  const pdfOpenBtn = document.getElementById('reciboPdfOpenBtn');

  const secureFetch = typeof window.csrfFetch === 'function'
    ? window.csrfFetch
    : (resource, options = {}) => fetch(resource, options);

  const notify = (message, type = 'info') => {
    if (typeof window.showFlash === 'function') {
      window.showFlash(message, type);
      return;
    }
    alert(message);
  };

  function toggleUploadTargets() {
    document.querySelectorAll('.js-toggle-upload').forEach((btn) => {
      btn.addEventListener('click', () => {
        const target = document.querySelector(btn.dataset.target || '');
        if (target) target.classList.toggle('d-none');
      });
    });
  }

  async function fetchRecibo(id) {
    const res = await secureFetch(`/cracha/recibos/${id}/json`);
    return res.json();
  }

  function setEditField(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value ?? '';
  }

  function showAdminPassword(isSigned) {
    const group = document.getElementById('editar_admin_password_group');
    const input = document.getElementById('editar_admin_password');
    if (!group || !input) return;
    if (isSigned) {
      group.classList.remove('d-none');
      input.required = true;
    } else {
      group.classList.add('d-none');
      input.required = false;
      input.value = '';
    }
  }

  async function openEditById(id) {
    if (!id) return;
    const data = await fetchRecibo(id);
    if (!data.success) {
      alert(data.message || 'Erro ao buscar recibo.');
      return;
    }
    const row = data.data || {};
    setEditField('editar_id', row.id);
    setEditField('editar_numeroRecibo', row.numero_recibo);
    setEditField('editar_cnpj', row.cnpj);
    setEditField('editar_cliente', row.cliente);
    setEditField('editar_unidade', row.unidade);
    setEditField('editar_endereco', row.endereco);
    setEditField('editar_totalEmEstoque', row.quantidade_anterior);
    setEditField('editar_quantidadeEntregue', row.quantidade_entregue);
    setEditField('editar_tipo_cracha', row.tipo_cracha);
    setEditField('editar_pedido', row.pedido);
    setEditField('editar_dataPedido', row.data_pedido);
    setEditField('editar_descricao', row.descricao);
    showAdminPassword(Boolean(row.is_signed));
    modalInstance?.show();
  }

  async function handleEditClick(event) {
    const btn = event.currentTarget;
    const id = btn.dataset.id;
    await openEditById(id);
  }

  async function handleDeleteClick(event) {
    const btn = event.currentTarget;
    const id = btn.dataset.id;
    const numero = btn.dataset.numero || '';
    if (!id) return;
    if (!confirm(`Deseja excluir o recibo ${numero}? Essa a\u00e7\u00e3o n\u00e3o pode ser desfeita.`)) return;

    const body = new URLSearchParams({ id });
    const res = await secureFetch('/cracha/recibos/excluir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body
    });
    const data = await res.json();
    if (data.success) {
      window.location.reload();
      return;
    }
    alert(data.message || 'Erro ao excluir recibo.');
  }

  async function lookupCnpj(cnpjInputEl, suffix = '') {
    const rawVal = cnpjInputEl.value;
    if (!rawVal) return;
    const cleanCnpj = rawVal.replace(/\D/g, '');
    // Padroniza o valor digitado no input removendo toda pontuação em tempo real
    cnpjInputEl.value = cleanCnpj;

    const res = await fetch(`/cracha/recibos/consultar-estoque?cnpj=${encodeURIComponent(cleanCnpj)}`);
    if (!res.ok) {
      return;
    }
    const data = await res.json();
    if (!data.success) {
      alert(data.message || 'CNPJ não encontrado.');
      return;
    }
    setEditField(suffix ? `editar_cliente` : 'cliente', data.nome_empresa);
    setEditField(suffix ? `editar_unidade` : 'unidade', data.unidade);
    setEditField(suffix ? `editar_totalEmEstoque` : 'totalEmEstoque', data.total_estoque);
  }

  async function lookupCep(cep, targetId) {
    const clean = (cep || '').replace(/\D/g, '');
    if (clean.length !== 8) return;
    const res = await fetch(`https://viacep.com.br/ws/${clean}/json/`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.erro) {
      alert('CEP n\u00e3o encontrado.');
      return;
    }
    const target = document.getElementById(targetId);
    if (target) {
      target.value = `${data.logradouro || ''}, ${data.bairro || ''}, ${data.localidade || ''} - ${data.uf || ''}`.replace(/^[, ]+|[, ]+$/g, '');
    }
  }

  document.querySelectorAll('.js-edit-recibo').forEach((btn) => {
    btn.addEventListener('click', handleEditClick);
  });

  document.querySelectorAll('.js-delete-recibo').forEach((btn) => {
    btn.addEventListener('click', handleDeleteClick);
  });

  document.querySelectorAll('.js-recibo-row').forEach((row) => {
    row.addEventListener('click', (event) => {
      const target = event.target;
      if (target.closest('button, a, input, select, textarea, label, form')) {
        return;
      }
      const id = row.dataset.id;
      openEditById(id);
    });
  });

  const cnpjInput = document.getElementById('cnpj');
  if (cnpjInput) {
    cnpjInput.addEventListener('change', () => lookupCnpj(cnpjInput, ''));
  }

  const cnpjEditInput = document.getElementById('editar_cnpj');
  if (cnpjEditInput) {
    cnpjEditInput.addEventListener('change', () => lookupCnpj(cnpjEditInput, 'editar'));
  }

  const cepInput = document.getElementById('cep');
  if (cepInput) {
    cepInput.addEventListener('change', () => lookupCep(cepInput.value, 'endereco'));
  }

  const cepEditInput = document.getElementById('editar_cep');
  if (cepEditInput) {
    cepEditInput.addEventListener('change', () => lookupCep(cepEditInput.value, 'editar_endereco'));
  }

  let pdfObjectUrl = null;
  let pdfFrameReady = false;
  let progressTimer = null;

  if (pdfFrame) {
    pdfFrame.addEventListener('load', () => {
      pdfFrameReady = true;
    });
  }

  if (pdfModalEl) {
    pdfModalEl.addEventListener('hidden.bs.modal', () => {
      if (pdfFrame) {
        pdfFrame.src = 'about:blank';
      }
      if (pdfObjectUrl) {
        URL.revokeObjectURL(pdfObjectUrl);
        pdfObjectUrl = null;
      }
    });
  }

  if (pdfPrintBtn) {
    pdfPrintBtn.addEventListener('click', () => {
      if (pdfFrame && pdfFrame.contentWindow && pdfFrameReady) {
        pdfFrame.contentWindow.focus();
        pdfFrame.contentWindow.print();
        return;
      }
      if (pdfObjectUrl) {
        window.open(pdfObjectUrl, '_blank');
      }
    });
  }

  if (pdfOpenBtn) {
    pdfOpenBtn.addEventListener('click', () => {
      if (pdfObjectUrl) {
        window.open(pdfObjectUrl, '_blank');
      }
    });
  }

  function setProgress(value) {
    if (!progressBar) return;
    const clamped = Math.max(0, Math.min(100, value));
    progressBar.style.width = `${clamped}%`;
  }

  function startProgress() {
    let current = 12;
    setProgress(current);
    if (progressTimer) {
      clearInterval(progressTimer);
    }
    progressTimer = setInterval(() => {
      current = Math.min(92, current + Math.random() * 8 + 4);
      setProgress(Math.round(current));
    }, 450);
  }

  function finishProgress() {
    if (progressTimer) {
      clearInterval(progressTimer);
      progressTimer = null;
    }
    setProgress(100);
    setTimeout(() => setProgress(0), 400);
  }

  let printFrame = null;
  let printTimeout = null;
  let printRequestId = null;
  let printListener = null;
  let activePrintButton = null;

  function stopLoading() {
    finishProgress();
    if (loadingModal) {
      setTimeout(() => loadingModal.hide(), 250);
    }
  }

  function cleanupPrintSession() {
    if (printTimeout) {
      clearTimeout(printTimeout);
      printTimeout = null;
    }
    if (printListener) {
      window.removeEventListener('message', printListener);
      printListener = null;
    }
    if (printFrame) {
      printFrame.remove();
      printFrame = null;
    }
    if (activePrintButton) {
      activePrintButton.disabled = false;
      delete activePrintButton.dataset.loading;
      activePrintButton = null;
    }
    printRequestId = null;
  }

  function buildPrintUrl(id, requestId) {
    const params = new URLSearchParams({
      embed: '1',
      auto: '1',
      request_id: requestId,
      t: Date.now().toString()
    });
    return `/cracha/recibos/imprimir/${id}?${params.toString()}`;
  }

  function createPrintFrame(url) {
    const frame = document.createElement('iframe');
    frame.setAttribute('title', 'Geracao do recibo');
    frame.setAttribute('aria-hidden', 'true');
    frame.style.position = 'fixed';
    frame.style.width = '1200px';
    frame.style.height = '1700px';
    frame.style.left = '-1300px';
    frame.style.top = '0';
    frame.style.border = '0';
    frame.style.opacity = '0';
    frame.style.visibility = 'hidden';
    frame.style.pointerEvents = 'none';
    frame.src = url;
    document.body.appendChild(frame);
    return frame;
  }

  function dataUrlToBlob(dataUrl) {
    if (!dataUrl || typeof dataUrl !== 'string') return null;
    const parts = dataUrl.split(',');
    if (parts.length < 2) return null;
    const header = parts[0];
    const mimeMatch = header.match(/data:(.*?);base64/);
    const mime = mimeMatch ? mimeMatch[1] : 'application/pdf';
    const binary = atob(parts[1]);
    const len = binary.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return new Blob([bytes], { type: mime });
  }

  function showPdfModal(url, filename) {
    if (pdfObjectUrl) {
      URL.revokeObjectURL(pdfObjectUrl);
    }
    pdfObjectUrl = url;
    pdfFrameReady = false;
    if (pdfFrame) {
      pdfFrame.src = url;
    }
    if (pdfDownloadBtn) {
      pdfDownloadBtn.href = url;
      pdfDownloadBtn.setAttribute('download', filename || 'recibo.pdf');
    }
    if (pdfModal) {
      pdfModal.show();
    } else {
      window.open(url, '_blank');
    }
  }

  function handlePrintMessage(event) {
    if (event.origin !== window.location.origin) return;
    const payload = event.data || {};
    if (payload.type !== 'recibo-pdf') return;
    if (printRequestId && payload.request_id && payload.request_id !== printRequestId) {
      return;
    }
    cleanupPrintSession();
    stopLoading();
    if (!payload.success) {
      notify(payload.message || 'Erro ao gerar recibo.', 'danger');
      return;
    }
    let blob = null;
    if (payload.buffer instanceof ArrayBuffer) {
      blob = new Blob([payload.buffer], { type: 'application/pdf' });
    } else if (payload.data_url) {
      blob = dataUrlToBlob(payload.data_url);
    }
    if (!blob) {
      notify('N\u00e3o foi poss\u00edvel montar o PDF gerado.', 'danger');
      return;
    }
    const url = URL.createObjectURL(blob);
    const filename = payload.filename || 'recibo.pdf';
    showPdfModal(url, filename);
  }

  async function handlePrintClick(event) {
    const btn = event.currentTarget;
    const id = btn.dataset.id;
    if (!id) return;
    if (btn.dataset.loading === '1') return;
    cleanupPrintSession();
    btn.dataset.loading = '1';
    btn.disabled = true;
    activePrintButton = btn;
    if (loadingModal) {
      loadingModal.show();
    }
    startProgress();
    printRequestId = `recibo-${id}-${Date.now()}`;
    printListener = handlePrintMessage;
    window.addEventListener('message', printListener);
    printTimeout = setTimeout(() => {
      cleanupPrintSession();
      stopLoading();
      notify('Tempo excedido ao gerar o recibo.', 'danger');
    }, 25000);
    const url = buildPrintUrl(id, printRequestId);
    printFrame = createPrintFrame(url);
  }

  document.querySelectorAll('.js-recibo-print').forEach((btn) => {
    btn.addEventListener('click', handlePrintClick);
  });

  toggleUploadTargets();
})();
