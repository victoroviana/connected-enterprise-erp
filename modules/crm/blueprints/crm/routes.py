"""Rotas do Sollus CRM."""
from __future__ import annotations

import csv
import io
from datetime import datetime, date, timedelta
from typing import Any

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    Response,
)
from flask_login import current_user
from sqlalchemy import func, or_

from extensions import csrf, db
from modules.propostas.blueprints.auth import login_required
from modules.propostas.models import User
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmOrigem,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmInteracao,
    CrmLeadMarketing,
    CrmTemplateMensagem,
    CrmRegraDistribuicao,
    CrmEquipamentoHistoricoPreco,
)
from modules.crm.services import (
    get_pipeline_data,
    move_deal_stage,
    get_deal_details,
    add_note,
    add_task,
    toggle_task,
    mark_deal_won,
    mark_deal_lost,
    capture_lead_from_website,
    create_deal_manual,
    get_crm_deal_form_metadata,
    search_crm_entities,
    format_currency_brl,
    format_datetime_br,
    get_consultor_sales_stats,
)
from modules.crm.services.crm_service import (
    get_cockpit_tasks,
    render_whatsapp_template,
    build_whatsapp_link,
    generate_whatsapp_url,
    sanitize_whatsapp_phone
)
from . import crm_bp
from . import webhooks  # noqa: F401


@crm_bp.before_request
def _ensure_crm_session_auth():
    """Garante que a sessão autenticada do usuário seja reconhecida pelo login_required."""
    from flask import session
    from flask_login import current_user, login_user
    if not current_user.is_authenticated:
        uid = session.get("usuario_id") or session.get("user_id") or session.get("_user_id")
        if uid:
            try:
                user = User.query.get(int(uid))
                if user and user.is_active:
                    login_user(user)
                    session["usuario_id"] = user.id
            except Exception:
                pass




def _can_view_all_deals(user=None) -> bool:
    """Verifica se o usuário pode visualizar todas as negociações no CRM ou apenas as suas próprias."""
    if user is None:
        user = current_user
    if not user or not user.is_authenticated:
        return False
    from modules.propostas.blueprints.auth.permissions_utils import normalize_role_key, current_permissions
    role_key = normalize_role_key(getattr(user, "tipo", None) or getattr(user, "role", None))
    if role_key in ("admin", "administrador", "gestor", "gerente", "coordenador"):
        return True
    try:
        perms = current_permissions()
        if perms.get("crm_ver_todos"):
            return True
    except Exception:
        pass
    return False


def _can_access_deal(deal: CrmNegociacao | None, user=None) -> bool:
    """Verifica se o usuário tem permissão para visualizar/editar uma negociação específica."""
    if not deal:
        return False
    if user is None:
        user = current_user
    if _can_view_all_deals(user):
        return True
    # Negociações sem responsável definido podem ser manipuladas por qualquer usuário com acesso ao CRM
    if deal.user_id is None:
        return True
    return deal.user_id == getattr(user, "id", None)


@crm_bp.route("/")
@login_required
def index():
    """Redireciona para o primeiro funil ativo."""
    funil = CrmFunil.query.filter_by(ativo=True).order_by(CrmFunil.ordem).first()
    if funil:
        return redirect(url_for("crm.kanban", funil_id=funil.id))
    return render_template("crm/empty.html")


@crm_bp.route("/tarefas")
@login_required
def tarefas():
    """Painel unificado de tarefas diárias do vendedor ('Tarefas')."""
    can_view_all = _can_view_all_deals()
    filtro = request.args.get("filtro", "hoje").strip().lower()
    user_id_param = request.args.get("user_id")
    funil_id_param = request.args.get("funil_id")
    deal_status = request.args.get("deal_status", "aberto")
    tipo_param = request.args.get("tipo")
    search_param = request.args.get("search")

    consultores = (
        User.query.filter(
            User.is_active == True,
            or_(
                User.department_id.in_([7, 12, 15]),  # 15: Assistência Técnica
                User.tipo.in_(["consultor", "consultorsp", "tecnico", "assistencia"]),
                User.id.in_([5004, 5005, 5006, 5008, 5009, 5010, 6847, 10, 14, 15, 16, 21, 22, 24, 30, 31, 6699, 6882, 6883, 6884])
            )
        )
        .order_by(User.nome_completo.asc())
        .all()
    )

    if user_id_param == "all":
        user_id = None
    elif user_id_param and user_id_param.isdigit():
        user_id = int(user_id_param) if can_view_all else current_user.id
    else:
        user_id = None if can_view_all else current_user.id

    funil_id = None if funil_id_param in (None, "", "all") else funil_id_param
    tipo = None if tipo_param in (None, "", "all") else tipo_param
    search = search_param.strip() if search_param else None

    cockpit_data = get_cockpit_tasks(
        user_id=user_id,
        funil_id=funil_id,
        tipo=tipo,
        deal_status=deal_status,
        search=search,
    )

    # Filtragem dos itens exibidos
    if filtro in ("atrasadas", "late"):
        tarefas_exibidas = cockpit_data["tasks"]["late"]
    elif filtro in ("hoje", "today"):
        tarefas_exibidas = cockpit_data["tasks"]["today"]
    elif filtro in ("proximas", "upcoming"):
        tarefas_exibidas = cockpit_data["tasks"]["upcoming"]
    elif filtro in ("concluidas", "done"):
        tarefas_exibidas = cockpit_data["tasks"]["done"]
    else:
        # 'todas' ou outro: exibe todas
        tarefas_exibidas = (
            cockpit_data["tasks"]["late"]
            + cockpit_data["tasks"]["today"]
            + cockpit_data["tasks"]["upcoming"]
            + cockpit_data["tasks"]["done"]
        )

    # Suporte a retorno JSON (Accept: application/json ou ?format=json)
    if (
        request.args.get("format") == "json"
        or request.is_json
        or "application/json" in (request.headers.get("Accept") or "")
    ):
        return jsonify({
            "success": True,
            "counts": cockpit_data["counts"],
            "filtro": filtro,
            "total": len(tarefas_exibidas),
            "funil_id": funil_id_param or "all",
            "deal_status": deal_status,
            "tarefas": [t.to_dict() for t in tarefas_exibidas]
        })

    funis = CrmFunil.query.filter_by(ativo=True).order_by(CrmFunil.ordem.asc()).all()
    templates_whatsapp = CrmTemplateMensagem.query.filter_by(ativo=True).all()

    # Separar consultores especificamente comerciais para o seletor executivo
    # Exclui administradores (como Victor Viana) e prioriza os consultores reais
    consultores_comerciais = [
        c for c in consultores
        if (getattr(c, "tipo", "") or "").lower() in ["consultor", "consultorsp"]
           or getattr(c, "department_id", None) == 7
           or c.id in [5008, 5009, 5010, 6847, 5004, 5005, 5058, 5060, 6558]
    ]
    if not consultores_comerciais:
        consultores_comerciais = [c for c in consultores if (getattr(c, "tipo", "") or "").lower() not in ["admin", "supervisorofcina"]] or consultores

    is_consultor_user = (getattr(current_user, "tipo", "") or "").lower() in ["consultor", "consultorsp"]

    # Identificar o consultor em destaque
    consultor_destaque = None
    if user_id:
        consultor_destaque = User.query.get(user_id)
    if not consultor_destaque:
        if is_consultor_user:
            consultor_destaque = current_user
        elif consultores_comerciais:
            # Para gestor e admin, exibe por padrão o primeiro consultor comercial da equipe
            consultor_destaque = consultores_comerciais[0]
        else:
            consultor_destaque = current_user

    sales_stats = get_consultor_sales_stats(
        user_id=consultor_destaque.id if consultor_destaque else None,
        user=consultor_destaque
    )

    return render_template(
        "crm/tarefas.html",
        tarefas=tarefas_exibidas,
        counts=cockpit_data["counts"],
        filtro=filtro,
        user_id=user_id,
        can_view_all_deals=can_view_all,
        funil_id=funil_id_param or "all",
        deal_status=deal_status,
        tipo=tipo_param or "all",
        search=search or "",
        funis=funis,
        consultores=consultores,
        consultores_comerciais=consultores_comerciais,
        templates_whatsapp=[t.to_dict() for t in templates_whatsapp],
        now_date=date.today(),
        now_year=date.today().year,
        form_meta=get_crm_deal_form_metadata(),
        consultor_destaque=consultor_destaque,
        sales_stats=sales_stats,
    )


@crm_bp.route("/api/consultor-vendas/<int:target_user_id>")
@login_required
def api_consultor_vendas(target_user_id: int):
    """Retorna estatísticas de vendas ganhas (mensal, anual, todas) do consultor em JSON."""
    if target_user_id == 0:
        stats = get_consultor_sales_stats(user_id=None, user=None)
        stats["consultor"]["nome"] = "Toda a Equipe Comercial"
        stats["consultor"]["cargo"] = "Equipe Comercial (Geral)"
        stats["consultor"]["email"] = "comercial@sollusgroup.com"
        return jsonify({
            "success": True,
            "data": stats
        })
    u = User.query.get_or_404(target_user_id)
    stats = get_consultor_sales_stats(user_id=u.id, user=u)
    return jsonify({
        "success": True,
        "data": stats
    })


