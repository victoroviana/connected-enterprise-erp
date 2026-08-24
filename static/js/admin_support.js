(function(){
  const formatDateTime = (value) => {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return (value || '').slice(0, 16);
    }
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  };

  const formatDisplayDate = (value) => {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value || '—';
    }
    return date.toLocaleString('pt-BR');
  };

  const normalizeRichText = (value = '') => {
    const normalized = (value || '').replace(/<br\s*\/?>/gi, '\n').trim();
    return normalized || '—';
  };

  const handleEditModal = () => {
    const editModal = document.getElementById('modalEditarAtendimento');
    if (!editModal) return;
    editModal.addEventListener('show.bs.modal', (event) => {
      const button = event.relatedTarget;
      if (!button) return;
      const fetchUrl = button.getAttribute('data-fetch-url');
      const updateUrl = button.getAttribute('data-update-url');
      const form = editModal.querySelector('form');
      if (!fetchUrl || !form) return;
      if (updateUrl) {
        form.setAttribute('action', updateUrl);
      }
      fetch(fetchUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then((response) => response.json())
        .then((data) => {
          const idField = form.querySelector('[name="atendimento_id"]');
          if (idField) idField.value = data.id;
          const fieldMap = [
            'cliente','cnpj','tipo_atendimento','status','os_entrada','os_saida','descricao',
            'resumo_atendimento','observacoes','observacoes_alerta','sistema','quantidade_pessoas','texto_mobile','email'
          ];
          fieldMap.forEach((name) => {
            const input = form.querySelector(`[name="${name}"]`);
            if (!input) return;
            input.value = data[name] || '';
          });
          const dataEntrada = form.querySelector('[name="data_entrada"]');
          if (dataEntrada) {
            dataEntrada.value = formatDateTime(data.data_entrada);
          }
          const dataAtendimento = form.querySelector('[name="data_atendimento"]');
          if (dataAtendimento) {
            dataAtendimento.value = formatDateTime(data.data_atendimento);
          }
          const tecnicoField = form.querySelector('[name="usuario_designado"]');
          if (tecnicoField) {
            tecnicoField.value = data.usuario_designado || 0;
          }
        })
        .catch(() => {
          window.alert('Não foi possível carregar os dados do atendimento.');
        });
    });
  };

  const handleCnpjLookup = () => {
    document.querySelectorAll('.js-fetch-cnpj').forEach((button) => {
      button.addEventListener('click', () => {
        const input = button.closest('.input-group').querySelector('input');
        const form = button.closest('form');
        if (!input || !form) return;
        const lookupUrl = input.dataset.cnpjLookupUrl;
        const value = input.value.trim();
        if (!lookupUrl || !value) {
          window.alert('Informe um CNPJ válido.');
          return;
        }
        button.disabled = true;
        fetch(`${lookupUrl}?cnpj=${encodeURIComponent(value)}`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
          .then((response) => response.json())
          .then((payload) => {
            if (payload.error) {
              window.alert(payload.error);
              return;
            }
            if (payload.cliente) {
              const clienteField = form.querySelector('input[name="cliente"]');
              if (clienteField) clienteField.value = payload.cliente;
            }
            if (payload.observacoes) {
              const obsField = form.querySelector('textarea[name="observacoes"]');
              if (obsField) obsField.value = payload.observacoes;
            }
            if (payload.observacoes_alerta) {
              const alertField = form.querySelector('textarea[name="observacoes_alerta"]');
              if (alertField) alertField.value = payload.observacoes_alerta;
            }
            if (payload.email) {
              const emailField = form.querySelector('input[name="email"]') || form.querySelector('input[name="email_responsavel"]');
              if (emailField) emailField.value = payload.email;
            }
          })
          .catch(() => window.alert('Não foi possível consultar o CNPJ.'))
          .finally(() => {
            button.disabled = false;
          });
      });
    });
  };

  const handleLogsModal = () => {
    const modal = document.getElementById('modalLogsAtendimento');
    if (!modal) return;
    const tbody = modal.querySelector('#supportLogsTableBody');
    modal.addEventListener('show.bs.modal', (event) => {
      if (!tbody) return;
      tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Carregando…</td></tr>';
      const button = event.relatedTarget;
      if (!button) return;
      const url = button.getAttribute('data-logs-url');
      if (!url) return;
      fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then((response) => response.json())
        .then((logs) => {
          if (!Array.isArray(logs) || !logs.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Nenhum registro encontrado.</td></tr>';
            return;
          }
          tbody.innerHTML = logs.map((log) => {
            const created = log.created_at ? new Date(log.created_at).toLocaleString('pt-BR') : '-';
            return `<tr><td>${log.campo || ''}</td><td>${log.valor_antigo || ''}</td><td>${log.valor_novo || ''}</td><td>${log.modificado_por || ''}</td><td>${created}</td></tr>`;
          }).join('');
        })
        .catch(() => {
          tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger">Erro ao carregar histórico.</td></tr>';
        });
    });
  };

  const handleChamadoEdit = () => {
    const modal = document.getElementById('modalEditarChamado');
    if (!modal) return;
    modal.addEventListener('show.bs.modal', (event) => {
      const button = event.relatedTarget;
      const form = modal.querySelector('form');
      if (!button || !form) return;
      const entryData = button.getAttribute('data-entry');
      const updateUrl = button.getAttribute('data-update-url');
      if (updateUrl) {
        form.setAttribute('action', updateUrl);
      }
      let data = {};
      try {
        data = JSON.parse(entryData || '{}');
      } catch (err) {
        data = {};
      }
      const fieldMap = ['cliente','bairro','ordem_servico','tipo_atendimento','tecnico','retorno','cnpj','email_responsavel','descricao'];
      fieldMap.forEach((name) => {
        const input = form.querySelector(`[name="${name}"]`);
        if (input) {
          input.value = data[name] || '';
        }
      });
      const regionField = form.querySelector('[name="region"]');
      const regionValue = button.getAttribute('data-region');
      if (regionField && regionValue) {
        regionField.value = regionValue;
      }
      const idField = form.querySelector('[name="chamado_id"]');
      if (idField) {
        idField.value = data.id || '';
      }
      const dataOs = form.querySelector('[name="data_os_criada"]');
      if (dataOs) {
        dataOs.value = (data.data_os_criada || '').slice(0, 10);
      }
      const dataPrevista = form.querySelector('[name="data_prevista"]');
      if (dataPrevista) {
        dataPrevista.value = (data.data || '').slice(0, 10);
      }
    });
  };

  const handleDetailsModal = () => {
    const modalEl = document.getElementById('modalDetalhesAtendimento');
    if (!modalEl || !window.bootstrap) return;
    const modalInstance = window.bootstrap.Modal.getOrCreateInstance(modalEl);
    const interactiveSelectors = 'a,button,input,label,textarea,select,.btn-group,form';

    const setField = (field, value) => {
      const target = modalEl.querySelector(`[data-detail="${field}"]`);
      if (!target) return;
      if (field === 'status') {
        const normalized = (value || '').toLowerCase();
        target.textContent = value || '-';
        target.classList.add('status-pill');
        target.classList.remove('status-pill--entrada', 'status-pill--atencao', 'status-pill--concluido');
        if (normalized.includes('concl')) {
          target.classList.add('status-pill--concluido');
        } else if (normalized.includes('aten')) {
          target.classList.add('status-pill--atencao');
        } else if (normalized.includes('entrada')) {
          target.classList.add('status-pill--entrada');
        }
        return;
      }
      if (field === 'meet_link') {
        const link = value || '-';
        target.innerHTML = '';
        if (!link || link === '-') {
          target.textContent = '-';
          return;
        }
        const anchor = document.createElement('a');
        anchor.href = link;
        anchor.target = '_blank';
        anchor.rel = 'noopener';
        anchor.textContent = link;
        target.appendChild(anchor);
        return;
      }
      const iconEl = target.querySelector('[data-icon]');
      const textEl = target.querySelector('[data-text]');
      if (iconEl || textEl) {
        if (textEl) textEl.textContent = value || '-';
        if (iconEl) {
          // show or hide icon depending on presence of value
          iconEl.style.display = value && value !== '—' ? '' : 'none';
        }
        return;
      }
      target.textContent = value || '—';
    };

    const attachRowListeners = () => {
      document.addEventListener('click', (evt) => {
        const row = evt.target.closest('[data-details-url]');
        if (!row) return;
        if (evt.target.closest(interactiveSelectors)) {
          return;
        }
        modalEl.dataset.fetchUrl = row.getAttribute('data-details-url');
        modalEl.dataset.entryId = row.getAttribute('data-entry-id') || '';
        modalInstance.show();
      });
    };

    modalEl.addEventListener('show.bs.modal', () => {
      const url = modalEl.dataset.fetchUrl;
      if (!url) {
        setField('cliente', 'Não foi possível carregar.');
        return;
      }
      setField('cliente', 'Carregando...');
      fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then((response) => response.json())
        .then((data) => {
          const technician = data.assigned_user_name
            ? `${data.assigned_user_name}${data.assigned_user_unit ? ` · ${data.assigned_user_unit}` : ''}`
            : 'Não atribuído';
          setField('cliente', data.cliente || '—');
          setField('cnpj', data.cnpj || '—');
          setField('tipo_atendimento', data.tipo_atendimento || '—');
          setField('status', data.status_label || data.status || '—');
          setField('data_entrada', formatDisplayDate(data.data_entrada));
          setField('data_atendimento', formatDisplayDate(data.data_atendimento));
          setField('usuario_designado_label', technician);
          setField('os_entrada', data.os_entrada || '—');
          setField('os_saida', data.os_saida || '—');
          setField('sistema', data.sistema || '—');
          setField('quantidade_pessoas', data.quantidade_pessoas || '-');
          setField('email', data.email || '-');
          setField('meet_start', formatDisplayDate(data.meet_start));
          setField('meet_link', data.meet_link || '-');
          setField('texto_mobile', normalizeRichText(data.texto_mobile || '')); 
          setField('observacoes', normalizeRichText(data.observacoes || ''));
          setField('observacoes_alerta', normalizeRichText(data.observacoes_alerta || ''));
          setField('resumo_atendimento', normalizeRichText(data.resumo_atendimento || ''));
          setField('descricao', normalizeRichText(data.descricao || ''));
          setField('criado_por', data.criado_por || '—');
        })
        .catch(() => {
          setField('cliente', 'Não foi possível carregar.');
        });
    });

    const editButton = modalEl.querySelector('[data-action="open-edit"]');
    if (editButton) {
      editButton.addEventListener('click', () => {
        const id = modalEl.dataset.entryId;
        modalInstance.hide();
        if (!id) return;
        const trigger = document.querySelector(`.js-edit-support[data-entry-id="${id}"]`);
        if (trigger) {
          trigger.click();
        }
      });
    }

    attachRowListeners();
  };

  const handleMeetPreview = () => {
    const modal = document.getElementById('modalNovoAtendimento');
    if (!modal) return;
    const form = modal.querySelector('form');
    const button = modal.querySelector('.js-generate-meet');
    const copyButton = modal.querySelector('.js-copy-meet');
    const previewField = modal.querySelector('#meetLinkPreview');
    if (!form || !button || !previewField || !copyButton) return;

    const meetLinkInput = form.querySelector('input[name="meet_link"]');
    const meetEventInput = form.querySelector('input[name="meet_event_id"]');
    const meetStartInput = form.querySelector('input[name="meet_start"]');
    const sessionKeyInput = form.querySelector('input[name="meet_session_key"]');
    const emailInput = form.querySelector('input[name="email"]');
    const extraEmailsInput = form.querySelector('textarea[name="meet_extra_emails"]');
    const tipoInput = form.querySelector('select[name="tipo_atendimento"]');
    const clienteInput = form.querySelector('input[name="cliente"]');
    const osEntradaInput = form.querySelector('input[name="os_entrada"]');
    const secureFetch = typeof window.csrfFetch === 'function' ? window.csrfFetch : fetch;

    const resetGenerateButton = () => {
      button.textContent = 'Gerar link';
      button.disabled = false;
      button.dataset.generated = '0';
    };

    const lockGenerateButton = () => {
      button.textContent = 'Link gerado';
      button.disabled = true;
      button.dataset.generated = '1';
    };

    const clearPreview = () => {
      previewField.value = '';
      if (meetLinkInput) meetLinkInput.value = '';
      if (meetEventInput) meetEventInput.value = '';
      copyButton.disabled = true;
      resetGenerateButton();
    };

    modal.addEventListener('hidden.bs.modal', clearPreview);

    copyButton.addEventListener('click', () => {
      const text = previewField.value || '';
      if (!text) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          window.alert('Link copiado.');
        });
        return;
      }
      previewField.focus();
      previewField.select();
      try {
        document.execCommand('copy');
        window.alert('Link copiado.');
      } catch (err) {
        window.alert('Nao foi possivel copiar o link.');
      }
    });

    button.addEventListener('click', () => {
      if (button.dataset.generated === '1' && previewField.value) {
        return;
      }
      const url = button.getAttribute('data-meet-preview-url');
      if (!url) return;
      if (!meetStartInput || !meetStartInput.value) {
        window.alert('Informe a data e hora da reuniao.');
        if (meetStartInput) meetStartInput.focus();
        return;
      }

      const payload = {
        meet_start: meetStartInput.value,
        meet_session_key: sessionKeyInput ? sessionKeyInput.value : '',
        email: emailInput ? emailInput.value : '',
        meet_extra_emails: extraEmailsInput ? extraEmailsInput.value : '',
        tipo_atendimento: tipoInput ? tipoInput.value : '',
        cliente: clienteInput ? clienteInput.value : '',
        os_entrada: osEntradaInput ? osEntradaInput.value : '',
        meet_link: meetLinkInput ? meetLinkInput.value : '',
        meet_event_id: meetEventInput ? meetEventInput.value : '',
      };

      button.disabled = true;
      const originalText = button.textContent;
      button.textContent = 'Gerando...';

      secureFetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify(payload),
      })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
          if (!ok || !data || data.ok === false) {
            const message = (data && data.message) ? data.message : 'Nao foi possivel gerar o link do Meet.';
            throw new Error(message);
          }
          const link = data.meet_link || '';
          previewField.value = link;
          if (meetLinkInput) meetLinkInput.value = link;
          if (meetEventInput) meetEventInput.value = data.meet_event_id || '';
          copyButton.disabled = !link;
          if (link) {
            lockGenerateButton();
          } else {
            resetGenerateButton();
          }
        })
        .catch((err) => {
          window.alert(err.message || 'Nao foi possivel gerar o link do Meet.');
          clearPreview();
        })
        .finally(() => {
          if (button.dataset.generated !== '1') {
            button.disabled = false;
            button.textContent = originalText;
          }
        });
    });
  };


  const handleAssignModal = () => {
    const modalEl = document.getElementById('modalDesignarTecnico');
    if (!modalEl || !window.bootstrap) return;
    window.bootstrap.Modal.getOrCreateInstance(modalEl);
    const form = modalEl.querySelector('form');
    const select = modalEl.querySelector('select[name="usuario_designado"]');
    modalEl.addEventListener('show.bs.modal', (event) => {
      const trigger = event.relatedTarget;
      if (!trigger || !form) return;
      const entryId = trigger.getAttribute('data-entry-id');
      const hidden = form.querySelector('input[name="atendimento_id"]');
      if (hidden) hidden.value = entryId || '';
      if (select) {
        select.value = trigger.getAttribute('data-current-tech') || '0';
      }
    });
  };

  const initTooltips = () => {
    if (!window.bootstrap) return;
    document.querySelectorAll('[data-tooltip="true"]').forEach((el) => {
      window.bootstrap.Tooltip.getOrCreateInstance(el);
    });
  };

  document.addEventListener('DOMContentLoaded', () => {
    handleEditModal();
    handleCnpjLookup();
    handleLogsModal();
    handleChamadoEdit();
    handleDetailsModal();
    handleMeetPreview();
    handleAssignModal();
    initTooltips();
  });
})();
