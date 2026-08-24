"""Rotas da assistência técnica (tarefas do legado)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List
import io
import unicodedata

from utils.helpers import (
    wants_json as _wants_json,
    format_date as _format_date,
)

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
    Blueprint,
    current_app,
    jsonify,
)
from flask_login import current_user, login_required
from sqlalchemy import text, exc

from extensions import db
from modules.propostas.blueprints.auth.permissions_utils import normalize_role_key, raw_permissions, current_permissions
from modules.propostas.models import AgendaEntry, User, Department, Equipment, Part
from ..forms import (
    ChamadoFiltroForm,
    CriarChamadoForm,
    EditarChamadoForm,
    FecharChamadoForm,
    AssistenciaEnvioForm,
    AssistenciaFiltroForm,
    AssistenciaRespostaForm,
    AssistenciaTarefaForm,
    EditarAssistenciaTarefaForm,
)
from ..models import (
    AssistenciaAnexo,
    AssistenciaEquipamentoProposta,
    AssistenciaOrcamento,
    AssistenciaTarefa,
    OrcamentoStatus,
    OrcamentoTemplate,
)
from ..services.assistencia import (
    ASSIST_STATUS,
    anexos_payload,
    available_departamentos,
    available_unidades,
    create_task_from_form,
    ensure_assistencia_schema,
    mark_factory_followup_if_needed,
    mark_os_devolucao_if_needed,
    fetch_tasks_cached,
    fetch_status_counts,
    enforce_decision_rules,
    normalize_status,
    resolve_assist_file,
    save_resposta_file,
    status_counters,
    update_factory_from_form,
    update_task_from_form,
)
from ..services.chamados import list_regions
from ..services.cnpj import (
    ReceitaAPIError,
    fetch_receita_data,
    normalize_cnpj,
    upsert_empresa_from_receita,
)
from ..services.assistencia_email import (
    send_assistencia_fabrica_email,
    send_assistencia_update_email,
)
from ..services.orcamentos import (
    ORCAMENTO_DEFINITIONS,
    build_orcamento_context,
    build_orcamento_items,
    build_snapshot,
    list_orcamento_types,
)
from .shared_agenda import register_agenda_routes

assist_bp = Blueprint("assist_bp", __name__, url_prefix="/assistencia")
register_agenda_routes(assist_bp)

STATUS_LABEL_MAP = {
    "Entrada": "Entrada",
    "em progresso": "Conserto interno",
    "fabrica": "Envio fábrica",
    "aguardando": "Aguardando retorno/aprovação",
    "concluído": "Retorno / testes finais",
    "devolucao_sem_reparo": "Devolucao sem reparo",
    "descarte": "Descarte",
    "retorno": "Retorno",
}
STATUS_DEPT_OWNERS = {
    "Entrada": {"ASSISTENCIA TECNICA", "ESTOQUE"},
    "em progresso": {"OFICINA", "ASSISTENCIA TECNICA"},
    "fabrica": {"ESTOQUE", "ASSISTENCIA TECNICA"},
    "aguardando": {"ASSISTENCIA TECNICA"},
    "concluído": {"OFICINA", "ASSISTENCIA TECNICA", "ESTOQUE"},
    "devolucao_sem_reparo": {"ASSISTENCIA TECNICA"},
    "descarte": {"ASSISTENCIA TECNICA"},
    "retorno": {"ESTOQUE", "ASSISTENCIA TECNICA"},
}
JOURNEY_STEPS = [
    {"key": "Entrada", "title": "Chegada / triagem", "owners": ["Assistência Técnica"]},
    {"key": "em progresso", "title": "Conserto interno", "owners": ["Oficina", "Assistência Técnica"]},
    {"key": "fabrica", "title": "Envio fábrica", "owners": ["Estoque", "Assistência Técnica"]},
    {"key": "aguardando", "title": "Aguardando retorno/aprovação", "owners": ["Assistência Técnica", "Cliente"]},
    {"key": "concluído", "title": "Retorno / testes finais", "owners": ["Oficina", "Assistência Técnica", "Estoque"]},
    {"key": "descarte", "title": "Descarte", "owners": ["Assistência Técnica"]},
    {"key": "retorno", "title": "Retorno", "owners": ["Estoque", "Assistência Técnica"]},
]


def _actor_label() -> str:
    return (
        getattr(current_user, "nome_completo", None)
        or getattr(current_user, "email", None)
        or "usuário"
    )


def _is_admin_like() -> bool:
    role = (getattr(current_user, "tipo", None) or session.get("tipo") or "").lower()
    return role in {"admin", "gestor"}


def _find_task_by_orcamento_os(orcamento: OrcamentoStatus) -> AssistenciaTarefa | None:
    os_code = (orcamento.ordem_servico or "").strip()
    if not os_code:
        return None
    candidates = {os_code}
    for suffix in (" SRJ", " TRJ", " SCP", " SES", " SPR", " SSP"):
        if os_code.upper().endswith(suffix):
            candidates.add(os_code[: -len(suffix)])
        else:
            candidates.add(f"{os_code}{suffix}")
    return AssistenciaTarefa.query.filter(AssistenciaTarefa.OS.in_(candidates)).first()


def _mark_devolucao_sem_reparo_from_budget(orcamento: OrcamentoStatus, actor: str) -> bool:
    tarefa = _find_task_by_orcamento_os(orcamento)
    if not tarefa:
        return False
    before_status = tarefa.status
    tarefa._actor = actor
    tarefa.status = "devolucao_sem_reparo"
    tarefa.ORCAMENTO = orcamento.status
    tarefa.notificacao = "devolucao"
    tarefa.data_modificacao = datetime.utcnow()
    ts = datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S")
    line = f"{ts} - Cliente nao aprovou o orcamento; OS marcada para devolucao sem reparo."
    tarefa.atualizacoes = ((tarefa.atualizacoes or "") + "<br>" if tarefa.atualizacoes else "") + line
    mark_os_devolucao_if_needed(tarefa, before_status=before_status, actor=actor)
    return True


def _can_edit_orcamento(orcamento) -> bool:
    if _is_admin_like():
        return True
    created_by = (getattr(orcamento, "created_by", None) or "").strip()
    if not created_by:
        return False
    actor = _actor_label().strip()
    if actor and created_by.lower() == actor.lower():
        return True
    user_email = (getattr(current_user, "email", None) or "").strip().lower()
    if user_email and user_email in created_by.lower():
        return True
    user_name = (getattr(current_user, "nome_completo", None) or "").strip().lower()
    if user_name and user_name in created_by.lower():
        return True
    return False


def _dept_names(user=None) -> set[str]:
    actor = user or current_user
    names: set[str] = set()
    try:
        for name in getattr(actor, "department_names", []) or []:
            cleaned = (name or "").strip()
            if cleaned:
                normalized = unicodedata.normalize("NFKD", cleaned)
                normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
                names.add(normalized.upper())
    except Exception:
        return set()
    return names


def _role_key() -> str:
    return normalize_role_key(getattr(current_user, "tipo", None) or session.get("tipo"))


def _has_assist_admin_permission() -> bool:
    perms = current_permissions()
    return perms.get("admin_assistencia") or perms.get("admin_suporte")


def _enforce_department_for_status(status: str) -> bool:
    """Restringe movimentação por setor, exceto admins."""
    if _role_key() in ("admin", "gestor") or _has_assist_admin_permission():
        return True
    dept_names = _dept_names()
    if not dept_names:
        return True  # sem departamento definido, não bloquear
    allowed = STATUS_DEPT_OWNERS.get(status)
    if not allowed:
        return True
    return bool(dept_names & allowed)


def _decorate_task(task: AssistenciaTarefa) -> Dict:
    today = date.today()
    due_days = None
    try:
        due_days = (task.data_fim - today).days if task.data_fim else None
    except Exception:
        due_days = None
    if due_days is None:
        due_class = "muted"
    elif due_days < 0:
        due_class = "danger"
    elif due_days <= 3:
        due_class = "warning"
    else:
        due_class = "ok"

    logs = getattr(task, "logs", []) or []
    try:
        logs = sorted(
            logs,
            key=lambda l: l.data_modificacao or datetime.min,
            reverse=True,
        )[:5]
    except Exception:
        logs = []

    # Monitoramento de fábrica: se enviado e sem retorno, alerta após 15 dias
    factory_waiting_days = None
    factory_followup_needed = False
    try:
        if task.data_envio and not task.data_retorno:
            factory_waiting_days = (today - task.data_envio).days
            factory_followup_needed = factory_waiting_days >= 15
    except Exception:
        factory_waiting_days = None
        factory_followup_needed = False

    requires_budget = False
    try:
        contrato = (task.CONTRATO or "").strip().lower()
        requires_budget = contrato != "sim" and (task.status in {"em progresso", "aguardando", "fabrica"})
    except Exception:
        requires_budget = False
    fluxo_tipo = "fabrica" if (task.status == "fabrica") else "interno"

    payload = task.to_dict()
    for key in (
        "nome",
        "cnpj",
        "departamento_responsavel",
        "usuario_designado",
        "descricao",
        "unidade",
        "os",
        "tipo_entrada",
        "orcamento",
        "contrato",
        "status",
        "criado_por",
        "atualizacoes",
        "resposta",
        "notificacao",
    ):
        if key in payload:
            payload[key] = _sanitize_text(payload.get(key))
    payload["unidade_label"] = _display_unit(payload.get("unidade"))
    payload["departamento_label"] = _display_departamento(payload.get("departamento_responsavel"))

    return {
        **payload,
        "status_label": task.status_label(),
        "due_days": due_days,
        "due_class": due_class,
        "fluxo_tipo": fluxo_tipo,
        "requires_budget": requires_budget,
        "factory_waiting_days": factory_waiting_days,
        "factory_followup_needed": factory_followup_needed,
        "anexos": anexos_payload(task),
        "resposta_name": Path(task.resposta).name if task.resposta else None,
        "logs": [
            {
                "campo": _sanitize_text(log.campo),
                "valor_antigo": _sanitize_text(log.valor_antigo),
                "valor_novo": _sanitize_text(log.valor_novo),
                "modificado_por": _sanitize_text(log.modificado_por),
                "data_modificacao": log.data_modificacao.strftime("%d/%m %H:%M")
                if log.data_modificacao
                else None,
            }
            for log in logs
        ],
    }


def _fill_common_choices(*forms):
    unidades = [
        "Rio de Janeiro",
        "Campos",
        "Espirito Santo",
        "Curitiba",
        "Sao Paulo",
    ]
    departamentos = ["SUPORTE", "OFICINA", "ESTOQUE", "ASSISTENCIA TECNICA", "AGUARDANDO"]

    unidade_choices = [(u, u) for u in unidades]
    departamento_choices = [(d, d) for d in departamentos]
    
    from .shared_agenda import _technician_role_slugs as shared_tech_slugs
    tech_slugs = shared_tech_slugs()
    tech_query = User.query.filter(User.is_active.is_(True))
    if tech_slugs:
        tech_query = tech_query.filter(db.func.lower(User.tipo).in_(tech_slugs))
    techs = tech_query.order_by(User.nome_completo.asc()).all()
    tech_choices = [("", "Selecione")] + [(t.nome_completo, t.nome_completo) for t in techs if t.nome_completo]
    tipo_atendimento_choices = [("", "Selecione")] + [(x, x) for x in ["SKYPE", "TREINAMENTO", "AVULSO", "EMAIL", "WHATSAPP", "DEMONSTRACAO", "INSTALACAO", "ATENDIMENTO", "ATENDIMENTO AVULSO", "EXTERNO", "TREINAMENTO COLETIVO"]]

    for form in forms:
        if hasattr(form, "unidade"):
            form.unidade.choices = unidade_choices
        if hasattr(form, "departamento_responsavel"):
            form.departamento_responsavel.choices = departamento_choices
            try:
                if not form.departamento_responsavel.data:
                    form.departamento_responsavel.data = "OFICINA"
            except Exception:
                pass
        if hasattr(form, "departamento"):
            form.departamento.choices = [("", "Todos")] + departamento_choices
        if hasattr(form, "unidade") and isinstance(form, AssistenciaFiltroForm):
            form.unidade.choices = [("", "Todas")] + unidade_choices
        if hasattr(form, "usuario_designado"):
            form.usuario_designado.choices = tech_choices
        if hasattr(form, "tipo_atendimento"):
            form.tipo_atendimento.choices = tipo_atendimento_choices


def fix_encoding(text):
    """Corrige problemas de encoding (UTF-8 interpretado como Latin-1)."""
    if not text:
        return text
    if not isinstance(text, str):
        return str(text)
    try:
        return text.encode('latin1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


UNIT_LABELS = {
    "Espirito Santo": "Espírito Santo",
    "Sao Paulo": "São Paulo",
}
DEPARTAMENTO_LABELS = {
    "ASSISTENCIA TECNICA": "ASSISTÊNCIA TÉCNICA",
}


def _sanitize_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        return fix_encoding(value)
    return value


def _display_unit(value: str | None) -> str | None:
    cleaned = _sanitize_text(value)
    if not cleaned:
        return cleaned
    return UNIT_LABELS.get(cleaned, cleaned)


def _display_departamento(value: str | None) -> str | None:
    cleaned = _sanitize_text(value)
    if not cleaned:
        return cleaned
    key = cleaned.strip().upper()
    return DEPARTAMENTO_LABELS.get(key, cleaned)




def _deny_access(area_label: str):
    if _wants_json():
        return jsonify({"ok": False, "message": "Você não tem permissão para acessar esta área."}), 403
    flash(
        "Você não tem permissão para acessar esta área. Procure seu superior caso precise de acesso.",
        "warning",
    )
    return redirect(url_for("sem_permissao", area=area_label))


def _render_assistencia_list(
    *,
    hero_title: str,
    hero_subtitle: str,
    hero_eyebrow: str,
    page_title: str | None = None,
    default_status: str = "",
    hide_tabs: bool = False,
    lock_status: bool = False,
    orcamento_filter: str | None = None,
):
    filtro_form = AssistenciaFiltroForm(request.args)
    status_value = default_status if lock_status else request.args.get("status", default_status or "")
    if "status" not in filtro_form:
        filtro_form.status = status_value
    else:
        try:
            filtro_form.status.data = status_value
        except Exception:
            filtro_form.status = status_value

    if orcamento_filter is not None:
        if hasattr(filtro_form, "orcamento_status"):
            try:
                filtro_form.orcamento_status.data = orcamento_filter
            except Exception:
                filtro_form.orcamento_status = orcamento_filter
        else:
            filtro_form.orcamento_status = orcamento_filter

    _fill_common_choices(filtro_form)

    create_form = AssistenciaTarefaForm()
    edit_form = EditarAssistenciaTarefaForm()
    envio_form = AssistenciaEnvioForm()
    resposta_form = AssistenciaRespostaForm()
    _fill_common_choices(create_form, edit_form)

    if not create_form.data_criacao.data:
        create_form.data_criacao.data = date.today()
    if not create_form.data_fim.data:
        create_form.data_fim.data = date.today() + timedelta(days=7)

    return render_template(
        "admin/assistencia/dashboard.html",
        filtro_form=filtro_form,
        create_form=create_form,
        edit_form=edit_form,
        envio_form=envio_form,
        resposta_form=resposta_form,
        status_label_map=STATUS_LABEL_MAP,
        api_endpoint=url_for("assist_bp.assistencia_dashboard_api"),
        hero_title=hero_title,
        hero_subtitle=hero_subtitle,
        hero_eyebrow=hero_eyebrow,
        page_title=page_title or f"{hero_title} - Sollus Connected",
        default_status=default_status or "",
        hide_tabs=hide_tabs,
        orcamento_filter=orcamento_filter,
    )


@assist_bp.before_request
def _check_permissions():
    from flask import request
    if "/api/" in getattr(request, "path", ""):
        return
    endpoint = getattr(request, "endpoint", "") or ""
    if endpoint and not endpoint.startswith("assist_bp."):
        return
    if not current_user.is_authenticated:
        return

    role_key = _role_key()
    is_admin = role_key in ("admin", "gestor") or _has_assist_admin_permission()

    # Enforce task-specific department visibility and mutation restrictions
    if not is_admin:
        view_args = request.view_args or {}
        tarefa_id = view_args.get("tarefa_id")
        anexo_id = view_args.get("anexo_id")
        dept_names = _dept_names()

        if tarefa_id:
            tarefa = AssistenciaTarefa.query.get(tarefa_id)
            if tarefa:
                task_dept = (tarefa.departamento_responsavel or "").strip()
                if task_dept:
                    normalized_task_dept = unicodedata.normalize("NFKD", task_dept)
                    normalized_task_dept = "".join(ch for ch in normalized_task_dept if not unicodedata.combining(ch)).upper()
                else:
                    normalized_task_dept = ""
                
                if normalized_task_dept not in dept_names:
                    return _deny_access("Controle de Equipamentos")

        if anexo_id:
            anexo = AssistenciaAnexo.query.get(anexo_id)
            if anexo and anexo.tarefa:
                task_dept = (anexo.tarefa.departamento_responsavel or "").strip()
                if task_dept:
                    normalized_task_dept = unicodedata.normalize("NFKD", task_dept)
                    normalized_task_dept = "".join(ch for ch in normalized_task_dept if not unicodedata.combining(ch)).upper()
                else:
                    normalized_task_dept = ""
                
                if normalized_task_dept not in dept_names:
                    return _deny_access("Controle de Equipamentos")

    allowed_depts = {"ASSISTENCIA TECNICA", "ESTOQUE", "OFICINA"}
    dept_names = _dept_names()
    perms = current_permissions()

    is_legacy_dept = bool(dept_names & allowed_depts)
    is_legacy_admin = bool(_has_assist_admin_permission())

    if is_legacy_admin or is_legacy_dept:
        return

    # 1. Agenda Técnica
    agenda_endpoints = {
        "assist_bp.agenda_tecnica",
        "assist_bp.agenda_tecnica_api",
        "assist_bp.criar_agendamento",
        "assist_bp.atualizar_agendamento",
        "assist_bp.excluir_agendamento",
    }
    if endpoint in agenda_endpoints:
        if perms.get("admin_agenda_tecnica") or perms.get("assistencia_agenda") or "SUPORTE" in dept_names:
            return
        return _deny_access("Agenda técnica")

    # 2. Chamados (OS)
    chamados_endpoints = {
        "assist_bp.assistencia_chamados",
        "assist_bp.assistencia_criar",
        "assist_bp.assistencia_editar",
        "assist_bp.assistencia_resposta",
    }
    if endpoint in chamados_endpoints:
        if perms.get("assistencia_chamados"):
            return
        return _deny_access("Chamados")

    # 3. Orçamentos
    orcamentos_endpoints = {
        "assist_bp.assistencia_orcamentos",
        "assist_bp.assistencia_orcamentos_gerar",
        "assist_bp.assistencia_orcamentos_pdf",
        "assist_bp.assistencia_orcamentos_historico",
    }
    if endpoint in orcamentos_endpoints:
        if perms.get("assistencia_orcamentos"):
            return
        return _deny_access("Orçamentos")

    # 4. Propostas de Equipamentos
    propostas_endpoints = {
        "assist_bp.assistencia_propostas_equipamentos_nova",
        "assist_bp.assistencia_propostas_equipamentos_historico",
        "assist_bp.assistencia_propostas_equipamentos_pdf",
    }
    if endpoint in propostas_endpoints:
        if perms.get("assistencia_propostas"):
            return
        return _deny_access("Propostas")

    # 5. Atestados
    if endpoint == "assist_bp.assistencia_atestados":
        if perms.get("assistencia_atestados"):
            return
        return _deny_access("Atestados")

    # 6. Controle de Equipamentos / Dashboard
    controle_endpoints = {
        "assist_bp.assistencia_dashboard",
        "assist_bp.assistencia_controle",
        "assist_bp.assistencia_equipamentos_fabrica",
        "assist_bp.assistencia_concluidos",
        "assist_bp.assistencia_cliente_nao_respondeu",
        "assist_bp.assistencia_fabrica",
        "assist_bp.assistencia_mover",
        "assist_bp.assistencia_dashboard_api",
        "assist_bp.assistencia_fluxo_api",
    }
    if endpoint in controle_endpoints:
        if perms.get("assistencia_equipamentos"):
            return
        return _deny_access("Controle de Equipamentos")

    if any(perms.get(k) for k in [
        "assistencia_atendimentos", "assistencia_chamados", "assistencia_equipamentos",
        "assistencia_orcamentos", "assistencia_propostas", "assistencia_atestados", "assistencia_agenda"
    ]):
        return

    return _deny_access("Assistência técnica")


@assist_bp.route("/")
@login_required
def assistencia_dashboard():
    return _render_assistencia_list(
        hero_title="Controle de equipamentos",
        hero_subtitle=(
            "Acompanhe as OS internas e externas, envie para fábrica quando necessário "
            "e registre retornos sem perder o histórico do legado."
        ),
        hero_eyebrow="Assistência técnica",
    )


@assist_bp.route("/controle-equipamentos")
@login_required
def assistencia_controle():
    return _render_assistencia_list(
        hero_title="Controle de equipamentos",
        hero_subtitle="Visão completa dos equipamentos em assistência, com filtros e histórico.",
        hero_eyebrow="Assistência técnica",
    )


@assist_bp.route("/chamados")
@login_required
def assistencia_chamados():
    regions = list_regions()
    if not regions:
        flash("Nenhuma unidade de chamados configurada.", "warning")
        return redirect(url_for("assist_bp.assistencia_dashboard"))

    form = ChamadoFiltroForm(request.args)
    form.region.choices = [(region.slug, region.label) for region in regions]

    create_form = CriarChamadoForm()
    edit_form = EditarChamadoForm()
    close_form = FecharChamadoForm()
    create_form.region.choices = [(region.slug, region.label) for region in regions]
    edit_form.region.choices = [(region.slug, region.label) for region in regions]

    from .atendimentos import _populate_chamado_form_choices, _distinct_chamado_choices, _chamado_technician_choices
    
    selected_region = None
    if regions:
        selected_region = next((r for r in regions if r.slug == form.region.data), regions[0])
        
        form.tecnico.choices = _chamado_technician_choices("Todos")
            
        _populate_chamado_form_choices(
            selected_region,
            create_form=create_form,
            edit_form=edit_form,
            close_form=close_form,
        )

    return render_template(
        "admin/support/chamados.html",
        form=form,
        regions=regions,
        create_form=create_form,
        edit_form=edit_form,
        close_form=close_form,
        api_endpoint=url_for("tech_bp.chamados_api"),
        chamados_namespace="tech_bp",
        hero_title="Chamados",
        hero_subtitle=(
            "Visualize a fila de visitas externas por unidade, acompanhe prazos "
            "e consulte os detalhes dos atendimentos."
        ),
        hero_eyebrow="Assistência técnica",
        page_title="Chamados - Sollus Connected",
        assistencia_tabs=False,
    )


@assist_bp.route("/equipamentos-fabrica")
@login_required
def assistencia_equipamentos_fabrica():
    return _render_assistencia_list(
        hero_title="Equipamentos na fábrica",
        hero_subtitle="Envios para fábrica com controle de datas previstas de retorno.",
        hero_eyebrow="Assistência técnica",
        default_status=normalize_status("fabrica") or "fabrica",
        hide_tabs=True,
        lock_status=True,
    )


@assist_bp.route("/concluidos")
@login_required
def assistencia_concluidos():
    return _render_assistencia_list(
        hero_title="Concluídos",
        hero_subtitle="OS finalizadas para consulta e acompanhamento de histórico.",
        hero_eyebrow="Assistência técnica",
        default_status=normalize_status("concluído") or "concluído",
        hide_tabs=True,
        lock_status=True,
    )


@assist_bp.route("/cliente-nao-respondeu")
@login_required
def assistencia_cliente_nao_respondeu():
    return _render_assistencia_list(
        hero_title="Cliente não respondeu",
        hero_subtitle="Chamados com orçamento aguardando retorno do cliente.",
        hero_eyebrow="Assistência técnica",
        hide_tabs=True,
        lock_status=True,
        orcamento_filter="AGUARDANDO RESPOSTA DO CLIENTE",
    )


@assist_bp.route("/api/dashboard")
@login_required
def assistencia_dashboard_api():
    filtro_form = AssistenciaFiltroForm(request.args)
    if 'status' not in filtro_form:
        filtro_form.status = request.args.get('status')
    _fill_common_choices(filtro_form)
    filtro_form.validate()

    tarefas = fetch_tasks_cached(filtro_form)
    
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = request.args.get("per_page", type=int) or 20
    total = len(tarefas)
    start = (page - 1) * per_page
    end = start + per_page
    slice_tasks = tarefas[start:end]
    decorated = [_decorate_task(task) for task in slice_tasks]
    
    # Busca contagens globais
    counters = fetch_status_counts(filtro_form)

    return jsonify(
        {
            "items": decorated,
            "status_counts": counters,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page if per_page else 1,
                "has_prev": page > 1,
                "has_next": end < total,
                "prev_num": page - 1,
                "next_num": page + 1
            },
        }
    )


@assist_bp.route("/api/fluxo")
@login_required
def assistencia_fluxo_api():
    filtro_form = AssistenciaFiltroForm(request.args)
    if 'status' not in filtro_form:
        filtro_form.status = request.args.get('status')
    _fill_common_choices(filtro_form)
    filtro_form.validate()

    tarefas = fetch_tasks_cached(filtro_form)
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = request.args.get("per_page", type=int) or 20
    total = len(tarefas)
    start = (page - 1) * per_page
    end = start + per_page

    decorated = [_decorate_task(task) for task in tarefas[start:end]]
    grouped: Dict[str, List[Dict]] = {}
    for item in decorated:
        grouped.setdefault(item.get("status") or "Entrada", []).append(item)

    counters = status_counters(tarefas)
    status_labels = sorted({status for status, _ in counters} | set(ASSIST_STATUS))

    return jsonify(
        {
            "status_counts": counters,
            "statuses": [
                {"key": key, "label": STATUS_LABEL_MAP.get(key, key.title())} for key in status_labels
            ],
            "groups": grouped,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "has_prev": page > 1,
                "has_next": end < total,
                "prev_num": page - 1 if page > 1 else None,
                "next_num": page + 1 if end < total else None,
                "pages": (total + per_page - 1) // per_page,
            },
        }
    )


@assist_bp.route("/atestados")
@login_required
def assistencia_atestados():
    return _render_assistencia_list(
        hero_title="Atestados",
        hero_subtitle="Acompanhe os atestados de garantia e serviços.",
        hero_eyebrow="Assistência técnica",
        default_status=normalize_status("atestado") or "atestado",
        hide_tabs=True,
        lock_status=True,
    )


@assist_bp.route("/fluxo")
@login_required
def assistencia_fluxo():
    return redirect(url_for("assist_bp.assistencia_dashboard"))


@assist_bp.route("/documentacao")
@login_required
def assistencia_doc():
    return render_template("admin/assistencia/doc.html")


@assist_bp.route("/<int:tarefa_id>/mover", methods=["POST"])
@login_required
def assistencia_mover(tarefa_id: int):
    tarefa = AssistenciaTarefa.query.get_or_404(tarefa_id)
    status_raw = request.form.get("status")
    novo_status = normalize_status(status_raw)
    if not novo_status:
        abort(400)
    if not _enforce_department_for_status(novo_status):
        flash("Seu setor não pode mover para esta etapa.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_fluxo"))
    try:
        enforce_decision_rules(tarefa, novo_status)
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_fluxo"))

    actor = _actor_label()
    before_status = tarefa.status
    tarefa._actor = actor
    tarefa.status = novo_status
    tarefa.data_modificacao = datetime.utcnow()
    mark_os_devolucao_if_needed(tarefa, before_status=before_status, actor=actor)
    mark_factory_followup_if_needed(tarefa, actor=actor)
    db.session.commit()
    flash("Status atualizado.", "success")
    return redirect(request.referrer or url_for("assist_bp.assistencia_fluxo"))


@assist_bp.route("/criar", methods=["POST"])
@login_required
def assistencia_criar():
    ensure_assistencia_schema()
    form = AssistenciaTarefaForm()
    _fill_common_choices(form)
    if not form.validate_on_submit():
        current_app.logger.warning("Falha de validacao ao criar OS: %s", form.errors)
        flash("Não foi possível criar a OS da assistência técnica.", "danger")
        return redirect(url_for("assist_bp.assistencia_dashboard"))

    try:
        create_task_from_form(form, actor=_actor_label())
        db.session.commit()
        flash("OS criada com sucesso.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Erro ao salvar OS da assistencia tecnica.")
        flash("Erro ao salvar a OS.", "danger")
    return redirect(url_for("assist_bp.assistencia_dashboard"))


@assist_bp.route("/<int:tarefa_id>/editar", methods=["POST"])
@login_required
def assistencia_editar(tarefa_id: int):
    tarefa = AssistenciaTarefa.query.get_or_404(tarefa_id)
    form = EditarAssistenciaTarefaForm()
    _fill_common_choices(form)
    if not form.validate_on_submit():
        current_app.logger.warning(
            "assistencia_editar: falha na validação do form para tarefa %s. Erros: %s",
            tarefa_id,
            form.errors,
        )
        err_msgs = [f"{field}: {', '.join(msgs)}" for field, msgs in form.errors.items()]
        flash(f"Não foi possível atualizar a OS. ({'; '.join(err_msgs)})", "danger")
        return redirect(url_for("assist_bp.assistencia_dashboard"))
    try:
        tarefa_id_form = int(form.tarefa_id.data or 0)
    except (ValueError, TypeError):
        flash("Não foi possível atualizar a OS.", "danger")
        return redirect(url_for("assist_bp.assistencia_dashboard"))
    if tarefa_id_form != tarefa.id:
        flash("Não foi possível atualizar a OS.", "danger")
        return redirect(url_for("assist_bp.assistencia_dashboard"))


    desired_status = normalize_status(form.status.data) or tarefa.status
    if desired_status != tarefa.status:
        if not _enforce_department_for_status(desired_status):
            flash("Seu setor não pode mover para esta etapa.", "warning")
            return redirect(url_for("assist_bp.assistencia_dashboard"))

    actor = _actor_label()
    before_status = tarefa.status
    try:
        update_task_from_form(tarefa, form, actor=actor)
        mark_os_devolucao_if_needed(tarefa, before_status=before_status, actor=actor)
        mark_factory_followup_if_needed(tarefa, actor=actor)
        db.session.commit()
        send_assistencia_update_email(tarefa, actor)
        flash("OS atualizada.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception:
        db.session.rollback()
        flash("Erro ao atualizar a OS.", "danger")
    return redirect(url_for("assist_bp.assistencia_dashboard"))


@assist_bp.route("/<int:tarefa_id>/fabrica", methods=["POST"])
@login_required
def assistencia_fabrica(tarefa_id: int):
    tarefa = AssistenciaTarefa.query.get_or_404(tarefa_id)
    form = AssistenciaEnvioForm()
    if not form.validate_on_submit() or int(form.tarefa_id.data) != tarefa.id:
        flash("Não foi possível atualizar o envio à fábrica.", "danger")
        return redirect(url_for("assist_bp.assistencia_dashboard"))

    desired_status = normalize_status("concluido") if form.acao_fabrica.data == "retorno" else "fabrica"
    if not _enforce_department_for_status(desired_status):
        flash("Seu setor não pode mover para esta etapa.", "warning")
        return redirect(url_for("assist_bp.assistencia_dashboard"))

    actor = _actor_label()
    before_status = tarefa.status
    try:
        update_factory_from_form(tarefa, form, actor=actor)
        mark_os_devolucao_if_needed(tarefa, before_status=before_status, actor=actor)
        mark_factory_followup_if_needed(tarefa, actor=actor)
        db.session.commit()
        send_assistencia_fabrica_email(tarefa, actor)
        flash("Envio/retorno ajustado.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception:
        db.session.rollback()
        flash("Erro ao salvar dados de fábrica.", "danger")
    return redirect(url_for("assist_bp.assistencia_dashboard"))


@assist_bp.route("/<int:tarefa_id>/resposta", methods=["POST"])
@login_required
def assistencia_resposta(tarefa_id: int):
    tarefa = AssistenciaTarefa.query.get_or_404(tarefa_id)
    form = AssistenciaRespostaForm()
    if not form.validate_on_submit() or int(form.tarefa_id.data) != tarefa.id:
        flash("Não foi possível anexar a resposta.", "danger")
        return redirect(url_for("assist_bp.assistencia_dashboard"))

    tarefa._actor = _actor_label()
    stored = save_resposta_file(form.arquivo_resposta.data)
    if not stored:
        flash("Arquivo inválido para resposta.", "warning")
        return redirect(url_for("assist_bp.assistencia_dashboard"))

    tarefa.resposta = stored
    tarefa.data_modificacao = datetime.utcnow()
    db.session.commit()
    flash("Resposta anexada.", "success")
    return redirect(url_for("assist_bp.assistencia_dashboard"))


@assist_bp.route("/anexos/<int:anexo_id>")
@login_required
def assistencia_download_anexo(anexo_id: int):
    anexo = AssistenciaAnexo.query.get_or_404(anexo_id)
    path = resolve_assist_file(anexo.url_arquivo)
    if not path:
        flash("Arquivo de anexo não encontrado.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_dashboard"))
    download_name = anexo.nome_arquivo or path.name
    try:
        return send_file(path, as_attachment=True, download_name=download_name)
    except OSError:
        current_app.logger.exception("Erro ao enviar anexo %s", anexo_id)
        flash("Não foi possível abrir o anexo.", "danger")
        return redirect(request.referrer or url_for("assist_bp.assistencia_dashboard"))


@assist_bp.route("/resposta/<int:tarefa_id>/download")
@login_required
def assistencia_download_resposta(tarefa_id: int):
    tarefa = AssistenciaTarefa.query.get_or_404(tarefa_id)
    if not tarefa.resposta:
        abort(404)
    path = resolve_assist_file(tarefa.resposta)
    if not path:
        flash("Arquivo de resposta não encontrado.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_dashboard"))
    try:
        return send_file(path, as_attachment=True, download_name=Path(tarefa.resposta).name)
    except OSError:
        current_app.logger.exception("Erro ao enviar resposta da OS %s", tarefa_id)
        flash("Não foi possível abrir a resposta.", "danger")
        return redirect(request.referrer or url_for("assist_bp.assistencia_dashboard"))


@assist_bp.route("/<int:tarefa_id>/excluir", methods=["POST"])
@login_required
def assistencia_excluir(tarefa_id: int):
    if not _is_admin_like():
        flash("Sem permissão para excluir esta OS.", "danger")
        return redirect(request.referrer or url_for("assist_bp.assistencia_dashboard"))
    tarefa = AssistenciaTarefa.query.get_or_404(tarefa_id)
    try:
        db.session.delete(tarefa)
        db.session.commit()
        flash("OS excluída com sucesso.", "success")
    except Exception:
        db.session.rollback()
        flash("Erro ao excluir a OS.", "danger")
    return redirect(request.referrer or url_for("assist_bp.assistencia_dashboard"))


ORCAMENTO_UNIDADES = [
    "SOLLUS",
    "TECHNOSOLLUS RJ",
    "TECHNOSOLLUS ES",
    "SS Santos",
    "SOLLUS PR",
    "SOLLUS SP",
]
ORCAMENTO_TIPO_VISITA = [
    "VENDA",
    "CORRETIVA",
    "OFICINA",
    "SUPORTE REMOTO",
    "PEDIDO VENDA",
]
ORCAMENTO_STATUS_FILTER = ["AGUARDANDO", "APROVADO"]
ORCAMENTO_STATUS_EDIT = ["APROVADO", "AGUARDANDO", "DESISTENCIA", "SEM RESPOSTA"]
ORCAMENTO_STATUS_HISTORICO = ["CONCLUIDOS", "SEM RESPOSTA", "DESISTENCIA", "TROCA"]


def _format_currency(value) -> str:
    num = float(value or 0.0)
    return f"R$ {num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _parse_currency(value: str | None) -> float:
    if not value:
        return 0.0
    cleaned = str(value).strip().replace("R$", "").replace(" ", "")
    if not cleaned:
        return 0.0
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_date(value: str | None) -> date | None:
    if not value or str(value).strip() in ("0000-00-00", "0000-00-00 00:00:00"):
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.strptime(str(value).strip(), "%d/%m/%Y").date()
        except ValueError:
            return None




def _orcamento_tecnico_form_context(
    *,
    selected_tarefa_id: int | None = None,
    selected_tipo: str | None = None,
    editing_orcamento: AssistenciaOrcamento | None = None,
) -> dict:
    tarefas = (
        AssistenciaTarefa.query.order_by(AssistenciaTarefa.id.desc())
        .limit(500)
        .all()
    )
    equipments = Part.query.order_by(Part.name.asc()).all()
    tipo_options = list_orcamento_types()
    default_tipo = selected_tipo or (tipo_options[0][0] if tipo_options else "")

    # Query active technicians
    allowed_slugs = ["oficina", "suporte", "assistencia-tecnica"]
    allowed_dept_ids = [
        d.id for d in Department.query.filter(Department.slug.in_(allowed_slugs)).all()
    ]
    tech_query = User.query.filter(User.is_active.is_(True))
    tech_conditions = [
        db.func.lower(User.tipo).in_(["suporte", "tecnico", "técnico", "oficina", "supervisorofcina"])
    ]
    if allowed_dept_ids:
        tech_conditions.append(User.department_id.in_(allowed_dept_ids))
        tech_conditions.append(User.departments.any(Department.id.in_(allowed_dept_ids)))
    tech_query = tech_query.filter(db.or_(*tech_conditions))
    techs = tech_query.order_by(User.nome_completo.asc()).all()
    tecnicos = [t.nome_completo for t in techs if t.nome_completo]
    departamentos = ["SUPORTE", "OFICINA", "ESTOQUE", "ASSISTENCIA TECNICA", "AGUARDANDO"]

    return {
        "tarefas": tarefas,
        "equipments": equipments,
        "tipo_options": tipo_options,
        "orcamento_defs": ORCAMENTO_DEFINITIONS,
        "selected_tarefa_id": selected_tarefa_id,
        "selected_tipo": default_tipo,
        "editing_orcamento": editing_orcamento,
        "unidades": ORCAMENTO_UNIDADES,
        "tecnicos": tecnicos,
        "departamentos": departamentos,
    }


def _build_orcamento_snapshot(tipo: str, tarefa: AssistenciaTarefa | None) -> dict:
    snapshot = build_snapshot(tarefa)
    if not tarefa:
        doc_type = (request.form.get("manual_document_type") or "cnpj").strip()
        doc_value = (request.form.get("manual_cnpj") or "").strip()
        client_name = (request.form.get("manual_client_name") or "").strip()
        if doc_type == "cpf":
            empresa = client_name or "Avulso (Sem OS)"
        else:
            empresa = (request.form.get("manual_empresa") or "").strip() or client_name or "Avulso (Sem OS)"

        snapshot["empresa"] = empresa
        snapshot["cnpj"] = doc_value
        snapshot["client_name"] = client_name
        snapshot["email"] = (request.form.get("manual_email") or "").strip()
        snapshot["telefone"] = (request.form.get("manual_telefone") or "").strip()
        snapshot["os"] = (request.form.get("manual_os") or "").strip() or "AVULSO"
        snapshot["unidade"] = (request.form.get("manual_unidade") or "").strip() or "Sem Unidade"
        snapshot["tecnico"] = (request.form.get("manual_tecnico") or "").strip()
        snapshot["departamento"] = (request.form.get("manual_departamento") or "").strip() or "ASSISTENCIA TECNICA"
        snapshot["descricao"] = (request.form.get("manual_descricao") or "").strip() or "Orçamento sem OS vinculada"
        snapshot["data_criacao"] = datetime.now().isoformat()

    meta = ORCAMENTO_DEFINITIONS.get(tipo, {})
    condicoes = []
    for index, pair in enumerate(meta.get("condicoes", [])):
        label = pair[0]
        default_value = pair[1] if len(pair) > 1 else ""
        value = (request.form.get(f"cond_value_{tipo}_{index}") or default_value or "").strip()
        condicoes.append((label, value))
    aceite_raw = request.form.get(f"aceite_{tipo}") or ""
    snapshot["condicoes"] = condicoes
    snapshot["observacao"] = (request.form.get(f"observacao_{tipo}") or meta.get("observacao") or "").strip()
    snapshot["aceite"] = [line.strip() for line in aceite_raw.splitlines() if line.strip()] or meta.get("aceite", [])
    return snapshot


def _send_orcamento_pdf(orcamento: AssistenciaOrcamento):
    from modules.propostas.gerar_proposta import render_proposta_html_pdf

    context = build_orcamento_context(orcamento, issued_by=_actor_label())
    pdf_bytes = render_proposta_html_pdf("admin/assistencia/orcamento_pdf.html", context)
    pdf_bin = io.BytesIO(pdf_bytes)
    os_code = context.get("os_code") or str(orcamento.id)
    tipo = (orcamento.tipo or "orcamento").replace(" ", "_")
    filename = f"orcamento_{tipo}_{os_code}.pdf"
    return send_file(
        pdf_bin,
        mimetype="application/pdf",
        as_attachment=request.args.get("inline") != "1",
        download_name=filename,
    )


def _parse_float_form(value: str | None) -> float:
    return _parse_currency(value)


def _build_equipamento_proposta_items() -> tuple[list[dict], float]:
    items = []
    total = 0.0
    indices = set()
    for key in request.form.keys():
        if key.startswith("equipamento_id_"):
            try:
                indices.add(int(key.rsplit("_", 1)[1]))
            except ValueError:
                continue
    for index in sorted(indices):
        equipamento_id = request.form.get(f"equipamento_id_{index}", type=int)
        quantidade = request.form.get(f"quantidade_{index}", type=int) or 0
        valor_unitario = _parse_float_form(request.form.get(f"valor_unitario_{index}"))
        desconto = _parse_float_form(request.form.get(f"desconto_{index}"))
        if not equipamento_id or quantidade <= 0:
            continue
        equipamento = Equipment.query.get(equipamento_id)
        if not equipamento:
            continue
        if valor_unitario <= 0:
            valor_unitario = float(equipamento.unit_price or 0.0)
        subtotal = max(0.0, (quantidade * valor_unitario) - desconto)
        total += subtotal
        items.append(
            {
                "equipment_id": equipamento.id,
                "name": equipamento.name or "Equipamento",
                "description": equipamento.description or "",
                "quantity": quantum,
                "unit_price": valor_unitario,
                "discount": desconto,
                "subtotal": subtotal,
                "image": equipamento.illustration_path,
            }
        )
    return items, total


def _equipamento_proposta_pdf_context(proposta: AssistenciaEquipamentoProposta) -> dict:
    from modules.propostas.gerar_proposta import _to_file_url

    issuer_name = "Sollus Tecnologia"
    issuer_email = "comercial@sollusgroup.com"
    issuer_phone = "21 2413-3203"
    issuer_site = "sollusgroup.com"
    issuer_address = ""
    items = []
    for item in proposta.itens or []:
        description_parts = [item.get("name") or "Equipamento"]
        if item.get("description"):
            description_parts.append(item.get("description"))
        image = item.get("image")
        items.append(
            {
                "description": "\n".join(description_parts),
                "quantity": int(item.get("quantity") or 0),
                "unit_price": _format_currency(item.get("unit_price") or 0),
                "discount": _format_currency(item.get("discount") or 0),
                "total_price": _format_currency(item.get("subtotal") or 0),
                "image": _to_file_url(image) if image else None,
            }
        )

    return {
        "proposta": proposta,
        "modalidade_label": "Locação" if proposta.modalidade == "locacao" else "Venda",
        "itens": proposta.itens or [],
        "items": items,
        "total_label": _format_currency(proposta.total),
        "investimento_total": _format_currency(proposta.total),
        "total_itens": len(items),
        "created_label": proposta.created_at.strftime("%d/%m/%Y") if proposta.created_at else "-",
        "proposal_code": str(proposta.id),
        "company": proposta.cliente,
        "cnpj": proposta.cnpj or "",
        "client_contact": proposta.contato or "",
        "client_phone_display": proposta.telefone or "",
        "email": proposta.email or "",
        "issuer_company": issuer_name,
        "issuer_contact_name": proposta.created_by or issuer_name,
        "issuer_email": issuer_email,
        "issuer_phone": issuer_phone,
        "issuer_phone_display": issuer_phone,
        "issuer_site": issuer_site,
        "issuer_address": issuer_address,
        "nome_colaborador": proposta.created_by or issuer_name,
        "email_colaborador": issuer_email,
        "consultor_phone_list": [issuer_phone] if issuer_phone else [],
        "issuer_footer_lines": [line for line in (issuer_address, issuer_phone, issuer_site) if line],
        "condicoes": [
            ("Modalidade", "Locação" if proposta.modalidade == "locacao" else "Venda"),
            ("Validade", proposta.validade or "-"),
            ("Pagamento", proposta.condicoes_pagamento or "-"),
            ("Prazo de entrega", proposta.prazo_entrega or "-"),
        ],
        "observacao": proposta.observacoes,
        "logo_image": _to_file_url("static/images/sollus_logo.png"),
        "logo_image_dark": _to_file_url("static/images/sollus_logo.png"),
        "favicon_ico": _to_file_url("static/images/favicon.ico"),
        "favicon_png": _to_file_url("static/images/favicon.png"),
        "whatsapp_icon": _to_file_url("static/images/whatsapp.png"),
        "linkedin_icon": _to_file_url("static/images/linkedin.png"),
        "facebook_icon": _to_file_url("static/images/Facebook_Logo_2023.png"),
        "instagram_icon": _to_file_url("static/images/instagram.png"),
        "youtube_icon": _to_file_url("static/images/Youtube_logo.png"),
    }


def _send_equipamento_proposta_pdf(proposta: AssistenciaEquipamentoProposta):
    from modules.propostas.gerar_proposta import render_proposta_html_pdf

    pdf_bytes = render_proposta_html_pdf(
        "admin/assistencia/equipamentos_proposta_pdf.html",
        _equipamento_proposta_pdf_context(proposta),
    )
    pdf_bin = io.BytesIO(pdf_bytes)
    filename = f"proposta_equipamentos_{proposta.modalidade}_{proposta.id}.pdf"
    return send_file(pdf_bin, mimetype="application/pdf", as_attachment=True, download_name=filename)


def _business_days_inclusive(start: date, end: date) -> int:
    if start > end:
        return 0
    current = start
    count = 0
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def _cobranca_blink_class(status: str | None, ultima_cobranca: date | None) -> str:
    if status != "AGUARDANDO" or not ultima_cobranca:
        return ""
    diff_days = _business_days_inclusive(ultima_cobranca, date.today())
    if 3 <= diff_days < 5:
        return "blink-yellow"
    if diff_days >= 5:
        return "blink-red"
    return ""


@assist_bp.route("/orcamentos/gerar", methods=["GET", "POST"])
@login_required
def assistencia_orcamentos_gerar():
    if request.method == "POST":
        wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        tarefa_id = request.form.get("tarefa_id", type=int)
        tipo = (request.form.get("tipo") or "").strip()
        tarefa = AssistenciaTarefa.query.get(tarefa_id) if tarefa_id else None

        if tarefa_id and not tarefa:
            if wants_json:
                return jsonify({"ok": False, "message": "A OS selecionada não é válida."}), 400
            flash("A OS selecionada não é válida.", "warning")
            return redirect(url_for("assist_bp.assistencia_orcamentos_gerar"))

        if tipo not in ORCAMENTO_DEFINITIONS:
            if wants_json:
                return jsonify({"ok": False, "message": "Selecione um tipo de orçamento valido."}), 400
            flash("Selecione um tipo de orçamento valido.", "warning")
            return redirect(url_for("assist_bp.assistencia_orcamentos_gerar", tarefa_id=tarefa_id or ""))

        items, total = build_orcamento_items(tipo, request.form)
        if not items:
            if wants_json:
                return jsonify({"ok": False, "message": "Adicione ao menos um item do estoque ao orçamento."}), 400
            flash("Adicione ao menos um item do estoque ao orçamento.", "warning")
            return redirect(url_for("assist_bp.assistencia_orcamentos_gerar", tarefa_id=tarefa_id or "", tipo=tipo))

        num_orcamento = (request.form.get("numero_orcamento") or "").strip()
        snapshot = _build_orcamento_snapshot(tipo, tarefa)
        if num_orcamento:
            snapshot["numero_proposta"] = num_orcamento
            update_budget_sequence(num_orcamento)

        orcamento = AssistenciaOrcamento(
            tarefa_id=tarefa.id if tarefa else None,
            tipo=tipo,
            itens=items,
            total=total,
            snapshot=snapshot,
            created_by=_actor_label(),
        )
        db.session.add(orcamento)
        db.session.flush()

        cliente_val = (getattr(tarefa, "nome", None) or (request.form.get("manual_empresa") or "").strip() or "Avulso (Sem OS)")[:255]
        os_val = str(getattr(tarefa, "OS", None) or (request.form.get("manual_os") or "").strip() or orcamento.id or "AVULSO")[:255]
        unidade_val = (getattr(tarefa, "unidade", None) or (request.form.get("manual_unidade") or "").strip() or ORCAMENTO_UNIDADES[0])[:64]

        status = OrcamentoStatus(
            data_envio=date.today(),
            tipo_visita=(ORCAMENTO_DEFINITIONS[tipo].get("label") or tipo)[:32].upper(),
            equipamento=", ".join(item["description"] for item in items[:3])[:255],
            cliente=cliente_val,
            numero_proposta=num_orcamento or os_val,
            ordem_servico=(request.form.get("manual_os") or "").strip() if not tarefa else getattr(tarefa, "OS", None),
            valor=total,
            status="AGUARDANDO",
            ultima_cobranca=date.today(),
            unidade=unidade_val,
            responsavel=_actor_label(),
            fabrica="",
        )
        db.session.add(status)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ao gerar orçamento técnico")
            if wants_json:
                return jsonify({"ok": False, "message": "Erro ao gerar o orçamento."}), 500
            flash("Erro ao gerar o orçamento.", "danger")
            return redirect(url_for("assist_bp.assistencia_orcamentos_gerar", tarefa_id=tarefa_id or "", tipo=tipo))

        if wants_json:
            pdf_url = url_for("assist_bp.assistencia_orcamentos_pdf", orcamento_id=orcamento.id)
            inline_url = url_for("assist_bp.assistencia_orcamentos_pdf", orcamento_id=orcamento.id, inline=1)
            os_code = num_orcamento or getattr(tarefa, "OS", None) or orcamento.id
            return jsonify(
                {
                    "ok": True,
                    "action": "visualizar",
                    "view_url": inline_url,
                    "download_url": pdf_url,
                    "download_name": f"orcamento_{tipo}_{os_code}.pdf",
                    "history_url": url_for("assist_bp.assistencia_orcamentos_historico"),
                    "open_url": url_for("assist_bp.assistencia_orcamentos"),
                }
            )
        return redirect(url_for("assist_bp.assistencia_orcamentos_pdf", orcamento_id=orcamento.id))

    selected_tarefa_id = request.args.get("tarefa_id", type=int)
    selected_tipo = (request.args.get("tipo") or "").strip() or None
    generated = (
        AssistenciaOrcamento.query.order_by(AssistenciaOrcamento.id.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "admin/assistencia/orcamento_gerar.html",
        **_orcamento_tecnico_form_context(
            selected_tarefa_id=selected_tarefa_id,
            selected_tipo=selected_tipo,
        ),
        generated_orcamentos=generated,
    )


@assist_bp.route("/orcamentos/gerados/<int:orcamento_id>/pdf")
@login_required
def assistencia_orcamentos_pdf(orcamento_id: int):
    orcamento = AssistenciaOrcamento.query.get_or_404(orcamento_id)
    return _send_orcamento_pdf(orcamento)


@assist_bp.route("/propostas-equipamentos", methods=["GET", "POST"])
@login_required
def assistencia_propostas_equipamentos_nova():
    if request.method == "POST":
        modalidade = (request.form.get("modalidade") or "venda").strip().lower()
        if modalidade not in {"venda", "locacao"}:
            modalidade = "venda"
        cliente = (request.form.get("cliente") or "").strip()
        if not cliente:
            flash("Informe o cliente da proposta.", "warning")
            return redirect(url_for("assist_bp.assistencia_propostas_equipamentos_nova"))
        items, total = _build_equipamento_proposta_items()
        if not items:
            flash("Adicione ao menos um equipamento à proposta.", "warning")
            return redirect(url_for("assist_bp.assistencia_propostas_equipamentos_nova"))

        proposta = AssistenciaEquipamentoProposta(
            modalidade=modalidade,
            cliente=cliente,
            cnpj=(request.form.get("cnpj") or "").strip(),
            contato=(request.form.get("contato") or "").strip(),
            email=(request.form.get("email") or "").strip(),
            telefone=(request.form.get("telefone") or "").strip(),
            validade=(request.form.get("validade") or "20 dias").strip(),
            prazo_entrega=(request.form.get("prazo_entrega") or "").strip(),
            condicoes_pagamento=(request.form.get("condicoes_pagamento") or "").strip(),
            observacoes=(request.form.get("observacoes") or "").strip(),
            itens=items,
            total=total,
            created_by=_actor_label(),
        )
        db.session.add(proposta)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ao criar proposta de equipamentos")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"ok": False, "message": "Erro ao criar a proposta de equipamentos."}), 500
            flash("Erro ao criar a proposta de equipamentos.", "danger")
            return redirect(url_for("assist_bp.assistencia_propostas_equipamentos_nova"))
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            pdf_url = url_for("assist_bp.assistencia_propostas_equipamentos_pdf", proposta_id=proposta.id)
            return jsonify(
                {
                    "ok": True,
                    "action": "visualizar",
                    "view_url": pdf_url,
                    "download_url": pdf_url,
                    "download_name": f"proposta_equipamentos_{proposta.modalidade}_{proposta.id}.pdf",
                    "history_url": url_for("assist_bp.assistencia_propostas_equipamentos_historico"),
                }
            )
        return redirect(url_for("assist_bp.assistencia_propostas_equipamentos_pdf", proposta_id=proposta.id))

    equipamentos = Equipment.query.order_by(Equipment.name.asc()).all()
    return render_template(
        "admin/assistencia/equipamentos_proposta_nova.html",
        equipamentos=equipamentos,
    )


@assist_bp.route("/propostas-equipamentos/historico")
@login_required
def assistencia_propostas_equipamentos_historico():
    page = max(1, request.args.get("page", type=int) or 1)
    filters = {
        "cliente": (request.args.get("cliente") or "").strip(),
        "modalidade": (request.args.get("modalidade") or "").strip(),
    }
    query = AssistenciaEquipamentoProposta.query
    if filters["cliente"]:
        query = query.filter(AssistenciaEquipamentoProposta.cliente.ilike(f"%{filters['cliente']}%"))
    if filters["modalidade"] in {"venda", "locacao"}:
        query = query.filter(AssistenciaEquipamentoProposta.modalidade == filters["modalidade"])
    pagination = query.order_by(AssistenciaEquipamentoProposta.id.desc()).paginate(
        page=page,
        per_page=20,
        error_out=False,
    )
    rows = [
        {
            "id": item.id,
            "created_at": item.created_at.strftime("%d/%m/%Y %H:%M") if item.created_at else "-",
            "cliente": item.cliente,
            "cnpj": item.cnpj or "-",
            "modalidade": "Locação" if item.modalidade == "locacao" else "Venda",
            "total": _format_currency(item.total),
            "created_by": item.created_by or "-",
            "pdf_url": url_for("assist_bp.assistencia_propostas_equipamentos_pdf", proposta_id=item.id),
        }
        for item in pagination.items
    ]
    return render_template(
        "admin/assistencia/equipamentos_proposta_historico.html",
        rows=rows,
        pagination=pagination,
        filters=filters,
        total=pagination.total,
    )


@assist_bp.route("/propostas-equipamentos/<int:proposta_id>/pdf")
@login_required
def assistencia_propostas_equipamentos_pdf(proposta_id: int):
    proposta = AssistenciaEquipamentoProposta.query.get_or_404(proposta_id)
    return _send_equipamento_proposta_pdf(proposta)


@assist_bp.route("/orcamentos")
@login_required
def assistencia_orcamentos():
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = 10

    filters = {
        "unidade": (request.args.get("unidadeFiltro") or "").strip(),
        "responsavel": (request.args.get("responsavelFiltro") or "").strip(),
        "status": (request.args.get("statusFiltro") or "").strip(),
        "cliente": (request.args.get("clienteFiltro") or "").strip(),
        "data_inicio": (request.args.get("dataInicio") or "").strip(),
        "data_fim": (request.args.get("dataFim") or "").strip(),
    }

    query = OrcamentoStatus.query.filter(OrcamentoStatus.status.in_(ORCAMENTO_STATUS_FILTER))
    if filters["unidade"]:
        query = query.filter_by(unidade=filters["unidade"])
    if filters["responsavel"]:
        query = query.filter_by(responsavel=filters["responsavel"])
    if filters["status"]:
        query = query.filter_by(status=filters["status"])
    if filters["cliente"]:
        query = query.filter(OrcamentoStatus.cliente.ilike(f"%{filters['cliente']}%"))

    data_inicio = _parse_date(filters["data_inicio"])
    if data_inicio:
        query = query.filter(OrcamentoStatus.data_envio >= data_inicio)
    data_fim = _parse_date(filters["data_fim"])
    if data_fim:
        query = query.filter(OrcamentoStatus.data_envio <= data_fim)

    total = query.count()
    total_pages = (total + per_page - 1) // per_page if total else 1
    page = min(page, total_pages) if total_pages else page
    offset = (page - 1) * per_page
    items = (
        query.order_by(OrcamentoStatus.id.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    visible_pages = 5
    start_page = max(1, page - (visible_pages // 2))
    end_page = min(total_pages, start_page + visible_pages - 1)
    if end_page - start_page + 1 < visible_pages:
        start_page = max(1, end_page - visible_pages + 1)

    rows = []
    for item in items:
        rows.append(
            {
                "id": item.id,
                "unidade": _sanitize_text(item.unidade),
                "data_envio": _format_date(item.data_envio),
                "responsavel": _sanitize_text(item.responsavel),
                "ultima_cobranca": _format_date(item.ultima_cobranca),
                "ultima_cobranca_iso": item.ultima_cobranca.strftime("%Y-%m-%d") if item.ultima_cobranca else "",
                "cliente": _sanitize_text(item.cliente or ""),
                "numero_proposta": _sanitize_text(item.numero_proposta or ""),
                "tipo_visita": _sanitize_text(item.tipo_visita or ""),
                "equipamento": _sanitize_text(item.equipamento or ""),
                "valor": _format_currency(item.valor),
                "status": _sanitize_text(item.status or ""),
                "blink_class": _cobranca_blink_class(item.status, item.ultima_cobranca),
                "data_aprovacao": _format_date(item.data_aprovacao),
                "data_atendimento": _format_date(item.data_atendimento),
                "ordem_servico": _sanitize_text(item.ordem_servico or ""),
                "nf_data": _sanitize_text(item.nf_data or ""),
                "outras_informacoes": _sanitize_text(item.outras_informacoes or ""),
                "fabrica": _sanitize_text(item.fabrica or ""),
                "has_data_atendimento": bool(item.data_atendimento),
                "can_edit_status": (item.status or "") == "AGUARDANDO",
            }
        )

    history_query = OrcamentoStatus.query.filter(OrcamentoStatus.status.in_(ORCAMENTO_STATUS_HISTORICO))
    if filters["unidade"]:
        history_query = history_query.filter_by(unidade=filters["unidade"])
    history_items = history_query.order_by(OrcamentoStatus.id.desc()).all()
    history_rows = []
    for item in history_items:
        history_rows.append(
            {
                "id": item.id,
                "unidade": _sanitize_text(item.unidade),
                "data_envio": _format_date(item.data_envio),
                "responsavel": _sanitize_text(item.responsavel),
                "ultima_cobranca": _format_date(item.ultima_cobranca),
                "tipo_visita": _sanitize_text(item.tipo_visita or ""),
                "equipamento": _sanitize_text(item.equipamento or ""),
                "cliente": _sanitize_text(item.cliente or ""),
                "numero_proposta": _sanitize_text(item.numero_proposta or ""),
                "valor": _format_currency(item.valor),
                "status": _sanitize_text(item.status or ""),
                "data_aprovacao": _format_date(item.data_aprovacao),
                "data_atendimento": _format_date(item.data_atendimento),
                "ordem_servico": _sanitize_text(item.ordem_servico or ""),
                "nf_data": _sanitize_text(item.nf_data or ""),
                "outras_informacoes": _sanitize_text(item.outras_informacoes or ""),
            }
        )

    return render_template(
        "admin/assistencia/orcamentos.html",
        orcamentos=rows,
        orcamentos_total=total,
        orcamentos_historico=history_rows,
        orcamentos_historico_total=len(history_rows),
        unidades=ORCAMENTO_UNIDADES,
        tipo_visita_options=ORCAMENTO_TIPO_VISITA,
        status_options=ORCAMENTO_STATUS_FILTER,
        status_edit_options=ORCAMENTO_STATUS_EDIT,
        filters=filters,
        pagination={
            "page": page,
            "total_pages": total_pages,
            "start_page": start_page,
            "end_page": end_page,
        },
        can_edit_nf=_is_admin_like() or _has_assist_admin_permission(),
    )


@assist_bp.route("/orcamentos/criar", methods=["POST"])
@login_required
def assistencia_orcamentos_criar():
    data_envio = _parse_date(request.form.get("dataEnvio"))
    tipo_visita = (request.form.get("tipoVisita") or "").strip().upper()
    equipamento = (request.form.get("equipamento") or "").strip()
    cliente = (request.form.get("cliente") or "").strip()
    numero_proposta = (request.form.get("numeroProposta") or "").strip()
    valor_raw = request.form.get("valor") or ""
    valor = _parse_currency(valor_raw)
    unidade = (request.form.get("unidade") or "").strip()

    if not data_envio or not tipo_visita or not equipamento or not cliente or not numero_proposta or not unidade:
        flash("Preencha todos os campos obrigatórios do orçamento.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))
    if not valor_raw.strip():
        flash("Informe o valor do orçamento.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))

    if tipo_visita not in ORCAMENTO_TIPO_VISITA:
        flash("Tipo de visita inválido.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))

    if unidade not in ORCAMENTO_UNIDADES:
        flash("Unidade inválida.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))

    orcamento = OrcamentoStatus(
        data_envio=data_envio,
        tipo_visita=tipo_visita,
        equipamento=equipamento,
        cliente=cliente,
        numero_proposta=numero_proposta,
        valor=valor,
        status="AGUARDANDO",
        ultima_cobranca=data_envio,
        unidade=unidade,
        responsavel=_actor_label(),
        fabrica="",
    )
    db.session.add(orcamento)
    try:
        db.session.commit()
        flash("Orçamento criado com sucesso.", "success")
    except Exception:
        db.session.rollback()
        flash("Erro ao criar o orçamento.", "danger")

    return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))


@assist_bp.route("/orcamentos/<int:orcamento_id>/cobranca", methods=["POST"])
@login_required
def assistencia_orcamentos_cobranca(orcamento_id: int):
    orcamento = OrcamentoStatus.query.get_or_404(orcamento_id)
    data_cobranca = _parse_date(request.form.get("dataCobranca"))
    descricao = (request.form.get("descricaoCobranca") or "").strip()
    if not data_cobranca:
        flash("Informe a data de cobrança.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))

    data_atual = orcamento.ultima_cobranca
    orcamento.ultima_cobranca = data_cobranca

    old_label = _format_date(data_atual) or "-"
    new_label = _format_date(data_cobranca)
    alteracao = f"Data de cobrança atualizada de {old_label} para {new_label}"
    data_hora = f"Alterado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    detalhe = f"Informacoes adicionais: {descricao} (Alterado por: {_actor_label()})"
    separador = "---------------------------"

    info_atual = (orcamento.outras_informacoes or "").strip()
    if info_atual:
        nova_info = f"{info_atual}<br>{separador}<br>{alteracao}<br>{data_hora}<br>{detalhe}"
    else:
        nova_info = f"{alteracao}<br>{data_hora}<br>{detalhe}"
    orcamento.outras_informacoes = nova_info

    try:
        db.session.commit()
        flash("Cobrança atualizada.", "success")
    except Exception:
        db.session.rollback()
        flash("Erro ao atualizar a cobrança.", "danger")

    return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))


@assist_bp.route("/orcamentos/<int:orcamento_id>/valor", methods=["POST"])
@login_required
def assistencia_orcamentos_valor(orcamento_id: int):
    orcamento = OrcamentoStatus.query.get_or_404(orcamento_id)
    novo_valor = _parse_currency(request.form.get("novoValor"))
    fabrica = "SIM" if request.form.get("fabrica") == "SIM" else ""
    orcamento.valor = novo_valor
    orcamento.fabrica = fabrica

    try:
        db.session.commit()
        flash("Valor atualizado.", "success")
    except Exception:
        db.session.rollback()
        flash("Erro ao atualizar o valor.", "danger")

    return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))


@assist_bp.route("/orcamentos/<int:orcamento_id>/status", methods=["POST"])
@login_required
def assistencia_orcamentos_status(orcamento_id: int):
    orcamento = OrcamentoStatus.query.get_or_404(orcamento_id)
    data_aprovacao = _parse_date(request.form.get("dataAprovacao"))
    novo_status = (request.form.get("status") or "").strip().upper()

    if novo_status not in ORCAMENTO_STATUS_EDIT:
        flash("Status inválido.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))
    if novo_status == "APROVADO" and not data_aprovacao:
        flash("Informe a data de aprovação.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))

    orcamento.status = novo_status
    orcamento.data_aprovacao = data_aprovacao if novo_status == "APROVADO" else None
    
    from .assistencia import _mark_devolucao_sem_reparo_from_budget
    devolucao_marked = False
    if novo_status in {"DESISTENCIA", "SEM RESPOSTA"}:
        devolucao_marked = _mark_devolucao_sem_reparo_from_budget(orcamento, _actor_label())

    try:
        db.session.commit()
        if devolucao_marked:
            flash("Status atualizado; OS vinculada marcada como devolucao sem reparo.", "success")
        else:
            flash("Status atualizado.", "success")
    except Exception:
        db.session.rollback()
        flash("Erro ao atualizar o status.", "danger")

    return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))


@assist_bp.route("/orcamentos/<int:orcamento_id>/atendimento", methods=["POST"])
@login_required
def assistencia_orcamentos_atendimento(orcamento_id: int):
    orcamento = OrcamentoStatus.query.get_or_404(orcamento_id)
    data_atendimento = _parse_date(request.form.get("dataAtendimento"))
    ordem_servico = (request.form.get("ordemServico") or "").strip()

    if not data_atendimento or not ordem_servico:
        flash("Informe a data de atendimento e a ordem de servico.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))

    orcamento.data_atendimento = data_atendimento
    orcamento.ordem_servico = ordem_servico

    try:
        db.session.commit()
        flash("Dados de atendimento atualizados.", "success")
    except Exception:
        db.session.rollback()
        flash("Erro ao atualizar o atendimento.", "danger")

    return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))


@assist_bp.route("/orcamentos/<int:orcamento_id>/nf", methods=["POST"])
@login_required
def assistencia_orcamentos_nf(orcamento_id: int):
    if not (_is_admin_like() or _has_assist_admin_permission()):
        flash("Sem permissão para editar NF.", "danger")
        return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))

    orcamento = OrcamentoStatus.query.get_or_404(orcamento_id)
    numero_nf = (request.form.get("numeroNotaFiscal") or "").strip()
    data_nf = _parse_date(request.form.get("dataNF"))
    if not numero_nf or not data_nf:
        flash("Informe o número da nota e a data.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))

    data_nf_label = data_nf.strftime("%d/%m/%Y")
    orcamento.nf_data = f"{numero_nf} - {data_nf_label}"
    orcamento.status = "CONCLUIDOS"

    try:
        db.session.commit()
        flash("NF atualizada.", "success")
    except Exception:
        db.session.rollback()
        flash("Erro ao atualizar a NF.", "danger")

    return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))


@assist_bp.route("/orcamentos/<int:orcamento_id>/excluir", methods=["POST"])
@login_required
def assistencia_orcamentos_excluir(orcamento_id: int):
    orcamento = OrcamentoStatus.query.get_or_404(orcamento_id)
    if (orcamento.status or "") not in ORCAMENTO_STATUS_FILTER:
        flash("Somente orçamentos em aberto podem ser removidos.", "warning")
        return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))

    try:
        db.session.delete(orcamento)
        db.session.commit()
        flash("Orçamento em aberto removido.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Erro ao remover orçamento em aberto")
        flash("Erro ao remover o orçamento.", "danger")

    return redirect(request.referrer or url_for("assist_bp.assistencia_orcamentos"))


@assist_bp.route("/orcamentos/historico")
@login_required
def assistencia_orcamentos_historico():
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = 20
    filters = {
        "cliente": (request.args.get("cliente") or "").strip(),
        "tipo": (request.args.get("tipo") or "").strip(),
        "data_inicio": (request.args.get("dataInicio") or "").strip(),
        "data_fim": (request.args.get("dataFim") or "").strip(),
    }

    query = AssistenciaOrcamento.query
    if filters["tipo"]:
        query = query.filter(AssistenciaOrcamento.tipo == filters["tipo"])
    data_inicio = _parse_date(filters["data_inicio"])
    if data_inicio:
        query = query.filter(AssistenciaOrcamento.created_at >= datetime.combine(data_inicio, datetime.min.time()))
    data_fim = _parse_date(filters["data_fim"])
    if data_fim:
        query = query.filter(AssistenciaOrcamento.created_at <= datetime.combine(data_fim, datetime.max.time()))
    if filters["cliente"]:
        like = f"%{filters['cliente'].lower()}%"
        query = query.filter(
            text("LOWER(JSON_UNQUOTE(JSON_EXTRACT(snapshot, '$.empresa'))) LIKE :cliente")
        ).params(cliente=like)

    pagination = query.order_by(AssistenciaOrcamento.id.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    rows = []
    for item in pagination.items:
        snapshot = item.snapshot or {}
        rows.append(
            {
                "id": item.id,
                "created_at": item.created_at.strftime("%d/%m/%Y %H:%M") if item.created_at else "-",
                "cliente": snapshot.get("empresa") or "-",
                "cnpj": snapshot.get("cnpj") or "-",
                "os": snapshot.get("os") or "-",
                "unidade": snapshot.get("unidade") or "-",
                "tipo": ORCAMENTO_DEFINITIONS.get(item.tipo, {}).get("label", item.tipo),
                "total": _format_currency(item.total),
                "created_by": item.created_by or "-",
                "pdf_url": url_for("assist_bp.assistencia_orcamentos_pdf", orcamento_id=item.id),
            }
        )

    return render_template(
        "admin/assistencia/orcamentos_historico.html",
        rows=rows,
        total=pagination.total,
        pagination=pagination,
        filters=filters,
        tipo_options=list_orcamento_types(),
    )


@assist_bp.route("/orcamentos/api/cnpj")
@login_required
def assistencia_orcamentos_cnpj():
    cnpj = normalize_cnpj(request.args.get("cnpj", ""))
    if not cnpj:
        return jsonify({"error": "CNPJ inválido"}), 400

    try:
        data = fetch_receita_data(cnpj)
        empresa = upsert_empresa_from_receita(cnpj, data)
        db.session.commit()
        return jsonify({"cliente": empresa.cliente, "cnpj": empresa.cnpj})
    except ReceitaAPIError as exc:
        return jsonify({"error": str(exc)}), 400


@assist_bp.route("/orcamento-templates")
@login_required
def listar_orcamento_templates():
    if not _is_admin_like():
        return _deny_access("Gerenciar Tipos de Orçamento")
    templates = OrcamentoTemplate.query.order_by(OrcamentoTemplate.label).all()
    return render_template("admin/assistencia/orcamento_templates.html", templates=templates)

@assist_bp.route("/orcamento-templates/salvar", methods=["POST"])
@login_required
def salvar_orcamento_template():
    try:
        data = request.json
        template_id = data.get("id")
        chave = data.get("chave", "").strip()
        label = data.get("label", "").strip()
        table_title = data.get("table_title", "").strip()
        ativo = data.get("ativo", True)
        observacao = data.get("observacao", "")
        
        items = data.get("items", [])
        condicoes = data.get("condicoes", [])
        aceite = data.get("aceite", [])
        
        if not chave or not label:
            return jsonify({"ok": False, "message": "Chave e Label são obrigatórios."}), 400
            
        if template_id:
            template = OrcamentoTemplate.query.get_or_404(template_id)
        else:
            if OrcamentoTemplate.query.filter_by(chave=chave).first():
                return jsonify({"ok": False, "message": "Chave já existe."}), 400
            template = OrcamentoTemplate(chave=chave)
            db.session.add(template)
            
        template.label = label
        template.table_title = table_title
        template.items = items
        template.condicoes = condicoes
        template.observacao = observacao
        template.aceite = aceite
        template.ativo = ativo
        
        db.session.commit()
        return jsonify({"ok": True, "message": "Template salvo com sucesso."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(e)}), 500

@assist_bp.route("/orcamento-templates/<int:template_id>/excluir", methods=["POST"])
@login_required
def excluir_orcamento_template(template_id):
    try:
        template = OrcamentoTemplate.query.get_or_404(template_id)
        db.session.delete(template)
        db.session.commit()
        return jsonify({"ok": True, "message": "Template excluído com sucesso."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(e)}), 500

@assist_bp.route("/orcamento-templates/excluir-por-chave/<string:chave>", methods=["POST"])
@login_required
def excluir_orcamento_template_por_chave(chave):
    try:
        template = OrcamentoTemplate.query.filter_by(chave=chave).first()
        if not template:
            return jsonify({"ok": False, "message": "Tipo de orçamento não encontrado."}), 404
        db.session.delete(template)
        db.session.commit()
        return jsonify({"ok": True, "message": "Tipo de orçamento excluído com sucesso."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(e)}), 500


# ==========================================
# BUDGET SEQUENTIAL NUMBERING HELPERS & APIS
# ==========================================

import json
import os

def _get_settings_path():
    return os.path.join(current_app.root_path, 'modules', 'suporte', 'budget_settings.json')

def load_budget_settings():
    path = _get_settings_path()
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        default_settings = {
            "sequences": {
                "RJ": 10671,
                "ES": 8537,
                "A": 404,
                "C": 7861,
                "SP": 158
            }
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(default_settings, f, indent=4)
        except Exception:
            pass
        return default_settings
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {
            "sequences": {
                "RJ": 10671,
                "ES": 8537,
                "A": 404,
                "C": 7861,
                "SP": 158
            }
        }

def save_budget_settings(settings):
    path = _get_settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception:
        return False

def get_prefix_for_unidade(unidade):
    u = (unidade or "").upper().strip()
    if "RJ" in u or u == "SOLLUS":
        return "RJ"
    if "ES" in u:
        return "ES"
    if "SANTOS" in u:
        return "A"
    if "PR" in u:
        return "C"
    if "SP" in u:
        return "SP"
    return "RJ"

def update_budget_sequence(submitted_number):
    import re
    match = re.match(r'^([A-Za-z]+)\s*(\d+)$', (submitted_number or "").strip())
    if not match:
        return
    prefix = match.group(1).upper()
    num = int(match.group(2))
    
    settings = load_budget_settings()
    sequences = settings.get("sequences", {})
    if prefix in sequences:
        if num >= sequences[prefix]:
            sequences[prefix] = num + 1
            save_budget_settings(settings)

@assist_bp.route("/orcamentos/api/next-number")
@login_required
def api_next_budget_number():
    unidade = request.args.get("unidade") or ""
    prefix = get_prefix_for_unidade(unidade)
    settings = load_budget_settings()
    sequences = settings.get("sequences", {})
    next_num = sequences.get(prefix, 1001)
    
    formatted = f"{prefix}{next_num}"
    if prefix == "A" or prefix == "SP":
        formatted = f"{prefix}{next_num:04d}"
        
    return jsonify({
        "ok": True,
        "prefix": prefix,
        "next_number": next_num,
        "formatted": formatted
    })

@assist_bp.route("/orcamentos/api/sequences", methods=["GET", "POST"])
@login_required
def api_budget_sequences():
    # Helper to check admin permission
    if not _is_admin_like():
        return jsonify({"ok": False, "message": "Acesso negado."}), 403
        
    if request.method == "POST":
        data = request.json or {}
        settings = load_budget_settings()
        sequences = settings.setdefault("sequences", {})
        
        for k in ["RJ", "ES", "A", "C", "SP"]:
            if k in data:
                try:
                    sequences[k] = int(data[k])
                except (ValueError, TypeError):
                    pass
        
        save_budget_settings(settings)
        return jsonify({"ok": True, "message": "Sequências atualizadas com sucesso."})
        
    settings = load_budget_settings()
    return jsonify({"ok": True, "sequences": settings.get("sequences", {})})