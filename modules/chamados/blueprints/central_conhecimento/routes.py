# modules/chamados/blueprints/central_conhecimento/routes.py
# SollusFlow — Gestao de Pedidos & Processos
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import List

from flask import render_template, request, jsonify, redirect, url_for, flash, session, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from . import central_conhecimento_bp, legacy_cc_bp
from extensions import db

from utils.helpers import wants_json as _wants_json
from modules.propostas.models import User, Department
from modules.propostas.blueprints.auth.permissions_utils import (
    normalize_role_key,
    current_permissions,
)
from modules.chamados.models import (
    SfPedido,
    SfFaseHistorico,
    SfChecklist,
    SfObservacao,
    SfConfig,
    SF_FASES,
)

import json

def _get_mariana_user_id() -> int | None:
    """Busca o ID da usuária Mariana Souza no sistema para atribuição do Pós-Venda."""
    try:
        u = User.query.filter(
            or_(
                User.usuario == "mariana.souza",
                User.email == "comercial6@sollusgroup.com",
                User.nome_completo.ilike("%Mariana Souza%")
            )
        ).first()
        return u.id if u else 6847
    except Exception:
        return 6847


def _get_fases_ordem() -> list[int]:
    """Retorna a ordem atual das fases (1..15) configurada no SollusFlow."""
    padrao = list(SF_FASES.keys())
    try:
        cfg = SfConfig.query.get("fases_ordem")
        if cfg and cfg.valor:
            ordem = json.loads(cfg.valor)
            if isinstance(ordem, list) and len(ordem) == len(padrao) and set(ordem) == set(padrao):
                return [int(x) for x in ordem]
    except Exception:
        pass
    return padrao


# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------

def _deny_access(area_label: str):
    if "/api/" in getattr(request, "path", "") or _wants_json():
        return jsonify({"error": "Access denied", "success": False,
                        "message": f"Voce nao tem permissao para acessar esta area ({area_label})."}), 403
    flash("Voce nao tem permissao para acessar esta area. Procure seu superior caso precise de acesso.", "warning")
    return redirect(url_for("sem_permissao", area=area_label))


@central_conhecimento_bp.before_request
def _check_access():
    endpoint = getattr(request, "endpoint", "") or ""
    if not endpoint.startswith("central_conhecimento."):
        return
    if endpoint == "sem_permissao":
        return
    if not current_user.is_authenticated and not session.get("usuario_id") and not session.get("user_id"):
        if "/api/" in getattr(request, "path", "") or _wants_json():
            return jsonify({"error": "Authentication required", "success": False}), 401
        try:
            login_url = url_for("auth_bp.login", next=request.full_path if request.method == "GET" else None)
        except Exception:
            login_url = "/login"
        return redirect(login_url)
    role_key = normalize_role_key(
        getattr(current_user, "tipo", None) or getattr(current_user, "role", None) or session.get("tipo")
    )
    if role_key in ("admin", "gestor"):
        return
    if current_permissions().get("central_conhecimento"):
        return
    return _deny_access("SollusFlow")


def _has_access() -> bool:
    if not current_user.is_authenticated:
        return False
    role_key = normalize_role_key(
        getattr(current_user, "tipo", None) or getattr(current_user, "role", None) or session.get("tipo")
    )
    if role_key in ("admin", "gestor"):
        return True
    return bool(current_permissions().get("central_conhecimento"))


def _can_create() -> bool:
    return _has_access()


def _users_list() -> List[User]:
    return User.query.filter(User.is_active.is_(True)).order_by(User.nome_completo.asc()).all()


def _today_iso():
    return date.today().isoformat()


def _pedido_status_badge(pedido: SfPedido) -> str:
    """Retorna 'atrasado', 'hoje' ou 'ok'."""
    if pedido.status != "ativo":
        return pedido.status
    if not pedido.data_prevista:
        return "ok"
    today = date.today()
    if pedido.data_prevista < today:
        return "atrasado"
    if pedido.data_prevista == today:
        return "hoje"
    return "ok"


