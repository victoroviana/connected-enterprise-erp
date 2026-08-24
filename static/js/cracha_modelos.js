(() => {
  const secureFetch = typeof window.csrfFetch === 'function'
    ? window.csrfFetch
    : (resource, options = {}) => fetch(resource, options);

  document.querySelectorAll('.js-cracha-approve').forEach((input) => {
    input.addEventListener('change', async () => {
      const id = input.dataset.id;
      if (!id) return;
      const aprovar = input.checked ? '1' : '0';
      input.disabled = true;
      try {
        const body = new URLSearchParams({ id, aprovar });
        const res = await secureFetch('/cracha/modelos/aprovacao-interna', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body
        });
        if (!res.ok) {
          throw new Error('Falha ao atualizar.');
        }
        const data = await res.json();
        if (!data.ok) {
          throw new Error(data.message || 'Erro ao salvar.');
        }
      } catch (err) {
        input.checked = !input.checked;
        alert(err.message || 'Erro ao atualizar aprova\u00e7\u00e3o.');
      } finally {
        input.disabled = false;
      }
    });
  });

  const modalEl = document.getElementById('crachaViewModal');
  const modal = modalEl && window.bootstrap ? new window.bootstrap.Modal(modalEl) : null;
  const fallbackFront = '/static/images/cracha_frente.jpg';
  const fallbackBack = '/static/images/cracha_verso.jpg';

  document.querySelectorAll('.js-cracha-row').forEach((row) => {
    row.addEventListener('click', (event) => {
      const target = event.target;
      if (target && target.closest('a, button, input, label, form')) {
        return;
      }
      if (!modal || !modalEl) return;
      const nome = row.dataset.nome || '-';
      const razao = row.dataset.razao || '-';
      const frente = row.dataset.frente || fallbackFront;
      const verso = row.dataset.verso || fallbackBack;
      const aprovado = row.dataset.aprovado === '1';

      const nomeEl = modalEl.querySelector('[data-field="nome"]');
      const razaoEl = modalEl.querySelector('[data-field="razao"]');
      const frenteEl = modalEl.querySelector('[data-field="frente"]');
      const versoEl = modalEl.querySelector('[data-field="verso"]');
      const statusEl = modalEl.querySelector('[data-field="status"]');

      if (nomeEl) nomeEl.textContent = nome;
      if (razaoEl) razaoEl.textContent = razao;
      if (frenteEl) frenteEl.setAttribute('src', frente || fallbackFront);
      if (versoEl) versoEl.setAttribute('src', verso || fallbackBack);
      if (statusEl) statusEl.textContent = aprovado ? 'Aprovado' : 'Pendente';

      modal.show();
    });
  });
})();
