// Catálogo Centralizado de Ajuda - Sollus Connected
// Contém os tutoriais completos, passo a passo, vinculados a capturas de tela e botões específicos.

window.SOLLUS_HELP_CATALOG = {
  // === PROPOSTAS ===
  "Cadastro de proposta": {
    "title": "Como usar a criação de proposta",
    "intro": "Passo a passo para montar e enviar a proposta.",
    "steps": [
      {
        "title": "Identificação do Cliente",
        "text": "Selecione CNPJ ou CPF; ao escolher CNPJ o campo Empresa aparece. Preencha contato, e-mail e telefone para que capa e carta usem os dados corretos.",
        "image": "proposta_cadastro_cliente.png"
      },
      {
        "title": "Configuração do Serviço",
        "text": "Em Configuração do serviço, defina tipo/modalidade e responsável. Adicione equipamentos pelo seletor, ajuste quantidade, preço (manual se precisar) e descontos percentuais para recalcular totais.",
        "image": "proposta_cadastro_geral.png"
      },
      {
        "title": "Condições e Finalização",
        "text": "Em Condições comerciais, revise pagamento, prazo, frete e garantias; finalize em 'Gerar proposta' e depois use os botões de enviar ou baixar conforme o cliente.",
        "image": "proposta_cadastro_geral.png"
      }
    ]
  },
  "Histórico de Propostas": {
    "title": "Histórico de Propostas",
    "intro": "Guia rápido para consultar e reutilizar propostas.",
    "steps": [
      {
        "title": "Filtrar Propostas",
        "text": "Combine filtros de cliente, data, usuário, serviço e modalidade para localizar a proposta antes de baixar.",
        "image": "propostas_historico_filtros.png"
      },
      {
        "title": "Abrir / Baixar PDF",
        "text": "Use o botão PDF para abrir ou baixar o documento gerado sem sair da página.",
        "image": "propostas_historico_geral.png"
      },
      {
        "title": "Editar ou Excluir",
        "text": "Clique em Editar para reabrir a proposta, ajustar dados e gerar novamente; administradores podem excluir entradas obsoletas.",
        "image": "propostas_historico_acoes.png"
      }
    ]
  },
  "Parâmetros da proposta": {
    "title": "Como usar os Parâmetros da Proposta",
    "intro": "Configure textos padrão, condições comerciais e materiais utilizados na geração das propostas comerciais.",
    "steps": [
      {
        "title": "Cadastrar Parâmetro",
        "text": "Use o formulário da esquerda para escolher a categoria e cadastrar o texto que entrará automaticamente nas propostas (pagamento, prazos, frete, garantias etc.).",
        "image": "parametros_formulario.png"
      },
      {
        "title": "Tabela de Parâmetros",
        "text": "Na tabela da direita, revise quem criou cada parâmetro e use a lixeira para remover de forma definitiva as entradas desatualizadas.",
        "image": "parametros_tabela.png"
      },
      {
        "title": "Sistema de Ponto",
        "text": "Na seção inferior 'Sistema de ponto', selecione o kit correspondente e edite descrições e imagens específicas. Salve cada formulário antes de alterar o kit.",
        "image": "parametros_ponto.png"
      }
    ]
  },

  // === FINANCEIRO ===
  "Contas a Receber": {
    "title": "Como usar o Contas a Receber",
    "intro": "Gerencie pendências financeiras, faturas e controle de inadimplência.",
    "steps": [
      {
        "title": "Visão Geral",
        "text": "A tabela principal mostra todas as contas com status <strong>ABERTO</strong>. Use o filtro do cabeçalho para alternar o mês de referência.",
        "image": "contas_receber.png"
      },
      {
        "title": "Adicionar Lançamento",
        "text": "Para iniciar um lançamento, clique no botão azul <strong>Adicionar Pendência</strong> no topo da tabela.",
        "image": "contas_receber_btn_adicionar.png"
      },
      {
        "title": "Formulário de Cadastro",
        "text": "Digite o CNPJ e o sistema fará a busca automática da Razão Social. Preencha o valor, número do contrato, software e a data da primeira pendência.",
        "image": "contas_receber_modal_form.png"
      },
      {
        "title": "Ações Disponíveis",
        "text": "Na coluna de ações de cada linha, você pode <strong>Quitar</strong> uma conta (altera o status para QUITADO) ou atualizar informações de cobrança.",
        "image": "contas_receber_acoes_tabela.png"
      },
      {
        "title": "Subpendências",
        "text": "Para parcelamentos ou cobranças extras, clique em <strong>Subpendências</strong> e preencha as parcelas associadas à conta principal.",
        "image": "contas_receber_modal_subpendencia.png"
      }
    ]
  },
  "Cota Mensal e Trimestral": {
    "title": "Como usar o Faturamento de Cotas",
    "intro": "Acompanhe e configure as metas de faturamento mensal e trimestral por unidade de negócio.",
    "steps": [
      {
        "title": "Painel Financeiro",
        "text": "O painel principal consolida as metas de faturamento de todas as unidades, exibindo o valor total planejado, o arrecadado e o pago.",
        "image": "cota_financeiro.png"
      },
      {
        "title": "Lançar Nova Meta",
        "text": "Clique no botão <strong>Adicionar Cota Mensal</strong> para cadastrar a meta de uma nova unidade.",
        "image": "cota_btn_adicionar_mensal.png"
      },
      {
        "title": "Preencher Cota Mensal",
        "text": "Selecione a empresa responsável, informe o valor da meta e o mês/ano de referência.",
        "image": "cota_modal_mensal.png"
      },
      {
        "title": "Cotas Trimestrais",
        "text": "Utilize a aba de cotas trimestrais e clique em <strong>Criar Cota Trimestral</strong> para agrupar metas de médio prazo.",
        "image": "cota_modal_trimestral.png"
      },
      {
        "title": "Fechar Mês Financeiro",
        "text": "Quando todas as faturas do mês forem consolidadas, clique em <strong>Fechar Mês</strong> para bloquear edições e arquivar o período.",
        "image": "cota_modal_fechar_mes.png"
      }
    ]
  },

  // === CONTRATOS ===
  "Contratos": {
    "title": "Como usar o Painel de Contratos",
    "intro": "Consulte contratos ativos, gerencie cancelamentos, reversões e histórico de clientes.",
    "steps": [
      {
        "title": "Painel de Contratos",
        "text": "A listagem principal exibe todos os contratos vigentes. Use a barra de pesquisa para buscar por cliente, software ou CNPJ.",
        "image": "contratos.png"
      },
      {
        "title": "Filtros de Status",
        "text": "Alterne entre as abas superiores para visualizar contratos <strong>Ativos</strong>, <strong>Cancelados</strong>, <strong>Revertidos</strong> ou <strong>Inativos</strong>.",
        "image": "contratos_abas.png"
      },
      {
        "title": "Histórico e Ações",
        "text": "Na coluna da direita, acesse o botão de histórico para ver anotações, solicitar cancelamentos de vigência ou realizar reparações de faturas.",
        "image": "contratos_linha_tabela.png"
      }
    ]
  },
  "Contas a Receber (Contratos)": {
    "title": "Como usar Contas a Receber de Contratos",
    "intro": "Controle faturamento e faturas extras associadas aos contratos de locação.",
    "steps": [
      {
        "title": "Listagem de Contas",
        "text": "A listagem exibe todas as cobranças recorrentes vinculadas aos contratos vigentes dos clientes.",
        "image": "contratos_contas_receber.png"
      },
      {
        "title": "Destaque Novo Lançamento",
        "text": "Clique em <strong>Nova Conta</strong> para abrir o modal de cadastro de faturas adicionais.",
        "image": "contratos_contas_receber.png"
      }
    ]
  },
  "Manutenções Agendadas": {
    "title": "Como usar a Agenda de Manutenções",
    "intro": "Controle e agende as visitas técnicas preventivas e corretivas dos contratos de locação.",
    "steps": [
      {
        "title": "Escala de Visitas",
        "text": "Visualize todos os agendamentos cadastrados no período, técnicos designados e a situação da visita.",
        "image": "manutencoes.png"
      },
      {
        "title": "Adicionar Visita",
        "text": "Clique no botão <strong>Novo Agendamento</strong> para iniciar a programação de uma nova manutenção.",
        "image": "manutencoes_btn_novo.png"
      },
      {
        "title": "Preencher Dados da Visita",
        "text": "Selecione o contrato do cliente, o técnico responsável, informe a data programada e a descrição do serviço a ser realizado.",
        "image": "manutencoes_modal_form.png"
      }
    ]
  },

  // === CRACHÁS ===
  "Controle de Crachás": {
    "title": "Como usar o Controle de Crachás",
    "intro": "Gerencie o fluxo de confecção, aprovação de modelos, controle de estoque e entrega de crachás.",
    "steps": [
      {
        "title": "Fluxo de Produção",
        "text": "Monitore os crachás pelas etapas: Aguardando Foto, Em Produção, Pronto para Entrega e Finalizado.",
        "image": "pedidos_crachas.png"
      },
      {
        "title": "Novo Pedido",
        "text": "Clique no botão azul <strong>Criar Pedido</strong> para abrir o formulário de cadastro.",
        "image": "crachas_btn_criar_pedido.png"
      }
    ]
  },
  "Modelos de Crachá": {
    "title": "Como usar Modelos de Crachá",
    "intro": "Cadastre e edite os layouts e modelos visuais homologados para os crachás de cada cliente.",
    "steps": [
      {
        "title": "Lista de Modelos",
        "text": "Consulte os layouts aprovados de crachá para cada empresa cadastrada.",
        "image": "modelos_cracha.png"
      }
    ]
  },
  "Extratos de Crachá": {
    "title": "Como usar Extratos de Crachá",
    "intro": "Acompanhe o faturamento de crachás emitidos e o saldo de pacotes por cliente.",
    "steps": [
      {
        "title": "Acompanhar Extrato",
        "text": "Consulte saldos acumulados de emissões e faturamento financeiro consolidado por cliente.",
        "image": "extratos_cracha.png"
      }
    ]
  },
  "Recibos de Crachá": {
    "title": "Como usar os Recibos",
    "intro": "Emita e assine os termos de recebimento e entrega de crachás confeccionados.",
    "steps": [
      {
        "title": "Listagem de Recibos",
        "text": "Consulte todos os recibos gerados e os status de assinatura e entrega física de cada lote.",
        "image": "crachas_recibos.png"
      },
      {
        "title": "Emitir Novo Recibo",
        "text": "Clique no botão <strong>Criar Recibo</strong> para gerar o termo de entrega para um lote de crachás.",
        "image": "crachas_btn_criar_recibo.png"
      },
      {
        "title": "Preenchimento do Lote",
        "text": "Selecione o cliente e os respectivos funcionários cujos crachás serão entregues nesta remessa.",
        "image": "crachas_modal_criar_recibo.png"
      }
    ]
  },
  "Cortador de Fotos": {
    "title": "Como usar o Cortador de Fotos",
    "intro": "Ferramenta para recortar e redimensionar fotos de funcionários para o padrão oficial dos crachás.",
    "steps": [
      {
        "title": "Carregar Foto",
        "text": "Arraste e solte o arquivo de imagem ou clique na área tracejada de upload para selecionar a foto original.",
        "image": "cortador_area_upload.png"
      },
      {
        "title": "Ajuste e Recorte",
        "text": "Use a ferramenta de corte na tela para enquadrar perfeitamente o rosto do funcionário no padrão 3x4 do crachá.",
        "image": "cortador_fotos.png"
      }
    ]
  },

  // === ADMINISTRAÇÃO E RH ===
  "Calendário de Aniversariantes": {
    "title": "Como usar o Calendário de Aniversariantes",
    "intro": "Monitore os aniversários dos colaboradores do time Sollus para o RH celebrar as datas.",
    "steps": [
      {
        "title": "Listagem Geral",
        "text": "Acompanhe os aniversariantes do mês organizados em ordem cronológica de dias.",
        "image": "aniversariantes.png"
      },
      {
        "title": "Cadastrar Colaborador",
        "text": "Clique no botão <strong>Adicionar</strong> para cadastrar um novo integrante no calendário.",
        "image": "aniversariantes_btn_adicionar.png"
      },
      {
        "title": "Formulário de Cadastro",
        "text": "Preencha o nome completo do colaborador e a respectiva data de nascimento.",
        "image": "aniversariantes_modal_form.png"
      }
    ]
  },
  "Mapa de Férias da Equipe": {
    "title": "Como usar o Mapa de Férias",
    "intro": "Controle os períodos de concessão de férias dos funcionários do Sollus Group.",
    "steps": [
      {
        "title": "Cronograma de Férias",
        "text": "Monitore a lista de férias programadas, visualizando as datas de saída, retorno e período aquisitivo.",
        "image": "ferias.png"
      },
      {
        "title": "Programar Férias",
        "text": "Clique em <strong>Adicionar Férias</strong> para registrar um novo período de descanso para um colaborador.",
        "image": "ferias_btn_adicionar.png"
      },
      {
        "title": "Preencher Período",
        "text": "Selecione o colaborador, defina a data de início, quantidade de dias e o ano de referência do período aquisitivo.",
        "image": "ferias_modal_form.png"
      }
    ]
  },
  "Agenda externa dos técnicos": {
    "title": "Como usar a Agenda Técnica",
    "intro": "Consulte a escala diária de atividades externas, atendimentos e visitas técnicas da equipe.",
    "steps": [
      {
        "title": "Visualizar Escala",
        "text": "Acompanhe a agenda completa de compromissos externos organizados por técnico e por data.",
        "image": "agenda_tecnica.png"
      },
      {
        "title": "Registrar Compromisso",
        "text": "Abra o modal de agendamento para preencher o cliente, o técnico e o intervalo de horário do atendimento.",
        "image": "agenda_tecnica_modal_form.png"
      }
    ]
  },
  "Gestão de Usuários": {
    "title": "Gestão de Usuários",
    "intro": "Gerencie o acesso à plataforma, redefina senhas e gerencie novos perfis.",
    "steps": [
      {
        "title": "Lista de Usuários",
        "text": "Visualize todos os funcionários ativos, inativos e seus cargos.",
        "image": "gestao_usuarios.png"
      }
    ]
  },
  "Tipos e Permissões": {
    "title": "Tipos e Permissões",
    "intro": "Gerencie permissões específicas de acessos de cada cargo no sistema.",
    "steps": [
      {
        "title": "Tabela de Permissões",
        "text": "Habilite ou desabilite o acesso a módulos por grupo de cargo (administrador, financeiro, etc.).",
        "image": "tipos_permissoes.png"
      }
    ]
  },
  "Auditoria": {
    "title": "Painel de Auditoria",
    "intro": "Consulte o histórico de logs e ações realizadas no banco de dados.",
    "steps": [
      {
        "title": "Logs do Sistema",
        "text": "Consulte registros contendo data, ação (inserir, editar, deletar) e o usuário responsável.",
        "image": "auditoria.png"
      }
    ]
  },
  "Central de Conhecimento": {
    "title": "Central de Conhecimento",
    "intro": "Base de conhecimento interna e guia de resoluções de problemas.",
    "steps": [
      {
        "title": "Ver Artigos",
        "text": "Navegue pelas categorias e leia os tutoriais desenvolvidos pelo suporte técnico.",
        "image": "central_conhecimento.png"
      }
    ]
  },
  "Estoque": {
    "title": "Estoque de Equipamentos",
    "intro": "Monitore os equipamentos de locação disponíveis em estoque.",
    "steps": [
      {
        "title": "Equipamentos",
        "text": "Consulte números de série, marcas e o status atual dos equipamentos.",
        "image": "estoque.png"
      }
    ]
  },
  "Estoque de Peças": {
    "title": "Estoque de Peças",
    "intro": "Controle o estoque de reposição física utilizado nas ordens de serviço.",
    "steps": [
      {
        "title": "Lista de Peças",
        "text": "Monitore quantidades mínimas, custos e estoque atual de insumos.",
        "image": "estoque_pecas.png"
      }
    ]
  }
};