# ---------------------------------------------------------------------------
# Board principal
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/", methods=["GET"])
@login_required
def board():
    filtro_fase = request.args.get("fase", "").strip()
    filtro_responsavel = request.args.get("responsavel", type=int)
    filtro_status = request.args.get("status", "ativo")
    filtro_cnpj = request.args.get("cnpj", "").strip()

    q = SfPedido.query
    if filtro_fase and filtro_fase != "ativas" and filtro_fase.isdigit():
        q = q.filter(SfPedido.fase_atual == int(filtro_fase))
    if filtro_responsavel:
        q = q.filter(SfPedido.responsavel_id == filtro_responsavel)
    if filtro_status:
        q = q.filter(SfPedido.status == filtro_status)
    if filtro_cnpj:
        q = q.filter(SfPedido.cliente_cnpj.ilike(f"%{filtro_cnpj}%"))

    pedidos = q.order_by(SfPedido.data_prevista.asc(), SfPedido.created_at.desc()).all()

    ordem_fases = _get_fases_ordem()

    # Organizar por fase para o kanban na ordem configurada
    fases_pedidos = {}
    if filtro_fase == "ativas":
        fases_com_cards = {p.fase_atual for p in pedidos}
        fases_exibir = [f for f in ordem_fases if f in SF_FASES and f in fases_com_cards]
    elif filtro_fase and filtro_fase.isdigit() and int(filtro_fase) in SF_FASES:
        fases_exibir = [int(filtro_fase)]
    else:
        fases_exibir = [f for f in ordem_fases if f in SF_FASES]

    for num in fases_exibir:
        fases_pedidos[num] = {
            "info": SF_FASES[num],
            "pedidos": [],
        }
    for p in pedidos:
        fase = p.fase_atual
        if fase in fases_pedidos:
            fases_pedidos[fase]["pedidos"].append(p)

    # Alertas: pedidos atrasados
    atrasados = sum(1 for p in pedidos if _pedido_status_badge(p) == "atrasado")

    users = _users_list()
    return render_template(
        "chamados/central_conhecimento/board.html",
        fases=SF_FASES,
        fases_ordem=ordem_fases,
        fases_pedidos=fases_pedidos,
        pedidos=pedidos,
        users=users,
        atrasados=atrasados,
        can_create=_can_create(),
        filtro_fase=filtro_fase,
        filtro_responsavel=filtro_responsavel,
        filtro_status=filtro_status,
        filtro_cnpj=filtro_cnpj,
        today=_today_iso(),
        badge_fn=_pedido_status_badge,
    )



# ---------------------------------------------------------------------------
# Historico de pedidos
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/historico", methods=["GET"])
@login_required
def history():
    filtro_status = request.args.get("status", "")
    filtro_cnpj = request.args.get("cnpj", "").strip()
    filtro_cliente = request.args.get("cliente", "").strip()

    q = SfPedido.query
    if filtro_status:
        q = q.filter(SfPedido.status == filtro_status)
    if filtro_cnpj:
        q = q.filter(SfPedido.cliente_cnpj.ilike(f"%{filtro_cnpj}%"))
    if filtro_cliente:
        q = q.filter(SfPedido.cliente_nome.ilike(f"%{filtro_cliente}%"))

    pedidos = q.order_by(SfPedido.updated_at.desc()).all()
    return render_template(
        "chamados/central_conhecimento/history.html",
        pedidos=pedidos,
        fases=SF_FASES,
        filtro_status=filtro_status,
        filtro_cnpj=filtro_cnpj,
        filtro_cliente=filtro_cliente,
        badge_fn=_pedido_status_badge,
    )


# ---------------------------------------------------------------------------
# Criar pedido
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/api/pedido", methods=["POST"])
@login_required
def criar_pedido():
    if not _can_create():
        return jsonify({"ok": False, "error": "Sem permissao"}), 403
    data = request.get_json(silent=True) or {}

    cliente_nome = (data.get("cliente_nome") or "").strip()
    if not cliente_nome:
        return jsonify({"ok": False, "error": "Nome do cliente e obrigatorio"}), 400

    tipo_pessoa = (data.get("tipo_pessoa") or "").strip().lower()
    if tipo_pessoa not in ("pj", "pf"):
        doc_digits = (data.get("cliente_cnpj") or "").replace(".", "").replace("-", "").replace("/", "").strip()
        tipo_pessoa = "pf" if len(doc_digits) == 11 else "pj"

    pedido = SfPedido(
        numero_pedido=(data.get("numero_pedido") or "").strip() or None,
        cliente_nome=cliente_nome,
        cliente_cnpj=(data.get("cliente_cnpj") or "").strip() or None,
        tipo_pessoa=tipo_pessoa,
        tipo=data.get("tipo", "venda"),
        valor=_parse_valor(data.get("valor")),
        consultor_id=data.get("consultor_id") or current_user.id,
        responsavel_id=data.get("responsavel_id") or current_user.id,
        fase_atual=1,
        prioridade=data.get("prioridade", "normal"),
        data_entrada=_parse_date(data.get("data_entrada")) or date.today(),
        data_prevista=_parse_date(data.get("data_prevista")),
        descricao=(data.get("descricao") or "").strip() or None,
    )
    db.session.add(pedido)
    db.session.flush()

    # Log inicial
    hist = SfFaseHistorico(
        pedido_id=pedido.id,
        fase_de=None,
        fase_para=1,
        usuario_id=current_user.id,
        observacao="Pedido criado",
    )
    db.session.add(hist)

    # Checklist padrao da fase 1
    _criar_checklist_padrao(pedido.id, 1)

    db.session.commit()
    return jsonify({"ok": True, "id": pedido.id, "pedido": pedido.as_dict()})