@crm_bp.route("/funil/<funil_id>")
@login_required
def kanban(funil_id: str):
    """Exibe o painel Kanban estilo RD Station CRM para o funil selecionado."""
    can_view_all = _can_view_all_deals()
    user_id_param = request.args.get("user_id")
    if can_view_all:
        user_id = int(user_id_param) if user_id_param and user_id_param.isdigit() else None
        include_unassigned = False
    else:
        user_id = current_user.id
        include_unassigned = True
    search = request.args.get("q", "").strip()
    filial = request.args.get("filial", "").strip()
    status_filter = request.args.get("status", "aberto").strip()
    origem_filter = request.args.get("origem", "").strip()
    temperatura_filter = request.args.get("temperatura", "").strip()

    # Dados do pipeline agrupados por etapa
    pipeline_data = get_pipeline_data(
        funil_id=funil_id,
        user_id=user_id,
        include_unassigned=include_unassigned,
        search=search if search else None,
        filial_filter=filial if filial else None,
        status_filter=status_filter,
        origem_filter=origem_filter if origem_filter else None,
        temperatura_filter=temperatura_filter if temperatura_filter else None
    )

    todos_funis = CrmFunil.query.filter_by(ativo=True).order_by(CrmFunil.ordem).all()
    origens = CrmOrigem.query.filter_by(ativo=True).order_by(CrmOrigem.ordem, CrmOrigem.nome).all()
    consultores = (
        User.query.filter(
            User.is_active == True,
            or_(
                User.department_id.in_([7, 12, 15]),  # 15: Assistência Técnica
                User.tipo.in_(["consultor", "consultorsp", "tecnico", "assistencia"]),
                User.id.in_([5004, 5006, 5008, 5009, 5010, 6847, 10, 14, 15, 16, 21, 22, 24, 30, 31, 6699, 6882, 6883, 6884])
            )
        )
        .order_by(User.nome_completo.asc())
        .all()
    )

    # Filiais suportadas para filtro (Santos substituído por Campos)
    filiais_disponiveis = [
        {"slug": "RJ", "nome": "Technosollus RJ"},
        {"slug": "SP", "nome": "Sollus SP"},
        {"slug": "PR", "nome": "Sollus PR"},
        {"slug": "ES", "nome": "Technosollus ES"},
        {"slug": "CAMPOS", "nome": "Sollus Campos"}
    ]

    return render_template(
        "crm/kanban.html",
        funil=pipeline_data.get("funil"),
        colunas=pipeline_data.get("colunas", []),
        stats=pipeline_data.get("stats", {}),
        todos_funis=[f.to_dict() for f in todos_funis],
        origens=origens,
        consultores=consultores,
        filiais=filiais_disponiveis,
        filtro_user_id=user_id,
        can_view_all_deals=can_view_all,
        filtro_search=search,
        filtro_filial=filial,
        filtro_status=status_filter,
        filtro_origem=origem_filter,
        filtro_temperatura=temperatura_filter,
        form_meta=get_crm_deal_form_metadata(funil_id),
    )


