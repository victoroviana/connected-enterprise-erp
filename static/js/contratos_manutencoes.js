(() => {
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
        inputEl.setCustomValidity(inputEl.required ? 'Selecione um cliente valido.' : '');
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
        inputEl.setCustomValidity(inputEl.required ? 'Selecione um cliente valido.' : '');
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

    const form = inputEl.closest('form');
    if (form) {
      form.addEventListener('submit', (event) => {
        if (inputEl.required && !selectEl.value) {
          inputEl.setCustomValidity('Selecione um cliente valido.');
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

  document.querySelectorAll('[data-select-target]').forEach(setupSelectSearch);

  const actionSelect = document.getElementById('acao');
  const bloco1 = document.getElementById('acao_1');
  const bloco2 = document.getElementById('acao_2');

  function toggleBlocos() {
    if (!actionSelect) return;
    const val = actionSelect.value;
    if (bloco1) bloco1.style.display = val === '1' ? '' : 'none';
    if (bloco2) bloco2.style.display = val === '2' ? '' : 'none';
  }

  if (actionSelect) {
    actionSelect.addEventListener('change', toggleBlocos);
    toggleBlocos();
  } else {
    if (bloco1) bloco1.style.display = '';
  }

  const clienteSelect = document.getElementById('selCliente');
  const contratoSelect = document.getElementById('selNumeroContratos');
  const localidadeSelect = document.getElementById('selLocalidade');

  async function loadContratos(clienteId) {
    if (!contratoSelect) return;
    contratoSelect.innerHTML = '<option value=""></option>';
    if (localidadeSelect) {
      localidadeSelect.innerHTML = '<option value=""></option>';
    }
    if (!clienteId) return;
    try {
      const res = await fetch(`/contratos/manutencoes-agendadas/contratos/${clienteId}`);
      if (!res.ok) return;
      const data = await res.json();
      data.forEach((row) => {
        const opt = document.createElement('option');
        opt.value = row.id;
        opt.textContent = row.contrato_numero || '';
        contratoSelect.appendChild(opt);
      });
      const selected = contratoSelect.dataset.selected;
      if (selected) {
        contratoSelect.value = selected;
        await loadLocalidades(selected);
      }
    } catch (err) {
      console.error('Falha ao carregar contratos', err);
    }
  }

  async function loadLocalidades(contratoId) {
    if (!localidadeSelect) return;
    localidadeSelect.innerHTML = '<option value=""></option>';
    if (!contratoId) return;
    try {
      const res = await fetch(`/contratos/manutencoes-agendadas/localidades/${contratoId}`);
      if (!res.ok) return;
      const data = await res.json();
      data.forEach((row) => {
        const opt = document.createElement('option');
        opt.value = row.id;
        opt.textContent = row.localidade || '';
        localidadeSelect.appendChild(opt);
      });
      const selected = localidadeSelect.dataset.selected;
      if (selected) {
        localidadeSelect.value = selected;
      }
    } catch (err) {
      console.error('Falha ao carregar localidades', err);
    }
  }

  if (clienteSelect) {
    clienteSelect.addEventListener('change', () => loadContratos(clienteSelect.value));
    if (clienteSelect.value) {
      loadContratos(clienteSelect.value);
    }
  }
  if (contratoSelect) {
    contratoSelect.addEventListener('change', () => loadLocalidades(contratoSelect.value));
  }

  const modalEl = document.getElementById('modalNovaManutencao');
  if (modalEl) {
    modalEl.addEventListener('show.bs.modal', async (event) => {
      const button = event.relatedTarget;
      const id = button ? button.dataset.id : null;
      const form = modalEl.querySelector('form');
      const titleEl = modalEl.querySelector('.modal-title');
      const acaoBlock = document.getElementById('acao') ? document.getElementById('acao').closest('.col-md-6') : null;

      if (id) {
        // Edit mode
        if (titleEl) titleEl.textContent = 'Editar agendamento';
        if (form) form.action = `/contratos/manutencoes-agendadas/${id}/editar`;
        if (acaoBlock) acaoBlock.style.display = 'none';

        try {
          const res = await fetch(`/contratos/manutencoes-agendadas/${id}/editar?format=json`);
          if (res.ok) {
            const data = await res.json();

            // Set hidden ID input
            const idInput = form.querySelector('[name="txtID"]');
            if (idInput) idInput.value = data.id_pk;

            // Set client select & sync search-select text input
            const cSelect = document.getElementById('selCliente');
            const cInput = document.querySelector('[data-select-target="selCliente"]');
            if (cSelect) {
              cSelect.value = data.idclientes_fk || '';
              const selectedOpt = cSelect.options[cSelect.selectedIndex];
              if (cInput) {
                cInput.value = selectedOpt ? selectedOpt.textContent : '';
              }
            }

            // Store selected values as dataset on the selects
            const ctSelect = document.getElementById('selNumeroContratos');
            if (ctSelect) ctSelect.dataset.selected = data.contrato_id || '';

            const lcSelect = document.getElementById('selLocalidade');
            if (lcSelect) lcSelect.dataset.selected = data.idcontrato_localidade_equipamento_fk || '';

            // Trigger change on client select to trigger cascade loading of contracts and localities
            if (cSelect) {
              cSelect.dispatchEvent(new Event('change', { bubbles: true }));
            }

            // Set acao value to '1' (Cadastrar ficha)
            const acSelect = document.getElementById('acao');
            if (acSelect) {
              acSelect.value = '1';
              acSelect.dispatchEvent(new Event('change', { bubbles: true }));
            }
            const acaoInput = form.querySelector('[name="acao"]');
            if (acaoInput) acaoInput.value = '1';

            // Other fields
            const dataAtendimentoInput = form.querySelector('[name="txtDataAtendimento"]');
            if (dataAtendimentoInput) dataAtendimentoInput.value = data.data_inicio_br || '';

            const tecnicoSelect = form.querySelector('[name="selUsuarios"]');
            if (tecnicoSelect) tecnicoSelect.value = data.idusuarios_fk || '';

            const dataVisitaInput = form.querySelector('[name="txtDataVisita"]');
            if (dataVisitaInput) dataVisitaInput.value = data.data_visita_br || '';

            const horaEntradaInput = form.querySelector('[name="txtHoraEntrada"]');
            if (horaEntradaInput) horaEntradaInput.value = data.hora_entrada || '';

            const horaSaidaInput = form.querySelector('[name="txtHoraSaida"]');
            if (horaSaidaInput) horaSaidaInput.value = data.hora_saida || '';
          }
        } catch (err) {
          console.error('Erro ao buscar dados do agendamento', err);
        }
      } else {
        // New mode
        if (titleEl) titleEl.textContent = 'Novo agendamento';
        if (form) form.action = '/contratos/manutencoes-agendadas/novo';
        if (acaoBlock) acaoBlock.style.display = '';

        const idInput = form.querySelector('[name="txtID"]');
        if (idInput) idInput.value = '';

        const cSelect = document.getElementById('selCliente');
        const cInput = document.querySelector('[data-select-target="selCliente"]');
        if (cSelect) cSelect.value = '';
        if (cInput) cInput.value = '';

        const ctSelect = document.getElementById('selNumeroContratos');
        if (ctSelect) {
          ctSelect.dataset.selected = '';
          ctSelect.innerHTML = '<option value=""></option>';
        }

        const lcSelect = document.getElementById('selLocalidade');
        if (lcSelect) {
          lcSelect.dataset.selected = '';
          lcSelect.innerHTML = '<option value=""></option>';
        }

        // Reset acao value
        const acSelect = document.getElementById('acao');
        if (acSelect) {
          acSelect.value = '1';
          acSelect.dispatchEvent(new Event('change', { bubbles: true }));
        }

        const dataAtendimentoInput = form.querySelector('[name="txtDataAtendimento"]');
        if (dataAtendimentoInput) dataAtendimentoInput.value = '';

        const tecnicoSelect = form.querySelector('[name="selUsuarios"]');
        if (tecnicoSelect) tecnicoSelect.value = '';

        const dataVisitaInput = form.querySelector('[name="txtDataVisita"]');
        if (dataVisitaInput) dataVisitaInput.value = '';

        const horaEntradaInput = form.querySelector('[name="txtHoraEntrada"]');
        if (horaEntradaInput) horaEntradaInput.value = '';

        const horaSaidaInput = form.querySelector('[name="txtHoraSaida"]');
        if (horaSaidaInput) horaSaidaInput.value = '';
      }
    });
  }

  const fichaForm = document.getElementById('formFichas');
  if (fichaForm) {
    fichaForm.addEventListener('submit', (event) => {
      const anyChecked = fichaForm.querySelector('input[type="checkbox"][name="ficha"]:checked');
      if (!anyChecked) {
        event.preventDefault();
        alert('Selecione pelo menos uma ficha.');
      }
    });
  }
})();