# ---------------------------------------------------------------------------
# Detalhes do pedido (API)
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/api/pedido/<int:pid>", methods=["GET"])
@login_required
def get_pedido(pid: int):
    pedido = SfPedido.query.get_or_404(pid)
    historico = [h.as_dict() for h in pedido.historico]
    checklist = [c.as_dict() for c in pedido.checklist]
    observacoes = [o.as_dict() for o in pedido.observacoes]
    return jsonify({
        "ok": True,
        "pedido": pedido.as_dict(),
        "historico": historico,
        "checklist": checklist,
        "observacoes": observacoes,
        "fases": {str(k): v for k, v in SF_FASES.items()},
        "fases_ordem": _get_fases_ordem(),
        "status_badge": _pedido_status_badge(pedido),
    })


# ---------------------------------------------------------------------------
# Editar pedido
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/api/pedido/<int:pid>", methods=["PATCH"])
@login_required
def editar_pedido(pid: int):
    if not _has_access():
        return jsonify({"ok": False, "error": "Sem permissao"}), 403
    pedido = SfPedido.query.get_or_404(pid)
    data = request.get_json(silent=True) or {}

    if "cliente_nome" in data and data["cliente_nome"].strip():
        pedido.cliente_nome = data["cliente_nome"].strip()
    if "tipo_pessoa" in data and data["tipo_pessoa"] in ("pj", "pf"):
        pedido.tipo_pessoa = data["tipo_pessoa"]
    if "cliente_cnpj" in data:
        pedido.cliente_cnpj = (data["cliente_cnpj"] or "").strip() or None
    if "numero_pedido" in data:
        pedido.numero_pedido = (data["numero_pedido"] or "").strip() or None
    if "tipo" in data:
        pedido.tipo = data["tipo"]
    if "valor" in data:
        pedido.valor = _parse_valor(data.get("valor"))
    if "prioridade" in data:
        pedido.prioridade = data["prioridade"]
    if "data_prevista" in data:
        pedido.data_prevista = _parse_date(data["data_prevista"])
    if "data_treinamento" in data:
        pedido.data_treinamento = _parse_date(data["data_treinamento"])
        # Se alterou data do treinamento e o primeiro item da fase 16 estiver pendente, ajusta para data_treinamento + 15 dias
        if pedido.data_treinamento:
            primeiro_pos = SfChecklist.query.filter_by(pedido_id=pedido.id, fase=16).order_by(SfChecklist.posicao.asc()).first()
            if primeiro_pos and not primeiro_pos.concluido:
                primeiro_pos.data_lembrete = pedido.data_treinamento + timedelta(days=15)
    if "data_ultimo_pos_venda" in data:
        pedido.data_ultimo_pos_venda = _parse_date(data["data_ultimo_pos_venda"])
    if "descricao" in data:
        pedido.descricao = (data["descricao"] or "").strip() or None
    if "responsavel_id" in data:
        pedido.responsavel_id = data["responsavel_id"] or None
    if "status" in data and data["status"] in ("ativo", "concluido", "cancelado"):
        pedido.status = data["status"]

    pedido.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "pedido": pedido.as_dict()})


