(() => {
  const formatosModalEl = document.getElementById('modalFormatoImagem');
  const formatosModal = formatosModalEl && window.bootstrap ? window.bootstrap.Modal.getOrCreateInstance(formatosModalEl) : null;
  const csrfTokenValue = window.csrfToken || '';

  function isImagemValida(file) {
    if (!file) return false;
    const validTypes = ['image/png', 'image/jpeg', 'image/jpg'];
    const maxSize = 5 * 1024 * 1024; // 5MB
    return validTypes.includes(file.type) && file.size <= maxSize;
  }

  function validarCampoImagem(input) {
    const file = input?.files?.[0];
    if (!file) {
      return true;
    }
    if (!isImagemValida(file)) {
      if (formatosModal) formatosModal.show();
      input.value = '';
      return false;
    }
    return true;
  }

  function formatarComoMoedaBR(valor) {
    const apenasDigitos = (valor || '').replace(/[^0-9]/g, '');
    if (!apenasDigitos) return '';
    const numero = parseInt(apenasDigitos, 10) / 100;
    return numero.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function aplicarMascaraPreco(campo) {
    if(!campo) return;
    campo.addEventListener('input', function () {
      this.value = formatarComoMoedaBR(this.value);
    });
  }

  function abrirModalEdicao(id) {
    csrfFetch(`/pecas/${id}`)
      .then(res => res.json())
      .then(data => {
        document.getElementById('pecaId').value = data.id;
        document.getElementById('pecaNome').value = data.nome;
        document.getElementById('pecaDescricao').value = data.descricao || '';
        document.getElementById('pecaPreco').value = (parseFloat(data.preco||0))
          .toFixed(2).replace('.',',').replace(/\B(?=(\d{3})+(?!\d))/g,'.');
        document.getElementById('pecaQuantidade').value = data.quantidade;
        const imagemCampo = document.getElementById('pecaImagem');
        if(imagemCampo){ imagemCampo.value = ''; }
        if(window.bootstrap){
          window.bootstrap.Modal.getOrCreateInstance(document.getElementById('modalEdicaoPeca')).show();
        }
      });
  }

  function salvarEdicaoPeca() {
    const id = document.getElementById('pecaId').value;
    const payload = {
      nome: document.getElementById('pecaNome').value,
      descricao: document.getElementById('pecaDescricao').value,
      preco: document.getElementById('pecaPreco').value,
      quantidade: parseInt(document.getElementById('pecaQuantidade').value, 10)
    };

    csrfFetch(`/pecas/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(() => {
      const imagemInput = document.getElementById('pecaImagem');
      const imagem = imagemInput && imagemInput.files ? imagemInput.files[0] : null;
      if (imagem) {
        if(!isImagemValida(imagem)){
          return Promise.resolve();
        }
        const formData = new FormData();
        formData.append('imagem', imagem);
        if(csrfTokenValue){
          formData.append('csrf_token', csrfTokenValue);
        }
        return csrfFetch(`/pecas/${id}/upload_imagem`, { method: 'POST', body: formData });
      }
      return null;
    })
    .finally(() => location.reload());
  }

  function confirmarExclusao(id) {
    document.getElementById('pecaIdParaExcluir').value = id;
    if(window.bootstrap){
      window.bootstrap.Modal.getOrCreateInstance(document.getElementById('modalConfirmarExclusao')).show();
    }
  }

  function excluirPeca() {
    const id = document.getElementById('pecaIdParaExcluir').value;
    csrfFetch(`/pecas/${id}`, { method: 'DELETE' })
      .then(res => res.json())
      .then(data => {
        if (data.success) location.reload();
        else alert('Erro ao excluir peça.');
      });
  }

  document.addEventListener('DOMContentLoaded', function () {
    const createIllustration = document.getElementById('pecaIllustration');
    if(createIllustration){
      createIllustration.addEventListener('change', function(){ validarCampoImagem(this); });
    }
    const editIllustration = document.getElementById('pecaImagem');
    if(editIllustration){
      editIllustration.addEventListener('change', function(){ validarCampoImagem(this); });
    }
    const createForm = document.querySelector('form[enctype="multipart/form-data"]');
    if(createForm){
      ensureFormCsrf?.(createForm);
      createForm.addEventListener('submit', function(evt){
        const input = createForm.querySelector('#pecaIllustration');
        if(input && input.files && input.files[0] && !validarCampoImagem(input)){
          evt.preventDefault();
        }
      });
    }
    const editForm = document.getElementById('formEdicaoPeca');
    if(editForm){
      ensureFormCsrf?.(editForm);
    }
    aplicarMascaraPreco(document.getElementById('precoCadastro'));
    aplicarMascaraPreco(document.getElementById('pecaPreco'));
  });

  window.validarCampoImagem = validarCampoImagem;
  window.abrirModalEdicao = abrirModalEdicao;
  window.salvarEdicaoPeca = salvarEdicaoPeca;
  window.confirmarExclusao = confirmarExclusao;
  window.excluirPeca = excluirPeca;
})();
