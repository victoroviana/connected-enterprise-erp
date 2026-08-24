(() => {
  const addButton = document.getElementById('btnAdicionarLinha');
  const container = document.getElementById('feriasPessoaContainer');
  if (addButton && container) {
    addButton.addEventListener('click', () => {
      const template = container.querySelector('[data-ferias-row]');
      if (!template) {
        return;
      }
      const clone = template.cloneNode(true);
      clone.querySelectorAll('input').forEach((input) => {
        input.value = '';
      });
      clone.querySelectorAll('select').forEach((select) => {
        select.selectedIndex = 0;
      });
      container.appendChild(clone);
    });
  }

  const editForm = document.getElementById('formEditarFerias');
  document.querySelectorAll('.js-edit-ferias').forEach((button) => {
    button.addEventListener('click', () => {
      if (!editForm) {
        return;
      }
      const dataset = button.getAttribute('data-ferias');
      let data;
      try {
        data = JSON.parse(dataset || '{}');
      } catch (err) {
        data = {};
      }
      const actionUrl = button.getAttribute('data-update-url');
      if (actionUrl) {
        editForm.setAttribute('action', actionUrl);
      }
      const userField = editForm.querySelector('[name="usuario_id"]');
      if (userField) {
        userField.value = data.user_id || '';
      }
      editForm.querySelector('[name="data_inicial"]').value = data.inicio || '';
      editForm.querySelector('[name="data_final"]').value = data.fim || '';
      const unitDisplay = document.getElementById('editFeriasUnit');
      if (unitDisplay) {
        unitDisplay.value = data.unit_label || '';
      }
    });
  });
})();
