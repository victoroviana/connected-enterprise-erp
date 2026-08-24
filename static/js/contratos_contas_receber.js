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

  const clienteSelect = document.getElementById('selCliente');
  const contratoSelect = document.getElementById('selNumeroContratos');
  const clienteEditSelect = document.getElementById('selClienteEdit');
  const contratoEditSelect = document.getElementById('selNumeroContratosEdit');
  const editModal = document.getElementById('modalEditarContaContrato');
  const editForm = editModal ? editModal.querySelector('form') : null;

  async function loadContratos({ clienteId, selectEl, selectedId }) {
    if (!selectEl) return;
    selectEl.innerHTML = '<option value=""></option>';
    if (!clienteId) return;
    try {
      const query = selectedId ? `?selected_id=${encodeURIComponent(selectedId)}` : '';
      const res = await fetch(`/contratos/contas-a-receber/contratos/${clienteId}${query}`);
      if (!res.ok) return;
      const data = await res.json();
      const seen = new Set();
      data.forEach((row) => {
        if (!row || row.id === null) return;
        const numero = (row.contrato_numero || '').toString().trim();
        if (!numero || seen.has(numero)) return;
        seen.add(numero);
        const opt = document.createElement('option');
        opt.value = row.id;
        opt.textContent = numero;
        selectEl.appendChild(opt);
      });
      const selected = selectedId || selectEl.dataset.selected;
      if (selected) {
        selectEl.value = selected;
      }
    } catch (err) {
      console.error('Falha ao carregar contratos', err);
    }
  }

  if (clienteSelect && contratoSelect) {
    clienteSelect.addEventListener('change', () => loadContratos({
      clienteId: clienteSelect.value,
      selectEl: contratoSelect,
    }));
    if (clienteSelect.value) {
      loadContratos({
        clienteId: clienteSelect.value,
        selectEl: contratoSelect,
      });
    }
  }

  if (clienteEditSelect && contratoEditSelect) {
    clienteEditSelect.addEventListener('change', () => loadContratos({
      clienteId: clienteEditSelect.value,
      selectEl: contratoEditSelect,
    }));
  }

  function setFieldValue(form, name, value) {
    if (!form) return;
    const field = form.querySelector(`[name="${name}"]`);
    if (field) {
      field.value = value || '';
    }
  }

  function buildActionUrl(template, contaId) {
    if (!template || !contaId) return template || '';
    return template.replace(/\/0(\/|$)/, `/${contaId}$1`);
  }

  if (editForm && editModal) {
    document.querySelectorAll('.btn-edit-conta').forEach((button) => {
      button.addEventListener('click', async () => {
        const contaId = button.dataset.contaId;
        const clienteId = button.dataset.clienteId || '';
        const contratoId = button.dataset.contratoId || '';
        const vencimento = button.dataset.vencimento || '';
        const valor = button.dataset.valor || '';
        const pagamento = button.dataset.pagamento || '';
        const valorPago = button.dataset.valorPago || '';

        editForm.action = buildActionUrl(editForm.dataset.actionTemplate, contaId);
        setFieldValue(editForm, 'txtID', contaId);
        setFieldValue(editForm, 'txtDataVencimento', vencimento);
        setFieldValue(editForm, 'txtValor', valor);
        setFieldValue(editForm, 'txtDataPagamento', pagamento);
        setFieldValue(editForm, 'txtValorPago', valorPago);

        if (clienteEditSelect) {
          clienteEditSelect.value = clienteId;
          syncSearchInput(clienteEditSelect);
        }
        if (contratoEditSelect) {
          contratoEditSelect.dataset.selected = contratoId;
          await loadContratos({
            clienteId,
            selectEl: contratoEditSelect,
            selectedId: contratoId,
          });
        }

        if (typeof bootstrap !== 'undefined') {
          bootstrap.Modal.getOrCreateInstance(editModal).show();
        }
      });
    });
  }
})();