@crm_bp.route("/api/meta-oportunidade", methods=["GET"])
@login_required
def api_meta_oportunidade():
    """Retorna os metadados necessários para o modal de criação de oportunidade."""
    funil_id = request.args.get("funil_id")
    try:
        data = get_crm_deal_form_metadata(funil_id)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        current_app.logger.exception(f"Erro ao obter metadados de oportunidade: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@crm_bp.route("/api/busca-rapida", methods=["GET"])
@login_required
def api_busca_rapida():
    """Busca rápida de empresas e contatos para autocompletar no cadastro de lead/oportunidade."""
    q = request.args.get("q", "").strip()
    try:
        data = search_crm_entities(q)
        return jsonify({"success": True, **data})
    except Exception as e:
        current_app.logger.exception(f"Erro na busca rápida de entidades: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@crm_bp.route("/api/negociacoes/criar", methods=["POST"])
@crm_bp.route("/api/leads/criar", methods=["POST"])
@login_required
def api_criar_negociacao():
    """Cria uma nova Oportunidade / Lead comercial manualmente (Estilo RD Station CRM)."""
    is_json = request.is_json
    if is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict()

    try:
        result = create_deal_manual(data, creator_user=current_user)
        if is_json:
            return jsonify(result)

        flash(result.get("message", "Oportunidade cadastrada com sucesso!"), "success")
        return redirect(url_for("crm.kanban", funil_id=result.get("funil_id")))
    except Exception as e:
        current_app.logger.exception(f"Erro ao criar negociação manual: {e}")
        if is_json:
            return jsonify({"success": False, "error": str(e)}), 400
        flash(f"Erro ao cadastrar oportunidade: {e}", "danger")
        return redirect(request.referrer or url_for("crm.index"))


@crm_bp.route("/api/negociacoes/<deal_id>/mover", methods=["POST"])
@login_required
def api_mover_negociacao(deal_id: str):
    """Muda a etapa de uma negociação (Drag & Drop)."""
    deal = CrmNegociacao.query.get_or_404(deal_id)
    if not _can_access_deal(deal):
        return jsonify({"success": False, "error": "Acesso não autorizado a esta negociação"}), 403

    data = request.get_json(force=True, silent=True) or {}
    new_etapa_id = data.get("new_etapa_id")
    if not new_etapa_id:
        return jsonify({"success": False, "error": "Nova etapa não informada"}), 400

    try:
        res = move_deal_stage(deal_id, new_etapa_id, user=current_user)
        return jsonify(res)
    except Exception as e:
        current_app.logger.exception(f"Erro ao mover negociação {deal_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@crm_bp.route("/api/negociacoes/<deal_id>/detalhes", methods=["GET"])
@login_required
def api_detalhes_negociacao(deal_id: str):
    """Retorna dados completos para a Ficha 360° (Gaveta lateral)."""
    deal = CrmNegociacao.query.get_or_404(deal_id)
    if not _can_access_deal(deal):
        return jsonify({"success": False, "error": "Acesso não autorizado a esta negociação"}), 403

    try:
        detalhes = get_deal_details(deal_id)
        return jsonify({"success": True, "data": detalhes})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 404


@crm_bp.route("/api/negociacoes/<deal_id>/qualificar", methods=["POST"])
@login_required
def api_qualificar_negociacao(deal_id: str):
    """Atualiza campos de qualificação da negociação e dados da empresa."""
    deal = CrmNegociacao.query.get_or_404(deal_id)
    if not _can_access_deal(deal):
        return jsonify({"success": False, "error": "Acesso não autorizado a esta negociação"}), 403
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        data = {}

    temperatura = data.get("temperatura")
    canal_preferencial = data.get("canal_preferencial")
    origem_id = data.get("origem_id")
    canal_origem = data.get("canal_origem")
    fonte_lead = data.get("fonte_lead")
    nivel_interesse = data.get("nivel_interesse")
    localidade_lead = data.get("localidade_lead")
    campanha = data.get("campanha")
    satisfacao_cliente = data.get("satisfacao_cliente")
    pos_venda_obs = data.get("pos_venda_obs")
    porte = data.get("porte")
    numero_funcionarios = data.get("numero_funcionarios")
    necessidade = data.get("necessidade")

    if "temperatura" in data:
        deal.temperatura = str(temperatura).strip() if temperatura else None
    if "canal_preferencial" in data:
        deal.canal_preferencial = str(canal_preferencial).strip() if canal_preferencial else None
    if "fonte_lead" in data:
        deal.fonte_lead = str(fonte_lead).strip() if fonte_lead else None
    if "nivel_interesse" in data:
        deal.nivel_interesse = str(nivel_interesse).strip() if nivel_interesse else None
    if "localidade_lead" in data:
        deal.localidade_lead = str(localidade_lead).strip() if localidade_lead else None
    if "campanha" in data:
        deal.campanha = str(campanha).strip() if campanha else None
    if "satisfacao_cliente" in data:
        try:
            deal.satisfacao_cliente = int(satisfacao_cliente) if satisfacao_cliente is not None and str(satisfacao_cliente).strip() != "" else None
        except (ValueError, TypeError):
            pass
    if "pos_venda_obs" in data:
        deal.pos_venda_obs = str(pos_venda_obs).strip() if pos_venda_obs else None
        if deal.satisfacao_cliente or deal.pos_venda_obs:
            deal.pos_venda_preenchido_por = getattr(current_user, "nome_completo", None) or getattr(current_user, "usuario", None) or "Pós-Venda"
            deal.pos_venda_em = datetime.utcnow()

    if "origem_id" in data:
        if origem_id is not None and str(origem_id).strip() != "":
            try:
                deal.origem_id = int(origem_id)
                origem_obj = CrmOrigem.query.get(deal.origem_id)
                if origem_obj:
                    deal.origem = origem_obj.nome
                    if not canal_origem and origem_obj.canal:
                        deal.canal_origem = origem_obj.canal
            except (ValueError, TypeError):
                deal.origem_id = None
        else:
            deal.origem_id = None

    if "canal_origem" in data:
        deal.canal_origem = str(canal_origem).strip() if canal_origem else None
    if "necessidade" in data:
        deal.necessidade = str(necessidade).strip() if necessidade else None

    if deal.empresa:
        if "cnpj" in data:
            cnpj_val = str(data.get("cnpj") or "").strip()
            deal.empresa.cnpj = cnpj_val if cnpj_val else None
        if "porte" in data:
            deal.empresa.porte = str(porte).strip() if porte else None
        if "numero_funcionarios" in data:
            if numero_funcionarios is not None and str(numero_funcionarios).strip() != "":
                try:
                    deal.empresa.numero_funcionarios = int(numero_funcionarios)
                except (ValueError, TypeError):
                    deal.empresa.numero_funcionarios = None
            else:
                deal.empresa.numero_funcionarios = None

    deal.updated_at = datetime.utcnow()

    # Timeline note
    temp_desc = deal.temperatura or ""
    canal_desc = deal.canal_preferencial or ""
    inter_desc = deal.nivel_interesse or ""
    fonte_desc = deal.fonte_lead or ""
    conteudo_interacao = f"Qualificação atualizada: Temp {temp_desc}, Canal {canal_desc}, Interesse {inter_desc}, Fonte {fonte_desc}"

    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_id=current_user.id if hasattr(current_user, "id") else None,
        user_name=getattr(current_user, "nome_completo", None) or getattr(current_user, "usuario", None) or "Sistema",
        tipo="anotacao",
        conteudo=conteudo_interacao
    )
    db.session.add(interacao)
    db.session.commit()

    return jsonify({"success": True, "deal": deal.to_dict()}), 200


@crm_bp.route("/api/negociacoes/<deal_id>/pausar", methods=["POST"])
@login_required
def api_pausar_negociacao(deal_id: str):
    """Pausa / congela a negociação no CRM."""
    deal_obj = CrmNegociacao.query.get_or_404(deal_id)
    if not _can_access_deal(deal_obj):
        return jsonify({"success": False, "error": "Acesso não autorizado a esta negociação"}), 403

    data = request.get_json(force=True, silent=True) or {}
    motivo = data.get("motivo")
    u_name = getattr(current_user, "nome_completo", None) or getattr(current_user, "usuario", None) or "Sistema"
    try:
        from modules.crm.services.crm_service import pause_deal
        deal = pause_deal(deal_id, motivo=motivo, user_name=u_name)
        return jsonify({"success": True, "deal": deal.to_dict()}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@crm_bp.route("/api/negociacoes/<deal_id>/reativar", methods=["POST"])
@login_required
def api_reativar_negociacao(deal_id: str):
    """Reativa uma negociação pausada, retornando ao status aberto."""
    deal_obj = CrmNegociacao.query.get_or_404(deal_id)
    if not _can_access_deal(deal_obj):
        return jsonify({"success": False, "error": "Acesso não autorizado a esta negociação"}), 403

    u_name = getattr(current_user, "nome_completo", None) or getattr(current_user, "usuario", None) or "Sistema"
    try:
        from modules.crm.services.crm_service import resume_deal
        deal = resume_deal(deal_id, user_name=u_name)
        return jsonify({"success": True, "deal": deal.to_dict()}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@crm_bp.route("/api/negociacoes/<deal_id>/pos-venda", methods=["POST"])
@login_required
def api_pos_venda_negociacao(deal_id: str):
    """Salva a avaliação de satisfação e dados de pós-venda."""
    deal_obj = CrmNegociacao.query.get_or_404(deal_id)
    if not _can_access_deal(deal_obj):
        return jsonify({"success": False, "error": "Acesso não autorizado a esta negociação"}), 403

    data = request.get_json(force=True, silent=True) or {}
    satisfacao = data.get("satisfacao_cliente")
    obs = data.get("pos_venda_obs")
    u_name = getattr(current_user, "nome_completo", None) or getattr(current_user, "usuario", None) or "Pós-Venda"
    try:
        from modules.crm.services.crm_service import update_deal_pos_venda
        deal = update_deal_pos_venda(deal_id, satisfacao_cliente=satisfacao, pos_venda_obs=obs, user_name=u_name)
        return jsonify({"success": True, "deal": deal.to_dict()}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@crm_bp.route("/api/origens", methods=["GET"])
@login_required
def api_listar_origens():
    """Retorna a lista de origens ativas de oportunidades."""
    origens = CrmOrigem.query.filter_by(ativo=True).order_by(CrmOrigem.ordem.asc(), CrmOrigem.nome.asc()).all()
    origens_list = [o.to_dict() for o in origens]
    return jsonify({
        "success": True,
        "origens": origens_list,
        "total": len(origens_list)
    }), 200


@crm_bp.route("/api/negociacoes/<deal_id>/anotacoes", methods=["POST"])
@crm_bp.route("/api/negociacoes/<deal_id>/interacoes", methods=["POST"])
@login_required
def api_adicionar_anotacao(deal_id: str):
    """Adiciona uma anotação ou interação à timeline."""
    deal_obj = CrmNegociacao.query.get_or_404(deal_id)
    if not _can_access_deal(deal_obj):
        return jsonify({"success": False, "error": "Acesso não autorizado a esta negociação"}), 403

    data = request.get_json(force=True, silent=True) or {}
    conteudo = data.get("conteudo") or data.get("descricao")
    if not conteudo or not str(conteudo).strip():
        return jsonify({"success": False, "error": "Conteúdo não pode ser vazio"}), 400

    tipo = data.get("tipo", "anotacao")
    try:
        nota = add_note(deal_id, str(conteudo).strip(), user=current_user, tipo=tipo)
        return jsonify({
            "success": True,
            "anotacao": nota.to_dict(),
            "interacao": nota.to_dict()
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@crm_bp.route("/api/negociacoes/<deal_id>/tarefas", methods=["POST"])
@login_required
def api_adicionar_tarefa(deal_id: str):
    """Agenda uma nova tarefa."""
    deal_obj = CrmNegociacao.query.get_or_404(deal_id)
    if not _can_access_deal(deal_obj):
        return jsonify({"success": False, "error": "Acesso não autorizado a esta negociação"}), 403

    data = request.get_json(force=True, silent=True) or {}
    titulo = data.get("titulo")
    tipo = data.get("tipo", "whatsapp")
    data_str = data.get("data_vencimento")

    if not titulo or not data_str:
        return jsonify({"success": False, "error": "Título e Data são obrigatórios"}), 400

    try:
        # Tenta parsear formato ISO ou datetime-local
        try:
            dt = datetime.fromisoformat(data_str.replace("Z", ""))
        except ValueError:
            dt = datetime.strptime(data_str, "%Y-%m-%dT%H:%M")

        tarefa = add_task(deal_id, titulo, tipo, dt, user=current_user)
        return jsonify({"success": True, "tarefa": tarefa.to_dict()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@crm_bp.route("/api/tarefas/<task_id>/toggle", methods=["POST"])
@login_required
def api_toggle_tarefa(task_id: str):
    """Marca ou desmarca uma tarefa como concluída."""
    data = request.get_json(force=True, silent=True) or {}
    concluida = bool(data.get("concluida", True))
    try:
        tarefa = toggle_task(task_id, concluida, user=current_user)
        return jsonify({"success": True, "tarefa": tarefa.to_dict()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


DEFAULT_WHATSAPP_TEMPLATES = [
    {
        "id": 1,
        "nome": "Primeiro Contato / SDR",
        "conteudo": "Olá {nome_contato}, tudo bem? Sou o {consultor} da Sollus Tecnologia. Recebemos seu interesse para a {empresa}. Quando poderíamos conversar por 5 minutos?"
    },
    {
        "id": 2,
        "nome": "Follow-up de Proposta",
        "conteudo": "Olá {nome_contato}! Aqui é o {consultor} da Sollus. Gostaria de saber se conseguiu avaliar a proposta comercial enviada para a {empresa}: {link_proposta}. Ficou alguma dúvida técnica ou comercial?"
    },
    {
        "id": 3,
        "nome": "Retomada de Negociação",
        "conteudo": "Olá {nome_contato}, como estão as coisas na {empresa}? Passando para saber se ainda está nos planos a implantação do sistema. Temos condições especiais para este mês!"
    },
    {
        "id": 4,
        "nome": "Agendamento de Demonstração",
        "conteudo": "Olá {nome_contato}! {saudacao}! Gostaria de agendar uma rápida demonstração das soluções Sollus para a {empresa}. Qual o melhor dia e horário para você?"
    }
]


@crm_bp.route("/api/templates-whatsapp", methods=["GET"])
@login_required
def api_templates_whatsapp():
    """Retorna templates de mensagens rápidas de WhatsApp cadastrados."""
    templates = CrmTemplateMensagem.query.filter_by(ativo=True).order_by(CrmTemplateMensagem.id.asc()).all()
    if not templates:
        return jsonify({
            "success": True,
            "templates": DEFAULT_WHATSAPP_TEMPLATES
        })
    return jsonify({
        "success": True,
        "templates": [t.to_dict() for t in templates]
    })


@crm_bp.route("/api/templates-whatsapp/render", methods=["POST"])
@login_required
def api_render_template_whatsapp():
    """Renderiza template com variáveis dinâmicas e gera o link WhatsApp."""
    data = request.get_json(force=True, silent=True) or {}
    template_text = data.get("template_text") or data.get("conteudo") or ""
    template_id = data.get("template_id")
    deal_id = data.get("deal_id")
    phone = data.get("telefone") or data.get("phone")

    if template_id and not template_text:
        try:
            tpl = CrmTemplateMensagem.query.get(int(template_id))
            if tpl:
                template_text = tpl.conteudo
        except (ValueError, TypeError):
            tpl = None
        if not template_text:
            for seed in DEFAULT_WHATSAPP_TEMPLATES:
                if str(seed["id"]) == str(template_id):
                    template_text = seed["conteudo"]
                    break

    deal = CrmNegociacao.query.get(deal_id) if deal_id else None
    if not phone and deal and deal.contato:
        phone = deal.contato.celular or deal.contato.telefone

    rendered = render_whatsapp_template(
        template_text,
        deal=deal,
        consultor=current_user,
        request=request
    )

    whatsapp_url = build_whatsapp_link(phone or "", rendered) if phone else ""

    return jsonify({
        "success": True,
        "rendered_text": rendered,
        "whatsapp_url": whatsapp_url,
        "phone_sanitized": sanitize_whatsapp_phone(phone) if phone else None
    })


@crm_bp.route("/api/negociacoes/<deal_id>/ganhar", methods=["POST"])
@login_required
def api_ganhar_negociacao(deal_id: str):
    """Marca negociação como Vendida/Ganha e aciona esteira SollusFlow."""
    try:
        res = mark_deal_won(deal_id, user=current_user)
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@crm_bp.route("/api/negociacoes/<deal_id>/perder", methods=["POST"])
@login_required
def api_perder_negociacao(deal_id: str):
    """Marca negociação como Perdida com motivo e categoria."""
    data = request.get_json(force=True, silent=True) or request.form.to_dict() or {}
    if not data:
        return jsonify({"success": False, "error": "Dados da perda são obrigatórios"}), 400

    raw_motivo = data.get("motivo")
    motivo = str(raw_motivo).strip() if raw_motivo is not None else ""
    if not motivo:
        return jsonify({"success": False, "error": "Motivo da perda é obrigatório"}), 400

    has_categoria_field = ("categoria" in data) or ("motivo_perda_categoria" in data)
    if not has_categoria_field:
        return jsonify({"success": False, "error": "Categoria da perda é obrigatória"}), 400

    raw_cat = data.get("categoria") if "categoria" in data else data.get("motivo_perda_categoria")
    if raw_cat is None:
        return jsonify({"success": False, "error": "Categoria da perda inválida"}), 400
    cat_str = str(raw_cat).strip().lower()
    if not cat_str:
        return jsonify({"success": False, "error": "Categoria da perda inválida"}), 400

    ALLOWED_CATEGORIES = {"preco", "concorrente", "sem_contato", "descarte", "outros", "outro"}
    if cat_str not in ALLOWED_CATEGORIES:
        from modules.crm.models import CrmMotivoPerda
        db_cat = CrmMotivoPerda.query.filter_by(categoria=cat_str).first()
        if not db_cat:
            return jsonify({"success": False, "error": "Categoria da perda inválida"}), 400

    categoria = "outros" if cat_str == "outro" else cat_str
    motivo_perda_id = data.get("motivo_perda_id")
    try:
        res = mark_deal_lost(deal_id, motivo=motivo, user=current_user, categoria=categoria, motivo_perda_id=motivo_perda_id)
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@crm_bp.route("/api/leads/captura", methods=["POST"])
@csrf.exempt
def api_captura_lead():
    """
    ENDPOINT UNIVERSAL DE CAPTURA DIRETA DO SITE (Opção A):
    Recebe leads de formulários (Elementor, CF7, GTM ou Webhook do RD)
    e cadastra como Empresa, Contato e Negociação no CRM.
    """
    data = request.get_json(force=True, silent=True) or request.form.to_dict()
    if not data:
        return jsonify({"error": "Payload vazio ou formato inválido"}), 400

    try:
        res = capture_lead_from_website(data)
        return jsonify({"status": "ok", "data": res}), 201
    except Exception as e:
        current_app.logger.exception(f"Erro na captura de lead: {e}")
        return jsonify({"error": str(e)}), 500


@crm_bp.route("/empresas")
@login_required
def empresas():
    """Listagem e diretório de empresas."""
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "").strip()
    
    query = CrmEmpresa.query
    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                CrmEmpresa.nome.ilike(s),
                CrmEmpresa.cnpj.ilike(s),
                CrmEmpresa.segmento.ilike(s),
                CrmEmpresa.telefone.ilike(s),
                CrmEmpresa.email.ilike(s)
            )
        )
        
    pagination = query.order_by(CrmEmpresa.nome.asc()).paginate(page=page, per_page=25, error_out=False)
    
    return render_template(
        "crm/empresas.html",
        empresas=pagination.items,
        pagination=pagination,
        search=search
    )


@crm_bp.route("/api/empresas/<empresa_id>/detalhes", methods=["GET"])
@login_required
def api_empresa_detalhes(empresa_id: str):
    """Retorna dados completos da empresa para o modal informativo."""
    try:
        from modules.crm.services.crm_service import get_empresa_details
        user_filter = None if _can_view_all_deals() else current_user.id
        detalhes = get_empresa_details(empresa_id, user_id=user_filter)
        return jsonify({"success": True, "empresa": detalhes})
    except Exception as e:
        current_app.logger.exception(f"Erro ao buscar detalhes da empresa {empresa_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 404


@crm_bp.route("/api/empresas/<empresa_id>/editar", methods=["POST"])
@login_required
def api_empresa_editar(empresa_id: str):
    """Atualiza dados cadastrais da empresa a partir do modal."""
    try:
        from modules.crm.services.crm_service import update_empresa_details
        data = request.get_json(force=True, silent=True) or {}
        empresa = update_empresa_details(
            empresa_id,
            data,
            user_name=getattr(current_user, "name", None) or getattr(current_user, "username", "Usuário")
        )
        return jsonify({
            "success": True,
            "message": "Dados da empresa atualizados com sucesso!",
            "empresa": empresa.to_dict()
        })
    except Exception as e:
        current_app.logger.exception(f"Erro ao atualizar empresa {empresa_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 400


@crm_bp.route("/contatos")
@login_required
def contatos():
    """Listagem de contatos comerciais."""
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "").strip()

    query = CrmContato.query
    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                CrmContato.nome.ilike(s),
                CrmContato.email.ilike(s),
                CrmContato.telefone.ilike(s),
                CrmContato.celular.ilike(s)
            )
        )

    pagination = query.order_by(CrmContato.nome.asc()).paginate(page=page, per_page=25, error_out=False)

    return render_template(
        "crm/contatos.html",
        contatos=pagination.items,
        pagination=pagination,
        search=search
    )


def _filter_leads_query(query, req):
    search = req.args.get("q", "").strip()
    perfil = req.args.get("perfil", "").strip().upper()
    tag = (req.args.get("tag") or req.args.get("tags") or "").strip()
    estado = (req.args.get("estado") or req.args.get("uf") or "").strip()
    ddd = req.args.get("ddd", "").strip()

    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                CrmLeadMarketing.nome.ilike(s),
                CrmLeadMarketing.email.ilike(s),
                CrmLeadMarketing.empresa.ilike(s),
                CrmLeadMarketing.telefone.ilike(s),
                CrmLeadMarketing.celular.ilike(s),
            )
        )
    if perfil in ("A", "B", "C", "D"):
        query = query.filter_by(lead_scoring_perfil=perfil)

    if tag:
        query = query.filter(CrmLeadMarketing.tags.ilike(f"%{tag}%"))

    if estado:
        query = query.filter(CrmLeadMarketing.estado.ilike(f"%{estado}%"))

    if ddd:
        query = query.filter(
            or_(
                CrmLeadMarketing.telefone.ilike(f"%({ddd})%"),
                CrmLeadMarketing.telefone.ilike(f"% {ddd} %"),
                CrmLeadMarketing.celular.ilike(f"%({ddd})%"),
                CrmLeadMarketing.celular.ilike(f"% {ddd} %"),
            )
        )
    return query


def _export_leads_csv(query):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=",")
    writer.writerow(["Nome", "Email", "Telefone", "Empresa", "Estado", "Cidade", "Tags", "Score Perfil", "Score Interesse", "Origem", "Conversoes"])
    for lead in query.order_by(CrmLeadMarketing.id.asc()).all():
        writer.writerow([
            lead.nome or "",
            lead.email or "",
            lead.telefone or lead.celular or "",
            lead.empresa or "",
            lead.estado or "",
            lead.cidade or "",
            lead.tags or "",
            lead.lead_scoring_perfil or "",
            lead.lead_scoring_interesse or 0,
            lead.origem_primeira or "",
            lead.total_conversoes or 1,
        ])
    csv_content = output.getvalue()
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=leads_export.csv",
            "Content-Type": "text/csv; charset=utf-8",
        }
    )


@crm_bp.route("/leads")
@login_required
def leads():
    """Base de leads importada do RD Station Marketing."""
    if request.args.get("export") == "csv":
        return _export_leads_csv(_filter_leads_query(CrmLeadMarketing.query, request))

    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "").strip()
    perfil = request.args.get("perfil", "").strip().upper()
    tag = (request.args.get("tag") or request.args.get("tags") or "").strip()
    estado = (request.args.get("estado") or request.args.get("uf") or "").strip()

    query = _filter_leads_query(CrmLeadMarketing.query, request)

    pagination = query.order_by(
        CrmLeadMarketing.lead_scoring_interesse.desc(),
        CrmLeadMarketing.id.desc()
    ).paginate(page=page, per_page=25, error_out=False)

    return render_template(
        "crm/leads.html",
        leads=pagination.items,
        pagination=pagination,
        search=search,
        filtro_perfil=perfil,
        filtro_tag=tag,
        filtro_estado=estado,
        form_meta=get_crm_deal_form_metadata(),
    )


@crm_bp.route("/leads/export")
@login_required
def leads_export():
    """Exportação CSV da base filtrada de leads."""
    query = _filter_leads_query(CrmLeadMarketing.query, request)
    return _export_leads_csv(query)


@crm_bp.route("/api/leads/<int:lead_id>/detalhes", methods=["GET"])
@crm_bp.route("/api/leads/<int:lead_id>/historico", methods=["GET"])
@login_required
def api_lead_detalhes(lead_id: int):
    """Retorna detalhes e histórico de conversões do lead para o drawer."""
    lead = CrmLeadMarketing.query.get_or_404(lead_id)
    lead_dict = lead.to_dict()
    lead_dict["total_conversoes"] = lead.total_conversoes
    lead_dict["evento_conversao"] = lead.evento_conversao or ""
    return jsonify({
        "success": True,
        "lead": lead_dict,
        "data": lead_dict,
    })


@crm_bp.route("/metricas")
@login_required
def metricas():
    """Dashboard de métricas comerciais."""
    # Métricas consolidadas por funil
    funis = CrmFunil.query.filter_by(ativo=True).order_by(CrmFunil.ordem).all()
    
    stats_funis = []
    for f in funis:
        total_deals = CrmNegociacao.query.filter_by(funil_id=f.id).count()
        ganhos = CrmNegociacao.query.filter_by(funil_id=f.id, status="ganho").count()
        perdidos = CrmNegociacao.query.filter_by(funil_id=f.id, status="perdido").count()
        abertos = CrmNegociacao.query.filter_by(funil_id=f.id, status="aberto").count()
        valor_total_ganho = db.session.query(func.sum(CrmNegociacao.valor_total)).filter_by(funil_id=f.id, status="ganho").scalar() or 0.0

        taxa_conversao = (ganhos / (ganhos + perdidos) * 100) if (ganhos + perdidos) > 0 else 0.0
        
        stats_funis.append({
            "funil": f,
            "total": total_deals,
            "abertos": abertos,
            "ganhos": ganhos,
            "perdidos": perdidos,
            "taxa_conversao": round(taxa_conversao, 1),
            "valor_ganho": format_currency_brl(valor_total_ganho)
        })

    # Ranking de Consultores
    commercial_user_ids = [5004, 5006, 5008, 5009, 5010, 6847]
    ranking_rows = (
        db.session.query(
            CrmNegociacao.user_name,
            func.count(CrmNegociacao.id).label("total_vendas"),
            func.sum(CrmNegociacao.valor_total).label("valor_total")
        )
        .filter(
            CrmNegociacao.status == "ganho",
            CrmNegociacao.user_name.isnot(None),
            CrmNegociacao.user_id.in_(commercial_user_ids)
        )
        .group_by(CrmNegociacao.user_name)
        .order_by(func.sum(CrmNegociacao.valor_total).desc())
        .limit(10)
        .all()
    )

    ranking = [
        {
            "nome": row.user_name,
            "vendas": row.total_vendas,
            "valor": format_currency_brl(row.valor_total)
        }
        for row in ranking_rows
    ]

    from modules.crm.services.crm_service import (
        get_channel_conversion_metrics,
        get_lead_geo_distribution,
        get_loss_reasons_breakdown,
    )
    metricas_canais = get_channel_conversion_metrics()
    geo_radar = get_lead_geo_distribution()
    motivos_perda_data = get_loss_reasons_breakdown()

    canais_dict = metricas_canais.get("channels", {})
    for c in canais_dict.values():
        c["valor_formatado"] = format_currency_brl(c.get("valor_total_ganho", 0.0))

    geo_dict = geo_radar.get("by_state", {})
    for g in geo_dict.values():
        g["valor_formatado"] = format_currency_brl(g.get("total_valor", 0.0))

    motivos_dict = motivos_perda_data.get("by_category", {})
    for m in motivos_dict.values():
        m["valor_formatado"] = format_currency_brl(m.get("total_value", 0.0))

    return render_template(
        "crm/metricas.html",
        stats_funis=stats_funis,
        ranking=ranking,
        canais_metricas=canais_dict,
        geo_radar=geo_dict,
        motivos_perda=motivos_dict,
        total_perdido_valor=format_currency_brl(motivos_perda_data.get("total_lost_value", 0.0)),
        total_perdido_count=motivos_perda_data.get("total_lost_count", 0),
    )


# --------------------------------------------------------------------------- #
# DESTINO DE LEADS (ROTEAMENTO REGIONAL DE LEADS)
# --------------------------------------------------------------------------- #

@crm_bp.route("/destino-leads")
@login_required
def destino_leads():
    """Configuração do destino de leads por região e estado."""
    from modules.crm.services.crm_service import STATE_TO_DDDS, STATE_NAMES

    regras = (
        CrmRegraDistribuicao.query.order_by(
            CrmRegraDistribuicao.ordem.asc(), CrmRegraDistribuicao.id.asc()
        ).all()
    )

    # Apenas consultores comerciais ativos (Ricardo Simões é Gerente de Projetos e não faz mais parte do Comercial)
    consultores = (
        User.query.filter(
            User.is_active == True,
            User.id != 5006,  # Exclui Ricardo Simões
            or_(
                User.tipo.ilike("%consultor%"),
                User.tipo.ilike("%comercial%"),
                User.id.in_([5004, 5008, 5009, 5010, 6847]),
            ),
        )
        .order_by(User.nome_completo.asc(), User.usuario.asc())
        .all()
    )

    estados_brasil = [
        ("RJ_NORTE", "Rio de Janeiro - Norte Fluminense, Lagos e Campos (DDD 22)"),
        ("RJ_CAPITAL", "Rio de Janeiro - Capital, Baixada e Demais (DDDs 21 e 24)"),
        ("SP", "São Paulo (SP)"),
        ("RJ", "Rio de Janeiro - Todo o Estado (Geral)"),
        ("CAMPOS", "Campos dos Goytacazes & Região dos Lagos (DDD 22)"),
        ("MG", "Minas Gerais (MG)"),
        ("ES", "Espírito Santo (ES)"),
        ("PR", "Paraná (PR)"),
        ("SC", "Santa Catarina (SC)"),
        ("RS", "Rio Grande do Sul (RS)"),
        ("DF", "Distrito Federal (DF)"),
        ("GO", "Goiás (GO)"),
        ("BA", "Bahia (BA)"),
        ("PE", "Pernambuco (PE)"),
        ("CE", "Ceará (CE)"),
        ("MT", "Mato Grosso (MT)"),
        ("MS", "Mato Grosso do Sul (MS)"),
        ("AM", "Amazonas (AM)"),
        ("PA", "Pará (PA)"),
        ("MA", "Maranhão (MA)"),
        ("PB", "Paraíba (PB)"),
        ("RN", "Rio Grande do Norte (RN)"),
        ("AL", "Alagoas (AL)"),
        ("SE", "Sergipe (SE)"),
        ("PI", "Piauí (PI)"),
        ("TO", "Tocantins (TO)"),
        ("RO", "Rondônia (RO)"),
        ("AC", "Acre (AC)"),
        ("AP", "Amapá (AP)"),
        ("RR", "Roraima (RR)"),
        ("OUTROS", "Demais Regiões (Nacional)"),
    ]

    return render_template(
        "crm/destino_leads.html",
        regras=regras,
        consultores=consultores,
        estados_brasil=estados_brasil,
    )


@crm_bp.route("/destino-leads/salvar", methods=["POST"])
@login_required
def destino_leads_salvar():
    """Cria ou atualiza uma regra de roteamento regional de leads (DDDs automáticos)."""
    from modules.crm.services.crm_service import STATE_TO_DDDS, STATE_NAMES

    data = request.get_json(silent=True) or request.form

    regra_id = data.get("regra_id") or data.get("id")
    regiao = (data.get("regiao") or data.get("estado") or "").strip().upper()
    consultor_id = data.get("consultor_id")
    ativo = str(data.get("ativo", "true")).lower() in ("true", "1", "on")

    if not regiao:
        if request.is_json:
            return jsonify({"success": False, "error": "Escolha do Estado é obrigatória"}), 400
        flash("Escolha do Estado é obrigatória.", "danger")
        return redirect(url_for("crm.destino_leads"))

    if not consultor_id:
        if request.is_json:
            return jsonify({"success": False, "error": "Consultor responsável é obrigatório"}), 400
        flash("Consultor responsável é obrigatório.", "danger")
        return redirect(url_for("crm.destino_leads"))

    try:
        cid = int(consultor_id)
        consultor = User.query.get(cid)
        if not consultor or consultor.id == 5006:
            raise ValueError("Consultor inválido")
    except Exception:
        if request.is_json:
            return jsonify({"success": False, "error": "Consultor inválido"}), 400
        flash("Consultor selecionado não foi encontrado.", "danger")
        return redirect(url_for("crm.destino_leads"))

    # Nome da regra: se não especificado, gera automaticamente
    nome = (data.get("nome") or "").strip()
    if not nome:
        nome_est = STATE_NAMES.get(regiao, regiao)
        nome = f"Leads de {nome_est} ({regiao})" if regiao != "OUTROS" else "Demais Regiões (Nacional)"

    # Preenchimento 100% automático de DDDs e Estados a partir da escolha do estado
    if regiao in ("RJ_NORTE", "CAMPOS"):
        estados = "RJ"
        ddds = "22"
        ordem = 5
    elif regiao == "RJ_CAPITAL":
        estados = "RJ"
        ddds = "21,24"
        ordem = 6
    else:
        estados = regiao if regiao != "OUTROS" else ""
        ddds = STATE_TO_DDDS.get(regiao, "")
        ordem = int(data.get("ordem") or (99 if regiao == "OUTROS" else 10))

    regra = None
    if regra_id:
        try:
            regra = CrmRegraDistribuicao.query.get(int(regra_id))
        except (ValueError, TypeError):
            pass

    if regra:
        regra.nome = nome
        regra.regiao = regiao
        regra.estados = estados
        regra.ddds = ddds
        regra.consultor_id = consultor.id
        regra.ativo = ativo
        regra.ordem = ordem
        regra.updated_at = datetime.utcnow()
    else:
        regra = CrmRegraDistribuicao(
            nome=nome,
            regiao=regiao,
            estados=estados,
            ddds=ddds,
            consultor_id=consultor.id,
            ativo=ativo,
            ordem=ordem,
        )
        db.session.add(regra)

    db.session.commit()

    if request.is_json:
        return jsonify({"success": True, "regra": regra.to_dict()})

    flash(f"Regra para '{regra.nome}' salva com sucesso!", "success")
    return redirect(url_for("crm.destino_leads"))


@crm_bp.route("/destino-leads/excluir/<int:id>", methods=["POST"])
@login_required
def destino_leads_excluir(id: int):
    """Remove uma regra de roteamento."""
    regra = CrmRegraDistribuicao.query.get_or_404(id)
    nome = regra.nome
    db.session.delete(regra)
    db.session.commit()

    if request.is_json:
        return jsonify({"success": True, "message": f"Regra '{nome}' removida"})

    flash(f"Regra '{nome}' removida com sucesso.", "success")
    return redirect(url_for("crm.destino_leads"))


@crm_bp.route("/destino-leads/simular", methods=["POST"])
@login_required
def destino_leads_simular():
    """Simulador para o gestor testar o roteamento de leads por DDD, UF ou campanha."""
    data = request.get_json(silent=True) or request.form
    telefone = data.get("telefone") or data.get("celular") or data.get("ddd")
    estado = data.get("estado") or data.get("uf")
    filial = data.get("filial")
    campanha = data.get("campanha")
    nome = data.get("nome") or "Lead Simulação"

    from modules.crm.services.crm_service import detect_lead_region, find_matching_distribution_rule

    det = detect_lead_region(
        filial=filial,
        estado=estado,
        telefone=telefone,
        campanha=campanha,
        nome=nome,
    )

    regra = find_matching_distribution_rule(
        regiao=det.get("regiao"),
        uf=det.get("uf"),
        ddd=det.get("ddd"),
    )

    consultor_dict = None
    if regra and regra.consultor:
        consultor_dict = {
            "id": regra.consultor.id,
            "nome": regra.consultor.nome_completo or regra.consultor.usuario,
            "email": regra.consultor.email or "",
            "tipo": getattr(regra.consultor, "tipo", ""),
        }

    return jsonify({
        "success": True,
        "deteccao": det,
        "regra": regra.to_dict() if regra else None,
        "consultor": consultor_dict,
        "fallback_usado": bool(regra is None),
    })


# --------------------------------------------------------------------------- #
# TABELA DE CONSULTA DE PREÇOS DE EQUIPAMENTOS (CRM & SINCRONIZAÇÃO ESTOQUE)
# --------------------------------------------------------------------------- #

@crm_bp.route("/tabela-precos")
@login_required
def tabela_precos():
    """Tabela de consulta de preços dos equipamentos para consultores do Sollus CRM."""
    from modules.propostas.models import Equipment
    from modules.propostas.blueprints.equipamentos.routes import (
        _resolve_equipment_image_src,
        _build_static_file_index,
    )

    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "").strip()
    filtro = request.args.get("filtro", "todos").strip().lower()
    fabricante = request.args.get("fabricante", "").strip()
    tipo = request.args.get("tipo", "").strip()
    modalidade = request.args.get("modalidade", "todos").strip().lower()

    query = Equipment.query

    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                Equipment.name.ilike(s),
                Equipment.description.ilike(s),
                Equipment.fabricante.ilike(s),
                Equipment.tipo_equipamento.ilike(s),
            )
        )

    if fabricante and fabricante.lower() not in ("todos", "todas", ""):
        query = query.filter(Equipment.fabricante == fabricante)

    if tipo and tipo.lower() not in ("todos", "todas", ""):
        query = query.filter(Equipment.tipo_equipamento == tipo)

    # Filtro de modalidade: no modo locação, mostra todos os itens (todos podem ser locados)
    # com destaque visual para o preço de locação no template.
    # No modo aquisição, mostra somente os que têm preço de aquisição definido.
    if modalidade == "aquisicao":
        query = query.filter(Equipment.unit_price.isnot(None), Equipment.unit_price > 0)
    # modalidade == "locacao" ou "todos": mostra todos os equipamentos sem filtro adicional

    now = datetime.utcnow()
    limite_7dias = now - timedelta(days=7)

    if filtro == "recentes":
        # Apenas equipamentos com alteração de preço nos últimos 7 dias (máximo 1 semana) e com variação real de valor
        query = query.filter(
            Equipment.preco_alterado_em.isnot(None),
            Equipment.preco_alterado_em >= limite_7dias,
            Equipment.preco_anterior.isnot(None),
            Equipment.preco_anterior != Equipment.unit_price,
        ).order_by(
            Equipment.preco_alterado_em.desc()
        )
    else:
        query = query.order_by(Equipment.name.asc())

    pagination = query.paginate(page=page, per_page=24, error_out=False)

    static_index = _build_static_file_index()

    for eq in pagination.items:
        eq.image_src = _resolve_equipment_image_src(
            getattr(eq, "_illustration_path", None),
            getattr(eq, "illustration_path", None),
            index=static_index,
        )
        eq.preco_atual_formatado = format_currency_brl(eq.unit_price or 0.0)
        # Preço de locação: se tiver valor > 0, formata; senão mostra R$ 0,00 (a definir)
        if eq.preco_locacao and eq.preco_locacao > 0:
            eq.preco_locacao_formatado = f"{format_currency_brl(eq.preco_locacao)} /mês"
            eq.preco_locacao_a_definir = False
        else:
            eq.preco_locacao_formatado = f"{format_currency_brl(0.0)} /mês"
            eq.preco_locacao_a_definir = True

        houve_alteracao_real = (
            eq.preco_anterior is not None and abs(float(eq.preco_anterior) - float(eq.unit_price or 0.0)) > 0.001
        )
        if houve_alteracao_real:
            eq.preco_anterior_formatado = format_currency_brl(eq.preco_anterior)
        else:
            eq.preco_anterior_formatado = None

        if eq.preco_alterado_em and houve_alteracao_real:
            eq.alterado_em_formatado = format_datetime_br(eq.preco_alterado_em)
            delta_dias = (now - eq.preco_alterado_em).days
            # Fica no máximo 1 semana (7 dias) com a tag de preço alterado e depois desaparece
            eq.tem_mudanca = (delta_dias <= 7)
            eq.mudanca_recente = (delta_dias <= 7)
        else:
            eq.alterado_em_formatado = None
            eq.tem_mudanca = False
            eq.mudanca_recente = False

    total_equipamentos = Equipment.query.count()
    total_aquisicao = Equipment.query.filter(Equipment.unit_price.isnot(None), Equipment.unit_price > 0).count()
    # Todos os equipamentos podem ser locados — total_locacao = total_equipamentos
    total_locacao = total_equipamentos
    total_com_locacao_definida = Equipment.query.filter(Equipment.preco_locacao.isnot(None), Equipment.preco_locacao > 0).count()
    total_alterados = Equipment.query.filter(
        Equipment.preco_alterado_em.isnot(None),
        Equipment.preco_alterado_em >= limite_7dias,
        Equipment.preco_anterior.isnot(None),
        Equipment.preco_anterior != Equipment.unit_price,
    ).count()

    # Lista de fabricantes e tipos cadastrados nos equipamentos
    try:
        fabricantes_raw = db.session.query(Equipment.fabricante).distinct().order_by(Equipment.fabricante.asc()).all()
        fabricantes = sorted(list({r[0] for r in fabricantes_raw if r[0]}))
    except Exception:
        fabricantes = []

    try:
        tipos_raw = db.session.query(Equipment.tipo_equipamento).distinct().order_by(Equipment.tipo_equipamento.asc()).all()
        tipos_equipamento = sorted(list({r[0] for r in tipos_raw if r[0]}))
    except Exception:
        tipos_equipamento = ["Relógio de Ponto", "Catraca", "Controle de Acesso", "Cancela & Barreira", "Acessórios & Suprimentos"]

    # ------------------------------------------------------------------ #
    # SISTEMAS, SOFTWARES E LICENÇAS SAAS
    # ------------------------------------------------------------------ #
    from modules.propostas.models import SoftwarePlan
    software_query = SoftwarePlan.query.filter_by(is_active=True)

    search_sistema = request.args.get("qs", "").strip()
    fabricante_sistema = request.args.get("fabricante_sistema", "").strip()
    categoria_sistema = request.args.get("categoria_sistema", "").strip()

    if search_sistema:
        ss = f"%{search_sistema}%"
        software_query = software_query.filter(
            or_(
                SoftwarePlan.name.ilike(ss),
                SoftwarePlan.codigo.ilike(ss),
                SoftwarePlan.description.ilike(ss),
                SoftwarePlan.fabricante.ilike(ss),
                SoftwarePlan.faixa_funcionarios.ilike(ss),
            )
        )

    if fabricante_sistema and fabricante_sistema.lower() not in ("todos", "todas", ""):
        software_query = software_query.filter(SoftwarePlan.fabricante == fabricante_sistema)

    if categoria_sistema and categoria_sistema.lower() not in ("todas", "todos", ""):
        software_query = software_query.filter(SoftwarePlan.categoria == categoria_sistema)

    software_plans_list = software_query.order_by(
        SoftwarePlan.fabricante.asc(),
        SoftwarePlan.categoria.asc(),
        SoftwarePlan.valor_mensal.asc()
    ).all()

    for sp in software_plans_list:
        sp.valor_mensal_formatado = format_currency_brl(sp.valor_mensal or 0.0)
        houve_mudanca_real_sp = (
            sp.preco_anterior is not None and abs(float(sp.preco_anterior) - float(sp.valor_mensal or 0.0)) > 0.001
        )
        if houve_mudanca_real_sp:
            sp.preco_anterior_formatado = format_currency_brl(sp.preco_anterior)
        else:
            sp.preco_anterior_formatado = None

        if sp.preco_alterado_em and houve_mudanca_real_sp:
            sp.alterado_em_formatado = format_datetime_br(sp.preco_alterado_em)
            delta_sp = (now - sp.preco_alterado_em).days
            # Tag de Preço Alterado fica no máximo 1 semana (7 dias) e depois desaparece
            sp.tem_mudanca = (delta_sp <= 7)
        else:
            sp.alterado_em_formatado = None
            sp.tem_mudanca = False

    try:
        s_fab_raw = db.session.query(SoftwarePlan.fabricante).distinct().order_by(SoftwarePlan.fabricante.asc()).all()
        sistemas_fabricantes = sorted(list({r[0] for r in s_fab_raw if r[0]}))
    except Exception:
        sistemas_fabricantes = []

    try:
        s_cat_raw = db.session.query(SoftwarePlan.categoria).distinct().order_by(SoftwarePlan.categoria.asc()).all()
        sistemas_categorias = sorted(list({r[0] for r in s_cat_raw if r[0]}))
    except Exception:
        sistemas_categorias = []

    total_sistemas = SoftwarePlan.query.filter_by(is_active=True).count()
    aba = request.args.get("aba", "sistemas" if (search_sistema or fabricante_sistema or categoria_sistema) else "equipamentos")

    return render_template(
        "crm/tabela_precos.html",
        equipamentos=pagination.items,
        pagination=pagination,
        search=search,
        filtro=filtro,
        modalidade=modalidade,
        fabricante=fabricante,
        fabricantes=fabricantes,
        tipo=tipo,
        tipos_equipamento=tipos_equipamento,
        total_equipamentos=total_equipamentos,
        total_aquisicao=total_aquisicao,
        total_locacao=total_locacao,
        total_com_locacao_definida=total_com_locacao_definida,
        total_alterados=total_alterados,
        software_plans=software_plans_list,
        sistemas_fabricantes=sistemas_fabricantes,
        sistemas_categorias=sistemas_categorias,
        total_sistemas=total_sistemas,
        search_sistema=search_sistema,
        fabricante_sistema=fabricante_sistema,
        categoria_sistema=categoria_sistema,
        aba=aba,
    )