# ---------------------------------------------------------------------------
# Mover / Avancar / Voltar fase (Drag & Drop ou Botoes)
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/api/pedido/<int:pid>/mover", methods=["POST"])
@central_conhecimento_bp.route("/api/pedido/<int:pid>/avancar", methods=["POST"])
@login_required
def mover_pedido(pid: int):
    if not _has_access():
        return jsonify({"ok": False, "error": "Sem permissao"}), 403
    pedido = SfPedido.query.get_or_404(pid)
    data = request.get_json(silent=True) or {}

    fase_de = pedido.fase_atual
    ordem_atual = _get_fases_ordem()
    if "fase" in data and data.get("fase") is not None:
        nova_fase = int(data["fase"])
    else:
        # Avancar para a proxima etapa seguindo a ordem configurada
        if fase_de in ordem_atual:
            idx = ordem_atual.index(fase_de)
            if idx + 1 < len(ordem_atual):
                nova_fase = ordem_atual[idx + 1]
            else:
                nova_fase = ordem_atual[-1]
        else:
            nova_fase = min(len(SF_FASES), fase_de + 1)

    if nova_fase not in SF_FASES:
        return jsonify({"ok": False, "error": "Fase invalida"}), 400

    fase_final = ordem_atual[-1] if ordem_atual else len(SF_FASES)
    direcao = "mesma etapa"
    if nova_fase in ordem_atual and fase_de in ordem_atual:
        idx_nova = ordem_atual.index(nova_fase)
        idx_velha = ordem_atual.index(fase_de)
        direcao = "avanço" if idx_nova > idx_velha else ("retorno" if idx_nova < idx_velha else "mesma etapa")
    else:
        direcao = "avanço" if nova_fase > fase_de else ("retorno" if nova_fase < fase_de else "mesma etapa")

    observacao = (data.get("observacao") or "").strip() or f"Movimentação ({direcao}) da Etapa {fase_de} para Etapa {nova_fase}"
    transferido_para_id = data.get("transferido_para_id") or None

    if "data_treinamento" in data and data.get("data_treinamento"):
        pedido.data_treinamento = _parse_date(data["data_treinamento"])

    # Se entrar na Etapa 16 (Pós-Venda) e não tiver transferência explícita, atribui à Mariana
    if nova_fase == 16 and not transferido_para_id:
        mariana_id = _get_mariana_user_id()
        if mariana_id:
            pedido.responsavel_id = mariana_id
            transferido_para_id = mariana_id

    pedido.fase_atual = nova_fase
    # Pedidos no fluxo continuam ativos (inclusive em Treinamento e Pós-Venda)
    # Caso estivesse concluído/arquivado e seja movimentado, reativa o pedido
    if pedido.status == "concluido":
        pedido.status = "ativo"

    pedido.updated_at = datetime.utcnow()

    # Atualiza responsavel se transferencia foi feita
    if transferido_para_id:
        pedido.responsavel_id = transferido_para_id

    hist = SfFaseHistorico(
        pedido_id=pedido.id,
        fase_de=fase_de,
        fase_para=nova_fase,
        usuario_id=current_user.id,
        transferido_para_id=transferido_para_id,
        observacao=observacao,
    )
    db.session.add(hist)

    # Criar checklist padrao da nova fase se nao existir
    existente = SfChecklist.query.filter_by(pedido_id=pid, fase=nova_fase).count()
    if existente == 0:
        _criar_checklist_padrao(pid, nova_fase)

    db.session.commit()
    return jsonify({"ok": True, "pedido": pedido.as_dict()})


# ---------------------------------------------------------------------------
# Reordenar colunas / blocos do Kanban
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/api/colunas/reordenar", methods=["POST"])
@login_required
def reordenar_colunas():
    if not _has_access():
        return jsonify({"ok": False, "error": "Sem permissao"}), 403
    data = request.get_json(silent=True) or {}
    nova_ordem = data.get("ordem") or []
    padrao = list(SF_FASES.keys())

    # Validar que contem todas as fases validas
    if not isinstance(nova_ordem, list) or len(nova_ordem) != len(padrao) or set(nova_ordem) != set(padrao):
        return jsonify({"ok": False, "error": "Lista de fases invalida"}), 400

    cfg = SfConfig.query.get("fases_ordem")
    if not cfg:
        cfg = SfConfig(chave="fases_ordem", valor=json.dumps(nova_ordem))
        db.session.add(cfg)
    else:
        cfg.valor = json.dumps(nova_ordem)
        cfg.updated_at = datetime.utcnow()

    db.session.commit()
    return jsonify({"ok": True, "ordem": nova_ordem})


@central_conhecimento_bp.route("/api/colunas/resetar", methods=["POST"])
@login_required
def resetar_ordem_colunas():
    if not _has_access():
        return jsonify({"ok": False, "error": "Sem permissao"}), 403
    padrao = list(SF_FASES.keys())
    cfg = SfConfig.query.get("fases_ordem")
    if cfg:
        cfg.valor = json.dumps(padrao)
        cfg.updated_at = datetime.utcnow()
        db.session.commit()
    return jsonify({"ok": True, "ordem": padrao})


