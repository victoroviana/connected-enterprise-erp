(() => {
  const modalEl = document.getElementById('modalEditarCliente');
  const modalInstance = modalEl && window.bootstrap ? window.bootstrap.Modal.getOrCreateInstance(modalEl) : null;

  function fillEditModal(data) {
    const idInput = document.getElementById('editar_cliente_id');
    const nomeInput = document.getElementById('editar_cliente_nome');
    const cnpjInput = document.getElementById('editar_cliente_cnpj');
    const qtdInput = document.getElementById('editar_cliente_quantidade');
    if (idInput) idInput.value = data.id || '';
    if (nomeInput) nomeInput.value = data.cliente || '';
    if (cnpjInput) cnpjInput.value = data.cnpj || '';
    if (qtdInput) qtdInput.value = data.quantidade || '';
  }

  document.querySelectorAll('.js-edit-cliente').forEach((btn) => {
    btn.addEventListener('click', () => {
      fillEditModal({
        id: btn.dataset.id,
        cliente: btn.dataset.cliente,
        cnpj: btn.dataset.cnpj,
        quantidade: btn.dataset.quantidade
      });
      modalInstance?.show();
    });
  });

  const cnpjInput = document.getElementById('cliente_cnpj');
  const clienteInput = document.getElementById('cliente_nome');
  if (cnpjInput && clienteInput) {
    cnpjInput.addEventListener('blur', async () => {
      const raw = (cnpjInput.value || '').trim();
      if (!raw) return;
      try {
        const res = await fetch(`/cracha/verifica-empresa?cnpj=${encodeURIComponent(raw)}`);
        if (!res.ok) return;
        const text = (await res.text()).trim();
        if (text && text.toLowerCase() !== 'cnpj n\u00e3o encontrado.') {
          clienteInput.value = text;
        }
      } catch (err) {
        console.error('Falha ao consultar CNPJ', err);
      }
    });
  }
})();