@crm_bp.route("/api/equipamentos/<int:equipment_id>/atualizar-preco", methods=["POST"])
@login_required
def api_atualizar_preco_equipamento(equipment_id: int):
    """Atualiza preço, fabricante e/ou descrição do equipamento com auditoria e sincronização bidirecional."""
    from modules.crm.services.crm_service import update_equipment_price_and_description

    data = request.get_json(silent=True) or request.form
    new_price = data.get("preco") or data.get("unit_price")
    new_preco_locacao = data.get("preco_locacao")
    new_desc = data.get("descricao") or data.get("description")
    new_name = data.get("nome") or data.get("name")
    new_fabricante = data.get("fabricante")
    new_tipo = data.get("tipo_equipamento") or data.get("tipo")

    u_name = "CRM"
    try:
        if current_user and getattr(current_user, "is_authenticated", False):
            u_name = current_user.nome_completo or current_user.usuario or "CRM"
    except Exception:
        pass

    try:
        eq, price_changed = update_equipment_price_and_description(
            equipment_id=equipment_id,
            new_price=new_price,
            new_preco_locacao=new_preco_locacao,
            new_description=new_desc,
            new_name=new_name,
            new_fabricante=new_fabricante,
            new_tipo_equipamento=new_tipo,
            user_name=u_name,
            origem="crm_tabela_precos",
        )
        db.session.commit()

        loc_definido = bool(eq.preco_locacao and eq.preco_locacao > 0)
        return jsonify({
            "success": True,
            "equipment_id": eq.id,
            "nome": eq.name,
            "fabricante": eq.fabricante or "",
            "tipo_equipamento": eq.tipo_equipamento or "",
            "novo_preco": eq.unit_price,
            "novo_preco_formatado": format_currency_brl(eq.unit_price),
            "preco_locacao": eq.preco_locacao,
            "preco_locacao_formatado": f"{format_currency_brl(eq.preco_locacao)} /mês" if loc_definido else f"{format_currency_brl(0.0)} /mês",
            "preco_locacao_a_definir": not loc_definido,
            "preco_anterior": eq.preco_anterior,
            "preco_anterior_formatado": format_currency_brl(eq.preco_anterior) if eq.preco_anterior is not None else None,
            "preco_mudou": price_changed,
            "alterado_em": format_datetime_br(eq.preco_alterado_em),
            "alterado_por": eq.preco_alterado_por or u_name,
        })
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400


