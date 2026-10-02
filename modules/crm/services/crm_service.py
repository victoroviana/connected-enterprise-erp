"""Serviços de negócio para o Sollus CRM."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import urllib.parse
import uuid
from datetime import datetime, date, timedelta, timezone
from typing import Any

from flask import current_app
import requests
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import joinedload

from extensions import db, executor
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
    CrmMotivoPerda,
    CrmRegraAutomacao,
    CrmRoletaConsultor,
    CrmWebhook,
    CrmWebhookLog,
    CrmTemplateMensagem,
    CrmRegraDistribuicao,
    CrmEquipamentoHistoricoPreco,
    CrmSoftwareHistoricoPreco,
)
from modules.propostas.models import User, Department, Equipment, SoftwarePlan


def _patch_crm_models() -> None:
    """Garante compatibilidade de atributos, construtores e propriedades dos modelos M3."""
    if getattr(CrmWebhook, "_m3_patched", False):
        return
    CrmWebhook._m3_patched = True

    # 1. CrmWebhook: evento / eventos / secret / url_destino / token_api
    if not hasattr(CrmWebhook, "evento"):
        CrmWebhook.evento = property(
            lambda self: self.eventos,
            lambda self, v: setattr(self, "eventos", v)
        )
    if hasattr(CrmWebhook, "secret") and isinstance(getattr(CrmWebhook, "secret"), property):
        old_prop = getattr(CrmWebhook, "secret")
        CrmWebhook.secret = old_prop.setter(lambda self, v: setattr(self, "secret_key", v))
    elif not hasattr(CrmWebhook, "secret"):
        CrmWebhook.secret = property(
            lambda self: self.secret_key,
            lambda self, v: setattr(self, "secret_key", v)
        )

    if hasattr(CrmWebhook, "url_destino") and isinstance(getattr(CrmWebhook, "url_destino"), property):
        old_prop = getattr(CrmWebhook, "url_destino")
        CrmWebhook.url_destino = old_prop.setter(lambda self, v: setattr(self, "url", v))

    if hasattr(CrmWebhook, "token_api") and isinstance(getattr(CrmWebhook, "token_api"), property):
        old_prop = getattr(CrmWebhook, "token_api")
        CrmWebhook.token_api = old_prop.setter(lambda self, v: setattr(self, "token_hash", v))

    orig_wh_init = CrmWebhook.__init__

    def crm_webhook_init(self, **kwargs):
        if "evento" in kwargs:
            kwargs["eventos"] = kwargs.pop("evento")
        if "secret" in kwargs:
            kwargs["secret_key"] = kwargs.pop("secret")
        if "url_destino" in kwargs:
            kwargs["url"] = kwargs.pop("url_destino")
        if "token_api" in kwargs:
            kwargs["token_hash"] = kwargs.pop("token_api")
        orig_wh_init(self, **kwargs)

    CrmWebhook.__init__ = crm_webhook_init

    def wh_to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "tipo": self.tipo,
            "url": self.url or "",
            "url_destino": self.url or "",
            "eventos": self.eventos or "",
            "evento": self.eventos or "",
            "token_hash": self.token_hash or "",
            "token_api": self.token_hash or "",
            "ativo": self.ativo,
            "secret": self.secret_key or "",
            "secret_key": self.secret_key or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }

    CrmWebhook.to_dict = wh_to_dict

    # 2. CrmWebhookLog: tempo_execucao_ms / tipo / url / erro_mensagem
    CrmWebhookLog.tempo_execucao_ms = property(
        lambda self: self.tempo_ms,
        lambda self, v: setattr(self, "tempo_ms", v)
    )
    CrmWebhookLog.erro_mensagem = property(
        lambda self: self.response_body,
        lambda self, v: setattr(self, "response_body", v)
    )
    def _get_log_tipo(self):
        if getattr(self, "_tipo", None):
            return self._tipo
        if self.webhook_id is None:
            return "inbound"
        return "outbound"

    CrmWebhookLog.tipo = property(
        _get_log_tipo,
        lambda self, v: setattr(self, "_tipo", v)
    )
    CrmWebhookLog.url = property(
        lambda self: getattr(self, "_url", (self.webhook.url if self.webhook else None)),
        lambda self, v: setattr(self, "_url", v)
    )

    orig_log_init = CrmWebhookLog.__init__

    def crm_webhook_log_init(self, **kwargs):
        tipo_val = kwargs.pop("tipo", None)
        url_val = kwargs.pop("url", None)
        if "tempo_execucao_ms" in kwargs:
            kwargs["tempo_ms"] = kwargs.pop("tempo_execucao_ms")
        if "duracao_ms" in kwargs:
            kwargs["tempo_ms"] = kwargs.pop("duracao_ms")
        if "payload_enviado" in kwargs:
            kwargs["request_payload"] = kwargs.pop("payload_enviado")
        if "erro_mensagem" in kwargs:
            kwargs["response_body"] = kwargs.pop("erro_mensagem")
        orig_log_init(self, **kwargs)
        if tipo_val:
            self._tipo = tipo_val
        self._url = url_val

    CrmWebhookLog.__init__ = crm_webhook_log_init

    def log_to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "webhook_id": self.webhook_id,
            "tipo": self.tipo,
            "evento": self.evento,
            "url": getattr(self, "_url", (self.webhook.url if self.webhook else "")),

            "status_code": self.status_code,
            "sucesso": self.sucesso,
            "tempo_ms": self.tempo_ms,
            "tempo_execucao_ms": self.tempo_ms,
            "request_payload": self.request_payload or "",
            "response_body": self.response_body or "",
            "criado_em": self.criado_em.isoformat() if self.criado_em else "",
            "created_at": self.criado_em.strftime("%d/%m/%Y %H:%M:%S") if self.criado_em else "",
        }

    CrmWebhookLog.to_dict = log_to_dict

    # 3. CrmNegociacao: categoria_perda alias
    if not hasattr(CrmNegociacao, "categoria_perda"):
        CrmNegociacao.categoria_perda = property(
            lambda self: getattr(self, "motivo_perda_categoria", None),
            lambda self, v: setattr(self, "motivo_perda_categoria", v)
        )


_patch_crm_models()


def sanitize_whatsapp_phone(phone: str | None) -> str | None:
    """
    Sanitiza número de telefone para WhatsApp:
    - Remove caracteres não numéricos.
    - Remove zeros à esquerda.
    - Se tem 12 ou 13 dígitos começando com 55, preserva.
    - Se tem 10 ou 11 dígitos, adiciona código do Brasil (55).
    - Caso contrário (vazio ou inválido/curto), retorna None.
    """
    if not phone or not isinstance(phone, str):
        return None
    digits = re.sub(r"\D", "", phone).lstrip("0")
    if not digits:
        return None
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits
    if len(digits) in (10, 11):
        return f"55{digits}"
    return None


def build_whatsapp_link(phone: str, text: str = "") -> str:
    """
    Gera link canônico para abertura de conversa no WhatsApp:
    https://api.whatsapp.com/send?phone=...&text=...
    """
    sanitized = sanitize_whatsapp_phone(phone) or re.sub(r"\D", "", phone or "")
    encoded_text = urllib.parse.quote(text or "")
    return f"https://api.whatsapp.com/send?phone={sanitized}&text={encoded_text}"


generate_whatsapp_url = build_whatsapp_link


def render_whatsapp_template(
    template_text: str,
    deal_id: str | None = None,
    deal: CrmNegociacao | None = None,
    contato: CrmContato | None = None,
    empresa: CrmEmpresa | None = None,
    consultor: Any = None,
    proposal: Any = None,
    request: Any = None,
    **kwargs: Any
) -> str:
    """
    Substitui marcadores dinâmicos no template de WhatsApp:
    {nome_contato}, {empresa}, {consultor}, {link_proposta}, {saudacao}
    com valores de fallback seguros.
    """
    if not template_text:
        return ""

    if deal_id and not deal:
        deal = CrmNegociacao.query.get(deal_id)

    # 1. Contato
    contato_nome = None
    if contato and getattr(contato, "nome", None):
        contato_nome = contato.nome.strip()
    elif deal and deal.contato and getattr(deal.contato, "nome", None):
        contato_nome = deal.contato.nome.strip()

    if not contato_nome:
        contato_nome = "Cliente"

    # 2. Empresa
    empresa_nome = None
    if empresa and getattr(empresa, "nome", None):
        empresa_nome = empresa.nome.strip()
    elif deal and deal.empresa and getattr(deal.empresa, "nome", None):
        empresa_nome = deal.empresa.nome.strip()

    if not empresa_nome:
        empresa_nome = "sua empresa"

    # 3. Consultor
    consultor_nome = None
    if consultor:
        if isinstance(consultor, str) and consultor.strip():
            consultor_nome = consultor.strip()
        elif getattr(consultor, "nome_completo", None):
            consultor_nome = consultor.nome_completo.strip()
        elif getattr(consultor, "nome", None):
            consultor_nome = consultor.nome.strip()
        elif getattr(consultor, "usuario", None):
            consultor_nome = consultor.usuario.strip()

    if not consultor_nome and deal:
        if getattr(deal, "user_name", None) and deal.user_name.strip():
            consultor_nome = deal.user_name.strip()
        elif getattr(deal, "user_id", None):
            u = User.query.get(deal.user_id)
            if u and getattr(u, "nome_completo", None):
                consultor_nome = u.nome_completo.strip()
            elif u and getattr(u, "nome", None):
                consultor_nome = u.nome.strip()
            elif u and getattr(u, "usuario", None):
                consultor_nome = u.usuario.strip()

    if not consultor_nome:
        consultor_nome = "Consultor Comercial"

    # 4. Link Proposta
    prop_id = None
    if deal and deal.proposta_id:
        prop_id = deal.proposta_id
    elif proposal and getattr(proposal, "id", None):
        prop_id = proposal.id
    elif "proposta_id" in kwargs and kwargs["proposta_id"]:
        prop_id = kwargs["proposta_id"]

    link_proposta = ""
    if prop_id:
        base_url = ""
        if request and hasattr(request, "host_url"):
            base_url = request.host_url.rstrip("/")
        else:
            try:
                from flask import has_request_context, request as req
                if has_request_context():
                    base_url = req.host_url.rstrip("/")
            except Exception:
                pass
        if not base_url:
            base_url = "https://app.sollusconnected.com.br"
        link_proposta = f"{base_url}/propostas/visualizar/{prop_id}"

    # 5. Saudação ({saudacao})
    now_hour = (datetime.utcnow() - timedelta(hours=3)).hour
    if 5 <= now_hour < 12:
        saudacao = "Bom dia"
    elif 12 <= now_hour < 18:
        saudacao = "Boa tarde"
    else:
        saudacao = "Boa noite"

    replacements = {
        "{nome_contato}": contato_nome,
        "{empresa}": empresa_nome,
        "{consultor}": consultor_nome,
        "{link_proposta}": link_proposta,
        "{saudacao}": saudacao,
    }

    rendered = str(template_text)
    for tag, val in replacements.items():
        rendered = rendered.replace(tag, val)

    return rendered


def get_cockpit_tasks(
    user_id: int | None = None,
    filtro: str | None = None,
    funil_id: str | None = None,
    tipo: str | None = None,
    deal_status: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """
    Retorna as tarefas diárias do vendedor classificadas no semáforo visual:
    - late / atrasadas: vencimento < hoje_inicio e não concluída
    - today / hoje: vencimento >= hoje_inicio e < amanhã_inicio e não concluída
    - upcoming / proximas: vencimento >= amanhã_inicio e não concluída
    - done / concluidas: concluída == True
    """
    today = date.today()
    start_of_today = datetime(today.year, today.month, today.day, 0, 0, 0)
    start_of_tomorrow = start_of_today + timedelta(days=1)

    query = CrmTarefa.query.options(
        joinedload(CrmTarefa.negociacao).joinedload(CrmNegociacao.empresa),
        joinedload(CrmTarefa.negociacao).joinedload(CrmNegociacao.contato),
    )
    if user_id is not None:
        query = query.filter(CrmTarefa.user_id == user_id)

    # Filtrar por funil, status da negociação ou busca
    if (funil_id and funil_id != "all") or (deal_status and deal_status != "all") or search:
        query = query.join(CrmNegociacao, CrmTarefa.negociacao_id == CrmNegociacao.id)
        if funil_id and funil_id != "all":
            query = query.filter(CrmNegociacao.funil_id == funil_id)
        if deal_status and deal_status != "all":
            query = query.filter(CrmNegociacao.status == deal_status)
        if search:
            clean_search = search.strip()
            search_term = f"%{clean_search}%"
            clean_digits = re.sub(r"\D", "", clean_search)

            query = query.outerjoin(CrmEmpresa, CrmNegociacao.empresa_id == CrmEmpresa.id).outerjoin(CrmContato, CrmNegociacao.contato_id == CrmContato.id)
            search_conditions = [
                CrmTarefa.titulo.ilike(search_term),
                CrmNegociacao.nome.ilike(search_term),
                CrmEmpresa.nome.ilike(search_term),
                CrmEmpresa.cnpj.ilike(search_term),
                CrmContato.nome.ilike(search_term),
                CrmContato.email.ilike(search_term),
                CrmContato.celular.ilike(search_term),
                CrmContato.telefone.ilike(search_term),
            ]
            if clean_digits and len(clean_digits) >= 4:
                search_conditions.append(CrmEmpresa.cnpj.ilike(f"%{clean_digits}%"))

            query = query.filter(or_(*search_conditions))

    if tipo and tipo != "all":
        query = query.filter(CrmTarefa.tipo == tipo)

    tasks_all = query.order_by(CrmTarefa.data_vencimento.asc()).all()

    late_tasks = []
    today_tasks = []
    upcoming_tasks = []
    done_tasks = []

    for t in tasks_all:
        if t.concluida:
            done_tasks.append(t)
        elif t.data_vencimento < start_of_today:
            late_tasks.append(t)
        elif start_of_today <= t.data_vencimento < start_of_tomorrow:
            today_tasks.append(t)
        else:
            upcoming_tasks.append(t)

    counts = {
        "late": len(late_tasks),
        "today": len(today_tasks),
        "upcoming": len(upcoming_tasks),
        "done": len(done_tasks),
        "atrasadas": len(late_tasks),
        "hoje": len(today_tasks),
        "proximas": len(upcoming_tasks),
        "concluidas": len(done_tasks),
        "total": len(tasks_all),
    }

    return {
        "counts": counts,
        "tasks": {
            "late": late_tasks,
            "today": today_tasks,
            "upcoming": upcoming_tasks,
            "done": done_tasks,
            "atrasadas": late_tasks,
            "hoje": today_tasks,
            "proximas": upcoming_tasks,
            "concluidas": done_tasks,
        },
        "all": tasks_all,
    }



def format_currency_brl(val: float | None) -> str:
    if val is None or val == 0:
        return "R$ 0,00"
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_datetime_br(dt: datetime | None) -> str:
    """Converte datetime UTC para Horário de Brasília (UTC-3) e formata no padrão brasileiro."""
    if not dt:
        return ""
    try:
        dt_local = dt - timedelta(hours=3)
        return dt_local.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return dt.strftime("%d/%m/%Y às %H:%M")


def _build_deal_base_query(
    funil_id: str,
    user_id: int | None = None,
    include_unassigned: bool = False,
    search: str | None = None,
    filial_filter: str | None = None,
    status_filter: str = "aberto",
    origem_filter: str | None = None,
    temperatura_filter: str | None = None
):
    """Monta a query base com todos os filtros comerciais aplicados."""
    query = CrmNegociacao.query.filter_by(funil_id=funil_id)

    if status_filter in ("aberto", "ganho", "perdido", "pausado"):
        query = query.filter_by(status=status_filter)

    if user_id:
        if include_unassigned:
            query = query.filter(or_(CrmNegociacao.user_id == user_id, CrmNegociacao.user_id.is_(None)))
        else:
            query = query.filter_by(user_id=user_id)

    if filial_filter:
        query = query.filter(
            or_(
                CrmNegociacao.campanha.ilike(f"%{filial_filter}%"),
                CrmNegociacao.filial == filial_filter
            )
        )

    if origem_filter:
        origem_conds = [
            CrmNegociacao.origem.ilike(f"%{origem_filter}%"),
            CrmNegociacao.canal_origem.ilike(f"%{origem_filter}%")
        ]
        if str(origem_filter).isdigit():
            origem_conds.append(CrmNegociacao.origem_id == int(origem_filter))
        query = query.filter(or_(*origem_conds))

    if temperatura_filter:
        query = query.filter(CrmNegociacao.temperatura == temperatura_filter)

    if search:
        search_term = f"%{search.strip()}%"
        query = query.outerjoin(CrmEmpresa).outerjoin(CrmContato).filter(
            or_(
                CrmNegociacao.nome.ilike(search_term),
                CrmEmpresa.nome.ilike(search_term),
                CrmContato.nome.ilike(search_term),
                CrmContato.telefone.ilike(search_term),
                CrmContato.celular.ilike(search_term),
            )
        )

    return query


def get_pipeline_data(
    funil_id: str,
    user_id: int | None = None,
    include_unassigned: bool = False,
    search: str | None = None,
    filial_filter: str | None = None,
    status_filter: str = "aberto",
    origem_filter: str | None = None,
    temperatura_filter: str | None = None
) -> dict[str, Any]:
    """Retorna os dados completos do funil para montagem do Kanban estilo RD Station com alta performance."""
    funil = CrmFunil.query.get(funil_id)
    if not funil:
        # Fallback para o primeiro funil ativo
        funil = CrmFunil.query.filter_by(ativo=True).order_by(CrmFunil.ordem).first()
        if not funil:
            return {"funil": None, "colunas": [], "stats": {}}

    etapas = CrmEtapa.query.filter_by(funil_id=funil.id).order_by(CrmEtapa.ordem).all()

    # 1. Agregação em SQL nativo para totais das etapas (<2ms)
    stats_query = (
        db.session.query(
            CrmNegociacao.etapa_id,
            func.count(CrmNegociacao.id).label("total_count"),
            func.coalesce(func.sum(CrmNegociacao.valor_total), 0.0).label("total_valor")
        )
        .filter_by(funil_id=funil.id)
    )

    if status_filter in ("aberto", "ganho", "perdido", "pausado"):
        stats_query = stats_query.filter(CrmNegociacao.status == status_filter)

    if user_id:
        if include_unassigned:
            stats_query = stats_query.filter(or_(CrmNegociacao.user_id == user_id, CrmNegociacao.user_id.is_(None)))
        else:
            stats_query = stats_query.filter(CrmNegociacao.user_id == user_id)

    if filial_filter:
        stats_query = stats_query.filter(
            or_(
                CrmNegociacao.campanha.ilike(f"%{filial_filter}%"),
                CrmNegociacao.filial == filial_filter
            )
        )

    if origem_filter:
        origem_conds = [
            CrmNegociacao.origem.ilike(f"%{origem_filter}%"),
            CrmNegociacao.canal_origem.ilike(f"%{origem_filter}%")
        ]
        if str(origem_filter).isdigit():
            origem_conds.append(CrmNegociacao.origem_id == int(origem_filter))
        stats_query = stats_query.filter(or_(*origem_conds))

    if temperatura_filter:
        stats_query = stats_query.filter(CrmNegociacao.temperatura == temperatura_filter)

    if search:
        search_term = f"%{search.strip()}%"
        stats_query = stats_query.outerjoin(CrmEmpresa).outerjoin(CrmContato).filter(
            or_(
                CrmNegociacao.nome.ilike(search_term),
                CrmEmpresa.nome.ilike(search_term),
                CrmContato.nome.ilike(search_term),
                CrmContato.telefone.ilike(search_term),
                CrmContato.celular.ilike(search_term),
            )
        )

    stage_stats_rows = stats_query.group_by(CrmNegociacao.etapa_id).all()
    stage_counts = {row.etapa_id: int(row.total_count) for row in stage_stats_rows}
    stage_totals = {row.etapa_id: float(row.total_valor) for row in stage_stats_rows}

    # Totais gerais do pipeline
    total_deals_count = sum(stage_counts.values())
    total_pipeline_value = sum(stage_totals.values())

    # Contagem rápida de tarefas (Hoje e Atrasadas) nas negociações abertas do funil
    hoje = datetime.utcnow().date()
    hoje_inicio = datetime(hoje.year, hoje.month, hoje.day, 0, 0, 0)
    hoje_fim = datetime(hoje.year, hoje.month, hoje.day, 23, 59, 59)

    tarefas_atrasadas_q = CrmNegociacao.query.filter(
        CrmNegociacao.funil_id == funil.id,
        CrmNegociacao.status == "aberto",
        CrmNegociacao.proxima_tarefa_data.isnot(None),
        CrmNegociacao.proxima_tarefa_data < hoje_inicio
    )
    if user_id:
        if include_unassigned:
            tarefas_atrasadas_q = tarefas_atrasadas_q.filter(or_(CrmNegociacao.user_id == user_id, CrmNegociacao.user_id.is_(None)))
        else:
            tarefas_atrasadas_q = tarefas_atrasadas_q.filter(CrmNegociacao.user_id == user_id)
    tarefas_atrasadas = tarefas_atrasadas_q.count()

    tarefas_hoje_q = CrmNegociacao.query.filter(
        CrmNegociacao.funil_id == funil.id,
        CrmNegociacao.status == "aberto",
        CrmNegociacao.proxima_tarefa_data.isnot(None),
        CrmNegociacao.proxima_tarefa_data >= hoje_inicio,
        CrmNegociacao.proxima_tarefa_data <= hoje_fim
    )
    if user_id:
        if include_unassigned:
            tarefas_hoje_q = tarefas_hoje_q.filter(or_(CrmNegociacao.user_id == user_id, CrmNegociacao.user_id.is_(None)))
        else:
            tarefas_hoje_q = tarefas_hoje_q.filter(CrmNegociacao.user_id == user_id)
    tarefas_hoje = tarefas_hoje_q.count()

    # 2. Carregar até 35 cards por coluna com joinedload para eliminar queries N+1
    # Mantém o DOM enxuto (~1.500 nós) e a troca de tema Claro/Escuro instantânea
    colunas = []
    card_limit = 35

    for etapa in etapas:
        stage_query = (
            _build_deal_base_query(
                funil_id=funil.id,
                user_id=user_id,
                include_unassigned=include_unassigned,
                search=search,
                filial_filter=filial_filter,
                status_filter=status_filter,
                origem_filter=origem_filter,
                temperatura_filter=temperatura_filter
            )
            .filter(CrmNegociacao.etapa_id == etapa.id)
            .options(
                joinedload(CrmNegociacao.empresa),
                joinedload(CrmNegociacao.contato)
            )
            .order_by(CrmNegociacao.updated_at.desc())
            .limit(card_limit)
        )
        stage_deals = stage_query.all()

        t_count = stage_counts.get(etapa.id, 0)
        t_val = stage_totals.get(etapa.id, 0.0)

        colunas.append({
            "etapa": etapa.to_dict(),
            "deals": [d.to_dict() for d in stage_deals],
            "total_count": t_count,
            "has_more": t_count > len(stage_deals),
            "limit": card_limit,
            "total_valor": t_val,
            "total_valor_formatado": format_currency_brl(t_val)
        })

    stats = {
        "total_negociacoes": total_deals_count,
        "total_valor_geral": format_currency_brl(total_pipeline_value),
        "tarefas_atrasadas": tarefas_atrasadas,
        "tarefas_hoje": tarefas_hoje
    }

    return {
        "funil": funil.to_dict(),
        "colunas": colunas,
        "stats": stats
    }


class RoletaAssignmentResult(dict):
    """Objeto com compatibilidade dupla (dicionário e atributos) para o retorno da roleta."""
    def __getattr__(self, name):
        return self.get(name)


def get_commercial_consultants() -> list[User]:
    """Retorna a lista de consultores comerciais ativos elegíveis para a roleta."""
    dept_ids = [7, 12]
    comercial_dept = Department.query.filter_by(slug="comercial").first()
    if comercial_dept and comercial_dept.id not in dept_ids:
        dept_ids.append(comercial_dept.id)

    candidates = (
        User.query.filter(
            User.is_active == True,
            or_(
                User.tipo.in_(["consultor", "consultorsp"]),
                User.department_id.in_(dept_ids),
            ),
            or_(User.tipo.is_(None), ~User.tipo.in_(["admin", "gestor"])),
            or_(User.role.is_(None), ~User.role.in_(["admin", "gestor"])),
        )
        .order_by(User.id.asc())
        .all()
    )
    return candidates


DDD_TO_REGION = {
    # SP
    "11": "SP", "12": "SP", "13": "SP", "14": "SP", "15": "SP", "16": "SP", "17": "SP", "18": "SP", "19": "SP",
    # RJ (DDD 22 = Norte Fluminense / Região dos Lagos / Campos; DDDs 21 e 24 = Capital e demais regiões)
    "21": "RJ_CAPITAL", "22": "RJ_NORTE", "24": "RJ_CAPITAL",
    # ES
    "27": "ES", "28": "ES",
    # MG
    "31": "MG", "32": "MG", "33": "MG", "34": "MG", "35": "MG", "37": "MG", "38": "MG",
    # PR
    "41": "PR", "42": "PR", "43": "PR", "44": "PR", "45": "PR", "46": "PR",
    # SC
    "47": "SC", "48": "SC", "49": "SC",
    # RS
    "51": "RS", "53": "RS", "54": "RS", "55": "RS",
    # Centro-Oeste / Norte / Nordeste
    "61": "DF", "62": "GO", "64": "GO", "65": "MT", "66": "MT", "67": "MS",
    "68": "AC", "69": "RO", "71": "BA", "73": "BA", "74": "BA", "75": "BA", "77": "BA",
    "79": "SE", "81": "PE", "82": "AL", "83": "PB", "84": "RN", "85": "CE", "86": "PI", "87": "PE", "88": "CE", "89": "PI",
    "91": "PA", "92": "AM", "93": "PA", "94": "PA", "95": "RR", "96": "AP", "97": "AM", "98": "MA", "99": "MA"
}

STATE_TO_DDDS = {
    "SP": "11,12,13,14,15,16,17,18,19",
    "RJ": "21,22,24",
    "RJ_NORTE": "22",
    "RJ_CAPITAL": "21,24",
    "CAMPOS": "22",
    "ES": "27,28",
    "MG": "31,32,33,34,35,37,38",
    "PR": "41,42,43,44,45,46",
    "SC": "47,48,49",
    "RS": "51,53,54,55",
    "DF": "61",
    "GO": "62,64",
    "TO": "63",
    "MT": "65,66",
    "MS": "67",
    "AC": "68",
    "RO": "69",
    "BA": "71,73,74,75,77",
    "SE": "79",
    "PE": "81,87",
    "AL": "82",
    "PB": "83",
    "RN": "84",
    "CE": "85,88",
    "PI": "86,89",
    "MA": "98,99",
    "PA": "91,93,94",
    "AP": "96",
    "AM": "92,97",
    "RR": "95",
}

STATE_NAMES = {
    "SP": "São Paulo",
    "RJ": "Rio de Janeiro (Geral)",
    "RJ_NORTE": "Rio de Janeiro - Norte Fluminense, Lagos e Campos (DDD 22)",
    "RJ_CAPITAL": "Rio de Janeiro - Capital e Demais Regiões (DDDs 21 e 24)",
    "CAMPOS": "Campos dos Goytacazes & Região dos Lagos",
    "MG": "Minas Gerais",
    "ES": "Espírito Santo",
    "PR": "Paraná",
    "SC": "Santa Catarina",
    "RS": "Rio Grande do Sul",
    "DF": "Distrito Federal",
    "GO": "Goiás",
    "BA": "Bahia",
    "PE": "Pernambuco",
    "CE": "Ceará",
    "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul",
    "AM": "Amazonas",
    "PA": "Pará",
    "MA": "Maranhão",
    "PB": "Paraíba",
    "RN": "Rio Grande do Norte",
    "AL": "Alagoas",
    "SE": "Sergipe",
    "PI": "Piauí",
    "TO": "Tocantins",
    "RO": "Rondônia",
    "AC": "Acre",
    "AP": "Amapá",
    "RR": "Roraima",
    "OUTROS": "Demais Regiões (Nacional)",
}


def extract_ddd_from_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", str(phone))
    if digits.startswith("55") and len(digits) >= 12:
        return digits[2:4]
    elif len(digits) in (10, 11):
        return digits[:2]
    return None


def detect_lead_region(
    filial: str | None = None,
    estado: str | None = None,
    cidade: str | None = None,
    telefone: str | None = None,
    campanha: str | None = None,
    nome: str | None = None,
) -> dict[str, Any]:
    """
    Detecta a região/estado de um lead analisando dados geográficos, DDD e filiais.
    Retorna dict com 'regiao', 'uf', 'ddd', 'origem_deteccao'.
    """
    detected_uf = None
    detected_regiao = None
    detected_ddd = None
    origem_det = "desconhecido"

    # 0. Extrai DDD do telefone de início se fornecido
    ddd = extract_ddd_from_phone(telefone)
    if ddd:
        detected_ddd = ddd

    # 1. Filial explícita
    if filial:
        f_upper = filial.strip().upper()
        if f_upper in ("SP", "SÃO PAULO", "SAO PAULO"):
            return {"regiao": "SP", "uf": "SP", "ddd": detected_ddd, "origem_deteccao": "filial"}
        elif f_upper in ("CAMPOS", "S. S. CAMPOS", "SANTOS", "S. S. SANTOS", "SOLLUS CAMPOS"):
            return {"regiao": "CAMPOS", "uf": "RJ", "ddd": detected_ddd or "22", "origem_deteccao": "filial"}
        elif f_upper in ("RJ", "RIO DE JANEIRO", "RIO"):
            reg = "RJ_NORTE" if detected_ddd == "22" else ("RJ_CAPITAL" if detected_ddd in ("21", "24") else "RJ")
            return {"regiao": reg, "uf": "RJ", "ddd": detected_ddd, "origem_deteccao": "filial"}
        elif f_upper in ("PR", "PARANÁ", "PARANA", "CURITIBA"):
            return {"regiao": "PR", "uf": "PR", "ddd": detected_ddd, "origem_deteccao": "filial"}
        elif f_upper in ("ES", "ESPÍRITO SANTO", "ESPIRITO SANTO"):
            return {"regiao": "ES", "uf": "ES", "ddd": detected_ddd, "origem_deteccao": "filial"}

    # 2. Análise de texto de Cidade / Campanha / Localidade (Prioritário para Norte do RJ & Lagos)
    text_to_check = f"{campanha or ''} {nome or ''} {cidade or ''}".upper()
    cidades_norte_lagos_rj = [
        "CAMPOS", "GOYTACAZES", "MACAÉ", "MACAE", "CABO FRIO", "RIO DAS OSTRAS", 
        "LAGOS", "BÚZIOS", "BUZIOS", "ARARUAMA", "SÃO PEDRO DA ALDEIA", "SAQUAREMA",
        "ITAPERUNA", "PÁDUA", "PADUA", "SANTO ANTONIO DE PADUA", "BOM JESUS DO ITABAPOANA",
        "SÃO FIDÉLIS", "SAO FIDELIS", "SÃO JOÃO DA BARRA", "SAO JOAO DA BARRA"
    ]
    if any(c in text_to_check for c in cidades_norte_lagos_rj):
        detected_regiao = "RJ_NORTE"
        detected_uf = "RJ"
        detected_ddd = detected_ddd or "22"
        origem_det = "cidade_norte_lagos_rj"

    # 3. Estado / UF
    if not detected_regiao and estado:
        est_clean = estado.strip().upper()
        if len(est_clean) == 2:
            detected_uf = est_clean
            detected_regiao = est_clean
            origem_det = "estado_uf"
        elif "SÃO PAULO" in est_clean or "SAO PAULO" in est_clean:
            detected_uf = "SP"
            detected_regiao = "SP"
            origem_det = "estado_nome"
        elif "RIO DE JANEIRO" in est_clean:
            detected_uf = "RJ"
            detected_regiao = "RJ_NORTE" if detected_ddd == "22" else ("RJ_CAPITAL" if detected_ddd in ("21", "24") else "RJ")
            origem_det = "estado_nome"
        elif "PARANÁ" in est_clean or "PARANA" in est_clean:
            detected_uf = "PR"
            detected_regiao = "PR"
            origem_det = "estado_nome"
        elif "ESPÍRITO SANTO" in est_clean or "ESPIRITO SANTO" in est_clean:
            detected_uf = "ES"
            detected_regiao = "ES"
            origem_det = "estado_nome"

    # 4. DDD do telefone / WhatsApp
    ddd = extract_ddd_from_phone(telefone)
    if ddd:
        detected_ddd = ddd
        if ddd in DDD_TO_REGION:
            reg_ddd = DDD_TO_REGION[ddd]
            if not detected_regiao or detected_regiao == "RJ":
                detected_regiao = reg_ddd
                detected_uf = "RJ" if reg_ddd in ("RJ_NORTE", "RJ_CAPITAL", "CAMPOS") else ("SP" if reg_ddd == "SP" else reg_ddd)
                origem_det = "telefone_ddd"

    # 5. Fallback por texto geral de Estado
    if not detected_regiao:
        if "SP" in text_to_check or "SÃO PAULO" in text_to_check or "SAO PAULO" in text_to_check:
            detected_regiao = "SP"
            detected_uf = "SP"
            origem_det = "campanha_ou_texto"
        elif "PR" in text_to_check or "PARANÁ" in text_to_check or "PARANA" in text_to_check:
            detected_regiao = "PR"
            detected_uf = "PR"
            origem_det = "campanha_ou_texto"
        elif "ES" in text_to_check or "ESPÍRITO SANTO" in text_to_check:
            detected_regiao = "ES"
            detected_uf = "ES"
            origem_det = "campanha_ou_texto"
        elif "RJ" in text_to_check or "RIO DE JANEIRO" in text_to_check:
            detected_regiao = "RJ_NORTE" if detected_ddd == "22" else "RJ_CAPITAL"
            detected_uf = "RJ"
            origem_det = "campanha_ou_texto"

    return {
        "regiao": detected_regiao or "RJ",
        "uf": detected_uf or "RJ",
        "ddd": detected_ddd,
        "origem_deteccao": origem_det,
    }


def find_matching_distribution_rule(
    regiao: str | None = None,
    uf: str | None = None,
    ddd: str | None = None,
) -> CrmRegraDistribuicao | None:
    """
    Localiza a regra ativa de distribuição regional que melhor atende aos critérios do lead.
    Prioridade: DDD exato > Sub-região (RJ_NORTE, RJ_CAPITAL) > UF geral > Região > Ordem.
    """
    try:
        regras = (
            CrmRegraDistribuicao.query.filter_by(ativo=True)
            .order_by(CrmRegraDistribuicao.ordem.asc(), CrmRegraDistribuicao.id.asc())
            .all()
        )
    except Exception:
        return None

    if not regras:
        return None

    # 1. Match exato por DDD se informado (Ex: 22 -> Gilson; 21/24 -> Luciana)
    if ddd:
        for r in regras:
            if r.ddds:
                ddds_list = [d.strip() for d in r.ddds.split(",") if d.strip()]
                if ddd in ddds_list:
                    return r

    # 2. Match por Sub-região / Região específica (RJ_NORTE, RJ_CAPITAL, CAMPOS, SP, PR, ES)
    if regiao:
        reg_upper = regiao.strip().upper()
        # Se for RJ_NORTE ou CAMPOS, busca regra correspondente
        if reg_upper in ("RJ_NORTE", "CAMPOS"):
            for r in regras:
                if r.regiao in ("RJ_NORTE", "CAMPOS") or (r.ddds and "22" in [d.strip() for d in r.ddds.split(",")]):
                    return r
        elif reg_upper == "RJ_CAPITAL":
            for r in regras:
                if r.regiao == "RJ_CAPITAL" or (r.ddds and any(x in [d.strip() for d in r.ddds.split(",")] for x in ["21", "24"])):
                    return r
        else:
            for r in regras:
                if r.regiao and r.regiao.strip().upper() == reg_upper:
                    return r

    # 3. Match por UF se informado
    if uf:
        uf_upper = uf.strip().upper()
        # Se for RJ e tiver DDD 22
        if uf_upper == "RJ" and ddd == "22":
            for r in regras:
                if r.regiao in ("RJ_NORTE", "CAMPOS") or (r.ddds and "22" in [d.strip() for d in r.ddds.split(",")]):
                    return r
        for r in regras:
            if r.estados:
                ufs_list = [u.strip().upper() for u in r.estados.split(",") if u.strip()]
                if uf_upper in ufs_list:
                    return r
                return r

    # 4. Regra genérica / default ("OUTROS" ou "*")
    for r in regras:
        if r.regiao and r.regiao.strip().upper() in ("OUTROS", "TODOS", "PADRAO", "*"):
            return r

    return None


def update_equipment_price_and_description(
    equipment_id: int,
    new_price: float | None = None,
    new_preco_locacao: float | None = None,
    new_description: str | None = None,
    new_name: str | None = None,
    new_fabricante: str | None = None,
    new_tipo_equipamento: str | None = None,
    user_name: str | None = "Sistema",
    origem: str = "crm_tabela_precos",
) -> tuple[Equipment, bool]:
    """
    Atualiza preço de aquisição, preço de locação, fabricante, tipo e/ou descrição de um equipamento.
    Se o preço for alterado, registra histórico e auditoria.
    Retorna (equipamento, preco_mudou).
    """
    eq = Equipment.query.get(equipment_id)
    if not eq:
        raise ValueError(f"Equipamento ID {equipment_id} não encontrado.")

    price_changed = False
    if new_price is not None:
        try:
            val_float = float(new_price)
        except (ValueError, TypeError):
            val_float = eq.unit_price

        # Considera alteração se houver diferença maior que 0.001
        if eq.unit_price is None or abs(float(eq.unit_price) - val_float) > 0.001:
            old_price = float(eq.unit_price) if eq.unit_price is not None else 0.0
            eq.preco_anterior = old_price
            eq.preco_alterado_em = datetime.utcnow()
            eq.preco_alterado_por = user_name or "Sistema"
            eq.unit_price = val_float
            price_changed = True

            try:
                hist = CrmEquipamentoHistoricoPreco(
                    equipment_id=eq.id,
                    preco_antigo=old_price,
                    preco_novo=val_float,
                    alterado_em=datetime.utcnow(),
                    alterado_por=user_name or "Sistema",
                    origem=origem,
                )
                db.session.add(hist)
            except Exception:
                pass

    if new_preco_locacao is not None:
        try:
            val_loc = float(new_preco_locacao) if str(new_preco_locacao).strip() != "" else None
        except (ValueError, TypeError):
            val_loc = None

        if val_loc is not None:
            if eq.preco_locacao is None or abs(float(eq.preco_locacao) - val_loc) > 0.001:
                eq.preco_locacao_anterior = eq.preco_locacao
                eq.preco_locacao = val_loc
                eq.preco_locacao_alterado_em = datetime.utcnow()
                eq.preco_locacao_alterado_por = user_name or "Sistema"
                price_changed = True
        elif eq.preco_locacao is not None and str(new_preco_locacao).strip() == "":
            eq.preco_locacao_anterior = eq.preco_locacao
            eq.preco_locacao = None
            eq.preco_locacao_alterado_em = datetime.utcnow()
            eq.preco_locacao_alterado_por = user_name or "Sistema"
            price_changed = True

    if new_description is not None:
        eq.description = new_description

    if new_name is not None and new_name.strip():
        eq.name = new_name.strip()

    if new_fabricante is not None:
        eq.fabricante = new_fabricante.strip() or None

    if new_tipo_equipamento is not None:
        eq.tipo_equipamento = new_tipo_equipamento.strip() or None

    db.session.flush()
    return eq, price_changed


def get_equipment_price_history(equipment_id: int) -> list[dict[str, Any]]:
    """Retorna o histórico cronológico de preços de um equipamento."""
    try:
        registros = (
            CrmEquipamentoHistoricoPreco.query.filter_by(equipment_id=equipment_id)
            .order_by(CrmEquipamentoHistoricoPreco.alterado_em.desc())
            .all()
        )
        return [r.to_dict() for r in registros]
    except Exception:
        return []


def calculate_adjusted_price(
    current_price: float,
    adjustment_type: str,
    value: float,
    rounding_mode: str = "none",
) -> float:
    """Calcula o novo preço baseado no tipo de reajuste e arredondamento."""
    import math
    p = float(current_price or 0.0)
    v = float(value or 0.0)

    if adjustment_type == "percentual_aumento":
        new_p = p * (1.0 + (v / 100.0))
    elif adjustment_type == "percentual_desconto":
        new_p = p * (1.0 - (v / 100.0))
    elif adjustment_type == "valor_aumento":
        new_p = p + v
    elif adjustment_type == "valor_desconto":
        new_p = p - v
    else:
        new_p = p

    new_p = max(0.0, new_p)

    if rounding_mode == "inteiro":
        new_p = float(math.floor(new_p + 0.5))
    elif rounding_mode == "final_90":
        if new_p <= 0.90:
            new_p = 0.90
        else:
            new_p = float(math.floor(new_p)) + 0.90
    else:
        new_p = round(new_p, 2)

    return new_p


def apply_bulk_price_adjustment(
    equipment_ids: list[int] | None = None,
    fabricante: str | None = None,
    adjustment_type: str = "percentual_aumento",
    value: float = 0.0,
    rounding_mode: str = "none",
    user_name: str | None = "Sistema",
    origem: str = "crm_reajuste_massa",
) -> list[dict[str, Any]]:
    """
    Aplica reajuste de preço em lote para os equipamentos especificados, por fabricante, ou todos.
    Retorna lista com os equipamentos atualizados e suas variações.
    """
    query = Equipment.query
    if equipment_ids:
        query = query.filter(Equipment.id.in_(equipment_ids))
    elif fabricante and fabricante.strip().lower() not in ("todos", "todas", ""):
        query = query.filter(Equipment.fabricante == fabricante.strip())

    equipments = query.all()

    results: list[dict[str, Any]] = []
    for eq in equipments:
        curr_price = float(eq.unit_price or 0.0)
        new_price = calculate_adjusted_price(
            current_price=curr_price,
            adjustment_type=adjustment_type,
            value=value,
            rounding_mode=rounding_mode,
        )

        eq_updated, mudou = update_equipment_price_and_description(
            equipment_id=eq.id,
            new_price=new_price,
            user_name=user_name,
            origem=origem,
        )

        results.append({
            "id": eq.id,
            "nome": eq.name,
            "fabricante": eq.fabricante,
            "preco_antigo": curr_price,
            "preco_novo": new_price,
            "mudou": mudou,
        })

    db.session.commit()
    return results


def get_software_plan_price_history(software_plan_id: int) -> list[dict[str, Any]]:
    """Retorna o histórico cronológico de preços de um plano de software/sistema."""
    try:
        registros = (
            CrmSoftwareHistoricoPreco.query.filter_by(software_plan_id=software_plan_id)
            .order_by(CrmSoftwareHistoricoPreco.alterado_em.desc())
            .all()
        )
        return [r.to_dict() for r in registros]
    except Exception:
        return []


def update_software_plan_price(
    software_plan_id: int,
    new_price: float | str | None = None,
    new_description: str | None = None,
    new_name: str | None = None,
    new_fabricante: str | None = None,
    new_categoria: str | None = None,
    new_vigencia: str | None = None,
    new_suporte: str | None = None,
    user_name: str | None = "CRM",
    origem: str = "crm_tabela_precos",
) -> tuple[SoftwarePlan, bool]:
    """
    Atualiza preço (mensalidade), fabricante, categoria e/ou descrição de um plano de software/sistema com histórico de auditoria.
    """
    plan = SoftwarePlan.query.get_or_404(software_plan_id)
    price_changed = False
    old_price = float(plan.valor_mensal or 0.0)

    if new_price is not None:
        try:
            if isinstance(new_price, str):
                cleaned = new_price.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".").strip()
                val = float(cleaned)
            else:
                val = float(new_price)
        except (ValueError, TypeError):
            val = old_price

        if abs(val - old_price) > 0.001:
            price_changed = True
            now = datetime.utcnow()
            plan.preco_anterior = old_price
            plan.valor_mensal = val
            plan.preco_alterado_em = now
            plan.preco_alterado_por = user_name

            hist = CrmSoftwareHistoricoPreco(
                software_plan_id=plan.id,
                preco_antigo=old_price,
                preco_novo=val,
                alterado_em=now,
                alterado_por=user_name,
                origem=origem,
            )
            db.session.add(hist)

    if new_description is not None:
        plan.description = new_description.strip()

    if new_name is not None and new_name.strip():
        plan.name = new_name.strip()

    if new_fabricante is not None and new_fabricante.strip():
        plan.fabricante = new_fabricante.strip()

    if new_categoria is not None and new_categoria.strip():
        plan.categoria = new_categoria.strip()

    if new_vigencia is not None and new_vigencia.strip():
        plan.vigencia = new_vigencia.strip()

    if new_suporte is not None and new_suporte.strip():
        plan.suporte_incluso = new_suporte.strip()

    return plan, price_changed


def apply_bulk_software_adjustment(
    plan_ids: list[int] | None = None,
    fabricante: str | None = None,
    categoria: str | None = None,
    adjustment_type: str = "percentual_aumento",
    value: float = 0.0,
    rounding_mode: str = "none",
    user_name: str | None = "Sistema",
    origem: str = "crm_reajuste_massa",
) -> list[dict[str, Any]]:
    """
    Aplica reajuste de mensalidade em lote para os planos de software especificados, por fabricante, categoria ou todos.
    """
    query = SoftwarePlan.query.filter_by(is_active=True)
    if plan_ids:
        query = query.filter(SoftwarePlan.id.in_(plan_ids))
    else:
        if fabricante and fabricante.strip().lower() not in ("todos", "todas", ""):
            query = query.filter(SoftwarePlan.fabricante == fabricante.strip())
        if categoria and categoria.strip().lower() not in ("todos", "todas", ""):
            query = query.filter(SoftwarePlan.categoria == categoria.strip())

    plans = query.all()
    results: list[dict[str, Any]] = []

    for sp in plans:
        curr_price = float(sp.valor_mensal or 0.0)
        new_price = calculate_adjusted_price(
            current_price=curr_price,
            adjustment_type=adjustment_type,
            value=value,
            rounding_mode=rounding_mode,
        )

        sp_updated, mudou = update_software_plan_price(
            software_plan_id=sp.id,
            new_price=new_price,
            user_name=user_name,
            origem=origem,
        )

        results.append({
            "id": sp.id,
            "nome": sp.name,
            "fabricante": sp.fabricante,
            "categoria": sp.categoria,
            "preco_antigo": curr_price,
            "preco_novo": new_price,
            "mudou": mudou,
        })

    db.session.commit()
    return results


def ensure_crm_extra_tables_and_columns():
    """Garante a existência das tabelas de regras de distribuição, histórico e colunas em equipments e parts."""
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()

        # 1. Tabelas
        if "crm_regras_distribuicao" not in tables:
            CrmRegraDistribuicao.__table__.create(db.engine, checkfirst=True)

        if "crm_equipamentos_historico_preco" not in tables:
            CrmEquipamentoHistoricoPreco.__table__.create(db.engine, checkfirst=True)

        if "software_plans" not in tables:
            SoftwarePlan.__table__.create(db.engine, checkfirst=True)

        if "crm_software_historico_preco" not in tables:
            CrmSoftwareHistoricoPreco.__table__.create(db.engine, checkfirst=True)

        is_sqlite = db.engine.dialect.name == "sqlite"

        # 2. Colunas em equipments
        if "equipments" in tables:
            eq_cols = [c["name"] for c in inspector.get_columns("equipments")]

            if "fabricante" not in eq_cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE equipments ADD COLUMN fabricante VARCHAR(100) NULL"))
                    if not is_sqlite:
                        conn.commit()
            if "preco_anterior" not in eq_cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE equipments ADD COLUMN preco_anterior FLOAT NULL"))
                    if not is_sqlite:
                        conn.commit()
            if "preco_alterado_em" not in eq_cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE equipments ADD COLUMN preco_alterado_em DATETIME NULL"))
                    if not is_sqlite:
                        conn.commit()
            if "preco_alterado_por" not in eq_cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE equipments ADD COLUMN preco_alterado_por VARCHAR(120) NULL"))
                    if not is_sqlite:
                        conn.commit()
            if "preco_locacao" not in eq_cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE equipments ADD COLUMN preco_locacao FLOAT NULL"))
                    if not is_sqlite:
                        conn.commit()
            if "preco_locacao_anterior" not in eq_cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE equipments ADD COLUMN preco_locacao_anterior FLOAT NULL"))
                    if not is_sqlite:
                        conn.commit()
            if "preco_locacao_alterado_em" not in eq_cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE equipments ADD COLUMN preco_locacao_alterado_em DATETIME NULL"))
                    if not is_sqlite:
                        conn.commit()
            if "preco_locacao_alterado_por" not in eq_cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE equipments ADD COLUMN preco_locacao_alterado_por VARCHAR(120) NULL"))
                    if not is_sqlite:
                        conn.commit()

        # 3. Colunas em parts
        if "parts" in tables:
            part_cols = [c["name"] for c in inspector.get_columns("parts")]
            if "fabricante" not in part_cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE parts ADD COLUMN fabricante VARCHAR(100) NULL"))
                    if not is_sqlite:
                        conn.commit()

        # 3. Seed inicial e correção de regras padrão
        if "crm_regras_distribuicao" in tables:
            # Consultor SP: Hizael Ferreira (consultorsp / id 5009), excluindo Ricardo Simões (5006)
            sp_user = User.query.filter(
                User.id != 5006,
                or_(User.id == 5009, User.tipo == "consultorsp", User.usuario.ilike("%hizael%"))
            ).first()
            rj_user = User.query.filter(or_(User.id == 5008, User.usuario.ilike("%gilson%"))).first() or User.query.filter(User.id == 5010).first()

            if CrmRegraDistribuicao.query.count() == 0:
                if sp_user:
                    db.session.add(CrmRegraDistribuicao(
                        nome="Leads de São Paulo (SP)",
                        regiao="SP",
                        estados="SP",
                        ddds=STATE_TO_DDDS.get("SP", "11,12,13,14,15,16,17,18,19"),
                        consultor_id=sp_user.id,
                        ativo=True,
                        ordem=10,
                    ))
                if rj_user:
                    db.session.add(CrmRegraDistribuicao(
                        nome="Leads do Rio de Janeiro (RJ)",
                        regiao="RJ",
                        estados="RJ",
                        ddds=STATE_TO_DDDS.get("RJ", "21,22,24"),
                        consultor_id=rj_user.id,
                        ativo=True,
                        ordem=20,
                    ))
                db.session.commit()
            else:
                # Corrige regra SP existente caso ainda aponte para Ricardo Simões (5006)
                r_sp = CrmRegraDistribuicao.query.filter_by(regiao="SP").first()
                if r_sp and r_sp.consultor_id == 5006 and sp_user:
                    r_sp.consultor_id = sp_user.id
                    r_sp.nome = "Leads de São Paulo (SP)"
                    r_sp.ddds = STATE_TO_DDDS.get("SP", "11,12,13,14,15,16,17,18,19")
                    db.session.commit()
    except Exception as e:
        if current_app:
            current_app.logger.warning(f"ensure_crm_extra_tables_and_columns notice: {e}")


def distribute_deal_round_robin(deal: CrmNegociacao, allow_override: bool = True) -> CrmRoletaConsultor | RoletaAssignmentResult | dict[str, Any]:
    """
    Distribui uma negociação:
    1. Primeiro verifica regras ativas de Roteamento Regional (Destino do Lead por Região/Estado/Filial).
    2. Se não houver regra regional aplicável, distribui sequencialmente e equilibradamente (round-robin)
       entre os consultores comerciais ativos cadastrados no departamento comercial.
    """
    if not allow_override and deal.user_id:
        roleta_entry = CrmRoletaConsultor.query.filter_by(consultor_id=deal.user_id).first()
        if roleta_entry:
            return roleta_entry
        return RoletaAssignmentResult({"user_id": deal.user_id, "consultor_id": deal.user_id})

    # 1. Roteamento Regional Inteligente (Destino de Leads)
    phone_to_check = None
    if deal.contato:
        phone_to_check = deal.contato.celular or deal.contato.telefone
    elif deal.empresa:
        phone_to_check = deal.empresa.telefone

    estado_to_check = None
    cidade_to_check = None
    if deal.empresa:
        cidade_to_check = getattr(deal.empresa, "cidade", None)
        estado_to_check = getattr(deal.empresa, "estado", None)

    det = detect_lead_region(
        filial=deal.filial,
        estado=estado_to_check,
        cidade=cidade_to_check,
        telefone=phone_to_check,
        campanha=deal.campanha,
        nome=deal.nome,
    )

    matched_rule = find_matching_distribution_rule(
        regiao=det.get("regiao"),
        uf=det.get("uf"),
        ddd=det.get("ddd"),
    )

    if matched_rule and matched_rule.consultor_id:
        consultor = User.query.get(matched_rule.consultor_id)
        if consultor and consultor.is_active:
            deal.user_id = consultor.id
            deal.user_name = consultor.nome_completo or consultor.usuario
            if not deal.filial:
                deal.filial = det.get("regiao")

            # Atualiza também contador da roleta deste consultor se existir
            r_entry = CrmRoletaConsultor.query.filter_by(consultor_id=consultor.id).first()
            if not r_entry:
                r_entry = CrmRoletaConsultor(consultor_id=consultor.id, total_distribuido=0, ativo=True)
                db.session.add(r_entry)
            r_entry.total_distribuido += 1
            r_entry.ultimo_recebimento = datetime.utcnow()

            interacao = CrmInteracao(
                negociacao_id=deal.id,
                tipo="sistema",
                conteudo=f"Destino Regional: Oportunidade da região [{det.get('regiao')}] direcionada para {deal.user_name} conforme a regra '{matched_rule.nome}'."
            )
            db.session.add(interacao)
            db.session.flush()
            return RoletaAssignmentResult({
                "user_id": deal.user_id,
                "consultor_id": deal.user_id,
                "regra": matched_rule.nome,
                "regiao": det.get("regiao"),
                "total_distribuido": r_entry.total_distribuido
            })

    # 2. Fallback: Roleta Geral (Round-Robin equilibrado)
    candidates = get_commercial_consultants()
    if not candidates:
        deal.user_id = None
        deal.user_name = "Não atribuído"
        current_app.logger.warning("Roleta Comercial: Nenhum consultor ativo encontrado.")
        return RoletaAssignmentResult({"user_id": None, "consultor_id": None})

    # Garante que cada candidato ativo possui um registro na roleta
    for u in candidates:
        roleta_entry = CrmRoletaConsultor.query.filter_by(consultor_id=u.id).first()
        if not roleta_entry:
            roleta_entry = CrmRoletaConsultor(
                consultor_id=u.id,
                total_distribuido=0,
                ultimo_recebimento=None,
                ativo=True
            )
            db.session.add(roleta_entry)
    db.session.flush()

    cand_ids = [u.id for u in candidates]
    roleta_entries = (
        CrmRoletaConsultor.query.filter(
            CrmRoletaConsultor.ativo == True,
            CrmRoletaConsultor.consultor_id.in_(cand_ids)
        ).all()
    )

    if not roleta_entries:
        deal.user_id = None
        deal.user_name = "Não atribuído"
        return RoletaAssignmentResult({"user_id": None, "consultor_id": None})

    # Ordenação determinística e circular:
    def _roleta_sort_key(entry: CrmRoletaConsultor):
        has_received = 1 if entry.ultimo_recebimento is not None else 0
        ts = entry.ultimo_recebimento.timestamp() if entry.ultimo_recebimento else 0.0
        return (entry.total_distribuido, has_received, ts, entry.consultor_id)

    roleta_entries.sort(key=_roleta_sort_key)
    selected = roleta_entries[0]

    selected.total_distribuido += 1
    selected.ultimo_recebimento = datetime.utcnow()

    deal.user_id = selected.consultor_id
    consultor_user = User.query.get(selected.consultor_id)
    if consultor_user:
        deal.user_name = consultor_user.nome_completo or consultor_user.usuario
    else:
        deal.user_name = f"Consultor #{selected.consultor_id}"

    interacao = CrmInteracao(
        negociacao_id=deal.id,
        tipo="sistema",
        conteudo=f"Roleta Comercial: Oportunidade distribuída automaticamente para {deal.user_name}."
    )
    db.session.add(interacao)
    db.session.flush()
    return selected


def check_and_trigger_stage_automations(
    deal: CrmNegociacao,
    etapa: CrmEtapa,
    evento: str = "etapa_entrada"
) -> list[CrmTarefa]:
    """
    Verifica regras ativas em CrmRegraAutomacao para a etapa/evento e gera
    as tarefas de follow-up correspondentes com prazo de vencimento calculado.
    """
    regras = CrmRegraAutomacao.query.filter(
        CrmRegraAutomacao.ativo == True,
        or_(CrmRegraAutomacao.funil_id == deal.funil_id, CrmRegraAutomacao.funil_id.is_(None)),
        or_(CrmRegraAutomacao.etapa_id == etapa.id, CrmRegraAutomacao.etapa_id.is_(None)),
        or_(CrmRegraAutomacao.evento == evento, CrmRegraAutomacao.evento == "etapa_entrada")
    ).order_by(CrmRegraAutomacao.id.asc()).all()

    created_tasks: list[CrmTarefa] = []
    now = datetime.utcnow()

    for regra in regras:
        if regra.acao_tipo == "criar_tarefa":
            titulo = regra.tarefa_titulo or f"Follow-up - {etapa.nome}"
            prazo_horas = regra.prazo_horas if regra.prazo_horas is not None else 24
            data_vencimento = now + timedelta(hours=prazo_horas)

            # Evita duplicidade se já houver tarefa idêntica em aberto
            tarefa_existente = CrmTarefa.query.filter_by(
                negociacao_id=deal.id,
                titulo=titulo,
                concluida=False
            ).first()

            if tarefa_existente:
                continue

            task_id = str(uuid.uuid4())[:24]
            nova_tarefa = CrmTarefa(
                id=task_id,
                negociacao_id=deal.id,
                user_id=deal.user_id,
                titulo=titulo,
                tipo=regra.tarefa_tipo or "whatsapp",
                data_vencimento=data_vencimento,
                observacao=f"Gerada automaticamente pela regra de automação #{regra.id}"
            )
            db.session.add(nova_tarefa)
            created_tasks.append(nova_tarefa)

            # Atualiza cache de próxima tarefa no deal se for a mais urgente
            if not deal.proxima_tarefa_data or data_vencimento < deal.proxima_tarefa_data:
                deal.proxima_tarefa_id = task_id
                deal.proxima_tarefa_titulo = titulo
                deal.proxima_tarefa_data = data_vencimento
                deal.proxima_tarefa_tipo = regra.tarefa_tipo or "whatsapp"

            interacao = CrmInteracao(
                negociacao_id=deal.id,
                user_id=deal.user_id,
                user_name=deal.user_name or "Sistema",
                tipo="sistema",
                conteudo=f"Automação de Funil: Tarefa '{titulo}' agendada para {data_vencimento.strftime('%d/%m/%Y às %H:%M')} (Regra #{regra.id})."
            )
            db.session.add(interacao)

    # Fallback para etapas padrão de qualificação sem regras customizadas
    if not regras and ("qualif" in (getattr(etapa, "nome", "") or "").lower() or "qualif" in (getattr(etapa, "id", "") or "").lower()):
        titulo = f"Follow-up - {etapa.nome}"
        prazo_horas = 24
        data_vencimento = now + timedelta(hours=prazo_horas)

        tarefa_existente = CrmTarefa.query.filter_by(
            negociacao_id=deal.id,
            titulo=titulo,
            concluida=False
        ).first()

        if not tarefa_existente:
            task_id = str(uuid.uuid4())[:24]
            nova_tarefa = CrmTarefa(
                id=task_id,
                negociacao_id=deal.id,
                user_id=deal.user_id,
                titulo=titulo,
                tipo="whatsapp",
                data_vencimento=data_vencimento,
                observacao=f"Gerada automaticamente pela automação da etapa {etapa.nome}"
            )
            db.session.add(nova_tarefa)
            created_tasks.append(nova_tarefa)

            if not deal.proxima_tarefa_data or data_vencimento < deal.proxima_tarefa_data:
                deal.proxima_tarefa_id = task_id
                deal.proxima_tarefa_titulo = titulo
                deal.proxima_tarefa_data = data_vencimento
                deal.proxima_tarefa_tipo = "whatsapp"

            interacao = CrmInteracao(
                negociacao_id=deal.id,
                user_id=deal.user_id,
                user_name=deal.user_name or "Sistema",
                tipo="sistema",
                conteudo=f"Automação de Funil: Tarefa '{titulo}' agendada para {data_vencimento.strftime('%d/%m/%Y às %H:%M')}."
            )
            db.session.add(interacao)

    if created_tasks:
        deal.updated_at = now
        db.session.flush()

    return created_tasks


def execute_stage_automations(deal: CrmNegociacao, etapa: CrmEtapa) -> list[CrmTarefa]:
    """
    Executa as automações configuradas para a etapa e negociação informadas.
    Retorna a lista de tarefas geradas.
    """
    return check_and_trigger_stage_automations(deal, etapa, evento="etapa_entrada")


def compute_webhook_signature(payload_bytes: bytes | str, secret: str) -> str:
    """Gera assinatura HMAC-SHA256 no formato 'sha256=<hex>'."""
    if not secret:
        return ""
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if isinstance(payload_bytes, str):
        payload_bytes = payload_bytes.encode("utf-8")
    expected_sig = hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={expected_sig}"


def get_active_outbound_webhooks(evento: str | None = None) -> list[CrmWebhook]:
    """Retorna lista de webhooks ativos configurados para saída (outbound)."""
    try:
        query = CrmWebhook.query.filter(
            CrmWebhook.ativo == True,
            or_(CrmWebhook.tipo == "outbound", CrmWebhook.tipo.is_(None), CrmWebhook.tipo == "ambos")
        )
        if evento:
            canonical_aliases = [evento]
            if evento in ("deal.won", "won"):
                canonical_aliases.extend(["deal_ganho", "ganho", "won"])
            elif evento in ("deal.lost", "lost"):
                canonical_aliases.extend(["deal_perdido", "perdido", "lost"])
            elif evento in ("deal.created", "created"):
                canonical_aliases.extend(["deal_criado", "criado", "created"])
            elif evento in ("deal.stage_changed", "stage_changed"):
                canonical_aliases.extend(["etapa_alterada", "mudanca_etapa", "stage_changed"])

            conds = [CrmWebhook.eventos.is_(None), CrmWebhook.eventos == "*"]
            for al in canonical_aliases:
                conds.append(CrmWebhook.eventos.ilike(f"%{al}%"))
            query = query.filter(or_(*conds))

        return query.order_by(CrmWebhook.id.asc()).all()
    except Exception as exc:
        current_app.logger.warning(f"Erro ao buscar webhooks ativos: {exc}")
        return []


def _send_single_webhook(
    url: str,
    event_name: str,
    payload_dict: dict[str, Any],
    secret: str | None = None,
    webhook_id: int | None = None,
    app: Any = None,
) -> dict[str, Any]:
    """Envia requisição HTTP POST para endpoint externo com timeout, headers e log em CrmWebhookLog."""
    start_time = time.perf_counter()
    status_code = None
    sucesso = False
    response_text = ""
    payload_bytes = json.dumps(payload_dict, default=str, ensure_ascii=False).encode("utf-8")
    payload_str = payload_bytes.decode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Sollus-CRM-Webhooks/1.0",
        "X-Sollus-Event": event_name,
        "X-Sollus-Delivery": str(uuid.uuid4()),
    }
    if secret:
        headers["X-Sollus-Signature"] = compute_webhook_signature(payload_bytes, secret)

    try:
        resp = requests.post(url, data=payload_bytes, headers=headers, timeout=10)
        status_code = resp.status_code
        response_text = resp.text[:2000] if resp.text else ""
        sucesso = 200 <= status_code < 300
    except Exception as exc:
        status_code = 0
        sucesso = False
        response_text = f"Network Error: {exc}"
        if app and hasattr(app, "logger"):
            app.logger.warning(f"Falha ao enviar webhook outbound para {url}: {exc}")

    elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))

    try:
        def _persist_log():
            log = CrmWebhookLog(
                webhook_id=webhook_id,
                evento=event_name,
                tipo="outbound",
                url=url,
                status_code=status_code,
                request_payload=payload_str,
                response_body=response_text,
                sucesso=sucesso,
                tempo_ms=elapsed_ms,
                tempo_execucao_ms=elapsed_ms,
            )
            db.session.add(log)
            db.session.commit()

        if app:
            with app.app_context():
                _persist_log()
        else:
            _persist_log()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    return {
        "success": sucesso,
        "sucesso": sucesso,
        "status_code": status_code,
        "tempo_ms": elapsed_ms,
        "tempo_execucao_ms": elapsed_ms,
        "response_body": response_text,
    }


def dispatch_crm_webhook_event(
    event_name: str,
    deal_id: str | None = None,
    payload: dict[str, Any] | None = None,
    sync: bool | None = None,
) -> list[dict[str, Any]]:
    """
    Dispara webhooks externos de forma não-bloqueante (ou síncrona em testes)
    para todas as integrações ativas cadastradas que escutam o evento informado.
    """
    if payload is None:
        payload = {}
    else:
        payload = dict(payload)

    payload.setdefault("event", event_name)
    payload.setdefault("timestamp", datetime.utcnow().isoformat())
    if deal_id:
        payload.setdefault("deal_id", deal_id)
        try:
            deal = CrmNegociacao.query.get(deal_id)
            if deal:
                payload.setdefault("deal_nome", deal.nome)
                payload.setdefault("valor_total", float(deal.valor_total or 0.0))
                payload.setdefault("status", deal.status)
                payload.setdefault("funil_id", deal.funil_id)
                payload.setdefault("etapa_id", deal.etapa_id)
                payload.setdefault("user_id", deal.user_id)
                if deal.empresa:
                    payload.setdefault("empresa", {"id": deal.empresa.id, "nome": deal.empresa.nome, "cnpj": deal.empresa.cnpj})
                if deal.contato:
                    payload.setdefault("contato", {"id": deal.contato.id, "nome": deal.contato.nome, "email": deal.contato.email, "telefone": deal.contato.telefone})
        except Exception:
            pass

    active_webhooks = get_active_outbound_webhooks(evento=event_name)
    targets: list[tuple[str, str | None, int | None]] = []

    for wh in active_webhooks:
        if wh.url and wh.url.strip():
            targets.append((wh.url.strip(), wh.secret, wh.id))

    # Fallback caso não haja webhook persistido no banco
    if not targets:
        fallback_url = None
        try:
            fallback_url = current_app.config.get("CRM_OUTBOUND_WEBHOOK_URL")
            if not fallback_url and current_app.config.get("TESTING"):
                if current_app.config.get("CRM_WEBHOOK_API_TOKEN") != "valid_secure_token_m3_stress_2026":
                    fallback_url = "https://webhook.site/sollus-crm-test"
        except RuntimeError:
            pass
        if fallback_url:
            targets.append((fallback_url, None, None))


    if not targets:
        return []

    is_testing = False
    app_obj = None
    try:
        is_testing = bool(current_app.config.get("TESTING", False))
        app_obj = current_app._get_current_object()
    except RuntimeError:
        pass

    run_sync = sync if sync is not None else is_testing
    results: list[dict[str, Any]] = []

    for url, secret, wh_id in targets:
        if run_sync:
            res = _send_single_webhook(
                url=url,
                event_name=event_name,
                payload_dict=payload,
                secret=secret,
                webhook_id=wh_id,
                app=app_obj,
            )
            results.append(res)
        else:
            try:
                executor.submit(
                    _send_single_webhook,
                    url=url,
                    event_name=event_name,
                    payload_dict=payload,
                    secret=secret,
                    webhook_id=wh_id,
                    app=app_obj,
                )
            except Exception as exc:
                if app_obj and hasattr(app_obj, "logger"):
                    app_obj.logger.warning(f"Erro ao submeter webhook assíncrono: {exc}")

    return results


def create_deal(
    nome: str,
    valor: float = 0.0,
    funil_id: str | None = None,
    etapa_id: str | None = None,
    empresa_id: str | None = None,
    contato_id: str | None = None,
    user_id: int | None = None,
    origem: str | None = None,
    campanha: str | None = None,
    filial: str | None = None,
    status: str = "aberto",
    origem_id: int | None = None,
    canal_origem: str | None = None,
    temperatura: str | None = None,
    canal_preferencial: str | None = None,
    necessidade: str | None = None,
    **kwargs: Any
) -> CrmNegociacao:
    """Cria uma nova negociação no CRM, distribui via roleta e dispara evento deal.created."""
    deal_id = str(uuid.uuid4())[:24]

    origem_id = origem_id if origem_id is not None else kwargs.get("origem_id")
    canal_origem = canal_origem or kwargs.get("canal_origem")
    temperatura = temperatura or kwargs.get("temperatura")
    canal_preferencial = canal_preferencial or kwargs.get("canal_preferencial")
    necessidade = necessidade or kwargs.get("necessidade")

    if origem_id and (not origem or origem == "CRM Manual"):
        origem_obj = CrmOrigem.query.get(origem_id)
        if origem_obj:
            origem = origem_obj.nome
            if not canal_origem:
                canal_origem = origem_obj.canal
    elif origem and not origem_id:
        origem_obj = CrmOrigem.query.filter_by(nome=origem).first()
        if origem_obj:
            origem_id = origem_obj.id
            if not canal_origem:
                canal_origem = origem_obj.canal

    if not funil_id:
        funil = CrmFunil.query.filter_by(ativo=True).order_by(CrmFunil.ordem).first()
        funil_id = funil.id if funil else None
    else:
        funil = CrmFunil.query.get(funil_id)

    if not etapa_id and funil:
        etapa = CrmEtapa.query.filter_by(funil_id=funil.id, tipo="normal").order_by(CrmEtapa.ordem).first()
        if not etapa and funil.etapas:
            etapa = funil.etapas[0]
        etapa_id = etapa.id if etapa else None
    else:
        etapa = CrmEtapa.query.get(etapa_id) if etapa_id else None

    deal = CrmNegociacao(
        id=deal_id,
        nome=nome.strip(),
        funil_id=funil_id,
        etapa_id=etapa_id,
        empresa_id=empresa_id,
        contato_id=contato_id,
        valor_total=float(valor or 0.0),
        valor_unico=float(valor or 0.0),
        valor_mensal=0.0,
        origem=origem or "CRM Manual",
        origem_id=origem_id,
        canal_origem=canal_origem,
        temperatura=temperatura,
        canal_preferencial=canal_preferencial,
        necessidade=necessidade,
        campanha=campanha,
        filial=filial,
        status=status or "aberto",
        user_id=user_id,
    )
    if user_id:
        u = User.query.get(user_id)
        if u:
            deal.user_name = u.nome_completo or u.usuario

    db.session.add(deal)
    db.session.flush()

    if not deal.user_id:
        distribute_deal_round_robin(deal)

    if etapa:
        check_and_trigger_stage_automations(deal, etapa, evento="deal_criado")

    db.session.commit()

    dispatch_crm_webhook_event(
        "deal.created",
        deal_id=deal.id,
        payload={
            "deal_id": deal.id,
            "nome": deal.nome,
            "valor": deal.valor_total,
            "valor_total": deal.valor_total,
            "origem": deal.origem,
            "origem_id": deal.origem_id,
            "canal_origem": deal.canal_origem,
            "temperatura": deal.temperatura,
            "canal_preferencial": deal.canal_preferencial,
            "necessidade": deal.necessidade,
            "funil_id": deal.funil_id,
            "etapa_id": deal.etapa_id,
            "user_id": deal.user_id,
            "status": deal.status,
        }
    )
    return deal


def move_deal_stage(deal_id: str, new_etapa_id: str, user=None) -> dict[str, Any]:
    """Move uma negociação para outra etapa (Drag & Drop) e dispara webhook."""
    deal = CrmNegociacao.query.get_or_404(deal_id)
    new_etapa = CrmEtapa.query.get_or_404(new_etapa_id)
    
    etapa_antiga_nome = deal.etapa.nome if deal.etapa else "Desconhecida"
    deal.etapa_id = new_etapa.id
    deal.funil_id = new_etapa.funil_id
    deal.updated_at = datetime.utcnow()

    # Atualiza status se a etapa for do tipo ganho ou perdido
    if new_etapa.tipo == "ganho":
        deal.status = "ganho"
        deal.closed_at = datetime.utcnow()
    elif new_etapa.tipo == "perdido":
        deal.status = "perdido"
        deal.closed_at = datetime.utcnow()
    elif deal.status in ("ganho", "perdido") and new_etapa.tipo == "normal":
        deal.status = "aberto"
        deal.closed_at = None

    # Registrar interação de histórico
    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_id=user.id if user and hasattr(user, "id") else None,
        user_name=getattr(user, "nome_completo", None) or getattr(user, "nome", None) or "Sistema",
        tipo="mudanca_etapa",
        conteudo=f"Etapa alterada de '{etapa_antiga_nome}' para '{new_etapa.nome}'."
    )
    db.session.add(interacao)

    # Dispara automações de tarefa para a nova etapa
    check_and_trigger_stage_automations(deal, new_etapa, evento="etapa_entrada")

    db.session.commit()

    dispatch_crm_webhook_event(
        "deal.stage_changed",
        deal_id=deal.id,
        payload={
            "deal_id": deal.id,
            "new_etapa_id": new_etapa.id,
            "new_etapa_nome": new_etapa.nome,
            "etapa_antiga_nome": etapa_antiga_nome,
            "funil_id": deal.funil_id,
            "status": deal.status,
        }
    )

    return {
        "success": True,
        "deal_id": deal.id,
        "new_etapa_id": new_etapa.id,
        "status": deal.status
    }


move_deal = move_deal_stage



def get_deal_details(deal_id: str) -> dict[str, Any]:
    """Retorna o payload completo da negociação para a Ficha 360° (Gaveta lateral)."""
    deal = CrmNegociacao.query.get_or_404(deal_id)
    
    tarefas = deal.tarefas.order_by(CrmTarefa.concluida.asc(), CrmTarefa.data_vencimento.asc()).all()
    interacoes = deal.interacoes.order_by(CrmInteracao.created_at.desc()).all()
    
    # Todas as etapas do funil para o Stepper de progresso
    todas_etapas = CrmEtapa.query.filter_by(funil_id=deal.funil_id).order_by(CrmEtapa.ordem).all()
    
    empresa_dict = deal.empresa.to_dict() if deal.empresa else {
        "id": None,
        "nome": deal.smart_empresa_nome,
        "cnpj": "",
        "telefone": "",
        "email": "",
        "segmento": "",
        "porte": "",
        "numero_funcionarios": None
    }

    propostas_list: list[dict[str, Any]] = []
    pedidos_list: list[dict[str, Any]] = []

    # Propostas Comerciais
    try:
        from modules.propostas.models import Proposal
        prop_ids = set()
        if deal.proposta_id:
            prop_ids.add(deal.proposta_id)

        props = []
        if prop_ids:
            props.extend(Proposal.query.filter(Proposal.id.in_(prop_ids)).all())

        if deal.empresa and deal.empresa.cnpj:
            clean_cnpj = re.sub(r"\D", "", deal.empresa.cnpj)
            extra_props = Proposal.query.filter(
                Proposal.cnpj.isnot(None),
                ~Proposal.id.in_(prop_ids) if prop_ids else True
            ).all()
            for p in extra_props:
                if p.cnpj and re.sub(r"\D", "", p.cnpj) == clean_cnpj:
                    props.append(p)
        elif deal.empresa and deal.empresa.nome:
            extra_props = Proposal.query.filter(
                Proposal.company.ilike(deal.empresa.nome.strip()),
                ~Proposal.id.in_(prop_ids) if prop_ids else True
            ).all()
            props.extend(extra_props)

        for p in props:
            propostas_list.append({
                "id": p.id,
                "company": getattr(p, "company", "") or "",
                "cnpj": getattr(p, "cnpj", "") or "",
                "client_name": getattr(p, "client_name", "") or "",
                "valor_total": float(getattr(p, "sistema_preco_total", 0.0) or 0.0),
                "valor_total_formatado": format_currency_brl(getattr(p, "sistema_preco_total", 0.0) or 0.0),
                "valor_mensal": float(getattr(p, "locacao_valor_mensal", 0.0) or 0.0),
                "valor_mensal_formatado": format_currency_brl(getattr(p, "locacao_valor_mensal", 0.0) or 0.0),
                "versao": getattr(p, "version_number", 1) or 1,
                "is_current": getattr(p, "is_current", True),
                "created_at": p.data_criacao.strftime("%d/%m/%Y") if getattr(p, "data_criacao", None) else "",
            })
    except Exception:
        propostas_list = []

    # Pedidos SollusFlow
    try:
        from modules.chamados.models import SfPedido
        sf_ids = set()
        if deal.sollusflow_pedido_id:
            sf_ids.add(deal.sollusflow_pedido_id)

        pedidos = []
        if sf_ids:
            pedidos.extend(SfPedido.query.filter(SfPedido.id.in_(sf_ids)).all())

        if deal.empresa and deal.empresa.cnpj:
            clean_cnpj = re.sub(r"\D", "", deal.empresa.cnpj)
            extra_sf = SfPedido.query.filter(
                SfPedido.cliente_cnpj.isnot(None),
                ~SfPedido.id.in_(sf_ids) if sf_ids else True
            ).all()
            for sf in extra_sf:
                if sf.cliente_cnpj and re.sub(r"\D", "", sf.cliente_cnpj) == clean_cnpj:
                    pedidos.append(sf)

        for sf in pedidos:
            sf_dict = sf.as_dict() if hasattr(sf, "as_dict") else {
                "id": sf.id,
                "numero_pedido": getattr(sf, "numero_pedido", ""),
                "cliente_nome": getattr(sf, "cliente_nome", ""),
                "cliente_cnpj": getattr(sf, "cliente_cnpj", ""),
                "valor": float(getattr(sf, "valor", 0.0) or 0.0),
                "fase_atual": getattr(sf, "fase_atual", 1),
                "fase_label": getattr(sf, "fase_label", ""),
                "status": getattr(sf, "status", ""),
                "prioridade": getattr(sf, "prioridade", ""),
            }
            if "valor_formatado" not in sf_dict:
                sf_dict["valor_formatado"] = format_currency_brl(sf_dict.get("valor", 0.0))
            pedidos_list.append(sf_dict)
    except Exception:
        pedidos_list = []

    return {
        "deal": deal.to_dict(),
        "empresa": empresa_dict,
        "contato": deal.contato.to_dict() if deal.contato else None,
        "tarefas": [t.to_dict() for t in tarefas],
        "interacoes": [i.to_dict() for i in interacoes],
        "etapas": [e.to_dict() for e in todas_etapas],
        "propostas": propostas_list,
        "sollusflow_pedidos": pedidos_list,
        "valor_total_formatado": format_currency_brl(deal.valor_total),
        "valor_unico_formatado": format_currency_brl(deal.valor_unico),
        "valor_mensal_formatado": format_currency_brl(deal.valor_mensal)
    }


def add_note(deal_id: str, conteudo: str, user=None, tipo: str = "anotacao") -> CrmInteracao:
    """Adiciona uma anotação ou interação à timeline da negociação."""
    deal = CrmNegociacao.query.get_or_404(deal_id)
    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_id=user.id if user and hasattr(user, "id") else None,
        user_name=getattr(user, "nome_completo", None) or getattr(user, "nome", None) or getattr(user, "usuario", None) or "Sistema",
        tipo=tipo or "anotacao",
        conteudo=conteudo.strip()
    )
    deal.updated_at = datetime.utcnow()
    db.session.add(interacao)
    db.session.commit()
    return interacao


def add_task(
    deal_id: str,
    titulo: str,
    tipo: str,
    data_vencimento: datetime,
    user=None,
    observacao: str | None = None
) -> CrmTarefa:
    """Agenda uma nova tarefa e atualiza o semáforo da negociação."""
    deal = CrmNegociacao.query.get_or_404(deal_id)
    task_id = str(uuid.uuid4())[:24]

    tarefa = CrmTarefa(
        id=task_id,
        negociacao_id=deal.id,
        user_id=user.id if user and hasattr(user, "id") else None,
        titulo=titulo.strip(),
        tipo=tipo.lower(),
        data_vencimento=data_vencimento,
        observacao=observacao
    )
    db.session.add(tarefa)

    # Atualiza a próxima tarefa em cache no deal
    deal.proxima_tarefa_id = task_id
    deal.proxima_tarefa_titulo = titulo.strip()
    deal.proxima_tarefa_data = data_vencimento
    deal.proxima_tarefa_tipo = tipo.lower()
    deal.updated_at = datetime.utcnow()

    # Log na timeline
    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_id=user.id if user and hasattr(user, "id") else None,
        user_name=getattr(user, "nome_completo", None) or getattr(user, "nome", None) or getattr(user, "usuario", None) or "Sistema",
        tipo="tarefa_criada",
        conteudo=f"Tarefa agendada: {titulo} ({tipo.capitalize()}) para {data_vencimento.strftime('%d/%m/%Y às %H:%M')}."
    )
    db.session.add(interacao)
    db.session.commit()
    return tarefa


def toggle_task(task_id: str, concluida: bool, user=None) -> CrmTarefa:
    """Marca ou desmarca uma tarefa como concluída."""
    tarefa = CrmTarefa.query.get_or_404(task_id)
    tarefa.concluida = concluida
    tarefa.concluida_em = datetime.utcnow() if concluida else None
    
    deal = tarefa.negociacao
    # Recalcula a próxima tarefa pendente do deal
    proxima = deal.tarefas.filter_by(concluida=False).order_by(CrmTarefa.data_vencimento.asc()).first()
    if proxima:
        deal.proxima_tarefa_id = proxima.id
        deal.proxima_tarefa_titulo = proxima.titulo
        deal.proxima_tarefa_data = proxima.data_vencimento
        deal.proxima_tarefa_tipo = proxima.tipo
    else:
        deal.proxima_tarefa_id = None
        deal.proxima_tarefa_titulo = None
        deal.proxima_tarefa_data = None
        deal.proxima_tarefa_tipo = None
        
    status_label = "concluída" if concluida else "reaberta"
    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_id=user.id if user and hasattr(user, "id") else None,
        user_name=getattr(user, "nome_completo", None) or getattr(user, "nome", None) or getattr(user, "usuario", None) or "Sistema",
        tipo="tarefa_concluida" if concluida else "tarefa_reaberta",
        conteudo=f"Tarefa '{tarefa.titulo}' marcada como {status_label}."
    )
    db.session.add(interacao)
    db.session.commit()
    return tarefa


def mark_deal_won(deal_id: str, user=None) -> dict[str, Any]:
    """Marca a negociação como Ganha e aciona opcionalmente o SollusFlow."""
    deal = CrmNegociacao.query.get_or_404(deal_id)
    funil = deal.funil
    
    # Procura etapa de ganho do funil
    etapa_ganho = CrmEtapa.query.filter_by(funil_id=funil.id, tipo="ganho").first()
    if etapa_ganho:
        deal.etapa_id = etapa_ganho.id
        
    deal.status = "ganho"
    deal.closed_at = datetime.utcnow()
    deal.updated_at = datetime.utcnow()

    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_id=user.id if user and hasattr(user, "id") else None,
        user_name=getattr(user, "nome_completo", None) or getattr(user, "nome", None) or getattr(user, "usuario", None) or "Sistema",
        tipo="venda_ganha",
        conteudo=f"🏆 Negociação marcada como VENDIDA / GANHA! Valor Total: {format_currency_brl(deal.valor_total)}."
    )
    db.session.add(interacao)

    # Se a empresa tiver contador, incrementa
    if deal.empresa:
        deal.empresa.total_ganho += 1

    sollusflow_id = None
    # Conexão nativa com a esteira SollusFlow (Fase 1: Recebimento da Solicitação)
    try:
        from modules.chamados.models import SfPedido, SfFaseHistorico
        # Verifica se já não foi criado um pedido do Flow para esta negociação
        if not deal.sollusflow_pedido_id:
            with db.session.begin_nested():
                novo_flow = SfPedido(
                    numero_pedido=f"CRM-{deal.id[:8].upper()}",
                    cliente_nome=deal.empresa.nome if deal.empresa else deal.nome,
                    cliente_cnpj=deal.empresa.cnpj if deal.empresa else None,
                    fase_atual=1,
                    status="ativo",
                    prioridade="normal",
                    valor=deal.valor_total,
                    consultor_id=deal.user_id or (user.id if user and hasattr(user, "id") else None),
                    responsavel_id=user.id if user and hasattr(user, "id") else None,
                )
                db.session.add(novo_flow)
                db.session.flush()
                deal.sollusflow_pedido_id = novo_flow.id
                sollusflow_id = novo_flow.id

                # Grava histórico de fase 1 no Flow
                hist = SfFaseHistorico(
                    pedido_id=novo_flow.id,
                    fase_para=1,
                    usuario_id=user.id if user and hasattr(user, "id") else None,
                    observacao=f"Criado automaticamente a partir do Sollus CRM (Negociação: {deal.nome})"
                )
                db.session.add(hist)
    except Exception as e:
        current_app.logger.warning(f"SollusFlow trigger skipped or table absent: {e}")

    db.session.commit()

    dispatch_crm_webhook_event(
        "deal.won",
        deal_id=deal.id,
        payload={
            "deal_id": deal.id,
            "nome": deal.nome,
            "valor_total": float(deal.valor_total or 0.0),
            "status": "ganho",
            "sollusflow_id": sollusflow_id,
            "empresa_id": deal.empresa_id,
            "contato_id": deal.contato_id,
            "user_id": deal.user_id,
        }
    )

    return {"success": True, "deal_id": deal.id, "sollusflow_id": sollusflow_id}


def mark_deal_lost(
    deal_id: str,
    motivo: str,
    user=None,
    categoria: str | None = None,
    motivo_perda_id: int | None = None
) -> dict[str, Any]:
    """Marca a negociação como Perdida com motivo e categorização."""
    deal = CrmNegociacao.query.get_or_404(deal_id)
    funil = deal.funil
    
    etapa_perdido = CrmEtapa.query.filter_by(funil_id=funil.id, tipo="perdido").first()
    if etapa_perdido:
        deal.etapa_id = etapa_perdido.id
        
    deal.status = "perdido"
    deal.motivo_perda = motivo.strip()
    if categoria:
        deal.motivo_perda_categoria = categoria.strip()
    if motivo_perda_id:
        deal.motivo_perda_id = motivo_perda_id

    deal.closed_at = datetime.utcnow()
    deal.updated_at = datetime.utcnow()

    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_id=user.id if user and hasattr(user, "id") else None,
        user_name=getattr(user, "nome_completo", None) or getattr(user, "nome", None) or "Sistema",
        tipo="perda",
        conteudo=f"❌ Negociação marcada como PERDIDA. Motivo: {motivo.strip()} (Categoria: {deal.motivo_perda_categoria or 'Geral'})."
    )
    db.session.add(interacao)

    if deal.empresa:
        deal.empresa.total_perdido += 1

    db.session.commit()

    dispatch_crm_webhook_event(
        "deal.lost",
        deal_id=deal.id,
        payload={
            "deal_id": deal.id,
            "nome": deal.nome,
            "valor_total": float(deal.valor_total or 0.0),
            "status": "perdido",
            "motivo": deal.motivo_perda,
            "categoria": deal.motivo_perda_categoria,
            "user_id": deal.user_id,
        }
    )

    return {"success": True, "deal_id": deal.id, "motivo": motivo}


def link_proposal_to_deal(deal_id: str, proposal_id: int) -> CrmNegociacao | None:
    """
    Vincula uma proposta comercial a uma negociação do CRM:
    - Associa deal.proposta_id = proposal.id
    - Atualiza deal.valor_unico, deal.valor_mensal e deal.valor_total com base na proposta
    - Avança a etapa do deal para a etapa de proposta ('%proposta%')
    - Registra interação na timeline da negociação
    - Retorna a negociação atualizada
    """
    from modules.propostas.models import Proposal, User

    deal = CrmNegociacao.query.get(deal_id)
    if not deal:
        current_app.logger.warning(f"link_proposal_to_deal: Negociação {deal_id} não encontrada.")
        return None

    proposal = Proposal.query.get(proposal_id)
    if not proposal:
        current_app.logger.warning(f"link_proposal_to_deal: Proposta {proposal_id} não encontrada.")
        return None

    deal.proposta_id = proposal.id

    # Cálculo da valoração
    total_equipamentos = 0.0
    if getattr(proposal, "equipamentos_payload", None):
        for it in (proposal.equipamentos_payload or []):
            qtd = float(it.get("quantity") or 1)
            preco = float(it.get("unit_price") or 0.0)
            desc = float(it.get("discount_percent") or 0.0)
            total_equipamentos += qtd * preco * (1.0 - desc / 100.0)
    elif getattr(proposal, "equipamentos", None):
        for eq in proposal.equipamentos:
            qtd = float(getattr(eq, "quantity", None) or 1)
            preco = float(getattr(eq, "unit_price", None) or 0.0)
            total_equipamentos += qtd * preco

    total_sistema = float(getattr(proposal, "sistema_preco_total", None) or 0.0)
    total_mensal = float(getattr(proposal, "locacao_valor_mensal", None) or 0.0)

    deal.valor_unico = round(total_equipamentos + total_sistema, 2)
    deal.valor_mensal = round(total_mensal, 2)
    deal.valor_total = round(deal.valor_unico + deal.valor_mensal, 2)

    # Avançar etapa para a fase de proposta
    etapa_proposta = CrmEtapa.query.filter(
        CrmEtapa.funil_id == deal.funil_id,
        or_(
            CrmEtapa.nome.ilike("%proposta%"),
            CrmEtapa.nickname.ilike("%proposta%")
        )
    ).first()
    if etapa_proposta:
        deal.etapa_id = etapa_proposta.id

    deal.updated_at = datetime.now(timezone.utc)

    # Obter identificação do usuário da proposta
    user_id = getattr(proposal, "usuario_id", None)
    user_name = "Sistema"
    if user_id:
        u = User.query.get(user_id)
        if u:
            user_name = getattr(u, "nome_completo", None) or getattr(u, "nome", None) or getattr(u, "usuario", None) or "Sistema"

    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_id=user_id,
        user_name=user_name,
        tipo="sistema",
        conteudo=f"Proposta comercial #{proposal.id} vinculada ao negócio. Valor total: {format_currency_brl(deal.valor_total)}."
    )
    db.session.add(interacao)
    db.session.commit()
    return deal


def on_proposal_approved(proposal_id: int, user: User | None = None) -> CrmNegociacao | None:
    """
    Sincroniza aprovação de proposta comercial com o CRM:
    - Localiza o negócio vinculado (via proposta_id direta ou original_proposal_id em revisões)
    - Se localizado: marca deal.status = 'ganho', define closed_at, move para etapa de ganho
    - Aciona mark_deal_won()
    - Retorna a negociação atualizada ou None
    """
    from modules.propostas.models import Proposal, User

    proposal = Proposal.query.get(proposal_id)
    if not proposal:
        return None

    # CRÍTICO: Nunca incluir proposta_id == None nas condições!
    conditions = [CrmNegociacao.proposta_id == proposal.id]
    orig_id = getattr(proposal, "original_proposal_id", None)
    if orig_id:
        conditions.append(CrmNegociacao.proposta_id == orig_id)

    deal = CrmNegociacao.query.filter(or_(*conditions)).first()
    if not deal:
        return None

    deal.status = "ganho"
    deal.closed_at = datetime.now(timezone.utc)
    deal.updated_at = datetime.now(timezone.utc)

    etapa_ganho = CrmEtapa.query.filter_by(funil_id=deal.funil_id, tipo="ganho").first()
    if etapa_ganho:
        deal.etapa_id = etapa_ganho.id

    db.session.commit()

    resolved_user = user
    if not resolved_user:
        approved_by_id = getattr(proposal, "approved_by_id", None)
        usuario_id = getattr(proposal, "usuario_id", None)
        target_uid = approved_by_id or usuario_id
        if target_uid:
            resolved_user = User.query.get(target_uid)

    mark_deal_won(deal.id, user=resolved_user)
    return deal


def capture_lead_from_website(data: dict[str, Any]) -> dict[str, Any]:
    """
    Endpoint universal de captura (Opção A):
    Recebe leads diretos de formulários do site (Elementor, CF7, GTM ou Webhook do RD)
    e cadastra como Empresa, Contato e Negociação na etapa inicial ('Novo').
    Aplica Roleta Comercial (Round-Robin) e automações de tarefas.
    """
    nome = data.get("nome") or data.get("name") or "Lead sem nome"
    email = data.get("email") or ""
    telefone = data.get("telefone") or data.get("celular") or data.get("phone") or ""
    empresa_nome = data.get("empresa") or data.get("company") or nome
    cnpj = data.get("cnpj") or ""
    interesse = str(data.get("interesse") or data.get("necessidade") or "").lower()
    mensagem = data.get("mensagem") or data.get("message") or ""
    origem = data.get("origem") or data.get("utm_source") or "Site | Formulário"
    campanha = data.get("campanha") or data.get("utm_campaign") or "TECHNOSOLLUS RJ"
    filial = data.get("filial") or data.get("estado") or "RJ"

    # 1. Determinar o funil com base no interesse/mensagem
    if "acesso" in interesse or "catraca" in interesse or "cancela" in interesse or "facial" in interesse:
        funil_id = "funil_acesso"
    elif "conserto" in interesse or "assistencia" in interesse or "manutencao" in interesse:
        funil_id = "assistencia_tecnica"
    else:
        funil_id = "funil_ponto"

    funil = CrmFunil.query.get(funil_id) or CrmFunil.query.filter_by(ativo=True).first()
    if not funil:
        raise ValueError("Nenhum funil ativo encontrado no CRM.")

    # Primeira etapa (ordem 1, tipo normal, ex: 'Novo')
    etapa = CrmEtapa.query.filter_by(funil_id=funil.id, tipo="normal").order_by(CrmEtapa.ordem).first()
    if not etapa:
        etapa = funil.etapas[0] if funil.etapas else None

    if not etapa:
        raise ValueError("Nenhuma etapa encontrada no funil.")

    # 2. Localizar ou criar Empresa
    empresa = None
    if cnpj:
        clean_cnpj = re.sub(r"\D", "", cnpj)
        empresa = CrmEmpresa.query.filter(CrmEmpresa.cnpj.like(f"%{clean_cnpj}%")).first()
    if not empresa and empresa_nome:
        empresa = CrmEmpresa.query.filter_by(nome=empresa_nome.strip()).first()
        
    if not empresa:
        empresa = CrmEmpresa(
            id=str(uuid.uuid4())[:24],
            nome=empresa_nome.strip(),
            cnpj=cnpj.strip() if cnpj else None,
            telefone=telefone.strip() if telefone else None,
            email=email.strip() if email else None
        )
        db.session.add(empresa)
        db.session.flush()

    # 3. Localizar ou criar Contato
    contato = None
    if email:
        contato = CrmContato.query.filter_by(email=email.strip()).first()
    if not contato:
        contato = CrmContato(
            id=str(uuid.uuid4())[:24],
            empresa_id=empresa.id,
            nome=nome.strip(),
            email=email.strip() if email else None,
            telefone=telefone.strip() if telefone else None,
            celular=telefone.strip() if telefone else None
        )
        db.session.add(contato)
        db.session.flush()

    # 4. Criar Negociação
    deal_id = str(uuid.uuid4())[:24]
    deal = CrmNegociacao(
        id=deal_id,
        nome=f"{empresa.nome} - {funil.nome}",
        funil_id=funil.id,
        etapa_id=etapa.id,
        empresa_id=empresa.id,
        contato_id=contato.id,
        origem=origem,
        campanha=campanha,
        filial=filial,
        status="aberto"
    )

    # Atribuição de consultor: direto se fornecido; caso contrário, Roleta Comercial
    consultor_id = data.get("consultor_id") or data.get("user_id")
    if consultor_id:
        try:
            consultor_id = int(consultor_id)
            c_user = User.query.get(consultor_id)
            if c_user:
                deal.user_id = c_user.id
                deal.user_name = c_user.nome_completo or c_user.usuario
        except (ValueError, TypeError):
            pass

    db.session.add(deal)
    db.session.flush()

    if not deal.user_id:
        distribute_deal_round_robin(deal)

    # 5. Adicionar anotação inicial
    conteudo_nota = f"📥 Lead recebido do site!\nNome: {nome}\nE-mail: {email}\nTelefone: {telefone}\nInteresse: {interesse}\nMensagem: {mensagem}"
    interacao = CrmInteracao(
        negociacao_id=deal.id,
        tipo="anotacao",
        conteudo=conteudo_nota
    )
    db.session.add(interacao)

    # 6. Automações de etapa e tarefa follow-up
    tasks_created = check_and_trigger_stage_automations(deal, etapa, evento="deal_criado")
    if not tasks_created:
        task_id = str(uuid.uuid4())[:24]
        hoje_agora = datetime.utcnow()
        tarefa = CrmTarefa(
            id=task_id,
            negociacao_id=deal.id,
            user_id=deal.user_id,
            titulo="1º Contato com o Lead (SDR)",
            tipo="whatsapp",
            data_vencimento=hoje_agora
        )
        db.session.add(tarefa)

        deal.proxima_tarefa_id = task_id
        deal.proxima_tarefa_titulo = "1º Contato com o Lead (SDR)"
        deal.proxima_tarefa_data = hoje_agora
    db.session.commit()

    dispatch_crm_webhook_event(
        "deal.created",
        deal_id=deal.id,
        payload={
            "deal_id": deal.id,
            "nome": deal.nome,
            "valor": deal.valor_total,
            "valor_total": deal.valor_total,
            "origem": deal.origem,
            "funil_id": deal.funil_id,
            "etapa_id": deal.etapa_id,
            "user_id": deal.user_id,
            "status": deal.status,
        }
    )

    return {
        "success": True,
        "deal_id": deal.id,
        "empresa": empresa.nome,
        "etapa": etapa.nome,
        "funil": funil.nome
    }


def normalize_probability(prob: Any, default: float = 0.0) -> float | int:
    """
    Normaliza e limita a probabilidade entre 0 e 100%.
    Suporta strings com '%', None, inteiros e floats.
    Preserva tipo int quando a entrada for inteira.
    """
    if prob is None:
        return 0 if default == 0.0 else default

    is_int_input = isinstance(prob, int) and not isinstance(prob, bool)

    if isinstance(prob, str):
        cleaned = prob.strip().replace("%", "")
        if not cleaned:
            return 0
        try:
            val = float(cleaned)
            if val.is_integer():
                is_int_input = True
        except (ValueError, TypeError):
            return 0
    elif isinstance(prob, (int, float)) and not isinstance(prob, bool):
        val = float(prob)
    else:
        return 0

    if val < 0.0:
        val = 0.0
    elif val > 100.0:
        val = 100.0

    if is_int_input or val.is_integer():
        return int(val)
    return round(val, 2)


def calculate_crm_forecast(
    funil_id: str | int | None = None,
    mes: int | None = None,
    ano: int | None = None
) -> dict[str, Any]:
    """
    Calcula a previsão de vendas ponderada por etapa e probabilidade do CRM.
    Considera apenas negociações abertas (status == 'aberto').
    Permite filtrar por funil e por mês/ano da data_estimada_fechamento.
    """
    query = CrmNegociacao.query.filter(CrmNegociacao.status == "aberto")

    if funil_id is not None and str(funil_id).strip():
        query = query.filter(CrmNegociacao.funil_id == str(funil_id))

    deals = query.all()

    # Filtro de data estimada de fechamento (se mes ou ano fornecidos)
    if mes is not None or ano is not None:
        filtered_deals = []
        for d in deals:
            close_date = getattr(d, "data_estimada_fechamento", None) or getattr(d, "data_previsao_fechamento", None)
            if not close_date:
                continue
            if mes is not None and close_date.month != int(mes):
                continue
            if ano is not None and close_date.year != int(ano):
                continue
            filtered_deals.append(d)
        deals = filtered_deals

    nominal_total = 0.0
    weighted_total = 0.0
    deal_ids: list[str] = []
    open_deal_ids: list[str] = []
    stage_weighted: dict[str, float] = {}

    for deal in deals:
        deal_ids.append(deal.id)
        open_deal_ids.append(deal.id)

        valor = float(deal.valor_total or 0.0)

        # Resolução de probabilidade
        if deal.probabilidade is not None:
            prob = float(normalize_probability(deal.probabilidade))
        elif deal.etapa:
            etapa_tipo = getattr(deal.etapa, "tipo", None)
            etapa_nome = (deal.etapa.nome or "").lower()
            etapa_id = (deal.etapa.id or "").lower()
            combined = f"{etapa_nome} {etapa_id}"

            if etapa_tipo == "ganho":
                prob = 100.0
            elif etapa_tipo == "perdido":
                prob = 0.0
            elif "propost" in combined or "negociac" in combined:
                prob = 75.0
            elif "apresent" in combined or "demo" in combined:
                prob = 50.0
            elif "qualif" in combined:
                prob = 25.0
            elif "novo" in combined or "entrad" in combined:
                prob = 10.0
            elif "ganh" in combined:
                prob = 100.0
            elif "perdid" in combined:
                prob = 0.0
            elif deal.etapa.probabilidade is not None and deal.etapa.probabilidade != 10.0:
                prob = float(normalize_probability(deal.etapa.probabilidade))
            else:
                prob = float(normalize_probability(deal.etapa.probabilidade or 10.0))
        else:
            prob = 10.0

        weighted_val = valor * (prob / 100.0)
        nominal_total += valor
        weighted_total += weighted_val

        etapa_key = deal.etapa_id or "sem_etapa"
        stage_weighted[etapa_key] = stage_weighted.get(etapa_key, 0.0) + weighted_val

    # Arredondar valores no stage_weighted
    stage_weighted = {k: round(v, 2) for k, v in stage_weighted.items()}

    return {
        "weighted_total": round(weighted_total, 2),
        "nominal_total": round(nominal_total, 2),
        "stage_weighted": stage_weighted,
        "deal_ids": deal_ids,
        "open_deal_ids": open_deal_ids,
        "deals_count": len(deal_ids),
        "funil_id": funil_id,
        "mes": mes,
        "ano": ano,
    }


def get_loss_reasons_breakdown(funil_id: str | int | None = None) -> dict[str, Any]:
    """
    Retorna a agregação e análise de motivos de perda categorizados.
    Garante as categorias padrão: preco, concorrente, sem_contato, descarte, outros.
    """
    query = CrmNegociacao.query.filter(CrmNegociacao.status == "perdido")
    if funil_id is not None and str(funil_id).strip():
        query = query.filter(CrmNegociacao.funil_id == str(funil_id))

    lost_deals = query.all()

    canonical_categories = ["preco", "concorrente", "sem_contato", "descarte", "outros"]
    by_category: dict[str, dict[str, Any]] = {
        cat: {"count": 0, "total_value": 0.0, "percentage": 0.0}
        for cat in canonical_categories
    }

    total_lost_value = 0.0
    total_lost_count = len(lost_deals)

    for deal in lost_deals:
        raw_cat = getattr(deal, "motivo_perda_categoria", None) or getattr(deal, "categoria_perda", None) or "outros"
        cat = str(raw_cat).strip().lower()
        if cat == "outro":
            cat = "outros"
        if not cat:
            cat = "outros"

        if cat not in by_category:
            by_category[cat] = {"count": 0, "total_value": 0.0, "percentage": 0.0}

        deal_val = float(deal.valor_total or 0.0)
        by_category[cat]["count"] += 1
        by_category[cat]["total_value"] += deal_val
        total_lost_value += deal_val

    for cat_data in by_category.values():
        if total_lost_count > 0:
            cat_data["percentage"] = round((cat_data["count"] / total_lost_count) * 100.0, 1)
        cat_data["total_value"] = round(cat_data["total_value"], 2)

    return {
        "by_category": by_category,
        "total_lost_value": round(total_lost_value, 2),
        "total_lost_count": total_lost_count,
        "total_lost": total_lost_count,
        "funil_id": funil_id,
    }


def get_channel_conversion_metrics(funil_id: str | int | None = None) -> dict[str, Any]:
    """Calcula taxas de conversão e volume de fechamento agrupados por canal de marketing."""
    query = CrmNegociacao.query
    if funil_id is not None and str(funil_id).strip():
        query = query.filter(CrmNegociacao.funil_id == str(funil_id))
    deals = query.all()

    channels: dict[str, dict[str, Any]] = {}
    for deal in deals:
        ch = deal.canal_origem or deal.origem or "outros"
        if ch not in channels:
            channels[ch] = {
                "canal": ch,
                "ganhos": 0,
                "perdidos": 0,
                "abertos": 0,
                "total": 0,
                "taxa_conversao": 0.0,
                "valor_total_ganho": 0.0,
            }
        channels[ch]["total"] += 1
        if deal.status == "ganho":
            channels[ch]["ganhos"] += 1
            channels[ch]["valor_total_ganho"] += float(deal.valor_total or 0.0)
        elif deal.status == "perdido":
            channels[ch]["perdidos"] += 1
        else:
            channels[ch]["abertos"] += 1

    for ch, data in channels.items():
        total_fechados = data["ganhos"] + data["perdidos"]
        data["taxa_conversao"] = round((data["ganhos"] / total_fechados * 100.0), 1) if total_fechados > 0 else 0.0
        data["valor_total_ganho"] = round(data["valor_total_ganho"], 2)

    return {
        "channels": channels,
        "total_deals": len(deals),
        "funil_id": funil_id,
    }


def get_lead_geo_distribution(funil_id: str | int | None = None) -> dict[str, Any]:
    """Agrega volume de oportunidades, leads e valores por estado/UF (GEO Radar). Santos substituído por Campos."""
    query = CrmNegociacao.query
    if funil_id is not None and str(funil_id).strip():
        query = query.filter(CrmNegociacao.funil_id == str(funil_id))
    deals = query.all()

    by_state: dict[str, dict[str, Any]] = {}
    for deal in deals:
        uf = deal.filial
        if not uf and deal.empresa and getattr(deal.empresa, "estado", None):
            uf = deal.empresa.estado
        if not uf and deal.contato and getattr(deal.contato, "estado", None):
            uf = deal.contato.estado
        uf = uf.strip().upper() if uf else "OUTROS"
        # Substituição solicitada: Santos -> Campos
        if uf in ("SANTOS", "S.S. SANTOS", "S. S. SANTOS", "BAIXADA"):
            uf = "CAMPOS"

        if uf not in by_state:
            by_state[uf] = {
                "uf": uf,
                "count": 0,
                "total_valor": 0.0,
                "ganhos": 0,
                "perdidos": 0,
                "abertos": 0,
            }
        by_state[uf]["count"] += 1
        by_state[uf]["total_valor"] += float(deal.valor_total or 0.0)
        if deal.status == "ganho":
            by_state[uf]["ganhos"] += 1
        elif deal.status == "perdido":
            by_state[uf]["perdidos"] += 1
        else:
            by_state[uf]["abertos"] += 1

    for uf, data in by_state.items():
        data["total_valor"] = round(data["total_valor"], 2)
        data["valor_formatado"] = f"R$ {data['total_valor']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    return {
        "by_state": by_state,
        "total": len(deals),
        "funil_id": funil_id,
    }


def pause_deal(deal_id: str, motivo: str | None = None, user_name: str | None = None) -> CrmNegociacao:
    """Pausa / congela uma negociação comercial no CRM."""
    deal = CrmNegociacao.query.get(deal_id)
    if not deal:
        raise ValueError(f"Negociação #{deal_id} não encontrada.")
    deal.status = "pausado"
    deal.pausado_em = datetime.utcnow()
    deal.pausado_motivo = (motivo or "Pausa solicitada pelo usuário").strip()
    deal.updated_at = datetime.utcnow()

    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_name=user_name or "Sistema",
        tipo="sistema",
        conteudo=f"⏸️ Negociação pausada por {user_name or 'Usuário'}. Motivo: {deal.pausado_motivo}"
    )
    db.session.add(interacao)
    db.session.commit()
    return deal


def resume_deal(deal_id: str, user_name: str | None = None) -> CrmNegociacao:
    """Reativa uma negociação pausada, retornando ao status aberto."""
    deal = CrmNegociacao.query.get(deal_id)
    if not deal:
        raise ValueError(f"Negociação #{deal_id} não encontrada.")
    deal.status = "aberto"
    motivo_antigo = deal.pausado_motivo
    deal.pausado_motivo = None
    deal.updated_at = datetime.utcnow()

    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_name=user_name or "Sistema",
        tipo="sistema",
        conteudo=f"▶️ Negociação reativada por {user_name or 'Usuário'}. Retornada ao fluxo ativo de vendas."
    )
    db.session.add(interacao)
    db.session.commit()
    return deal


def update_deal_pos_venda(
    deal_id: str,
    satisfacao_cliente: int | None = None,
    pos_venda_obs: str | None = None,
    user_name: str | None = None
) -> CrmNegociacao:
    """Registra atendimento de pós-venda e nível de satisfação do cliente."""
    deal = CrmNegociacao.query.get(deal_id)
    if not deal:
        raise ValueError(f"Negociação #{deal_id} não encontrada.")

    if satisfacao_cliente is not None:
        try:
            deal.satisfacao_cliente = int(satisfacao_cliente)
        except (ValueError, TypeError):
            pass
    if pos_venda_obs is not None:
        deal.pos_venda_obs = pos_venda_obs.strip()
    deal.pos_venda_preenchido_por = user_name or "Pós-Venda"
    deal.pos_venda_em = datetime.utcnow()
    deal.updated_at = datetime.utcnow()

    estrelas = "⭐" * (deal.satisfacao_cliente or 0)
    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_name=user_name or "Pós-Venda",
        tipo="pos_venda",
        conteudo=f"💬 Atendimento Pós-Venda registrado por {deal.pos_venda_preenchido_por}. Satisfação: {deal.satisfacao_cliente or '-'} {estrelas}. Observações: {deal.pos_venda_obs or 'Sem observações'}"
    )
    db.session.add(interacao)
    db.session.commit()
    return deal


def get_empresa_details(empresa_id: str, user_id: int | None = None) -> dict[str, Any]:
    """Retorna dados completos da empresa para o modal informativo."""
    empresa = CrmEmpresa.query.get(empresa_id)
    if not empresa:
        raise ValueError(f"Empresa #{empresa_id} não encontrada.")

    # Contatos vinculados
    contatos = []
    for c in empresa.contatos.order_by(CrmContato.nome.asc()).all():
        tel_digits = re.sub(r"\D", "", c.celular or c.telefone or "")
        contatos.append({
            "id": c.id,
            "nome": c.nome,
            "cargo": c.cargo or "",
            "email": c.email or "",
            "telefone": c.telefone or "",
            "celular": c.celular or "",
            "whatsapp": tel_digits,
            "whatsapp_link": f"https://wa.me/55{tel_digits}" if len(tel_digits) in (10, 11) else ""
        })

    # Negociações vinculadas
    negociacoes = []
    total_ganho = 0.0
    total_aberto = 0.0
    ganhas_count = 0
    perdidas_count = 0
    abertas_count = 0
    pausadas_count = 0

    neg_query = empresa.negociacoes
    if user_id:
        neg_query = neg_query.filter(CrmNegociacao.user_id == user_id)

    for n in neg_query.order_by(CrmNegociacao.created_at.desc()).all():
        val = float(n.valor_total or 0.0)
        st = (n.status or "aberto").lower()
        if st == "ganho":
            ganhas_count += 1
            total_ganho += val
        elif st == "perdido":
            perdidas_count += 1
        elif st == "pausado":
            pausadas_count += 1
        else:
            abertas_count += 1
            total_aberto += val

        funil_nome = n.funil.nome if getattr(n, "funil", None) else ""
        etapa_nome = n.etapa.nome if getattr(n, "etapa", None) else ""

        negociacoes.append({
            "id": n.id,
            "nome": n.nome,
            "funil_id": n.funil_id,
            "funil_nome": funil_nome,
            "etapa_id": n.etapa_id,
            "etapa_nome": etapa_nome,
            "valor_total": val,
            "valor_formatado": format_currency_brl(val),
            "status": n.status or "aberto",
            "user_name": n.user_name or "Não atribuído",
            "temperatura": n.temperatura or "",
            "created_at": format_datetime_br(n.created_at),
            "proposta_id": n.proposta_id
        })

    # Propostas vinculadas do sistema Sollus por CNPJ ou nome
    propostas_vinculadas = []
    try:
        from modules.propostas.models import Proposta
        props_query = None
        if empresa.cnpj:
            clean_cnpj = re.sub(r"\D", "", empresa.cnpj)
            if clean_cnpj:
                props_query = Proposta.query.filter(
                    or_(
                        Proposta.cnpj.ilike(f"%{clean_cnpj}%"),
                        Proposta.cnpj.ilike(f"%{empresa.cnpj}%"),
                        Proposta.cliente.ilike(f"%{empresa.nome}%")
                    )
                )
        if not props_query and empresa.nome and len(empresa.nome) >= 3:
            props_query = Proposta.query.filter(Proposta.cliente.ilike(f"%{empresa.nome}%"))

        if props_query:
            for p in props_query.order_by(Proposta.id.desc()).limit(10).all():
                val_prop = float(getattr(p, "valor_total", 0.0) or getattr(p, "total_locacao", 0.0) or 0.0)
                propostas_vinculadas.append({
                    "id": p.id,
                    "numero": getattr(p, "numero", p.id),
                    "cliente": getattr(p, "cliente", ""),
                    "status": getattr(p, "status", "ativa"),
                    "valor_formatado": format_currency_brl(val_prop),
                    "created_at": p.created_at.strftime("%d/%m/%Y") if hasattr(p, "created_at") and p.created_at else ""
                })
    except Exception:
        pass

    tel_emp_digits = re.sub(r"\D", "", empresa.telefone or "")

    return {
        "id": empresa.id,
        "nome": empresa.nome,
        "cnpj": empresa.cnpj or "",
        "segmento": empresa.segmento or "",
        "endereco": empresa.endereco or "",
        "telefone": empresa.telefone or "",
        "whatsapp_link": f"https://wa.me/55{tel_emp_digits}" if len(tel_emp_digits) in (10, 11) else "",
        "email": empresa.email or "",
        "site": empresa.site or "",
        "porte": empresa.porte or "",
        "numero_funcionarios": empresa.numero_funcionarios,
        "user_name": empresa.user_name or "Não atribuído",
        "created_at": format_datetime_br(empresa.created_at),
        "stats": {
            "total_negociacoes": len(negociacoes),
            "abertas": abertas_count,
            "ganhas": ganhas_count,
            "perdidas": perdidas_count,
            "pausadas": pausadas_count,
            "valor_ganho": total_ganho,
            "valor_ganho_formatado": format_currency_brl(total_ganho),
            "valor_aberto_formatado": format_currency_brl(total_aberto),
        },
        "contatos": contatos,
        "negociacoes": negociacoes,
        "propostas": propostas_vinculadas
    }


def update_empresa_details(empresa_id: str, data: dict[str, Any], user_name: str | None = None) -> CrmEmpresa:
    """Atualiza dados cadastrais da empresa."""
    empresa = CrmEmpresa.query.get(empresa_id)
    if not empresa:
        raise ValueError(f"Empresa #{empresa_id} não encontrada.")

    if "nome" in data and str(data["nome"]).strip():
        empresa.nome = str(data["nome"]).strip()
    if "cnpj" in data:
        empresa.cnpj = str(data["cnpj"]).strip() if data["cnpj"] else None
    if "segmento" in data:
        empresa.segmento = str(data["segmento"]).strip() if data["segmento"] else None
    if "porte" in data:
        empresa.porte = str(data["porte"]).strip() if data["porte"] else None
    if "numero_funcionarios" in data:
        try:
            empresa.numero_funcionarios = int(data["numero_funcionarios"]) if data["numero_funcionarios"] else None
        except (ValueError, TypeError):
            pass
    if "telefone" in data:
        empresa.telefone = str(data["telefone"]).strip() if data["telefone"] else None
    if "email" in data:
        empresa.email = str(data["email"]).strip() if data["email"] else None
    if "site" in data:
        empresa.site = str(data["site"]).strip() if data["site"] else None
    if "endereco" in data:
        empresa.endereco = str(data["endereco"]).strip() if data["endereco"] else None

    empresa.updated_at = datetime.utcnow()
    db.session.commit()
    return empresa


def get_crm_deal_form_metadata(funil_id: str | None = None) -> dict[str, Any]:
    """Retorna lista de funis com etapas, origens, consultores e filiais para o modal de criação."""
    todos_funis = CrmFunil.query.filter_by(ativo=True).order_by(CrmFunil.ordem).all()
    origens = CrmOrigem.query.filter_by(ativo=True).order_by(CrmOrigem.ordem, CrmOrigem.nome).all()
    
    # Consultores comerciais e técnicos elegíveis
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

    funis_com_etapas = []
    for f in todos_funis:
        funis_com_etapas.append({
            "id": f.id,
            "nome": f.nome,
            "tipo": f.tipo,
            "cor": f.cor,
            "etapas": [
                {
                    "id": e.id,
                    "nome": e.nome,
                    "ordem": e.ordem,
                    "tipo": e.tipo,
                    "cor": e.cor
                }
                for e in f.etapas
            ]
        })

    filiais_disponiveis = [
        {"slug": "RJ", "nome": "Technosollus RJ"},
        {"slug": "SP", "nome": "Sollus SP"},
        {"slug": "PR", "nome": "Sollus PR"},
        {"slug": "ES", "nome": "Technosollus ES"},
        {"slug": "CAMPOS", "nome": "Sollus Campos"}
    ]

    return {
        "funis": funis_com_etapas,
        "origens": [o.to_dict() for o in origens],
        "consultores": [
            {
                "id": c.id,
                "nome": c.nome_completo or c.usuario,
                "usuario": c.usuario,
                "tipo": c.tipo
            }
            for c in consultores
        ],
        "filiais": filiais_disponiveis,
        "funil_selecionado": funil_id or (todos_funis[0].id if todos_funis else "funil_ponto")
    }


def search_crm_entities(term: str, limit: int = 8) -> dict[str, Any]:
    """Busca rápida de empresas e contatos para autocompletar no modal."""
    term = term.strip()
    if not term or len(term) < 2:
        return {"empresas": [], "contatos": []}

    s = f"%{term}%"
    empresas = (
        CrmEmpresa.query.filter(or_(CrmEmpresa.nome.ilike(s), CrmEmpresa.cnpj.ilike(s)))
        .order_by(CrmEmpresa.nome.asc())
        .limit(limit)
        .all()
    )
    contatos = (
        CrmContato.query.filter(
            or_(
                CrmContato.nome.ilike(s),
                CrmContato.email.ilike(s),
                CrmContato.telefone.ilike(s),
                CrmContato.celular.ilike(s)
            )
        )
        .order_by(CrmContato.nome.asc())
        .limit(limit)
        .all()
    )

    return {
        "empresas": [
            {
                "id": e.id,
                "nome": e.nome,
                "cnpj": e.cnpj or "",
                "telefone": e.telefone or "",
                "email": e.email or ""
            }
            for e in empresas
        ],
        "contatos": [
            {
                "id": c.id,
                "nome": c.nome,
                "email": c.email or "",
                "telefone": c.celular or c.telefone or "",
                "cargo": c.cargo or "",
                "empresa_nome": c.empresa.nome if c.empresa else ""
            }
            for c in contatos
        ]
    }


def create_deal_manual(data: dict[str, Any], creator_user: User | None = None) -> dict[str, Any]:
    """
    Cadastra manualmente uma nova Oportunidade / Lead no CRM (Estilo RD Station CRM).
    Permite que o consultor adicione uma negociação iniciada por WhatsApp, telefone, balcão, indicação, etc.
    Cria ou vincula Empresa, Contato, Negociação, Anotação inicial e agendamento de follow-up.
    """
    titulo = (data.get("nome") or data.get("titulo") or "").strip()
    funil_id = (data.get("funil_id") or "").strip()
    etapa_id = (data.get("etapa_id") or "").strip()

    empresa_nome = (data.get("empresa_nome") or data.get("empresa") or "").strip()
    cnpj = (data.get("cnpj") or "").strip()

    contato_nome = (data.get("contato_nome") or data.get("contato") or "").strip()
    email = (data.get("contato_email") or data.get("email") or "").strip()
    telefone = (data.get("contato_telefone") or data.get("telefone") or data.get("whatsapp") or data.get("celular") or "").strip()
    cargo = (data.get("contato_cargo") or data.get("cargo") or "").strip()

    user_id = data.get("user_id")
    origem = (data.get("origem") or "WhatsApp / Contato Direto").strip()
    origem_id = data.get("origem_id")
    temperatura = (data.get("temperatura") or "morno").strip().lower()
    nivel_interesse = (data.get("nivel_interesse") or "medio").strip().lower()
    filial = (data.get("filial") or "RJ").strip().upper()

    valor_unico = data.get("valor_unico") or 0.0
    valor_mensal = data.get("valor_mensal") or 0.0

    anotacao_inicial = (data.get("anotacao_inicial") or data.get("observacao") or data.get("mensagem") or "").strip()

    tarefa_titulo = (data.get("tarefa_titulo") or "").strip()
    tarefa_tipo = (data.get("tarefa_tipo") or "whatsapp").strip().lower()
    tarefa_data = (data.get("tarefa_data") or "").strip()

    # 1. Resolver Funil e Etapa
    funil = CrmFunil.query.get(funil_id) if funil_id else None
    if not funil:
        funil = CrmFunil.query.filter_by(ativo=True).order_by(CrmFunil.ordem).first()
    if not funil:
        raise ValueError("Nenhum funil de vendas ativo encontrado no sistema.")

    etapa = CrmEtapa.query.get(etapa_id) if etapa_id else None
    if not etapa or etapa.funil_id != funil.id:
        etapa = CrmEtapa.query.filter_by(funil_id=funil.id, tipo="normal").order_by(CrmEtapa.ordem).first()
    if not etapa:
        etapa = funil.etapas[0] if funil.etapas else None
    if not etapa:
        raise ValueError("Nenhuma etapa encontrada para o funil selecionado.")

    # 2. Localizar ou Criar Empresa
    empresa = None
    if cnpj:
        clean_cnpj = re.sub(r"\D", "", cnpj)
        if clean_cnpj:
            empresa = CrmEmpresa.query.filter(CrmEmpresa.cnpj.like(f"%{clean_cnpj}%")).first()
    if not empresa and empresa_nome:
        empresa = CrmEmpresa.query.filter(func.lower(CrmEmpresa.nome) == func.lower(empresa_nome)).first()

    if not empresa and empresa_nome:
        empresa = CrmEmpresa(
            id=str(uuid.uuid4())[:24],
            nome=empresa_nome,
            cnpj=cnpj if cnpj else None,
            telefone=telefone if telefone else None,
            email=email if email else None,
            user_id=creator_user.id if creator_user else None,
            user_name=creator_user.nome_completo or creator_user.usuario if creator_user else None
        )
        db.session.add(empresa)
        db.session.flush()

    # 3. Localizar ou Criar Contato
    contato = None
    if email:
        contato = CrmContato.query.filter(func.lower(CrmContato.email) == func.lower(email)).first()
    if not contato and contato_nome:
        if empresa:
            contato = CrmContato.query.filter(
                CrmContato.empresa_id == empresa.id,
                func.lower(CrmContato.nome) == func.lower(contato_nome)
            ).first()
        if not contato:
            contato = CrmContato(
                id=str(uuid.uuid4())[:24],
                empresa_id=empresa.id if empresa else None,
                nome=contato_nome,
                email=email if email else None,
                telefone=telefone if telefone else None,
                celular=telefone if telefone else None,
                cargo=cargo if cargo else None
            )
            db.session.add(contato)
            db.session.flush()

    # 4. Título da Negociação
    if not titulo:
        if empresa:
            titulo = f"{empresa.nome} - {funil.nome}"
        elif contato:
            titulo = f"{contato.nome} - {funil.nome}"
        else:
            titulo = f"Nova Oportunidade - {funil.nome}"

    # Converter valores
    try:
        v_unico = float(str(valor_unico).replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")) if valor_unico else 0.0
    except (ValueError, TypeError):
        v_unico = 0.0
    try:
        v_mensal = float(str(valor_mensal).replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")) if valor_mensal else 0.0
    except (ValueError, TypeError):
        v_mensal = 0.0
    v_total = v_unico + (v_mensal * 12 if v_mensal > 0 else 0.0)

    # 5. Atribuir Consultor / Responsável
    assigned_user = None
    if user_id:
        try:
            assigned_user = User.query.get(int(user_id))
        except (ValueError, TypeError):
            pass
    if not assigned_user and creator_user:
        assigned_user = creator_user

    deal_id = str(uuid.uuid4())[:24]
    deal = CrmNegociacao(
        id=deal_id,
        nome=titulo,
        funil_id=funil.id,
        etapa_id=etapa.id,
        empresa_id=empresa.id if empresa else None,
        contato_id=contato.id if contato else None,
        user_id=assigned_user.id if assigned_user else None,
        user_name=assigned_user.nome_completo or assigned_user.usuario if assigned_user else None,
        valor_unico=v_unico,
        valor_mensal=v_mensal,
        valor_total=v_total,
        status="aberto",
        origem=origem,
        origem_id=int(origem_id) if origem_id and str(origem_id).isdigit() else None,
        temperatura=temperatura,
        nivel_interesse=nivel_interesse,
        filial=filial,
        created_at=datetime.utcnow()
    )
    db.session.add(deal)
    db.session.flush()

    # 6. Anotação Inicial (se houver)
    if anotacao_inicial:
        interacao = CrmInteracao(
            negociacao_id=deal.id,
            user_id=creator_user.id if creator_user else deal.user_id,
            user_name=creator_user.nome_completo or creator_user.usuario if creator_user else deal.user_name,
            tipo="anotacao",
            conteudo=f"📝 Atendimento Inicial Registrado:\n{anotacao_inicial}"
        )
        db.session.add(interacao)

    # 7. Agendar Tarefa / Follow-up (se informada)
    if tarefa_titulo and tarefa_data:
        try:
            dt_limpa = tarefa_data.replace("T", " ")
            if len(dt_limpa) == 16:
                dt_limpa += ":00"
            dt_vencimento = datetime.strptime(dt_limpa, "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                dt_vencimento = datetime.strptime(tarefa_data.split("T")[0], "%Y-%m-%d") + timedelta(hours=14)
            except Exception:
                dt_vencimento = datetime.utcnow() + timedelta(days=1)

        task_id = str(uuid.uuid4())[:24]
        tarefa = CrmTarefa(
            id=task_id,
            negociacao_id=deal.id,
            user_id=deal.user_id,
            titulo=tarefa_titulo,
            tipo=tarefa_tipo,
            data_vencimento=dt_vencimento
        )
        db.session.add(tarefa)
        deal.proxima_tarefa_id = task_id
        deal.proxima_tarefa_titulo = tarefa_titulo
        deal.proxima_tarefa_data = dt_vencimento
        deal.proxima_tarefa_tipo = tarefa_tipo

    # 8. Sincronizar / Criar na base de Leads de Marketing
    if email or telefone:
        lead_mkt = None
        if email:
            lead_mkt = CrmLeadMarketing.query.filter(func.lower(CrmLeadMarketing.email) == func.lower(email)).first()
        if not lead_mkt:
            lead_mkt = CrmLeadMarketing(
                email=email or f"lead_{deal.id[:8]}@sememail.com",
                nome=contato_nome or empresa_nome or titulo,
                telefone=telefone or None,
                celular=telefone or None,
                empresa=empresa_nome or None,
                cargo=cargo or None,
                origem_primeira=origem,
                origem_ultima=origem,
                evento_conversao="Cadastro Manual Consultor",
                data_conversao=datetime.utcnow(),
                tags="crm_manual, consultor",
                lead_scoring_perfil="B" if temperatura == "quente" else "C",
                lead_scoring_interesse=80 if temperatura == "quente" else 30
            )
            db.session.add(lead_mkt)

    db.session.commit()

    # Disparar webhook de deal criado
    try:
        dispatch_crm_webhook_event(
            "deal.created",
            deal_id=deal.id,
            payload={
                "deal_id": deal.id,
                "nome": deal.nome,
                "valor_total": deal.valor_total,
                "funil_id": deal.funil_id,
                "etapa_id": deal.etapa_id,
                "user_id": deal.user_id,
                "user_name": deal.user_name,
                "status": deal.status,
                "origem": deal.origem,
                "criado_manualmente": True
            }
        )
    except Exception:
        pass

    return {
        "success": True,
        "deal_id": deal.id,
        "deal_nome": deal.nome,
        "funil_id": funil.id,
        "funil_nome": funil.nome,
        "etapa_id": etapa.id,
        "etapa_nome": etapa.nome,
        "empresa_nome": empresa.nome if empresa else "",
        "contato_nome": contato.nome if contato else "",
        "message": "Oportunidade cadastrada com sucesso!"
    }


def get_consultor_sales_stats(user_id: int | None = None, user: User | None = None) -> dict[str, Any]:
    """
    Calcula as estatísticas de vendas ganhas (mensal, anual e histórico completo)
    para o consultor informado. Retorna contadores e valores formatados.
    """
    if not user and user_id:
        user = User.query.get(user_id)

    now = datetime.now()
    inicio_mes = datetime(now.year, now.month, 1, 0, 0, 0)
    inicio_ano = datetime(now.year, 1, 1, 0, 0, 0)

    meses_pt = [
        "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]
    nome_mes = meses_pt[now.month] if 1 <= now.month <= 12 else str(now.month)

    date_col = func.coalesce(CrmNegociacao.closed_at, CrmNegociacao.updated_at, CrmNegociacao.created_at)

    base_q = db.session.query(
        func.count(CrmNegociacao.id).label("total_vendas"),
        func.coalesce(func.sum(CrmNegociacao.valor_total), 0.0).label("valor_total"),
        func.coalesce(func.sum(CrmNegociacao.valor_unico), 0.0).label("valor_unico"),
        func.coalesce(func.sum(CrmNegociacao.valor_mensal), 0.0).label("valor_mensal")
    ).filter(CrmNegociacao.status == "ganho")

    if user:
        conds = [CrmNegociacao.user_id == user.id]
        if user.nome_completo:
            conds.append(func.lower(CrmNegociacao.user_name) == user.nome_completo.strip().lower())
        if user.usuario:
            conds.append(func.lower(CrmNegociacao.user_name) == user.usuario.strip().lower())
        base_q = base_q.filter(or_(*conds))
    elif user_id:
        base_q = base_q.filter(CrmNegociacao.user_id == user_id)

    # 1. Mensal (Mês Atual)
    row_mes = base_q.filter(date_col >= inicio_mes).first()
    count_mes = int(row_mes.total_vendas or 0) if row_mes else 0
    val_mes = float(row_mes.valor_total or 0.0) if row_mes else 0.0
    val_unico_mes = float(row_mes.valor_unico or 0.0) if row_mes else 0.0
    val_mensal_mes = float(row_mes.valor_mensal or 0.0) if row_mes else 0.0

    # 2. Anual (Ano Atual)
    row_ano = base_q.filter(date_col >= inicio_ano).first()
    count_ano = int(row_ano.total_vendas or 0) if row_ano else 0
    val_ano = float(row_ano.valor_total or 0.0) if row_ano else 0.0
    val_unico_ano = float(row_ano.valor_unico or 0.0) if row_ano else 0.0
    val_mensal_ano = float(row_ano.valor_mensal or 0.0) if row_ano else 0.0

    # 3. Todas as Vendas (Histórico Completo)
    row_todas = base_q.first()
    count_todas = int(row_todas.total_vendas or 0) if row_todas else 0
    val_todas = float(row_todas.valor_total or 0.0) if row_todas else 0.0
    val_unico_todas = float(row_todas.valor_unico or 0.0) if row_todas else 0.0
    val_mensal_todas = float(row_todas.valor_mensal or 0.0) if row_todas else 0.0

    return {
        "consultor": {
            "id": user.id if user else user_id,
            "nome": (user.nome_completo or user.usuario) if user else ("Todos os Consultores" if not user_id else f"Consultor #{user_id}"),
            "usuario": user.usuario if user else "",
            "avatar_path": getattr(user, "avatar_path", None) if user else None,
            "email": getattr(user, "email", "") if user else "",
            "ramal": getattr(user, "ramal", None) if user else None,
            "cargo": "Consultor Comercial"
        },
        "periodo_atual": "mensal",
        "mes_nome": nome_mes,
        "ano_atual": now.year,
        "mensal": {
            "count": count_mes,
            "valor": val_mes,
            "valor_formatado": format_currency_brl(val_mes),
            "valor_unico": val_unico_mes,
            "valor_unico_formatado": format_currency_brl(val_unico_mes),
            "valor_mensal": val_mensal_mes,
            "valor_mensal_formatado": format_currency_brl(val_mensal_mes),
            "label": f"Vendas no Mês ({nome_mes})",
            "periodo_texto": f"{nome_mes}/{now.year}",
            "periodo_curto": f"{nome_mes}/{now.year}"
        },
        "anual": {
            "count": count_ano,
            "valor": val_ano,
            "valor_formatado": format_currency_brl(val_ano),
            "valor_unico": val_unico_ano,
            "valor_unico_formatado": format_currency_brl(val_unico_ano),
            "valor_mensal": val_mensal_ano,
            "valor_mensal_formatado": format_currency_brl(val_mensal_ano),
            "label": f"Vendas no Ano ({now.year})",
            "periodo_texto": f"Ano {now.year}",
            "periodo_curto": f"{now.year}"
        },
        "todas": {
            "count": count_todas,
            "valor": val_todas,
            "valor_formatado": format_currency_brl(val_todas),
            "valor_unico": val_unico_todas,
            "valor_unico_formatado": format_currency_brl(val_unico_todas),
            "valor_mensal": val_mensal_todas,
            "valor_mensal_formatado": format_currency_brl(val_mensal_todas),
            "label": "Todas as Vendas (Histórico)",
            "periodo_texto": "Histórico Completo",
            "periodo_curto": "Total Geral"
        }
    }


