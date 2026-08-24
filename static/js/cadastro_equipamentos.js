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
    csrfFetch(`/equipamentos/${id}`)
      .then(res => res.json())
      .then(data => {
        document.getElementById('equipamentoId').value = data.id;
        document.getElementById('equipamentoNome').value = data.nome;
        document.getElementById('equipamentoDescricao').value = data.descricao || '';
        document.getElementById('equipamentoPreco').value = (parseFloat(data.preco||0))
          .toFixed(2).replace('.',',').replace(/\B(?=(\d{3})+(?!\d))/g,'.');
        document.getElementById('equipamentoQuantidade').value = data.quantidade;
        const imagemCampo = document.getElementById('equipamentoImagem');
        if(imagemCampo){ imagemCampo.value = ''; }
        if(window.bootstrap){
          window.bootstrap.Modal.getOrCreateInstance(document.getElementById('modalEdicaoEquipamento')).show();
        }
      });
  }

  function salvarEdicaoEquipamento() {
    const id = document.getElementById('equipamentoId').value;
    const payload = {
      nome: document.getElementById('equipamentoNome').value,
      descricao: document.getElementById('equipamentoDescricao').value,
      preco: document.getElementById('equipamentoPreco').value,
      quantidade: parseInt(document.getElementById('equipamentoQuantidade').value, 10)
    };

    csrfFetch(`/equipamentos/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(() => {
      const imagemInput = document.getElementById('equipamentoImagem');
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
        return csrfFetch(`/equipamentos/${id}/upload_imagem`, { method: 'POST', body: formData });
      }
      return null;
    })
    .finally(() => location.reload());
  }

  function confirmarExclusao(id) {
    document.getElementById('equipamentoIdParaExcluir').value = id;
    if(window.bootstrap){
      window.bootstrap.Modal.getOrCreateInstance(document.getElementById('modalConfirmarExclusao')).show();
    }
  }

  function excluirEquipamento() {
    const id = document.getElementById('equipamentoIdParaExcluir').value;
    csrfFetch(`/equipamentos/${id}`, { method: 'DELETE' })
      .then(res => res.json())
      .then(data => {
        if (data.success) location.reload();
        else alert('Erro ao excluir equipamento.');
      });
  }

  document.addEventListener('DOMContentLoaded', function () {
    const createIllustration = document.getElementById('equipamentoIllustration');
    if(createIllustration){
      createIllustration.addEventListener('change', function(){ validarCampoImagem(this); });
    }
    const editIllustration = document.getElementById('equipamentoImagem');
    if(editIllustration){
      editIllustration.addEventListener('change', function(){ validarCampoImagem(this); });
    }
    const createForm = document.querySelector('form[enctype="multipart/form-data"]');
    if(createForm){
      ensureFormCsrf?.(createForm);
      createForm.addEventListener('submit', function(evt){
        const input = createForm.querySelector('#equipamentoIllustration');
        if(input && input.files && input.files[0] && !validarCampoImagem(input)){
          evt.preventDefault();
        }
      });
    }
    const editForm = document.getElementById('formEdicaoEquipamento');
    if(editForm){
      ensureFormCsrf?.(editForm);
    }
    aplicarMascaraPreco(document.getElementById('precoCadastro'));
    aplicarMascaraPreco(document.getElementById('equipamentoPreco'));
  });

  window.validarCampoImagem = validarCampoImagem;
  window.abrirModalEdicao = abrirModalEdicao;
  window.salvarEdicaoEquipamento = salvarEdicaoEquipamento;
  window.confirmarExclusao = confirmarExclusao;
  window.excluirEquipamento = excluirEquipamento;
})();