@crm_bp.route("/api/equipamentos/<int:equipment_id>/historico-precos", methods=["GET"])
@login_required
def api_historico_precos_equipamento(equipment_id: int):
    """Retorna o histórico cronológico de preços de um equipamento."""
    from modules.crm.services.crm_service import get_equipment_price_history
    historico = get_equipment_price_history(equipment_id)
    return jsonify({
        "success": True,
        "equipment_id": equipment_id,
        "historico": historico,
    })


@crm_bp.route("/api/equipamentos/<int:equipment_id>/upload-foto", methods=["POST"])
@login_required
def api_upload_foto_equipamento(equipment_id: int):
    """Permite alterar a foto do equipamento diretamente pelo CRM, sincronizando com o Estoque."""
    from modules.propostas.models import Equipment
    from modules.propostas.blueprints.equipamentos.routes import (
        _save_image_letterbox,
        _resolve_equipment_image_src,
        _build_static_file_index,
    )

    eq = Equipment.query.get_or_404(equipment_id)
    foto = request.files.get("foto") or request.files.get("imagem")
    if not foto or not getattr(foto, "filename", ""):
        return jsonify({"success": False, "error": "Nenhum arquivo de imagem foi enviado"}), 400

    try:
        saved_path = _save_image_letterbox(foto, filename_hint=f"eq_{equipment_id}")
        eq.illustration_path = saved_path
        db.session.commit()

        static_index = _build_static_file_index()
        image_src = _resolve_equipment_image_src(
            eq.illustration_path,
            index=static_index,
        )

        return jsonify({
            "success": True,
            "equipment_id": eq.id,
            "image_src": image_src or url_for("static", filename=saved_path.replace("static/", "")),
            "message": "Foto atualizada com sucesso!"
        })
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400


