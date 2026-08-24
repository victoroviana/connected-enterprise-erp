(() => {
  const formEdicao = document.getElementById('formEdicaoUsuario');
  const formNovo = document.getElementById('formNovoUsuario');
  const permissionInputs = formEdicao ? Array.from(formEdicao.querySelectorAll('input[name="permisses"]')) : [];
  const selectSearchMap = new Map();
  const departmentTagSelects = new Map();

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
  }

  function selectedValues(selectEl) {
    return Array.from(selectEl.selectedOptions || []).map((option) => option.value);
  }

  function renderDepartmentTags(selectEl) {
    const wrapper = departmentTagSelects.get(selectEl);
    if (!wrapper) return;
    const selected = new Set(selectedValues(selectEl));
    wrapper.innerHTML = '';
    Array.from(selectEl.options || []).forEach((option) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `department-tag${selected.has(option.value) ? ' is-selected' : ''}`;
      btn.textContent = option.textContent || '';
      btn.dataset.value = option.value;
      btn.setAttribute('aria-pressed', selected.has(option.value) ? 'true' : 'false');
      wrapper.appendChild(btn);
    });
  }

  function refreshDepartmentTags(selectEl) {
    if (!selectEl) return;
    renderDepartmentTags(selectEl);
  }

  function setupDepartmentTagSelect(selectEl) {
    if (!selectEl || departmentTagSelects.has(selectEl)) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'department-tag-select';
    selectEl.insertAdjacentElement('afterend', wrapper);
    departmentTagSelects.set(selectEl, wrapper);

    wrapper.addEventListener('click', (event) => {
      const btn = event.target.closest('.department-tag');
      if (!btn) return;
      const option = Array.from(selectEl.options || []).find((item) => item.value === btn.dataset.value);
      if (!option) return;

      if (option.value === '0') {
        Array.from(selectEl.options || []).forEach((item) => {
          item.selected = item === option ? !option.selected : false;
        });
      } else {
        option.selected = !option.selected;
        const noneOption = Array.from(selectEl.options || []).find((item) => item.value === '0');
        if (noneOption) noneOption.selected = false;
      }

      selectEl.dispatchEvent(new Event('change', { bubbles: true }));
    });

    selectEl.addEventListener('change', () => renderDepartmentTags(selectEl));
    renderDepartmentTags(selectEl);
  }

  const buildPhoneEntry = (value = '') => {
    const div = document.createElement('div');
    div.className = 'input-group input-group-sm mb-2 phone-extra-entry';
    div.innerHTML = `
      <input type="text" class="form-control" name="extra_phones[]" placeholder="(00) 00000-0000">
      <button type="button" class="btn btn-outline-danger" data-remove-phone title="Remover telefone">
        <i class="bi bi-x-lg"></i>
      </button>
    `;
    const input = div.querySelector('input');
    if (input) input.value = value || '';
    return div;
  };

  function initPhoneManagers(root = document) {
    root.querySelectorAll('[data-phone-manager]').forEach((wrapper) => {
      const list = wrapper.querySelector('[data-phone-list]');
      const addBtn = wrapper.querySelector('[data-add-phone]');

      if (list && !list.querySelector('.phone-extra-entry')) {
        list.appendChild(buildPhoneEntry());
      }

      addBtn?.addEventListener('click', () => {
        list?.appendChild(buildPhoneEntry());
      });

      list?.addEventListener('click', (event) => {
        const btn = event.target.closest('[data-remove-phone]');
        if (!btn) return;
        const row = btn.closest('.phone-extra-entry');
        row?.remove();
        if (list && !list.querySelector('.phone-extra-entry')) {
          list.appendChild(buildPhoneEntry());
        }
      });
    });
  }

  function resetAvatarPreview() {
    const avatarImg = document.getElementById('edit_avatar_preview');
    const avatarCaption = document.getElementById('edit_avatar_caption');
    if (avatarImg) {
      const placeholder = avatarImg.dataset.placeholder || '';
      avatarImg.src = placeholder;
      if (avatarCaption) {
        avatarCaption.textContent = 'Sem foto cadastrada';
      }
    }
  }

  function aplicarPermissoes(perms) {
    permissionInputs.forEach(input => {
      input.checked = !!perms[input.value];
    });
  }

  function abrirModalEdicaoUsuario(id) {
    const modalElement = document.getElementById('modalEdicaoUsuario');
    const modalInstance = window.bootstrap ? window.bootstrap.Modal.getOrCreateInstance(modalElement) : null;
    resetAvatarPreview();
    permissionInputs.forEach(input => { input.checked = false; });

    csrfFetch(`/auth/editar_usuario/${id}`)
      .then(res => res.json())
      .then(data => {
        if (data.error) { alert(data.error); return; }
        document.getElementById('usuario_id').value         = data.id;
        document.getElementById('edit_usuario').value       = data.usuario || '';
        document.getElementById('edit_nome_completo').value = data.nome_completo || '';
        document.getElementById('edit_email').value         = data.email || '';
        document.getElementById('edit_tipo').value          = data.tipo || '';
        document.getElementById('edit_prox_num').value      = data.prox_num || '';
        const editPhone = document.getElementById('edit_phone');
        if(editPhone){ editPhone.value = data.phone || ''; }
        const editRamal = document.getElementById('edit_ramal');
        if(editRamal){ editRamal.value = data.ramal || ''; }
        const editDept = document.getElementById('edit_department_ids');
        if(editDept){
          const deptIds = Array.isArray(data.department_ids) ? data.department_ids.map(String) : [];
          const hasSelection = deptIds.length > 0;
          Array.from(editDept.options || []).forEach((option) => {
            option.selected = deptIds.includes(option.value);
          });
          if (!hasSelection) {
            const fallback = Array.from(editDept.options || []).find((opt) => opt.value === '0');
            if (fallback) {
              fallback.selected = true;
            }
          }
          refreshDepartmentTags(editDept);
        }
        const editUnit = document.getElementById('edit_unit_code');
        if(editUnit){
          const fallbackUnit = editUnit.dataset?.defaultUnit || '';
          editUnit.value = data.unit_code || fallbackUnit;
        }
        const editActive = document.getElementById('edit_is_active');
        if(editActive){
          editActive.checked = Boolean(data.is_active);
        }
        document.getElementById('edit_senha').value         = '';

        // Telefones adicionais
        const phoneWrapper = document.getElementById('editExtraPhones');
        const phoneList = phoneWrapper ? phoneWrapper.querySelector('[data-phone-list]') : null;
        if (phoneList) {
          phoneList.innerHTML = '';
          const extras = Array.isArray(data.extra_phones) && data.extra_phones.length ? data.extra_phones : [''];
          extras.forEach((val) => phoneList.appendChild(buildPhoneEntry(val)));
        }

        aplicarPermissoes(data.permissions || {});

        const avatarImg = document.getElementById('edit_avatar_preview');
        const avatarCaption = document.getElementById('edit_avatar_caption');
        if (avatarImg) {
          if (data.avatar_url) {
            avatarImg.src = `${data.avatar_url}?t=${Date.now()}`;
            if (avatarCaption) {
              avatarCaption.textContent = 'Foto cadastrada';
            }
          } else {
            resetAvatarPreview();
          }
        }

        modalInstance?.show();
      });
  }

  if(formEdicao){
    ensureFormCsrf?.(formEdicao);
    formEdicao.addEventListener('submit', function (event) {
      event.preventDefault();
      const id = document.getElementById('usuario_id').value;
      const body = new URLSearchParams(new FormData(formEdicao));
      csrfFetch(`/auth/editar_usuario/${id}`, {
        method : 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) location.reload();
        else alert('Erro ao salvar alterações.');
      });
    });
  }

  if(formNovo){
    ensureFormCsrf?.(formNovo);
  }

  document.addEventListener('click', (event) => {
    selectSearchMap.forEach(({ wrapper }) => {
      if (!wrapper.contains(event.target)) {
        wrapper.classList.remove('is-open');
      }
    });
  });

  document.querySelectorAll('[data-select-target]').forEach(setupSelectSearch);
  document.querySelectorAll('select[data-tag-select]').forEach(setupDepartmentTagSelect);

  window.abrirModalEdicaoUsuario = abrirModalEdicaoUsuario;
  initPhoneManagers();
})();