# ---------------------------------------------------------------------------
# Transferir responsavel
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/api/pedido/<int:pid>/transferir", methods=["POST"])
@login_required
def transferir_pedido(pid: int):
    if not _has_access():
        return jsonify({"ok": False, "error": "Sem permissao"}), 403
    pedido = SfPedido.query.get_or_404(pid)
    data = request.get_json(silent=True) or {}

    novo_resp_id = data.get("responsavel_id")
    if not novo_resp_id:
        return jsonify({"ok": False, "error": "responsavel_id e obrigatorio"}), 400

    novo_resp = User.query.get(novo_resp_id)
    if not novo_resp:
        return jsonify({"ok": False, "error": "Usuario nao encontrado"}), 404

    observacao = (data.get("observacao") or "").strip() or f"Transferido para {novo_resp.nome_completo or novo_resp.email}"

    hist = SfFaseHistorico(
        pedido_id=pedido.id,
        fase_de=pedido.fase_atual,
        fase_para=pedido.fase_atual,
        usuario_id=current_user.id,
        transferido_para_id=novo_resp_id,
        observacao=observacao,
    )
    db.session.add(hist)
    pedido.responsavel_id = novo_resp_id
    pedido.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "pedido": pedido.as_dict()})


# ---------------------------------------------------------------------------
# Checklist & Lembretes
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/api/pedido/<int:pid>/checklist", methods=["GET"])
@login_required
def get_checklist(pid: int):
    pedido = SfPedido.query.get_or_404(pid)
    items = SfChecklist.query.filter_by(pedido_id=pid).order_by(SfChecklist.fase, SfChecklist.posicao).all()
    return jsonify({"ok": True, "checklist": [i.as_dict() for i in items]})


@central_conhecimento_bp.route("/api/pedido/<int:pid>/checklist", methods=["POST"])
@login_required
def add_checklist(pid: int):
    pedido = SfPedido.query.get_or_404(pid)
    data = request.get_json(silent=True) or {}
    titulo = (data.get("titulo") or "").strip()
    if not titulo:
        return jsonify({"ok": False, "error": "Titulo obrigatorio"}), 400
    fase = data.get("fase", pedido.fase_atual)
    posicao = SfChecklist.query.filter_by(pedido_id=pid, fase=fase).count()
    data_lembrete = _parse_date(data.get("data_lembrete"))
    item = SfChecklist(
        pedido_id=pid,
        fase=fase,
        titulo=titulo,
        posicao=posicao,
        data_lembrete=data_lembrete,
        criado_por_id=current_user.id if current_user.is_authenticated else None,
    )
    db.session.add(item)
    db.session.commit()

    if data_lembrete:
        try:
            import threading
            from flask import current_app
            from modules.chamados.services.lembretes_flow import processar_lembretes_sollusflow
            app_obj = current_app._get_current_object()
            threading.Thread(target=processar_lembretes_sollusflow, args=(app_obj,), daemon=True).start()
        except Exception:
            pass

    return jsonify({"ok": True, "item": item.as_dict()})


@central_conhecimento_bp.route("/api/checklist/<int:cid>", methods=["PATCH"])
@login_required
def edit_checklist(cid: int):
    item = SfChecklist.query.get_or_404(cid)
    data = request.get_json(silent=True) or {}
    if "titulo" in data and data["titulo"].strip():
        item.titulo = data["titulo"].strip()
    if "data_lembrete" in data:
        item.data_lembrete = _parse_date(data["data_lembrete"])
        if item.data_lembrete and item.data_lembrete >= date.today():
            item.alerta_5d_enviado = False
            item.alerta_3d_enviado = False
            item.alerta_0d_enviado = False
            try:
                import threading
                from flask import current_app
                from modules.chamados.services.lembretes_flow import processar_lembretes_sollusflow
                app_obj = current_app._get_current_object()
                threading.Thread(target=processar_lembretes_sollusflow, args=(app_obj,), daemon=True).start()
            except Exception:
                pass
    db.session.commit()
    return jsonify({"ok": True, "item": item.as_dict()})