@crm_bp.route("/api/equipamentos/previa-reajuste", methods=["POST"])
@login_required
def api_previa_reajuste():
    """Calcula a simulação de reajuste em massa e retorna a prévia com valores antes e depois."""
    from modules.propostas.models import Equipment
    from modules.crm.services.crm_service import calculate_adjusted_price

    data = request.get_json(silent=True) or request.form
    equipment_ids = data.get("equipment_ids")
    fabricante = (data.get("fabricante") or "").strip()
    adjustment_type = data.get("adjustment_type", "percentual_aumento")
    try:
        value = float(data.get("value") or 0.0)
    except (ValueError, TypeError):
        value = 0.0
    rounding_mode = data.get("rounding_mode", "none")

    if equipment_ids and isinstance(equipment_ids, list):
        try:
            ids = [int(x) for x in equipment_ids if str(x).isdigit()]
            equipments = Equipment.query.filter(Equipment.id.in_(ids)).order_by(Equipment.name.asc()).all()
        except Exception:
            equipments = Equipment.query.order_by(Equipment.name.asc()).all()
    elif fabricante and fabricante.lower() not in ("todos", "todas", ""):
        equipments = Equipment.query.filter(Equipment.fabricante == fabricante).order_by(Equipment.name.asc()).all()
    else:
        equipments = Equipment.query.order_by(Equipment.name.asc()).all()

    items_previa = []
    for eq in equipments:
        curr_p = float(eq.unit_price or 0.0)
        new_p = calculate_adjusted_price(curr_p, adjustment_type, value, rounding_mode)
        diff = new_p - curr_p
        diff_pct = (diff / curr_p * 100.0) if curr_p > 0 else 0.0

        items_previa.append({
            "id": eq.id,
            "nome": eq.name,
            "fabricante": eq.fabricante or "",
            "preco_atual": curr_p,
            "preco_atual_formatado": format_currency_brl(curr_p),
            "novo_preco": new_p,
            "novo_preco_formatado": format_currency_brl(new_p),
            "diferenca": diff,
            "diferenca_formatada": format_currency_brl(diff),
            "diferenca_percentual": f"{'+' if diff >= 0 else ''}{diff_pct:.1f}%",
        })

    return jsonify({
        "success": True,
        "total_itens": len(items_previa),
        "itens": items_previa,
    })


