/**
 * Sollus CRM - Controlador do Kanban & Ficha 360°
 * Drag & Drop, Drawer Lateral, Agendamento de Tarefas e Ações Rápidas
 */

document.addEventListener("DOMContentLoaded", function () {
    const kanbanWrapper = document.querySelector(".crm-kanban-wrapper");
    if (!kanbanWrapper) return;

    const drawerBackdrop = document.getElementById("crmDrawerBackdrop");
    const drawer = document.getElementById("crmDrawer");
    const drawerCloseBtn = document.getElementById("crmDrawerCloseBtn");

    let currentDealId = null;

    // Helper para Obter CSRF Token
    function getCsrfToken() {
        const tokenInput = document.querySelector('input[name="csrf_token"]');
        if (tokenInput) return tokenInput.value;
        const metaToken = document.querySelector('meta[name="csrf-token"]');
        return metaToken ? metaToken.getAttribute("content") : "";
    }

    // 1. Inicializar Drag & Drop com SortableJS (se disponível) ou HTML5 Drag & Drop
    const containers = document.querySelectorAll(".crm-cards-container");
    if (typeof Sortable !== "undefined") {
        containers.forEach((container) => {
            new Sortable(container, {
                group: "crm-kanban",
                animation: 150,
                ghostClass: "crm-deal-card-ghost",
                chosenClass: "crm-deal-card-chosen",
                dragClass: "crm-deal-card-dragging",
                onEnd: function (evt) {
                    const card = evt.item;
                    const dealId = card.getAttribute("data-deal-id");
                    const oldColumn = evt.from.closest(".crm-kanban-column");
                    const newColumn = evt.to.closest(".crm-kanban-column");
                    const newEtapaId = newColumn ? newColumn.getAttribute("data-etapa-id") : null;

                    if (dealId && newEtapaId && oldColumn !== newColumn) {
                        moverNegociacao(dealId, newEtapaId, card, oldColumn, newColumn);
                    }
                },
            });
        });
    }

    // Função de Troca de Etapa via API
    function moverNegociacao(dealId, newEtapaId, cardElement, oldColumn, newColumn) {
        fetch(`/crm/api/negociacoes/${dealId}/mover`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCsrfToken(),
            },
            body: JSON.stringify({ new_etapa_id: newEtapaId }),
        })
            .then((res) => res.json())
            .then((data) => {
                if (!data.success) {
                    alert("Erro ao mover negociação: " + (data.error || "Erro desconhecido"));
                    window.location.reload();
                } else {
                    if (oldColumn && newColumn && oldColumn !== newColumn) {
                        const oldCounter = oldColumn.querySelector(".crm-column-counter");
                        const newCounter = newColumn.querySelector(".crm-column-counter");
                        if (oldCounter) {
                            const val = parseInt(oldCounter.textContent.trim(), 10) || 0;
                            oldCounter.textContent = Math.max(0, val - 1);
                        }
                        if (newCounter) {
                            const val = parseInt(newCounter.textContent.trim(), 10) || 0;
                            newCounter.textContent = val + 1;
                        }
                    }
                }
            })
            .catch((err) => {
                console.error("Erro na requisição de mover negociação:", err);
            });
    }

    // 2. Abrir Gaveta Lateral (Ficha 360°)
    document.querySelectorAll(".crm-deal-card").forEach((card) => {
        card.addEventListener("click", function (e) {
            // Se clicou no botão de WhatsApp rápido, não abre o drawer
            if (e.target.closest(".crm-btn-quick-wa")) return;

            const dealId = this.getAttribute("data-deal-id");
            if (dealId) {
                abrirFicha360(dealId);
            }
        });
    });

    function abrirFicha360(dealId) {
        currentDealId = dealId;
        drawerBackdrop.classList.add("active");
        drawer.classList.add("active");

        // Elementos do Drawer
        const titleEl = document.getElementById("crmDrawerDealTitle");
        const companyEl = document.getElementById("crmDrawerCompany");
        const contactEl = document.getElementById("crmDrawerContact");
        const waLinkEl = document.getElementById("crmDrawerWaBtn");
        const propLinkEl = document.getElementById("crmDrawerPropBtn");
        const valueTotalEl = document.getElementById("crmDrawerTotalValue");
        const stepperContainer = document.getElementById("crmDrawerStepper");
        const timelineList = document.getElementById("crmDrawerTimeline");
        const tasksList = document.getElementById("crmDrawerTasks");

        // Loading state
        if (titleEl) titleEl.textContent = "Carregando negociação...";
        if (timelineList) timelineList.innerHTML = '<div class="text-center py-4 text-muted"><div class="spinner-border spinner-border-sm me-2"></div>Buscando dados...</div>';

        fetch(`/crm/api/negociacoes/${dealId}/detalhes`)
            .then((res) => res.json())
            .then((res) => {
                if (!res.success) {
                    alert("Erro ao carregar detalhes: " + res.error);
                    fecharFicha360();
                    return;
                }

                const d = res.data;
                const deal = d.deal;
                const empresa = d.empresa || {};
                const contato = d.contato || {};

                if (titleEl) titleEl.textContent = deal.nome;

                // Extração inteligente de empresa
                let compNome = (empresa && empresa.nome) ? empresa.nome.trim() : (deal.empresa_nome || "").trim();
                if (!compNome && deal.nome) {
                    if (deal.nome.includes(" - ")) {
                        const parts = deal.nome.split(" - ").map(p => p.trim()).filter(Boolean);
                        compNome = parts.length >= 2 ? parts[parts.length - 1] : deal.nome;
                    } else {
                        compNome = deal.nome;
                    }
                }
                if (companyEl) {
                    companyEl.textContent = compNome || "Sollus Comercial";
                }

                // Extração inteligente de contato ou responsável
                const contNome = (contato && contato.nome) ? contato.nome.trim() : (deal.contato_nome || "").trim();
                if (contactEl) {
                    if (contNome) {
                        contactEl.textContent = `${contNome}${contato.cargo ? ' (' + contato.cargo + ')' : ''}`;
                        if (contactEl.parentElement) contactEl.parentElement.style.display = "";
                    } else if (deal.user_name && deal.user_name !== "Não atribuído") {
                        contactEl.textContent = `Resp: ${deal.user_name}`;
                        if (contactEl.parentElement) contactEl.parentElement.style.display = "";
                    } else {
                        if (contactEl.parentElement) contactEl.parentElement.style.display = "none";
                    }
                }
                if (valueTotalEl) valueTotalEl.textContent = d.valor_total_formatado;

                // Configurar Link do WhatsApp
                const phoneClean = (contato.whatsapp || "").replace(/\D/g, "");
                if (waLinkEl) {
                    if (phoneClean) {
                        const fullPhone = phoneClean.startsWith("55") ? phoneClean : "55" + phoneClean;
                        waLinkEl.href = `https://wa.me/${fullPhone}?text=Olá ${encodeURIComponent(contato.nome || '')}, tudo bem? Sou da Sollus Tecnologia referente à sua solicitação.`;
                        waLinkEl.classList.remove("d-none");
                    } else {
                        waLinkEl.classList.add("d-none");
                    }
                }

                // Configurar Botão 1-Click Proposta
                if (propLinkEl) {
                    propLinkEl.href = `/propostas/nova?empresa_nome=${encodeURIComponent(empresa.nome || deal.nome)}&contato_nome=${encodeURIComponent(contato.nome || '')}&contato_email=${encodeURIComponent(contato.email || '')}&contato_telefone=${encodeURIComponent(contato.telefone || contato.celular || '')}`;
                }

                // Renderizar Stepper de Etapas
                if (stepperContainer && d.etapas) {
                    stepperContainer.innerHTML = "";
                    let encontrouAtual = false;

                    d.etapas.forEach((etapa, idx) => {
                        const isCurrent = etapa.id === deal.etapa_id;
                        const isCompleted = !encontrouAtual && !isCurrent;
                        if (isCurrent) encontrouAtual = true;

                        const stepNode = document.createElement("div");
                        stepNode.className = `crm-step-node ${isCurrent ? "active" : ""} ${isCompleted ? "completed" : ""}`;
                        stepNode.title = `Clique para mover para: ${etapa.nome}`;
                        stepNode.innerHTML = `
                            <div class="crm-step-circle">${idx + 1}</div>
                            <div class="crm-step-label">${etapa.nome}</div>
                        `;

                        stepNode.addEventListener("click", () => {
                            moverNegociacao(deal.id, etapa.id);
                            abrirFicha360(deal.id);
                        });

                        stepperContainer.appendChild(stepNode);
                    });
                }

                // Renderizar Tarefas
                if (tasksList) {
                    tasksList.innerHTML = "";
                    if (!d.tarefas || d.tarefas.length === 0) {
                        tasksList.innerHTML = '<div class="text-muted small py-2">Nenhuma tarefa agendada.</div>';
                    } else {
                        d.tarefas.forEach((t) => {
                            const item = document.createElement("div");
                            item.className = "d-flex align-items-center justify-content-between p-2 mb-2 rounded bg-light border";
                            item.innerHTML = `
                                <div class="form-check mb-0">
                                    <input class="form-check-input crm-task-checkbox" type="checkbox" data-task-id="${t.id}" ${t.concluida ? "checked" : ""}>
                                    <label class="form-check-label ${t.concluida ? "text-decoration-line-through text-muted" : "fw-semibold"}">
                                        ${t.titulo}
                                    </label>
                                    <div class="small text-muted">${t.data_vencimento} • <span class="badge bg-secondary">${t.tipo}</span></div>
                                </div>
                            `;
                            tasksList.appendChild(item);
                        });

                        // Event listeners nos checkboxes de tarefas
                        tasksList.querySelectorAll(".crm-task-checkbox").forEach((chk) => {
                            chk.addEventListener("change", function () {
                                const tId = this.getAttribute("data-task-id");
                                toggleTarefa(tId, this.checked);
                            });
                        });
                    }
                }

                // Renderizar Linha do Tempo (Timeline / Anotações)
                if (timelineList) {
                    timelineList.innerHTML = "";
                    if (!d.interacoes || d.interacoes.length === 0) {
                        timelineList.innerHTML = '<div class="text-muted small py-2">Nenhuma anotação registrada ainda.</div>';
                    } else {
                        d.interacoes.forEach((i) => {
                            const item = document.createElement("div");
                            item.className = "border-start border-3 border-primary ps-3 pb-3 mb-2";
                            item.innerHTML = `
                                <div class="d-flex justify-content-between align-items-center mb-1">
                                    <span class="fw-bold small text-primary">${i.user_name}</span>
                                    <span class="text-muted" style="font-size: 0.72rem;">${i.created_at}</span>
                                </div>
                                <div class="small text-secondary" style="white-space: pre-line;">${i.conteudo}</div>
                            `;
                            timelineList.appendChild(item);
                        });
                    }
                }
            })
            .catch((err) => {
                console.error("Erro ao carregar detalhes:", err);
                if (titleEl) titleEl.textContent = "Erro ao carregar negociação.";
            });
    }

    function fecharFicha360() {
        drawerBackdrop.classList.remove("active");
        drawer.classList.remove("active");
        currentDealId = null;
    }

    if (drawerCloseBtn) drawerCloseBtn.addEventListener("click", fecharFicha360);
    if (drawerBackdrop) drawerBackdrop.addEventListener("click", fecharFicha360);

    // 3. Adicionar Nova Anotação
    const formAddNote = document.getElementById("crmFormAddNote");
    if (formAddNote) {
        formAddNote.addEventListener("submit", function (e) {
            e.preventDefault();
            if (!currentDealId) return;

            const input = document.getElementById("crmInputNoteContent");
            const conteudo = input ? input.value.trim() : "";
            if (!conteudo) return;

            fetch(`/crm/api/negociacoes/${currentDealId}/anotacoes`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify({ conteudo: conteudo }),
            })
                .then((res) => res.json())
                .then((data) => {
                    if (data.success) {
                        input.value = "";
                        abrirFicha360(currentDealId);
                    } else {
                        alert("Erro ao adicionar anotação: " + data.error);
                    }
                });
        });
    }

    // 4. Adicionar Nova Tarefa
    const formAddTask = document.getElementById("crmFormAddTask");
    if (formAddTask) {
        formAddTask.addEventListener("submit", function (e) {
            e.preventDefault();
            if (!currentDealId) return;

            const titulo = document.getElementById("crmInputTaskTitle").value.trim();
            const tipo = document.getElementById("crmSelectTaskType").value;
            const dataVenc = document.getElementById("crmInputTaskDate").value;

            if (!titulo || !dataVenc) {
                alert("Preencha o título e a data da tarefa.");
                return;
            }

            fetch(`/crm/api/negociacoes/${currentDealId}/tarefas`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify({
                    titulo: titulo,
                    tipo: tipo,
                    data_vencimento: dataVenc,
                }),
            })
                .then((res) => res.json())
                .then((data) => {
                    if (data.success) {
                        document.getElementById("crmInputTaskTitle").value = "";
                        abrirFicha360(currentDealId);
                    } else {
                        alert("Erro ao agendar tarefa: " + data.error);
                    }
                });
        });
    }

    // 5. Toggle Concluir Tarefa
    function toggleTarefa(taskId, concluida) {
        fetch(`/crm/api/tarefas/${taskId}/toggle`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCsrfToken(),
            },
            body: JSON.stringify({ concluida: concluida }),
        })
            .then((res) => res.json())
            .then((data) => {
                if (data.success && currentDealId) {
                    abrirFicha360(currentDealId);
                }
            });
    }

    // 6. Botão Ganhar Negociação
    const btnGanhar = document.getElementById("crmDrawerBtnGanhar");
    if (btnGanhar) {
        btnGanhar.addEventListener("click", function () {
            if (!currentDealId) return;
            if (!confirm("Confirmar fechamento desta negociação como VENDIDA/GANHA?")) return;

            fetch(`/crm/api/negociacoes/${currentDealId}/ganhar`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
            })
                .then((res) => res.json())
                .then((data) => {
                    if (data.success) {
                        alert("🏆 Parabéns! Venda registrada com sucesso!" + (data.sollusflow_id ? " Card criado na Fase 1 do SollusFlow." : ""));
                        window.location.reload();
                    } else {
                        alert("Erro ao finalizar venda: " + data.error);
                    }
                });
        });
    }

    // 7. Botão Perder Negociação
    const btnPerder = document.getElementById("crmDrawerBtnPerder");
    if (btnPerder) {
        btnPerder.addEventListener("click", function () {
            if (!currentDealId) return;
            const motivo = prompt("Informe o motivo da perda (Ex: Preço, Concorrência, Sem interesse, Desistência):");
            if (!motivo) return;

            let categoria = "outros";
            const motivoLower = motivo.toLowerCase();
            if (motivoLower.includes("preço") || motivoLower.includes("preco") || motivoLower.includes("caro") || motivoLower.includes("orçamento") || motivoLower.includes("orcamento") || motivoLower.includes("budget") || motivoLower.includes("valor")) {
                categoria = "preco";
            } else if (motivoLower.includes("concorr") || motivoLower.includes("henry") || motivoLower.includes("dimep") || motivoLower.includes("control id") || motivoLower.includes("competidor")) {
                categoria = "concorrente";
            } else if (motivoLower.includes("sem contato") || motivoLower.includes("não responde") || motivoLower.includes("nao responde") || motivoLower.includes("sumiu") || motivoLower.includes("sem retorno")) {
                categoria = "sem_contato";
            } else if (motivoLower.includes("descarte") || motivoLower.includes("sem fit") || motivoLower.includes("fora") || motivoLower.includes("inválido") || motivoLower.includes("invalido")) {
                categoria = "descarte";
            }

            fetch(`/crm/api/negociacoes/${currentDealId}/perder`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify({ motivo: motivo, categoria: categoria }),
            })
                .then((res) => res.json())
                .then((data) => {
                    if (data.success) {
                        alert("Negociação marcada como perdida.");
                        window.location.reload();
                    } else {
                        alert("Erro ao marcar como perdida: " + data.error);
                    }
                });
        });
    }
});