@central_conhecimento_bp.route("/api/checklist/<int:cid>/toggle", methods=["POST"])
@login_required
def toggle_checklist(cid: int):
    item = SfChecklist.query.get_or_404(cid)
    item.concluido = not item.concluido
    if item.concluido:
        item.concluido_por_id = current_user.id
        item.concluido_at = datetime.utcnow()

        # REGRA AUTOMÁTICA DE PÓS-VENDA RECORRENTE (Mariana - 60 em 60 dias)
        if item.fase == 16:
            pedido = item.pedido
            pedido.data_ultimo_pos_venda = date.today()

            # Verificar se já existe algum item pendente na fase 16
            tem_pendente = SfChecklist.query.filter(
                SfChecklist.pedido_id == pedido.id,
                SfChecklist.fase == 16,
                SfChecklist.concluido.is_(False)
            ).first()

            if not tem_pendente:
                ciclos_concluidos = SfChecklist.query.filter(
                    SfChecklist.pedido_id == pedido.id,
                    SfChecklist.fase == 16,
                    SfChecklist.concluido.is_(True)
                ).count()

                mariana_id = _get_mariana_user_id()
                data_proximo = date.today() + timedelta(days=60)
                posicao = SfChecklist.query.filter_by(pedido_id=pedido.id, fase=16).count()

                novo_ciclo = SfChecklist(
                    pedido_id=pedido.id,
                    fase=16,
                    titulo=f"Ciclo de Acompanhamento ({ciclos_concluidos + 1}º Contato - 60 dias) - Avaliação de serviços e produtos",
                    posicao=posicao,
                    responsavel_id=mariana_id,
                    data_lembrete=data_proximo
                )
                db.session.add(novo_ciclo)

                autor_nome = getattr(current_user, "nome_completo", None) or "Mariana Souza"
                obs = SfObservacao(
                    pedido_id=pedido.id,
                    autor_id=current_user.id if current_user.is_authenticated else mariana_id,
                    corpo=f"✅ Avaliação de Pós-Venda registrada por {autor_nome}. Próximo acompanhamento agendado para {data_proximo.strftime('%d/%m/%Y')} (ciclo de 60 dias para Mariana Souza)."
                )
                db.session.add(obs)
    else:
        item.concluido_por_id = None
        item.concluido_at = None
    db.session.commit()
    return jsonify({"ok": True, "item": item.as_dict()})


@central_conhecimento_bp.route("/api/checklist/<int:cid>", methods=["DELETE"])
@login_required
def delete_checklist(cid: int):
    item = SfChecklist.query.get_or_404(cid)
    db.session.delete(item)
    db.session.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Disparo manual de lembretes (para testes e automação)
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/api/lembretes/processar", methods=["POST"])
@login_required
def disparar_lembretes():
    from modules.chamados.services.lembretes_flow import processar_lembretes_sollusflow
    res = processar_lembretes_sollusflow()
    return jsonify(res)


# ---------------------------------------------------------------------------
# Observacoes
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/api/pedido/<int:pid>/observacao", methods=["POST"])
@login_required
def add_observacao(pid: int):
    SfPedido.query.get_or_404(pid)
    data = request.get_json(silent=True) or {}
    corpo = (data.get("corpo") or "").strip()
    if not corpo:
        return jsonify({"ok": False, "error": "Observacao nao pode ser vazia"}), 400
    obs = SfObservacao(pedido_id=pid, autor_id=current_user.id, corpo=corpo)
    db.session.add(obs)
    db.session.commit()
    return jsonify({"ok": True, "observacao": obs.as_dict()})


@central_conhecimento_bp.route("/api/observacao/<int:oid>", methods=["DELETE"])
@login_required
def delete_observacao(oid: int):
    obs = SfObservacao.query.get_or_404(oid)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    if obs.autor_id != current_user.id and role_key not in ("admin", "gestor"):
        return jsonify({"ok": False, "error": "Sem permissao"}), 403
    db.session.delete(obs)
    db.session.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Historico do cliente por CNPJ
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/cliente/<path:cnpj>", methods=["GET"])
@login_required
def historico_cliente(cnpj: str):
    cnpj_clean = cnpj.strip()
    pedidos = (SfPedido.query
               .filter(SfPedido.cliente_cnpj.ilike(f"%{cnpj_clean}%"))
               .order_by(SfPedido.created_at.desc())
               .all())
    return render_template(
        "chamados/central_conhecimento/cliente.html",
        pedidos=pedidos,
        cnpj=cnpj_clean,
        fases=SF_FASES,
        badge_fn=_pedido_status_badge,
        cliente_nome=pedidos[0].cliente_nome if pedidos else cnpj_clean,
    )


