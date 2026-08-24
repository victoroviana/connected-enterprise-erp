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

  const modalInstance = (id) => {
    const el = document.getElementById(id);
    if (!el || typeof bootstrap === 'undefined') {
      return null;
    }
    return bootstrap.Modal.getOrCreateInstance(el);
  };

  const openModal = (id) => {
    const modal = modalInstance(id);
    if (modal) {
      modal.show();
    }
  };

  let confirmModalInstance = null;
  const confirmTitle = document.getElementById('confirmFinanceActionTitle');
  const confirmMessage = document.getElementById('confirmFinanceActionMessage');
  const confirmButton = document.getElementById('confirmFinanceActionBtn');
  let pendingFinanceAction = null;

  const confirmFinanceAction = ({ title, message, onConfirm }) => {
    const modal = modalInstance('confirmFinanceActionModal');
    const button = document.getElementById('confirmFinanceActionBtn');
    const titleEl = document.getElementById('confirmFinanceActionTitle');
    const messageEl = document.getElementById('confirmFinanceActionMessage');
    if (!modal || !button) {
      return onConfirm();
    }
    if (titleEl) titleEl.textContent = title || 'Confirmação';
    if (messageEl) messageEl.textContent = message || 'Deseja prosseguir?';
    pendingFinanceAction = () => {
      onConfirm();
      pendingFinanceAction = null;
    };
    modal.show();
    confirmModalInstance = modal;
  };

  const handleConfirmClick = () => {
    if (pendingFinanceAction) {
      pendingFinanceAction();
    }
    if (confirmModalInstance) {
      confirmModalInstance.hide();
    }
  };

  document.getElementById('confirmFinanceActionBtn')?.addEventListener('click', handleConfirmClick);

  const formatDateTime = () => {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(now.getDate())}/${pad(now.getMonth() + 1)}/${now.getFullYear()} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  };

  const parseNumber = (value) => {
    if (!value) return 0;
    const raw = String(value).replace(/[^\d,-]/g, '').replace(/\./g, '').replace(',', '.');
    const parsed = parseFloat(raw);
    return Number.isNaN(parsed) ? 0 : parsed;
  };

  const formatBR = (value) => {
    try {
      return new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value || 0);
    } catch (e) {
      return (value || 0).toFixed(2).replace('.', ',');
    }
  };

  const setCurrencyInput = (input, value) => {
    if (!input) return;
    const parsed = parseNumber(value);
    if (Number.isNaN(parsed)) {
      input.value = value || '';
      return;
    }
    input.value = formatBR(parsed);
  };

  const table = document.querySelector('table.finance-table');
  const isCancelados = table && table.dataset.pageMode === 'cancelados';
  if (!isCancelados) {
    document.querySelectorAll('tr[data-dias-atraso]').forEach((row) => {
      const dias = parseInt(row.dataset.diasAtraso || '0', 10);
      if (dias > 89) {
        row.classList.add('blink-danger');
      } else if (dias > 59) {
        row.classList.add('blink-warning');
      }
    });
  }

  const cnpjInput = document.getElementById('cadastro-cnpj');
  if (cnpjInput) {
    cnpjInput.addEventListener('blur', async () => {
      const cnpj = cnpjInput.value.replace(/\D+/g, '');
      if (!cnpj) return;
      try {
        const response = await fetch(`/financeiro/verifica-empresa?cnpj=${encodeURIComponent(cnpj)}`);
        const text = await response.text();
        const clienteInput = document.getElementById('cadastro-cliente');
        if (clienteInput && text) {
          clienteInput.value = text;
        }
      } catch (err) {
        console.error('Falha ao verificar CNPJ', err);
      }
    });
  }

  document.querySelectorAll('.js-add-subpendencia').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.getElementById('sub-id-pai').value = btn.dataset.id || '';
      document.getElementById('sub-cliente').value = btn.dataset.cliente || '';
      document.getElementById('sub-cnpj').value = btn.dataset.cnpj || '';
      document.getElementById('sub-contrato').value = btn.dataset.contrato || '';
      document.getElementById('sub-software').value = btn.dataset.software || '';
      document.getElementById('sub-data-pendencia').value = '';
      document.getElementById('sub-valor').value = '';
      document.getElementById('sub-informacoes').value = '';
      openModal('modalSubpendencia');
    });
  });

  document.querySelectorAll('.js-subpendencias').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const cliente = btn.dataset.cliente || '';
      const tbody = document.getElementById('subpendencias-tbody');
      const title = document.getElementById('subpendencias-cliente');
      if (!tbody || !id) return;
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-3">Carregando...</td></tr>';
      if (title) {
        title.textContent = cliente;
      }
      openModal('modalSubpendenciasLista');
      try {
        const response = await csrfFetch('/financeiro/contas-receber/subpendencias', {
          method: 'POST',
          body: toFormData({ id_pai: id })
        });
        const data = await response.json();
        if (!data.ok || !data.items.length) {
          tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-3">Nenhuma subpendência encontrada.</td></tr>';
          return;
        }
        tbody.innerHTML = data.items.map((item) => {
          return `
            <tr>
              <td>${item.cliente || ''}</td>
              <td>${item.cnpj || ''}</td>
              <td>${item.contrato || ''}</td>
              <td>${item.empresa_responsavel || '-'}</td>
              <td>${item.software || ''}</td>
              <td>${item.data_primeira_pendencia_br || ''}</td>
              <td>R$ ${item.valor_display || '0,00'}</td>
              <td>
                <button type="button" class="btn btn-sm btn-outline-primary js-edit-sub"
                  data-id="${item.id}" data-cliente="${item.cliente || ''}" data-cnpj="${item.cnpj || ''}"
                  data-contrato="${item.contrato || ''}" data-unidade="${item.empresa_responsavel || ''}"
                  data-software="${item.software || ''}" data-data-pendencia="${item.data_primeira_pendencia || ''}"
                  data-qt-pendencias="${item.qt_pendencias || 1}" data-valor="${item.valor || 0}">
                  Editar
                </button>
              </td>
            </tr>`;
        }).join('');
      } catch (err) {
        console.error(err);
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-3">Erro ao carregar subpendências.</td></tr>';
      }
    });
  });

  document.addEventListener('click', (event) => {
    const btn = event.target.closest('.js-edit-sub');
    if (!btn) return;
    document.getElementById('edit-sub-id').value = btn.dataset.id || '';
    document.getElementById('edit-sub-cliente').value = btn.dataset.cliente || '';
    document.getElementById('edit-sub-cnpj').value = btn.dataset.cnpj || '';
    document.getElementById('edit-sub-contrato').value = btn.dataset.contrato || '';
    document.getElementById('edit-sub-unidade').value = btn.dataset.unidade || '';
    document.getElementById('edit-sub-software').value = btn.dataset.software || '';
    document.getElementById('edit-sub-data').value = btn.dataset.dataPendencia || '';
    document.getElementById('edit-sub-qt').value = btn.dataset.qtPendencias || 1;
    setCurrencyInput(document.getElementById('edit-sub-valor'), btn.dataset.valor || '');
    openModal('modalEditarSubConta');
  });

  document.querySelectorAll('.js-edit-conta').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.getElementById('edit-id').value = btn.dataset.id || '';
      document.getElementById('edit-cliente').value = btn.dataset.cliente || '';
      document.getElementById('edit-cnpj').value = btn.dataset.cnpj || '';
      document.getElementById('edit-contrato').value = btn.dataset.contrato || '';
      document.getElementById('edit-unidade').value = btn.dataset.unidade || '';
      document.getElementById('edit-software').value = btn.dataset.software || '';
      document.getElementById('edit-data-pendencia').value = btn.dataset.dataPendencia || '';
      document.getElementById('edit-qt-pendencias').value = btn.dataset.qtPendencias || 1;
      setCurrencyInput(document.getElementById('edit-valor'), btn.dataset.valor || '');
      openModal('modalEditarConta');
    });
  });

  document.querySelectorAll('.js-add-valor').forEach((btn) => {
    btn.addEventListener('click', () => {
      const valorAtual = parseNumber(btn.dataset.valor || '0');
      document.getElementById('valor-id').value = btn.dataset.id || '';
      document.getElementById('valor-atual').value = formatBR(valorAtual);
      document.getElementById('valor-adicionar').value = '';
      openModal('modalAdicionarValor');
    });
  });

  document.querySelectorAll('.js-update-info').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.getElementById('info-id').value = btn.dataset.id || '';
      document.getElementById('info-text').value = '';
      openModal('modalAtualizarInfo');
    });
  });

  const infoForm = document.getElementById('formAtualizarInfo');
  if (infoForm) {
    infoForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const id = document.getElementById('info-id').value;
      const info = document.getElementById('info-text').value.trim();
      if (!id || !info) return;
      try {
        const res = await csrfFetch('/financeiro/contas-receber/update-info', {
          method: 'POST',
          body: toFormData({ id, new_info: info })
        });
          const data = await res.json();
          if (data.ok) {
            location.reload();
            return;
          }
          alert(data.message || 'Não foi possível excluir esta pendência.');
      } catch (err) {
        console.error(err);
      }
    });
  }

  document.querySelectorAll('.js-historico').forEach((btn) => {
    btn.addEventListener('click', async (event) => {
      event.preventDefault();
      const id = btn.dataset.id;
      const target = document.getElementById('historico-content');
      if (!id || !target) return;
      target.innerHTML = '<p class="text-muted">Carregando...</p>';
      openModal('modalHistorico');
      try {
        const res = await csrfFetch('/financeiro/contas-receber/historico', {
          method: 'POST',
          body: toFormData({ id })
        });
        const data = await res.json();
        target.innerHTML = data.html || '<p class="text-muted">Sem histórico.</p>';
      } catch (err) {
        console.error(err);
        target.innerHTML = '<p class="text-danger">Erro ao carregar histórico.</p>';
      }
    });
  });

  document.querySelectorAll('.js-quitar').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      if (!id) return;
      if (!confirm('Confirmar quitação da conta?')) return;
      try {
        const res = await csrfFetch('/financeiro/contas-receber/quitar', {
          method: 'POST',
          body: toFormData({ id })
        });
        const data = await res.json();
        if (data.ok) {
          location.reload();
        }
      } catch (err) {
        console.error(err);
      }
    });
  });

  document.querySelectorAll('.js-bloqueio').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.id;
      if (!id) return;
      confirmFinanceAction({
        title: 'Solicitar bloqueio',
        message: 'Confirma que deseja solicitar o bloqueio desta pendência?',
        onConfirm: async () => {
          try {
            const res = await csrfFetch('/financeiro/contas-receber/solicitar-bloqueio', {
              method: 'POST',
              body: toFormData({ id, data_bloqueio: formatDateTime() })
            });
            const data = await res.json();
            if (data.ok) {
              location.reload();
            } else {
              alert(data.message || 'Não foi possível solicitar bloqueio.');
            }
          } catch (err) {
            console.error(err);
          }
        },
      });
    });
  });

  document.querySelectorAll('.js-cancelamento').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      if (!id) return;
      confirmFinanceAction({
        title: 'Solicitar cancelamento',
        message: 'Confirma que deseja solicitar o cancelamento desta pendência?',
        onConfirm: async () => {
          try {
            const res = await csrfFetch('/financeiro/contas-receber/cancelamento', {
              method: 'POST',
              body: toFormData({ id, cancelamento: formatDateTime() })
            });
            const data = await res.json();
            if (data.ok) {
              location.reload();
            }
          } catch (err) {
            console.error(err);
          }
        },
      });
    });
  });

  document.querySelectorAll('.js-deferimento').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const dias = btn.dataset.dias || '0';
      if (!id) return;
      confirmFinanceAction({
        title: 'Deferir cancelamento',
        message: 'Deseja realmente deferir o cancelamento desta conta?',
        onConfirm: async () => {
          try {
            const res = await csrfFetch('/financeiro/contas-receber/deferimento', {
              method: 'POST',
              body: toFormData({ id, deferimento: formatDateTime(), diasAtraso: dias })
            });
            const data = await res.json();
            if (data.ok) {
              location.reload();
            }
          } catch (err) {
            console.error(err);
          }
        },
      });
    });
  });

  document.querySelectorAll('.js-excluir').forEach((btn) => {
    btn.addEventListener('click', () => {
      const tr = btn.closest('tr');
      const id = btn.dataset.id || tr?.dataset.id;
      if (!id) return;
      confirmFinanceAction({
        title: 'Excluir pendência',
        message: 'Deseja excluir permanentemente esta pendência? Esta ação não pode ser desfeita.',
        onConfirm: async () => {
          try {
            const res = await csrfFetch('/financeiro/contas-receber/excluir', {
              method: 'POST',
              body: toFormData({ id })
            });
            const data = await res.json();
            if (data.ok) {
              location.reload();
            }
          } catch (err) {
            console.error(err);
          }
        },
      });
    });
  });

  const valorForm = document.getElementById('formAdicionarValor');
  if (valorForm) {
    valorForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const id = document.getElementById('valor-id').value;
      const valor = document.getElementById('valor-adicionar').value;
      if (!id || !valor) return;
      try {
        const res = await csrfFetch('/financeiro/contas-receber/valor', {
          method: 'POST',
          body: toFormData({ id, valor: parseNumber(valor) })
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
})();