@crm_bp.route("/api/equipamentos/reajuste-massa", methods=["POST"])
@login_required
def api_reajuste_massa():
    """Aplica o reajuste de preços em lote em todos, por fabricante ou nos itens selecionados."""
    from modules.crm.services.crm_service import apply_bulk_price_adjustment

    data = request.get_json(silent=True) or request.form
    equipment_ids = data.get("equipment_ids")
    fabricante = (data.get("fabricante") or "").strip()
    adjustment_type = data.get("adjustment_type", "percentual_aumento")
    try:
        value = float(data.get("value") or 0.0)
    except (ValueError, TypeError):
        value = 0.0
    rounding_mode = data.get("rounding_mode", "none")

    ids: list[int] | None = None
    if equipment_ids and isinstance(equipment_ids, list):
        try:
            ids = [int(x) for x in equipment_ids if str(x).isdigit()]
        except Exception:
            ids = None

    u_name = "CRM (Reajuste em Massa)"
    try:
        if current_user and getattr(current_user, "is_authenticated", False):
            u_name = current_user.nome_completo or current_user.usuario or u_name
    except Exception:
        pass

    try:
        resultados = apply_bulk_price_adjustment(
            equipment_ids=ids,
            fabricante=fabricante if not ids else None,
            adjustment_type=adjustment_type,
            value=value,
            rounding_mode=rounding_mode,
            user_name=u_name,
            origem="crm_reajuste_massa",
        )
        return jsonify({
            "success": True,
            "total_atualizados": len(resultados),
            "resultados": resultados,
            "message": f"Preço de {len(resultados)} equipamentos reajustado com sucesso!"
        })
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400


# --------------------------------------------------------------------------- #
# APIS PARA SISTEMAS & SOFTWARES (TABELA DE PREÇOS CRM)
# --------------------------------------------------------------------------- #

@crm_bp.route("/api/sistemas/<int:plan_id>/atualizar-preco", methods=["POST"])
@login_required
def api_atualizar_preco_sistema(plan_id: int):
    """Atualiza mensalidade, fabricante, categoria e/ou descrição de um plano de software/sistema."""
    from modules.crm.services.crm_service import update_software_plan_price

    data = request.get_json(silent=True) or request.form
    new_price = data.get("valor_mensal") or data.get("preco") or data.get("unit_price")
    new_desc = data.get("descricao") or data.get("description")
    new_name = data.get("nome") or data.get("name")
    new_fabricante = data.get("fabricante")
    new_categoria = data.get("categoria")
    new_vigencia = data.get("vigencia")
    new_suporte = data.get("suporte_incluso")

    u_name = "CRM"
    try:
        if current_user and getattr(current_user, "is_authenticated", False):
            u_name = current_user.nome_completo or current_user.usuario or "CRM"
    except Exception:
        pass

    try:
        sp, price_changed = update_software_plan_price(
            software_plan_id=plan_id,
            new_price=new_price,
            new_description=new_desc,
            new_name=new_name,
            new_fabricante=new_fabricante,
            new_categoria=new_categoria,
            new_vigencia=new_vigencia,
            new_suporte=new_suporte,
            user_name=u_name,
            origem="crm_tabela_precos",
        )
        db.session.commit()

        return jsonify({
            "success": True,
            "plan_id": sp.id,
            "nome": sp.name,
            "fabricante": sp.fabricante or "",
            "categoria": sp.categoria or "",
            "novo_valor_mensal": sp.valor_mensal,
            "novo_valor_mensal_formatado": format_currency_brl(sp.valor_mensal),
            "preco_anterior": sp.preco_anterior,
            "preco_anterior_formatado": format_currency_brl(sp.preco_anterior) if sp.preco_anterior is not None else None,
            "preco_mudou": price_changed,
            "alterado_em": format_datetime_br(sp.preco_alterado_em),
            "alterado_por": sp.preco_alterado_por or u_name,
        })
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400