# ---------------------------------------------------------------------------
# Deletar pedido
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/api/pedido/<int:pid>", methods=["DELETE"])
@login_required
def delete_pedido(pid: int):
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    if role_key not in ("admin", "gestor"):
        return jsonify({"ok": False, "error": "Somente admin/gestor pode excluir pedidos"}), 403
    pedido = SfPedido.query.get_or_404(pid)
    db.session.delete(pedido)
    db.session.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API: Contagem de alertas (para badge no menu)
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/api/alertas", methods=["GET"])
@login_required
def api_alertas():
    today = date.today()
    atrasados = SfPedido.query.filter(
        SfPedido.status == "ativo",
        SfPedido.data_prevista < today,
    ).count()
    hoje = SfPedido.query.filter(
        SfPedido.status == "ativo",
        SfPedido.data_prevista == today,
    ).count()
    return jsonify({"ok": True, "atrasados": atrasados, "hoje": hoje})


@central_conhecimento_bp.route("/api/alerta_atrasados_diario", methods=["POST"])
@login_required
def api_disparar_alerta_atrasados():
    user_tipo = (getattr(current_user, "tipo", "") or "").lower()
    user_role = (getattr(current_user, "role", "") or "").lower()
    is_admin = getattr(current_user, "is_admin", False) or user_tipo in ["admin", "gestor"] or user_role in ["admin", "gestor"]
    if not is_admin:
        return jsonify({"ok": False, "message": "Apenas administradores e gestores podem disparar este alerta."}), 403

    force_email = None
    if request.is_json and request.json:
        force_email = request.json.get("email")

    from modules.chamados.services.lembretes_flow import enviar_alerta_diario_pedidos_atrasados
    res = enviar_alerta_diario_pedidos_atrasados(current_app._get_current_object(), force_email=force_email)
    return jsonify(res)


# ---------------------------------------------------------------------------
# Configurações do SollusFlow & Alertas de Gestão
# ---------------------------------------------------------------------------

@central_conhecimento_bp.route("/configuracoes", methods=["GET", "POST"])
@login_required
def configuracoes():
    user_tipo = (getattr(current_user, "tipo", "") or "").lower()
    user_role = (getattr(current_user, "role", "") or "").lower()
    perms = current_permissions()
    is_admin = (
        getattr(current_user, "is_admin", False)
        or user_tipo in ["admin", "gestor"]
        or user_role in ["admin", "gestor"]
        or perms.get("admin")
        or perms.get("central_conhecimento_config")
    )
    if not is_admin:
        flash("Acesso restrito a administradores e gestores do sistema.", "warning")
        return redirect(url_for("central_conhecimento.board"))

    from modules.chamados.services.lembretes_flow import (
        get_sollusflow_alert_config,
        save_sollusflow_alert_config,
    )

    if request.method == "POST":
        ativo = bool(request.form.get("ativo"))
        horario = request.form.get("horario", "08:30").strip()
        destinatarios_modo = request.form.get("destinatarios_modo", "selecionados").strip()
        
        usuarios_ids_raw = request.form.getlist("usuarios_ids")
        usuarios_ids = []
        for uid in usuarios_ids_raw:
            try:
                usuarios_ids.append(int(uid))
            except (ValueError, TypeError):
                pass
                
        emails_adicionais = request.form.get("emails_adicionais", "").strip()
        incluir_responsaveis = bool(request.form.get("incluir_responsaveis"))
        apenas_dominio_corporativo = bool(request.form.get("apenas_dominio_corporativo"))
        incluir_ti = bool(request.form.get("incluir_ti"))

        nova_config = {
            "ativo": ativo,
            "horario": horario,
            "destinatarios_modo": destinatarios_modo,
            "usuarios_ids": usuarios_ids,
            "emails_adicionais": emails_adicionais,
            "incluir_responsaveis": incluir_responsaveis,
            "apenas_dominio_corporativo": apenas_dominio_corporativo,
            "incluir_ti": incluir_ti,
        }

        salvo = save_sollusflow_alert_config(nova_config)
        if salvo:
            flash("Configurações do SollusFlow atualizadas com sucesso!", "success")
        else:
            flash("Ocorreu um erro ao salvar as configurações no banco de dados.", "danger")

        return redirect(url_for("central_conhecimento.configuracoes"))

    config = get_sollusflow_alert_config()
    users = (
        User.query
        .filter(User.is_active.is_(True))
        .order_by(User.nome_completo.asc(), User.usuario.asc())
        .all()
    )

    today = date.today()
    pedidos_atrasados_count = SfPedido.query.filter(
        SfPedido.status == "ativo",
        SfPedido.data_prevista.isnot(None),
        SfPedido.data_prevista < today,
    ).count()

    return render_template(
        "chamados/central_conhecimento/configuracoes.html",
        config=config,
        users=users,
        pedidos_atrasados_count=pedidos_atrasados_count,
    )


