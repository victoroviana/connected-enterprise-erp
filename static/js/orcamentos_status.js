(function(){
  function formatCurrencyFromDigits(raw) {
    if (!raw) { return ''; }
    var digits = String(raw).replace(/\D/g, '');
    if (!digits) { return ''; }
    var value = (parseInt(digits, 10) / 100).toFixed(2);
    var parts = value.split('.');
    var integer = parts[0];
    var decimal = parts[1] || '00';
    integer = integer.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return integer + ',' + decimal;
  }

  document.addEventListener('input', function(event) {
    var target = event.target;
    if (!target || !target.matches('[data-currency]')) { return; }
    target.value = formatCurrencyFromDigits(target.value);
  });

  var cnpjInput = document.getElementById('orcamento-cnpj');
  var clienteInput = document.getElementById('orcamento-cliente');
  var feedback = document.getElementById('cnpj-feedback');
  if (!cnpjInput || !clienteInput) { return; }

  function setFeedback(message, isError) {
    if (!feedback) { return; }
    feedback.textContent = message || '';
    feedback.classList.toggle('text-danger', !!isError);
    feedback.classList.toggle('text-muted', !isError);
  }

  cnpjInput.addEventListener('blur', function() {
    var url = cnpjInput.getAttribute('data-cnpj-lookup');
    var value = cnpjInput.value || '';
    var cleaned = value.replace(/\D/g, '');
    if (!url || cleaned.length < 14) {
      setFeedback('');
      return;
    }

    setFeedback('Consultando CNPJ...', false);
    fetch(url + '?cnpj=' + encodeURIComponent(cleaned), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function(response){ return response.json(); })
      .then(function(payload){
        if (payload && payload.cliente) {
          clienteInput.value = payload.cliente;
          setFeedback('Cliente localizado.', false);
          return;
        }
        if (payload && payload.error) {
          setFeedback(payload.error, true);
          return;
        }
        setFeedback('CNPJ não encontrado.', true);
      })
      .catch(function(){
        setFeedback('Erro ao consultar CNPJ.', true);
      });
  });
})();
