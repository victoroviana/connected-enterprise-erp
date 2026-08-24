(() => {
  const getToken = () => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return (meta ? meta.getAttribute('content') : '') || window.csrfToken || '';
  };

  const csrfFetch = (resource, options = {}) => {
    if (typeof window.csrfFetch === 'function') {
      return window.csrfFetch(resource, options);
    }
    const opts = { ...options };
    const method = (opts.method || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') {
      const headers = new Headers(opts.headers || {});
      const token = getToken();
      if (token && !headers.has('X-CSRFToken')) {
        headers.set('X-CSRFToken', token);
      }
      if (!headers.has('X-Requested-With')) {
        headers.set('X-Requested-With', 'XMLHttpRequest');
      }
      opts.headers = headers;
    }
    if (!opts.credentials) {
      opts.credentials = 'same-origin';
    }
    return fetch(resource, opts);
  };

  const toFormData = (payload) => {
    const fd = new FormData();
    Object.entries(payload || {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        fd.append(key, value);
      }
    });
    const token = getToken();
    if (token && !fd.has('csrf_token')) {
      fd.append('csrf_token', token);
    }
    return fd;
  };

  const formatBR = (value) => {
    try {
      return new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value || 0);
    } catch (e) {
      return (value || 0).toFixed(2).replace('.', ',');
    }
  };

  const parseMoney = (value) => {
    if (!value) return 0;
    const raw = String(value).replace(/[^\d,-]/g, '').replace(/\./g, '').replace(',', '.');
    const parsed = parseFloat(raw);
    return Number.isNaN(parsed) ? 0 : parsed;
  };

  const bindMoneyField = (inputId, previewId) => {
    const input = document.getElementById(inputId);
    if (!input) return () => {};
    const preview = document.getElementById(previewId);
    const update = () => {
      const value = parseMoney(input.value);
      if (preview) {
        preview.textContent = `R$ ${formatBR(value)}`;
      }
    };
    input.addEventListener('input', update);
    input.addEventListener('blur', () => {
      const value = parseMoney(input.value);
      input.value = value ? formatBR(value) : '';
      update();
    });
    update();
    return update;
  };

  const setupSelectYears = (select, selectedYear) => {
    if (!select) return;
    const current = new Date().getFullYear();
    const start = current - 4;
    const end = current + 4;
    select.innerHTML = '';
    for (let year = start; year <= end; year += 1) {
      const opt = document.createElement('option');
      opt.value = String(year);
      opt.textContent = String(year);
      if (year === selectedYear) {
        opt.selected = true;
      }
      select.appendChild(opt);
    }
  };

  const setupSelectMonths = (select, selectedMonth) => {
    if (!select) return;
    select.innerHTML = '';
    for (let month = 1; month <= 12; month += 1) {
      const opt = document.createElement('option');
      opt.value = String(month).padStart(2, '0');
      opt.textContent = String(month).padStart(2, '0');
      if (opt.value === selectedMonth) {
        opt.selected = true;
      }
      select.appendChild(opt);
    }
  };

  setupSelectYears(document.getElementById('selectAno'), Number(SELECTED_YEAR));
  setupSelectYears(document.getElementById('selectAnoPDF'), Number(SELECTED_YEAR));
  setupSelectMonths(document.getElementById('selectMesPDF'), String(SELECTED_MONTH));

  const selectedMonth = String(SELECTED_MONTH).padStart(2, '0');
  const selectedYear = String(SELECTED_YEAR);
  bindMoneyField('valorMesInput', 'previewValorMes');
  const updateNovoValor = bindMoneyField('inputNovoValor', 'previewNovoValor');
  const updateNovoValorPago = bindMoneyField('inputNovoValorValorPago', 'previewNovoValorPago');

  const btnConfirmarMes = document.getElementById('btnConfirmarMes');
  if (btnConfirmarMes) {
    btnConfirmarMes.addEventListener('click', () => {
      const mes = document.getElementById('selectMes')?.value || String(SELECTED_MONTH);
      const ano = document.getElementById('selectAno')?.value || String(SELECTED_YEAR);
      if (!mes || !ano) return;
      window.location.href = `/financeiro/cota?filtro=${encodeURIComponent(`${mes}-${ano}`)}`;
    });
  }

  const btnGerarPDF = document.getElementById('btnGerarPDF');
  if (btnGerarPDF) {
    btnGerarPDF.addEventListener('click', () => {
      const mes = document.getElementById('selectMesPDF')?.value || selectedMonth;
      const ano = document.getElementById('selectAnoPDF')?.value || selectedYear;
      if (!mes || !ano) return;
      window.open(`/financeiro/cota/pdf-mensal?mes=${mes}&ano=${ano}`, '_blank');
    });
  }

  const btnEnviarData = document.getElementById('btnEnviarData');
  if (btnEnviarData) {
    btnEnviarData.addEventListener('click', () => {
      const data = document.getElementById('dataSelecionada')?.value;
      if (!data) return;
      window.open(`/financeiro/cota/pdf-trimestre?data_inicial=${data}`, '_blank');
    });
  }

  const btnEnviarEmail = document.getElementById('btnEnviarEmail');
  if (btnEnviarEmail) {
    btnEnviarEmail.addEventListener('click', async () => {
      const tableHtml = document.getElementById('cota-email-table')?.innerHTML || '';
      if (!tableHtml) return;
      try {
        const res = await csrfFetch('/financeiro/cota/enviar-email', {
          method: 'POST',
          body: toFormData({ tabela: tableHtml })
        });
        const data = await res.json();
        if (data.ok) {
          alert('E-mail enviado com sucesso!');
        } else {
          alert('Falha ao enviar e-mail.');
        }
      } catch (err) {
        console.error(err);
        alert('Erro ao enviar e-mail.');
      }
    });
  }

  const modalFecharMes = document.getElementById('modalFecharMes');
  const mesFechamento = document.getElementById('mesFechamento');
  if (modalFecharMes && mesFechamento) {
    modalFecharMes.addEventListener('show.bs.modal', () => {
      mesFechamento.textContent = `${selectedMonth}/${selectedYear}`;
    });
  }

  const btnFecharMes = document.getElementById('btnFecharMes');
  if (btnFecharMes) {
    btnFecharMes.addEventListener('click', async () => {
      try {
        const res = await csrfFetch('/financeiro/cota/fechar-mes', {
          method: 'POST',
          body: toFormData({ filtro: `${selectedMonth}-${selectedYear}` })
        });
        const data = await res.json();
        if (data.ok) {
          location.reload();
        } else {
          alert(data.message || 'Falha ao fechar o mês.');
        }
      } catch (err) {
        console.error(err);
        alert('Erro ao fechar o mês.');
      }
    });
  }

  const showModal = (id) => {
    const el = document.getElementById(id);
    if (!el || typeof bootstrap === 'undefined') return;
    bootstrap.Modal.getOrCreateInstance(el).show();
  };

  document.querySelectorAll('.js-edit-arrecadado').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.getElementById('inputID').value = btn.dataset.id || '';
      document.getElementById('inputValorAtual').value = formatBR(parseMoney(btn.dataset.valor || '0'));
      document.getElementById('inputNovoValor').value = '';
      updateNovoValor();
      showModal('modalAdicionarValor');
    });
  });

  document.querySelectorAll('.js-edit-pago').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.getElementById('inputIDValorPago').value = btn.dataset.id || '';
      document.getElementById('inputValorAtualValorPago').value = formatBR(parseMoney(btn.dataset.valor || '0'));
      document.getElementById('inputNovoValorValorPago').value = '';
      updateNovoValorPago();
      showModal('modalAdicionarValorPago');
    });
  });

  const formValor = document.getElementById('formAdicionarValor');
  if (formValor) {
    formValor.addEventListener('submit', async (event) => {
      event.preventDefault();
      const id = document.getElementById('inputID').value;
      const valor = document.getElementById('inputNovoValor').value;
      const tipo = formValor.querySelector('input[name="tipo"]:checked')?.value || 'adicionar';
      if (!id || !valor) return;
      try {
        const res = await csrfFetch('/financeiro/cota/valor', {
          method: 'POST',
          body: toFormData({ id, valor: parseMoney(valor), tipo })
        });
        const data = await res.json();
        if (data.ok) {
          location.reload();
        }
      } catch (err) {
        console.error(err);
      }
    });
  }

  const formPago = document.getElementById('formAdicionarValorPago');
  if (formPago) {
    formPago.addEventListener('submit', async (event) => {
      event.preventDefault();
      const id = document.getElementById('inputIDValorPago').value;
      const valor = document.getElementById('inputNovoValorValorPago').value;
      const tipo = formPago.querySelector('input[name="tipo"]:checked')?.value || 'adicionar';
      if (!id || !valor) return;
      try {
        const res = await csrfFetch('/financeiro/cota/valor-pago', {
          method: 'POST',
          body: toFormData({ id, valor: parseMoney(valor), tipo })
        });
        const data = await res.json();
        if (data.ok) {
          location.reload();
        }
      } catch (err) {
        console.error(err);
      }
    });
  }

  const drawMensal = () => {
    const container = document.getElementById('chart_div');
    if (!container || typeof google === 'undefined') return;
    const data = new google.visualization.DataTable();
    data.addColumn('string', 'Unidade');
    data.addColumn('number', 'Valor Arrecadado');

    if (!CHART_MENSAL || !CHART_MENSAL.length) {
      data.addRow(['Sem dados', 1]);
    } else {
      CHART_MENSAL.forEach((row) => data.addRow([row[0], row[1]]));
    }

    const chart = new google.visualization.PieChart(container);
    chart.draw(data, {
      title: 'Valor arrecadado por unidade',
      pieHole: 0.45,
      legend: { position: 'right' },
      chartArea: { left: '4%', top: 20, width: '68%', height: '78%' },
      backgroundColor: 'transparent'
    });
  };

  const drawTrimestral = () => {
    const container = document.getElementById('chart_trimestral');
    if (!container || typeof google === 'undefined') return;
    const data = new google.visualization.DataTable();
    data.addColumn('string', 'Mês');
    data.addColumn('number', 'Faturado');
    data.addColumn('number', 'Recebido');

    if (!CHART_TRIMESTRAL || !CHART_TRIMESTRAL.length) {
      data.addRow(['Sem dados', 0, 0]);
    } else {
      CHART_TRIMESTRAL.forEach((row) => data.addRow([row[0], row[1], row[2]]));
    }

    const chart = new google.visualization.ColumnChart(container);
    chart.draw(data, {
      legend: { position: 'bottom' },
      backgroundColor: 'transparent'
    });
  };

  const updateMetaText = () => {
    const el = document.getElementById('faltaParaBaterMeta');
    if (!el) return;
    if (!META_VALOR) {
      el.textContent = 'Meta não definida para este mês.';
      return;
    }
    if (TOTAL_ARRECADADO >= META_VALOR) {
      el.textContent = 'Meta batida!';
    } else {
      const diff = META_VALOR - TOTAL_ARRECADADO;
      el.textContent = `Faltam R$ ${formatBR(diff)} para bater a meta.`;
    }
  };

  if (typeof google !== 'undefined') {
    google.charts.load('current', { packages: ['corechart'] });
    google.charts.setOnLoadCallback(() => {
      drawMensal();
      drawTrimestral();
      updateMetaText();
    });
  }
})();
