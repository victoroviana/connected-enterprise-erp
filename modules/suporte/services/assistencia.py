"""Serviços para tarefas de assistência técnica."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import time
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Any

from flask import current_app
from sqlalchemy import func, case, and_, inspect, text
from sqlalchemy.orm import joinedload
from werkzeug.datastructures import FileStorage

from extensions import db
from ..models import AssistenciaAnexo, AssistenciaTarefa, AssistenciaTarefaLog, Empresa, OrcamentoStatus
from ..services.cnpj import ensure_empresa_record

STATUS_ORDER = {
    "Entrada": 0,
    "em progresso": 1,
    "aguardando": 2,
    "fabrica": 3,
    "concluído": 4,
    "devolucao_sem_reparo": 5,
    "descarte": 6,
    "retorno": 7,
}

ASSIST_STATUS = list(STATUS_ORDER.keys())
_CACHE: Dict[str, tuple[datetime, List[AssistenciaTarefa]]] = {}
_CACHE_TTL_SECONDS = 15
_LEGACY_UNIT_SUFFIX = {
    "rio de janeiro": "SRJ",
    "tecnho rio de janeiro": "TRJ",
    "campos": "SCP",
    "espirito santo": "SES",
    "curitiba": "SPR",
    "sao paulo": "SSP",
}
_LEGACY_RESPOSTA_EXTENSIONS = {"pdf", "doc", "docx", "jpg", "png", "jpeg", "msg"}


def ensure_assistencia_schema() -> None:
    """Mantem a tabela legada tarefas compativel com o fluxo atual."""
    inspector = inspect(db.engine)
    if "tarefas" not in inspector.get_table_names():
        return
    if db.engine.dialect.name not in {"mysql", "mariadb"}:
        return
    statements = [
        "ALTER TABLE tarefas MODIFY usuario_designado VARCHAR(255) NULL",
        "ALTER TABLE tarefas MODIFY descricao TEXT NULL",
        "ALTER TABLE tarefas MODIFY unidade VARCHAR(64) NOT NULL",
        "ALTER TABLE tarefas MODIFY status VARCHAR(32) NOT NULL DEFAULT 'Entrada'",
        "ALTER TABLE tarefas MODIFY notificacao VARCHAR(8) NULL DEFAULT 'nao'",
        "ALTER TABLE tarefas MODIFY data_envio DATE NULL",
        "ALTER TABLE tarefas MODIFY data_retorno DATE NULL",
        "ALTER TABLE tarefas MODIFY cnpj VARCHAR(20) NULL",
        "ALTER TABLE tarefas MODIFY ORCAMENTO VARCHAR(50) NULL",
        "ALTER TABLE tarefas MODIFY CONTRATO VARCHAR(50) NULL",
        "ALTER TABLE tarefas MODIFY criado_por VARCHAR(50) NULL",
        "ALTER TABLE tarefas MODIFY atualizacoes TEXT NULL",
    ]
    with db.engine.begin() as connection:
        for statement in statements:
            try:
                connection.execute(text(statement))
            except Exception:
                current_app.logger.exception("Falha ao ajustar schema da tabela tarefas: %s", statement)


def _now() -> datetime:
    return datetime.utcnow()


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def apply_legacy_os_suffix(os_value: str, unidade: str | None) -> str:
    base = (os_value or "").strip()
    if not base:
        return base
    unit_key = (unidade or "").strip().lower()
    suffix = _LEGACY_UNIT_SUFFIX.get(unit_key)
    if not suffix:
        return base
    if base.upper().endswith(f" {suffix}"):
        return base
    return f"{base} {suffix}"


def _assist_root() -> Path:
    base = current_app.config.get("ASSISTENCIA_UPLOAD_ROOT")
    return Path(base) if base else Path(current_app.root_path).parent


def _anexo_dir(create: bool = True) -> Path:
    base = _assist_root() / (current_app.config.get("ASSISTENCIA_ANEXO_DIR") or "anexos")
    if create:
        base.mkdir(parents=True, exist_ok=True)
    return base


def _resposta_dir(create: bool = True) -> Path:
    base = _assist_root() / (current_app.config.get("ASSISTENCIA_RESPOSTA_DIR") or Path("uploads") / "respostas")
    if create:
        base.mkdir(parents=True, exist_ok=True)
    return base


def resolve_assist_file(stored_path: str | None) -> Optional[Path]:
    if not stored_path:
        return None

    try:
        candidate = Path(stored_path)
        if candidate.is_file():
            return candidate
    except OSError:
        return None

    # Tenta resolver tanto caminhos relativos quanto nomes simples
    bases = [
        _assist_root(),
        _anexo_dir(create=False),
        _resposta_dir(create=False),
    ]
    for base in bases:
        try:
            resolved = base / stored_path
            if resolved.is_file():
                return resolved
        except OSError:
            continue
    return None


def snapshot_task(task: AssistenciaTarefa) -> Dict[str, str]:
    return {
        "nome": task.nome,
        "cnpj": task.cnpj,
        "unidade": task.unidade,
        "departamento_responsavel": task.departamento_responsavel,
        "usuario_designado": task.usuario_designado,
        "tipo_entrada": task.tipo_entrada,
        "CONTRATO": task.CONTRATO,
        "ORCAMENTO": task.ORCAMENTO,
        "OS": task.OS,
        "data_criacao": task.data_criacao,
        "data_fim": task.data_fim,
        "data_envio": task.data_envio,
        "data_retorno": task.data_retorno,
        "status": task.status,
        "descricao": task.descricao,
        "notificacao": task.notificacao,
        "resposta": task.resposta,
    }


def log_task_changes(
    tarefa: AssistenciaTarefa, *, before: Dict[str, str], actor: str | None = None
) -> List[AssistenciaTarefaLog]:
    changes: List[AssistenciaTarefaLog] = []
    after = snapshot_task(tarefa)
    for field, old in before.items():
        new = after.get(field)
        if _stringify(old) == _stringify(new):
            continue
        log = AssistenciaTarefaLog(
            tarefa_id=tarefa.id,
            campo=field,
            valor_antigo=_stringify(old),
            valor_novo=_stringify(new),
            modificado_por=actor or "sistema",
            data_modificacao=_now(),
        )
        db.session.add(log)
        changes.append(log)
    return changes


def mark_factory_followup_if_needed(tarefa: AssistenciaTarefa, actor: str | None = None) -> bool:
    """Marca alerta de cobrança após 15 dias sem retorno da fábrica."""
    try:
        if not tarefa.data_envio or tarefa.data_retorno:
            return False
        envio = tarefa.data_envio
        if isinstance(envio, str):
            envio = date.fromisoformat(envio)
        days = (date.today() - envio).days
        if days < 15:
            return False
    except Exception:
        return False

    if (tarefa.notificacao or "").lower() == "alerta15d":
        return False

    tarefa.notificacao = "alerta15d"
    tarefa.data_modificacao = _now()
    if actor:
        tarefa._actor = actor
    return True


def mark_os_devolucao_if_needed(tarefa: AssistenciaTarefa, before_status: str | None = None, actor: str | None = None) -> bool:
    """Registra gatilho de OS de devolução quando conclui/testa."""
    previous = (before_status or "").strip() or None
    current = (tarefa.status or "").strip()
    if current != "concluído":
        return False
    if previous == "concluído":
        return False

    # Já marcado
    if (tarefa.notificacao or "").lower() == "devolucao":
        return False

    tarefa.notificacao = "devolucao"
    tarefa.data_modificacao = _now()
    if actor:
        tarefa._actor = actor
    return True


def normalize_status(value: str | None) -> Optional[str]:
    """Normaliza o status para os valores aceitos pelo legado."""
    if not value:
        return None
    normalized = (value or "").strip().lower()
    mapping = {
        "entrada": "Entrada",
        "em progresso": "em progresso",
        "progresso": "em progresso",
        "aguardando": "aguardando",
        "fabrica": "fabrica",
        "fábrica": "fabrica",
        "concluido": "conclu\u00eddo",
        "conclu\u00eddo": "conclu\u00eddo",
        "devolucao sem reparo": "devolucao_sem_reparo",
        "devolu\u00e7\u00e3o sem reparo": "devolucao_sem_reparo",
        "devolucao_sem_reparo": "devolucao_sem_reparo",
        "descarte": "descarte",
        "retorno": "retorno",
    }
    return mapping.get(normalized)


def save_anexo(file_storage: FileStorage | None, tarefa: AssistenciaTarefa) -> Optional[AssistenciaAnexo]:
    if not file_storage or not getattr(file_storage, "filename", None):
        return None

    filename = Path(file_storage.filename or "").name
    if not filename:
        return None

    target_dir = _anexo_dir()
    target_path = target_dir / filename
    file_storage.save(target_path)

    rel_path = str(target_path.relative_to(_assist_root()))
    anexo = AssistenciaAnexo(
        tarefa=tarefa,
        nome_arquivo=filename,
        url_arquivo=rel_path,
    )
    db.session.add(anexo)
    return anexo


def save_resposta_file(file_storage: FileStorage | None) -> Optional[str]:
    if not file_storage or not getattr(file_storage, "filename", None):
        return None

    filename = Path(file_storage.filename or "").name
    if not filename:
        return None

    parts = filename.rsplit(".", 1)
    if len(parts) != 2:
        return None
    ext = parts[1].lower()
    if ext not in _LEGACY_RESPOSTA_EXTENSIONS:
        return None

    stamp = str(int(time.time()))
    digest = hashlib.md5(f"{stamp}{filename}".encode("utf-8")).hexdigest()
    stored_name = f"{digest}.{ext}"

    target_dir = _resposta_dir()
    target_path = target_dir / stored_name
    file_storage.save(target_path)

    return stored_name


def _apply_filters(query, form, ignore_status=False) -> Iterable[AssistenciaTarefa]:
    # Restrição de visualização por departamento para usuários comuns
    from flask import has_request_context, session
    from flask_login import current_user

    if has_request_context() and current_user and current_user.is_authenticated:
        role = (getattr(current_user, "tipo", None) or session.get("tipo") or "").lower()
        is_admin_like = role in {"admin", "gestor"}

        from modules.propostas.blueprints.auth.permissions_utils import current_permissions
        perms = current_permissions()
        is_legacy_admin = bool(perms.get("admin_assistencia") or perms.get("admin_suporte"))

        if not (is_admin_like or is_legacy_admin):
            user_depts = set()
            try:
                for name in getattr(current_user, "department_names", []) or []:
                    cleaned = (name or "").strip()
                    if cleaned:
                        normalized = unicodedata.normalize("NFKD", cleaned)
                        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
                        user_depts.add(normalized.upper())
            except Exception:
                pass

            if user_depts:
                query = query.filter(AssistenciaTarefa.departamento_responsavel.in_(user_depts))
            else:
                query = query.filter(AssistenciaTarefa.id == -1)

    # Se os_codigo estiver preenchido, ignoramos os filtros de status/status_group
    # para permitir encontrar a OS específica independentemente do seu status.
    has_os_search = False
    os_field = getattr(form, "os_codigo", None)
    if os_field:
        if hasattr(os_field, "data"):
            if os_field.data:
                has_os_search = True
        elif os_field:
            has_os_search = True

    if not ignore_status and not has_os_search:
        status_val = None
        if hasattr(form, 'status'):
            if hasattr(form.status, 'data'):
                status_val = form.status.data
            else:
                status_val = form.status

        status_group = None
        if hasattr(form, "status_group"):
            status_group = (form.status_group.data if hasattr(form.status_group, "data") else form.status_group) or None

        if status_val:
            normalized_status = normalize_status(status_val) or status_val
            query = query.filter(AssistenciaTarefa.status == normalized_status)
        elif status_group:
            if status_group == "open":
                query = query.filter(
                    AssistenciaTarefa.status.in_({"Entrada", "em progresso", "aguardando", "fabrica", "retorno"})
                )
            elif status_group == "closed":
                closed_status = normalize_status("concluido") or "concluido"
                query = query.filter(
                    AssistenciaTarefa.status.in_({closed_status, "devolucao_sem_reparo", "descarte"})
                )

    if getattr(form, "unidade", None) and form.unidade.data:
        query = query.filter(AssistenciaTarefa.unidade == form.unidade.data)
    if getattr(form, "departamento", None) and form.departamento.data:
        query = query.filter(
            AssistenciaTarefa.departamento_responsavel == form.departamento.data
        )
    if getattr(form, "os_codigo", None) and form.os_codigo.data:
        query = query.filter(AssistenciaTarefa.OS.ilike(f"%{form.os_codigo.data}%"))
    if getattr(form, "cliente", None) and form.cliente.data:
        query = query.filter(AssistenciaTarefa.nome.ilike(f"%{form.cliente.data}%"))
    if getattr(form, "orcamento_status", None) and form.orcamento_status.data:
        value = (form.orcamento_status.data or "").strip()
        if value:
            query = query.filter(AssistenciaTarefa.ORCAMENTO.ilike(f"%{value}%"))
    if getattr(form, "fabrica_scope", None) and form.fabrica_scope.data:
        scope = (form.fabrica_scope.data or "").strip()
        if scope == "na_fabrica":
            query = query.filter(AssistenciaTarefa.data_envio.isnot(None))
        elif scope == "envio":
            query = query.filter(AssistenciaTarefa.data_envio.is_(None))
    if getattr(form, "contrato", None) and form.contrato.data:
        query = query.filter(AssistenciaTarefa.CONTRATO.ilike(form.contrato.data))
    if getattr(form, "tipo_entrada", None) and form.tipo_entrada.data:
        query = query.filter(AssistenciaTarefa.tipo_entrada == form.tipo_entrada.data)
    if getattr(form, "data_inicial", None) and form.data_inicial.data:
        query = query.filter(AssistenciaTarefa.data_fim >= form.data_inicial.data)
    if getattr(form, "data_final", None) and form.data_final.data:
        query = query.filter(AssistenciaTarefa.data_fim <= form.data_final.data)
    return query


def fetch_tasks(form) -> List[AssistenciaTarefa]:
    query = AssistenciaTarefa.query.options(
        joinedload(AssistenciaTarefa.logs),
        joinedload(AssistenciaTarefa.anexos),
    )
    query = _apply_filters(query, form)
    return (
        query.order_by(
            AssistenciaTarefa.data_fim.asc(),
            AssistenciaTarefa.data_criacao.desc(),
            AssistenciaTarefa.id.desc(),
        )
        .limit(current_app.config.get("ASSISTENCIA_PAGE_LIMIT", 500))
        .all()
    )


def _cache_key(form) -> str:
    parts = []
    for name in ("status", "status_group", "fabrica_scope", "unidade", "departamento", "os_codigo", "cliente", "contrato", "tipo_entrada", "orcamento_status"):
        if hasattr(form, name):
            val = getattr(form, name).data
            parts.append(f"{name}={val}")
    return "|".join(parts)


def fetch_tasks_cached(form) -> List[AssistenciaTarefa]:
    """Cache leve em memória para aliviar a carga do dashboard/fluxo.

    Mantido apenas para compatibilidade: retornamos sempre uma consulta
    fresca para evitar instâncias destacadas entre requisições.
    """
    return fetch_tasks(form)


def fetch_status_counts(form) -> List[Dict[str, Any]]:
    """Busca contagens de tarefas por status, aplicando todos os filtros exceto o de status."""
    today = date.today()
    warning_limit = today + timedelta(days=3)

    query = db.session.query(
        AssistenciaTarefa.status,
        func.count(AssistenciaTarefa.id).label("total"),
        func.sum(case((AssistenciaTarefa.data_fim < today, 1), else_=0)).label("danger"),
        func.sum(case((and_(AssistenciaTarefa.data_fim >= today, AssistenciaTarefa.data_fim <= warning_limit), 1), else_=0)).label("warning")
    ).group_by(AssistenciaTarefa.status)
    
    query = _apply_filters(query, form, ignore_status=True)
    
    results = query.all()
    
    counts_map = {
        row.status: {
            "total": row.total,
            "danger": int(row.danger or 0),
            "warning": int(row.warning or 0)
        }
        for row in results
    }
    
    output = []
    for key in ASSIST_STATUS:
        data = counts_map.get(key, {"total": 0, "danger": 0, "warning": 0})
        output.append({
            "key": key,
            "label": key.title(), # Será ajustado no template se necessário
            "count": data["total"],
            "danger": data["danger"],
            "warning": data["warning"]
        })
        
    output.sort(key=lambda x: STATUS_ORDER.get(x["key"], 99))
    return output


def status_counters(tasks: Sequence[AssistenciaTarefa]) -> List[Tuple[str, int]]:
    """Mantido para compatibilidade reversa se necessário, mas fetch_status_counts é preferível."""
    buckets: Dict[str, int] = {key: 0 for key in ASSIST_STATUS}
    for task in tasks:
        buckets[task.status or "Entrada"] = buckets.get(task.status or "Entrada", 0) + 1
    ordered = sorted(buckets.items(), key=lambda kv: STATUS_ORDER.get(kv[0], 99))
    return ordered


def _plain_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _latest_budget_status(tarefa: AssistenciaTarefa) -> OrcamentoStatus | None:
    os_code = (tarefa.OS or "").strip()
    if not os_code:
        return None
    os_values = {os_code}
    parts = os_code.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].upper() in set(_LEGACY_UNIT_SUFFIX.values()):
        os_values.add(parts[0])
    return (
        OrcamentoStatus.query.filter(OrcamentoStatus.ordem_servico.in_(os_values))
        .order_by(OrcamentoStatus.data_envio.desc(), OrcamentoStatus.id.desc())
        .first()
    )


def _budget_is_registered(tarefa: AssistenciaTarefa) -> bool:
    if (tarefa.ORCAMENTO or "").strip():
        return True
    return _latest_budget_status(tarefa) is not None


def _budget_is_approved(tarefa: AssistenciaTarefa) -> bool:
    linked_budget = _latest_budget_status(tarefa)
    if linked_budget and linked_budget.data_aprovacao:
        return True
    if linked_budget and "aprov" in _plain_text(linked_budget.status):
        return True

    text = _plain_text(tarefa.ORCAMENTO)
    if not text:
        return False
    if any(token in text for token in ("reprov", "nao aprovado", "nao aprovada", "recus", "cancel")):
        return False
    return "aprov" in text


def _needs_budget(tarefa: AssistenciaTarefa, status: str) -> bool:
    """Define se o passo exige orçamento quando não há contrato."""
    contrato = (tarefa.CONTRATO or "").strip().lower()
    if contrato == "sim":
        return False
    return status in {"em progresso", "aguardando", "fabrica"}


def _legacy_enforce_decision_rules(tarefa: AssistenciaTarefa, status: str) -> str:
    """Aplica as regras de decisão (contrato/orçamento) do legado."""
    if _needs_budget(tarefa, status):
        has_budget = bool((tarefa.ORCAMENTO or "").strip())
        if not has_budget:
            if status == "em progresso":
                raise ValueError("Sem contrato: registre o orçamento aprovado antes de iniciar o conserto interno.")
            if status == "fabrica":
                raise ValueError("Sem contrato: informe o orçamento da fábrica antes de enviar.")
            raise ValueError("Sem contrato: informe o orçamento antes de avançar para esta etapa.")
    return status


def enforce_decision_rules(tarefa: AssistenciaTarefa, status: str) -> str:
    """Aplica as regras de decisao do fluxo de controle de equipamentos."""
    if _needs_budget(tarefa, status):
        has_budget = _budget_is_registered(tarefa)
        approved = _budget_is_approved(tarefa)
        if status == "aguardando" and not has_budget:
            raise ValueError("Sem contrato: registre o orcamento antes de aguardar retorno do cliente.")
        if status in {"em progresso", "fabrica"} and not approved:
            if status == "em progresso":
                raise ValueError("Sem contrato: registre a aprovacao do orcamento antes de iniciar o conserto interno.")
            if status == "fabrica":
                raise ValueError("Sem contrato: registre a aprovacao do orcamento da fabrica antes de enviar.")

    if status == normalize_status("concluido") and tarefa.status == "fabrica" and tarefa.data_envio and not tarefa.data_retorno:
        raise ValueError("Registre o retorno da fabrica antes de concluir/testar a OS.")
    return status


def apply_status_with_rules(tarefa: AssistenciaTarefa, desired_status: str | None) -> str:
    """Normaliza o status e aplica regras de decisão."""
    normalized = normalize_status(desired_status) or "Entrada"
    enforced = enforce_decision_rules(tarefa, normalized)
    tarefa.status = enforced
    return enforced


def compute_initial_status(fluxo_tipo: str | None, contrato: str | None) -> str:
    """Define status inicial guiado pelas escolhas Interno/Fábrica + contrato."""
    fluxo = (fluxo_tipo or "").lower()
    contrato_val = (contrato or "").strip().lower()
    has_contrato = contrato_val == "sim"

    if fluxo == "interno":
        return "em progresso" if has_contrato else "Entrada"
    if fluxo == "fabrica":
        return "fabrica" if has_contrato else "Entrada"
    return "Entrada"


def available_unidades() -> List[str]:
    rows = db.session.query(AssistenciaTarefa.unidade).distinct().all()
    values = [row[0] for row in rows if row[0]]
    return sorted(values)


def available_departamentos() -> List[str]:
    rows = db.session.query(AssistenciaTarefa.departamento_responsavel).distinct().all()
    values = [row[0] for row in rows if row[0]]
    return sorted(values)


def create_task_from_form(form, actor: str | None = None) -> AssistenciaTarefa:
    data_criacao = form.data_criacao.data or date.today()
    data_fim = data_criacao + timedelta(days=7)
    os_base = form.os_codigo.data.strip()
    os_full = apply_legacy_os_suffix(os_base, form.unidade.data)
    if AssistenciaTarefa.query.filter_by(OS=os_full).first():
        raise ValueError("A ordem de servico ja existe.")

    nome = form.nome.data.strip()
    cnpj = (form.cnpj.data or "").strip() or None
    ensure_empresa_record(cnpj, nome)

    fluxo_tipo = getattr(getattr(form, "fluxo_tipo", None), "data", None)
    initial_status = compute_initial_status(fluxo_tipo, form.contrato.data)
    tarefa = AssistenciaTarefa(
        nome=nome,
        cnpj=cnpj,
        cep=(form.cep.data or "").strip() or None,
        bairro=(form.bairro.data or "").strip() or None,
        unidade=form.unidade.data,
        departamento_responsavel=form.departamento_responsavel.data,
        usuario_designado=(form.usuario_designado.data or "").strip(),
        tipo_entrada=form.tipo_entrada.data,
        tipo_atendimento=form.tipo_atendimento.data,
        CONTRATO=form.contrato.data,
        ORCAMENTO=(form.orcamento.data or "").strip(),
        OS=os_full,
        data_criacao=data_criacao,
        data_fim=data_fim,
        descricao=form.descricao.data or "",
        notificacao=form.notificacao.data or "nao",
        criado_por=actor or "sistema",
        atualizacoes="",
    )
    desired_initial = initial_status or form.status.data or "Entrada"
    if (form.contrato.data or "").strip().lower() != "sim" and fluxo_tipo in {"interno", "fabrica"}:
        if _budget_is_approved(tarefa):
            desired_initial = "fabrica" if fluxo_tipo == "fabrica" else "em progresso"
        elif _budget_is_registered(tarefa):
            desired_initial = "aguardando"
    apply_status_with_rules(tarefa, desired_initial)
    db.session.add(tarefa)
    db.session.flush()
    save_anexo(form.arquivo.data, tarefa)
    return tarefa


def update_task_from_form(
    tarefa: AssistenciaTarefa,
    form,
    actor: str | None = None,
) -> AssistenciaTarefa:
    tarefa._actor = actor or getattr(tarefa, "_actor", None) or "sistema"
    tarefa.nome = form.nome.data.strip()
    tarefa.cnpj = (form.cnpj.data or "").strip() or None
    tarefa.cep = (form.cep.data or "").strip() or None
    tarefa.bairro = (form.bairro.data or "").strip() or None
    tarefa.unidade = form.unidade.data
    tarefa.departamento_responsavel = form.departamento_responsavel.data
    tarefa.usuario_designado = (form.usuario_designado.data or "").strip() or None
    tarefa.tipo_entrada = form.tipo_entrada.data
    tarefa.tipo_atendimento = getattr(form, "tipo_atendimento").data if hasattr(form, "tipo_atendimento") else None
    tarefa.CONTRATO = form.contrato.data
    tarefa.ORCAMENTO = (form.orcamento.data or "").strip() or None
    tarefa.OS = form.os_codigo.data.strip()
    if form.data_criacao.data is not None:
        tarefa.data_criacao = form.data_criacao.data
    if form.data_fim.data is not None:
        tarefa.data_fim = form.data_fim.data
    fluxo_tipo = getattr(getattr(form, "fluxo_tipo", None), "data", None)
    desired_status = form.status.data or compute_initial_status(fluxo_tipo, form.contrato.data)
    apply_status_with_rules(tarefa, desired_status or tarefa.status)
    tarefa.descricao = form.descricao.data
    tarefa.notificacao = form.notificacao.data or tarefa.notificacao
    # Atualizacoes estilo legado: concatena com <br> e timestamp
    update_text = None
    if hasattr(form, "atualizar_tarefa") and form.atualizar_tarefa.data:
        update_text = form.atualizar_tarefa.data
    elif hasattr(form, "atualizacoes") and getattr(form, "atualizacoes").data:
        update_text = getattr(form, "atualizacoes").data

    if update_text:
        update_text = update_text.strip()
    if update_text:
        ts = _now().strftime("%d/%m/%Y %H:%M:%S")
        new_line = f"{ts} - {update_text}"
        existing = tarefa.atualizacoes or ""
        tarefa.atualizacoes = (existing + "<br>" if existing else "") + new_line
    tarefa.data_modificacao = _now()

    save_anexo(form.arquivo.data, tarefa)
    return tarefa


def update_factory_from_form(
    tarefa: AssistenciaTarefa, form, actor: str | None = None
) -> AssistenciaTarefa:
    tarefa._actor = actor or getattr(tarefa, "_actor", None) or "sistema"
    action = (getattr(getattr(form, "acao_fabrica", None), "data", "") or "").strip().lower()
    event_date = getattr(getattr(form, "data_evento", None), "data", None)
    note = (getattr(getattr(form, "obs", None), "data", "") or "").strip()
    if not action:
        action = "retorno" if getattr(getattr(form, "data_retorno", None), "data", None) else "envio"

    if action == "envio":
        tarefa.data_envio = event_date or form.data_envio.data
        if not tarefa.data_envio:
            raise ValueError("Informe a data de envio para fabrica.")
        apply_status_with_rules(tarefa, "fabrica")
    elif action == "retorno":
        if not tarefa.data_envio:
            raise ValueError("Registre o envio para fabrica antes do retorno.")
        tarefa.data_retorno = event_date or form.data_retorno.data
        if not tarefa.data_retorno:
            raise ValueError("Informe a data de retorno da fabrica.")
        apply_status_with_rules(tarefa, normalize_status("concluido"))
    else:
        raise ValueError("Acao de fabrica invalida.")

    if getattr(form, "orcamento", None) and form.orcamento.data:
        tarefa.ORCAMENTO = form.orcamento.data
    if note:
        ts = _now().strftime("%d/%m/%Y %H:%M:%S")
        new_line = f"{ts} - {note}"
        existing = tarefa.atualizacoes or ""
        tarefa.atualizacoes = (existing + "<br>" if existing else "") + new_line
    tarefa.data_modificacao = _now()
    return tarefa


def anexos_payload(task: AssistenciaTarefa) -> List[Dict[str, str]]:
    payload: List[Dict[str, str]] = []
    for anexo in task.anexos or []:
        payload.append(
            {
                "id": anexo.id,
                "nome": anexo.nome_arquivo,
                "path": anexo.url_arquivo,
            }
        )
    return payload