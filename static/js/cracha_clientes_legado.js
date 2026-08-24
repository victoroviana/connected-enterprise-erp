(() => {
  const tipoInputs = document.querySelectorAll('input[name="radTipo"]');
  const juridicaFields = document.querySelectorAll('.p-juridica');
  const fisicaFields = document.querySelectorAll('.p-fisica');

  function applyTipo() {
    const selected = document.querySelector('input[name="radTipo"]:checked');
    const tipo = selected ? selected.value : '2';
    juridicaFields.forEach((el) => {
      el.style.display = tipo === '2' ? '' : 'none';
    });
    fisicaFields.forEach((el) => {
      el.style.display = tipo === '1' ? '' : 'none';
    });
  }

  tipoInputs.forEach((input) => input.addEventListener('change', applyTipo));
  applyTipo();
})();
