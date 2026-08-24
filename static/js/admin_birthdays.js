(() => {
  const editModal = document.getElementById('modalEditarAniversariante');
  const editForm = document.getElementById('formEditarAniversariante');
  if (!editModal || !editForm) {
    return;
  }

  editModal.addEventListener('show.bs.modal', (event) => {
    const trigger = event.relatedTarget;
    if (!trigger) {
      return;
    }
    const payload = trigger.getAttribute('data-birthday');
    const targetUrl = trigger.getAttribute('data-update-url');
    if (targetUrl) {
      editForm.setAttribute('action', targetUrl);
    }
    let data;
    try {
      data = JSON.parse(payload || '{}');
    } catch (err) {
      data = {};
    }
    const nameField = editForm.querySelector('[name="nome_exibicao"]');
    if (nameField) {
      nameField.value = data.nome || '';
    }
    const isoDate = (data.data_nascimento || '').slice(0, 10);
    if (isoDate) {
      const parts = isoDate.split('-');
      if (parts.length === 3) {
        const dayVal = parseInt(parts[2], 10);
        const monthVal = parseInt(parts[1], 10);
        const dayField = editForm.querySelector('[name="dia"]');
        const monthField = editForm.querySelector('[name="mes"]');
        if (dayField) dayField.value = dayVal;
        if (monthField) monthField.value = monthVal;
      }
    }
  });
})();