@crm_bp.route("/api/sistemas/<int:plan_id>/historico-precos", methods=["GET"])
@login_required
def api_historico_precos_sistema(plan_id: int):
    """Retorna o histórico cronológico de preços de um plano de software/sistema."""
    from modules.crm.services.crm_service import get_software_plan_price_history
    historico = get_software_plan_price_history(plan_id)
    return jsonify({
        "success": True,
        "plan_id": plan_id,
        "historico": historico,
    })


@crm_bp.route("/api/sistemas/previa-reajuste", methods=["POST"])
@login_required
def api_previa_reajuste_sistema():
    """Calcula a simulação de reajuste em massa para planos de sistemas e retorna prévia."""
    from modules.propostas.models import SoftwarePlan
    from modules.crm.services.crm_service import calculate_adjusted_price

    data = request.get_json(silent=True) or request.form
    plan_ids = data.get("plan_ids")
    fabricante = (data.get("fabricante") or "").strip()
    categoria = (data.get("categoria") or "").strip()
    adjustment_type = data.get("adjustment_type", "percentual_aumento")
    try:
        value = float(data.get("value") or 0.0)
    except (ValueError, TypeError):
        value = 0.0
    rounding_mode = data.get("rounding_mode", "none")

    query = SoftwarePlan.query.filter_by(is_active=True)
    if plan_ids and isinstance(plan_ids, list):
        try:
            ids = [int(x) for x in plan_ids if str(x).isdigit()]
            query = query.filter(SoftwarePlan.id.in_(ids))
        except Exception:
            pass
    elif fabricante and fabricante.lower() not in ("todos", "todas", ""):
        query = query.filter(SoftwarePlan.fabricante == fabricante)

    if categoria and categoria.lower() not in ("todos", "todas", ""):
        query = query.filter(SoftwarePlan.categoria == categoria)

    plans = query.order_by(SoftwarePlan.fabricante.asc(), SoftwarePlan.name.asc()).all()

    items_previa = []
    for sp in plans:
        curr_p = float(sp.valor_mensal or 0.0)
        new_p = calculate_adjusted_price(curr_p, adjustment_type, value, rounding_mode)
        diff = new_p - curr_p
        diff_pct = (diff / curr_p * 100.0) if curr_p > 0 else 0.0

        items_previa.append({
            "id": sp.id,
            "nome": sp.name,
            "fabricante": sp.fabricante or "",
            "categoria": sp.categoria or "",
            "preco_atual": curr_p,
            "preco_atual_formatado": format_currency_brl(curr_p),
            "novo_preco": new_p,
            "novo_preco_formatado": format_currency_brl(new_p),
            "diferenca": diff,
            "diferenca_formatada": format_currency_brl(diff),
            "diferenca_percentual": f"{'+' if diff >= 0 else ''}{diff_pct:.1f}%",
        })

    return jsonify({
        "success": True,
        "total_itens": len(items_previa),
        "itens": items_previa,
    })


@crm_bp.route("/api/sistemas/reajuste-massa", methods=["POST"])
@login_required
def api_reajuste_massa_sistema():
    """Aplica o reajuste de preços/mensalidades em massa em planos de software."""
    from modules.crm.services.crm_service import apply_bulk_software_adjustment

    data = request.get_json(silent=True) or request.form
    plan_ids = data.get("plan_ids")
    fabricante = (data.get("fabricante") or "").strip()
    categoria = (data.get("categoria") or "").strip()
    adjustment_type = data.get("adjustment_type", "percentual_aumento")
    try:
        value = float(data.get("value") or 0.0)
    except (ValueError, TypeError):
        value = 0.0
    rounding_mode = data.get("rounding_mode", "none")

    ids: list[int] | None = None
    if plan_ids and isinstance(plan_ids, list):
        try:
            ids = [int(x) for x in plan_ids if str(x).isdigit()]
        except Exception:
            ids = None

    u_name = "CRM (Reajuste Sistemas)"
    try:
        if current_user and getattr(current_user, "is_authenticated", False):
            u_name = current_user.nome_completo or current_user.usuario or u_name
    except Exception:
        pass

    try:
        resultados = apply_bulk_software_adjustment(
            plan_ids=ids,
            fabricante=fabricante if not ids else None,
            categoria=categoria if not ids else None,
            adjustment_type=adjustment_type,
            value=value,
            rounding_mode=rounding_mode,
            user_name=u_name,
            origem="crm_reajuste_massa_sistemas",
        )
        return jsonify({
            "success": True,
            "total_atualizados": len(resultados),
            "resultados": resultados,
            "message": f"Mensalidade de {len(resultados)} planos de software/sistemas reajustada com sucesso!"
        })
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400


@crm_bp.route("/api/auditoria/historico-completo", methods=["GET"])
@login_required
def api_auditoria_historico_completo():
    """Retorna o histórico geral e unificado de auditoria de alterações de preços."""
    from modules.crm.models import CrmEquipamentoHistoricoPreco, CrmSoftwareHistoricoPreco
    from modules.propostas.models import Equipment, SoftwarePlan

    tipo = request.args.get("tipo", "todos").strip().lower()
    dias_str = request.args.get("dias", "todos").strip().lower()
    busca = request.args.get("q", "").strip().lower()

    limite_data = None
    if dias_str.isdigit():
        limite_data = datetime.utcnow() - timedelta(days=int(dias_str))

    registros = []

    # 1. Equipamentos Físicos
    if tipo in ("todos", "equipamentos", "equipamento"):
        q_eq = db.session.query(
            CrmEquipamentoHistoricoPreco, Equipment.name, Equipment.fabricante
        ).join(Equipment, CrmEquipamentoHistoricoPreco.equipment_id == Equipment.id)

        if limite_data:
            q_eq = q_eq.filter(CrmEquipamentoHistoricoPreco.alterado_em >= limite_data)

        for hist, eq_name, eq_fab in q_eq.order_by(CrmEquipamentoHistoricoPreco.alterado_em.desc()).all():
            diff = hist.preco_novo - hist.preco_antigo
            diff_pct = (diff / hist.preco_antigo * 100.0) if hist.preco_antigo > 0 else 0.0
            diff_str = f"{'+' if diff >= 0 else ''}{format_currency_brl(diff)}"
            diff_pct_str = f"{'+' if diff >= 0 else ''}{diff_pct:.1f}%"

            registros.append({
                "id": f"eq_{hist.id}",
                "tipo": "equipamento",
                "tipo_label": "Equipamento",
                "item_id": hist.equipment_id,
                "item_nome": eq_name or f"Equipamento #{hist.equipment_id}",
                "fabricante": eq_fab or "Não definido",
                "preco_antigo": hist.preco_antigo,
                "preco_antigo_formatado": format_currency_brl(hist.preco_antigo),
                "preco_novo": hist.preco_novo,
                "preco_novo_formatado": format_currency_brl(hist.preco_novo),
                "diferenca": diff,
                "diferenca_formatada": diff_str,
                "diferenca_percentual": diff_pct_str,
                "is_aumento": diff >= 0,
                "alterado_em": format_datetime_br(hist.alterado_em),
                "alterado_em_raw": hist.alterado_em.isoformat() if hist.alterado_em else "",
                "alterado_por": hist.alterado_por or "Sistema",
                "origem": hist.origem or "crm_tabela_precos",
                "origem_label": "Reajuste em Massa" if "massa" in (hist.origem or "").lower() else "Tabela de Preços CRM",
            })

    # 2. Sistemas & Softwares
    if tipo in ("todos", "sistemas", "software", "softwares"):
        q_soft = db.session.query(
            CrmSoftwareHistoricoPreco, SoftwarePlan.name, SoftwarePlan.fabricante
        ).join(SoftwarePlan, CrmSoftwareHistoricoPreco.software_plan_id == SoftwarePlan.id)

        if limite_data:
            q_soft = q_soft.filter(CrmSoftwareHistoricoPreco.alterado_em >= limite_data)

        for hist, sp_name, sp_fab in q_soft.order_by(CrmSoftwareHistoricoPreco.alterado_em.desc()).all():
            diff = hist.preco_novo - hist.preco_antigo
            diff_pct = (diff / hist.preco_antigo * 100.0) if hist.preco_antigo > 0 else 0.0
            diff_str = f"{'+' if diff >= 0 else ''}{format_currency_brl(diff)}"
            diff_pct_str = f"{'+' if diff >= 0 else ''}{diff_pct:.1f}%"

            registros.append({
                "id": f"soft_{hist.id}",
                "tipo": "sistema",
                "tipo_label": "Sistema / SaaS",
                "item_id": hist.software_plan_id,
                "item_nome": sp_name or f"Plano #{hist.software_plan_id}",
                "fabricante": sp_fab or "Sollus",
                "preco_antigo": hist.preco_antigo,
                "preco_antigo_formatado": format_currency_brl(hist.preco_antigo),
                "preco_novo": hist.preco_novo,
                "preco_novo_formatado": format_currency_brl(hist.preco_novo),
                "diferenca": diff,
                "diferenca_formatada": diff_str,
                "diferenca_percentual": diff_pct_str,
                "is_aumento": diff >= 0,
                "alterado_em": format_datetime_br(hist.alterado_em),
                "alterado_em_raw": hist.alterado_em.isoformat() if hist.alterado_em else "",
                "alterado_por": hist.alterado_por or "Sistema",
                "origem": hist.origem or "crm_tabela_precos",
                "origem_label": "Reajuste em Massa" if "massa" in (hist.origem or "").lower() else "Tabela de Preços CRM",
            })

    # Ordena pelo mais recente
    registros.sort(key=lambda x: x["alterado_em_raw"], reverse=True)

    # Filtragem textual se houver busca
    if busca:
        registros = [
            r for r in registros
            if busca in r["item_nome"].lower()
            or busca in r["fabricante"].lower()
            or busca in r["alterado_por"].lower()
            or busca in r["origem_label"].lower()
        ]

    return jsonify({
        "success": True,
        "total": len(registros),
        "registros": registros
    })