@central_conhecimento_bp.route("/configuracoes/testar-disparo", methods=["POST"])
@login_required
def api_testar_disparo_alerta():
    user_tipo = (getattr(current_user, "tipo", "") or "").lower()
    user_role = (getattr(current_user, "role", "") or "").lower()
    perms = current_permissions()
    is_admin = (
        getattr(current_user, "is_admin", False)
        or user_tipo in ["admin", "gestor"]
        or user_role in ["admin", "gestor"]
        or perms.get("admin")
    )
    if not is_admin:
        return jsonify({"ok": False, "message": "Acesso não autorizado."}), 403

    target_email = request.form.get("target_email") or (request.json.get("target_email") if request.is_json and request.json else None)
    if not target_email or "@" not in target_email:
        target_email = current_user.email

    from modules.chamados.services.lembretes_flow import enviar_alerta_diario_pedidos_atrasados
    res = enviar_alerta_diario_pedidos_atrasados(current_app._get_current_object(), force_email=target_email)
    return jsonify(res)



# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _parse_date(val) -> date | None:
    if not val:
        return None
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val).strip()[:10])
    except Exception:
        return None


def _parse_valor(val) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    s = s.replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


# Checklist padrao por fase
_CHECKLIST_PADRAO: dict[int, list[str]] = {
    1: ["Receber solicitacao do consultor", "Confirmar tipo de pedido (venda/contrato)", "Registrar data de entrada"],
    2: ["Verificar documentos enviados", "Validar CNPJ no sistema", "Conferir dados do cliente"],
    3: ["Cadastrar cliente no Base ERP", "Confirmar cadastro e codigo do cliente"],
    4: ["Verificar disponibilidade no estoque", "Solicitar reserva do equipamento"],
    5: ["Gerar pedido de venda / contrato", "Enviar para aprovacao se necessario"],
    6: ["Confirmar recebimento do pagamento de entrada", "Registrar comprovante"],
    7: ["Emitir ordem de compra do equipamento", "Acompanhar prazo de entrega"],
    8: ["Enviar pedido/contrato assinado ao cliente", "Confirmar recebimento pelo cliente"],
    9: ["Preparar formulario de instalacao", "Enviar formulario ao cliente"],
    10: ["Agendar data de instalacao", "Confirmar disponibilidade tecnica e do cliente"],
    11: ["Solicitar emissao da nota fiscal", "Solicitar abertura de O.S"],
    12: ["Enviar login e senha do sistema", "Confirmar recebimento pelo cliente"],
    13: ["Enviar e-mail de boas-vindas", "Confirmar recebimento dos acessos pelo cliente"],
    14: ["Alinhar disponibilidade e agendar data do treinamento com o cliente", "Confirmar participação dos responsáveis do cliente", "Realizar e registrar conclusão do treinamento"],
    15: ["Aguardar retorno / posicionamento do cliente", "Realizar follow-up com o cliente se necessário"],
    16: ["1º Contato de Pós-Venda (15 dias após treinamento) - Avaliação de serviços e produtos"],
}


def _criar_checklist_padrao(pedido_id: int, fase: int):
    pedido = SfPedido.query.get(pedido_id)
    items = _CHECKLIST_PADRAO.get(fase, [])
    mariana_id = _get_mariana_user_id()

    for pos, titulo in enumerate(items):
        data_lembrete = None
        responsavel_id = None

        if fase == 16:
            responsavel_id = mariana_id
            ref_date = (pedido.data_treinamento if pedido and pedido.data_treinamento else date.today())
            data_lembrete = ref_date + timedelta(days=15)
        elif fase == 14 and pedido and pedido.data_treinamento:
            data_lembrete = pedido.data_treinamento

        item = SfChecklist(
            pedido_id=pedido_id,
            fase=fase,
            titulo=titulo,
            posicao=pos,
            responsavel_id=responsavel_id,
            data_lembrete=data_lembrete
        )
        db.session.add(item)


# ---------------------------------------------------------------------------
# Redirecionamento legado de /central-conhecimento para /sollus-flow
# ---------------------------------------------------------------------------

@legacy_cc_bp.route("/", defaults={"subpath": ""})
@legacy_cc_bp.route("/<path:subpath>")
def _redirect_legacy_cc(subpath: str = ""):
    target = f"/sollus-flow/{subpath}".rstrip("/") if subpath else "/sollus-flow/"
    if request.query_string:
        target += f"?{request.query_string.decode('utf-8')}"
    return redirect(target, code=302)
