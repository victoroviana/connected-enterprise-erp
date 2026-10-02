"""Rotas da Rede de Empresas Parceiras e Histórico de Serviços Terceirizados."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
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
)
from flask_login import current_user, login_required
from sqlalchemy import or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from extensions import db
from modules.propostas.models import EmpresaParceira, ParceiroServicoHistorico, User
from modules.audit.utils import write_audit
from . import propostas_bp

UFS_BRASIL = [
    ("AC", "Acre"), ("AL", "Alagoas"), ("AP", "Amapá"), ("AM", "Amazonas"),
    ("BA", "Bahia"), ("CE", "Ceará"), ("DF", "Distrito Federal"), ("ES", "Espírito Santo"),
    ("GO", "Goiás"), ("MA", "Maranhão"), ("MT", "Mato Grosso"), ("MS", "Mato Grosso do Sul"),
    ("MG", "Minas Gerais"), ("PA", "Pará"), ("PB", "Paraíba"), ("PR", "Paraná"),
    ("PE", "Pernambuco"), ("PI", "Piauí"), ("RJ", "Rio de Janeiro"), ("RN", "Rio Grande do Norte"),
    ("RS", "Rio Grande do Sul"), ("RO", "Rondônia"), ("RR", "Roraima"), ("SC", "Santa Catarina"),
    ("SP", "São Paulo"), ("SE", "Sergipe"), ("TO", "Tocantins")
]

TIPOS_SERVICO_PADRAO = [
    "Instalação de Catraca",
    "Instalação de Relógio de Ponto",
    "Instalação de Controle de Acesso",
    "Manutenção Corretiva",
    "Manutenção Preventiva",
    "Passagem de Cabos / Infraestrutura",
    "Treinamento Operacional",
    "Troca de Peça / Reposição",
    "Visita Técnica Diagnóstica",
    "Outro",
]


def _can_access_parceiros() -> bool:
    if not current_user or not current_user.is_authenticated:
        return False
    if getattr(current_user, "role", "") == "admin" or getattr(current_user, "tipo", "") == "admin":
        return True
    perms = getattr(current_user, "permissions", {}) or {}
    if perms.get("comercial_parceiros") or perms.get("propostas"):
        return True
    # Usuários comerciais, suporte e assistência técnica têm acesso à rede credenciada
    user_tipo = getattr(current_user, "tipo", "").lower()
    if user_tipo in ["consultor", "consultorsp", "gestor", "suporte", "tecnico", "técnico", "oficina"]:
        return True
    return True


def _can_manage_parceiros() -> bool:
    if not current_user or not current_user.is_authenticated:
        return False
    if getattr(current_user, "role", "") in ["admin", "gestor"]:
        return True
    if getattr(current_user, "tipo", "") in ["admin", "gestor"]:
        return True
    perms = getattr(current_user, "permissions", {}) or {}
    return bool(perms.get("comercial_parceiros") or perms.get("propostas"))


def _clean_phone_for_whatsapp(phone: str | None) -> str:
    """Extrai apenas dígitos e prepara para link internacional wa.me."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return ""
    if len(digits) in [10, 11] and not digits.startswith("55"):
        digits = "55" + digits
    return digits


@propostas_bp.route("/comercial/parceiros", methods=["GET"])
@login_required
def parceiros_index():
    if not _can_access_parceiros():
        flash("Acesso restrito à rede de empresas parceiras.", "warning")
        return redirect(url_for("home"))

    uf_filtro = (request.args.get("uf") or "").strip().upper()
    cidade_filtro = (request.args.get("cidade") or "").strip()
    especialidade_filtro = (request.args.get("especialidade") or "").strip()
    search = (request.args.get("search") or "").strip()
    status_filtro = (request.args.get("status") or "ativo").strip().lower()
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 12

    query = EmpresaParceira.query

    if status_filtro and status_filtro != "todos":
        query = query.filter(EmpresaParceira.status == status_filtro)

    if uf_filtro:
        query = query.filter(EmpresaParceira.estado == uf_filtro)

    if cidade_filtro:
        query = query.filter(EmpresaParceira.cidade.ilike(f"%{cidade_filtro}%"))

    if especialidade_filtro:
        query = query.filter(EmpresaParceira.especialidades.ilike(f"%{especialidade_filtro}%"))

    if search:
        query = query.filter(
            or_(
                EmpresaParceira.razao_social.ilike(f"%{search}%"),
                EmpresaParceira.nome_fantasia.ilike(f"%{search}%"),
                EmpresaParceira.cnpj.ilike(f"%{search}%"),
                EmpresaParceira.responsavel.ilike(f"%{search}%"),
                EmpresaParceira.regiao_atendimento.ilike(f"%{search}%"),
                EmpresaParceira.cidade.ilike(f"%{search}%"),
            )
        )

    # Ordena por melhor avaliação, total de atendimentos e nome
    query = query.order_by(
        EmpresaParceira.avaliacao_media.desc(),
        EmpresaParceira.total_atendimentos.desc(),
        EmpresaParceira.razao_social.asc(),
    )

    total = query.count()
    parceiros = query.offset((page - 1) * per_page).limit(per_page).all()
    total_pages = (total + per_page - 1) // per_page if per_page else 1

    # Prepara links WhatsApp para cada parceiro
    for p in parceiros:
        p.wa_clean = _clean_phone_for_whatsapp(p.whatsapp or p.telefone)

    # Estatísticas gerais
    try:
        total_ativos = EmpresaParceira.query.filter(EmpresaParceira.status == "ativo").count()
        total_servicos_realizados = ParceiroServicoHistorico.query.count()
        estados_cobertos = db.session.query(EmpresaParceira.estado).distinct().count()
    except Exception:
        total_ativos = total
        total_servicos_realizados = 0
        estados_cobertos = 0

    return render_template(
        "propostas/parceiros_index.html",
        parceiros=parceiros,
        total=total,
        page=page,
        total_pages=total_pages,
        ufs=UFS_BRASIL,
        filtro_uf=uf_filtro,
        filtro_cidade=cidade_filtro,
        filtro_especialidade=especialidade_filtro,
        filtro_search=search,
        filtro_status=status_filtro,
        can_manage=_can_manage_parceiros(),
        stats={
            "total_ativos": total_ativos,
            "total_servicos": total_servicos_realizados,
            "estados_cobertos": estados_cobertos,
        },
    )


@propostas_bp.route("/comercial/parceiros/novo", methods=["GET", "POST"])
@login_required
def parceiros_novo():
    if not _can_manage_parceiros():
        flash("Permissão negada para cadastrar empresas parceiras.", "danger")
        return redirect(url_for("propostas_bp.parceiros_index"))

    if request.method == "POST":
        razao_social = (request.form.get("razao_social") or "").strip()
        nome_fantasia = (request.form.get("nome_fantasia") or "").strip()
        cnpj = (request.form.get("cnpj") or "").strip()
        responsavel = (request.form.get("responsavel") or "").strip()
        telefone = (request.form.get("telefone") or "").strip()
        whatsapp = (request.form.get("whatsapp") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        estado = (request.form.get("estado") or "").strip().upper()
        cidade = (request.form.get("cidade") or "").strip()
        regiao_atendimento = (request.form.get("regiao_atendimento") or "").strip()
        especialidades = (request.form.get("especialidades") or "").strip()
        status = (request.form.get("status") or "ativo").strip().lower()
        observacoes = (request.form.get("observacoes") or "").strip()

        if not razao_social:
            flash("A Razão Social é obrigatória.", "warning")
            return render_template(
                "propostas/parceiros_form.html",
                parceiro=None,
                ufs=UFS_BRASIL,
                action_url=url_for("propostas_bp.parceiros_novo"),
            )

        if not estado or len(estado) != 2:
            flash("Selecione o Estado (UF) de atuação.", "warning")
            return render_template(
                "propostas/parceiros_form.html",
                parceiro=None,
                ufs=UFS_BRASIL,
                action_url=url_for("propostas_bp.parceiros_novo"),
            )

        if not cidade:
            flash("Informe a Cidade sede do parceiro.", "warning")
            return render_template(
                "propostas/parceiros_form.html",
                parceiro=None,
                ufs=UFS_BRASIL,
                action_url=url_for("propostas_bp.parceiros_novo"),
            )

        try:
            parceiro = EmpresaParceira(
                razao_social=razao_social,
                nome_fantasia=nome_fantasia or razao_social,
                cnpj=cnpj,
                responsavel=responsavel,
                telefone=telefone,
                whatsapp=whatsapp or telefone,
                email=email,
                estado=estado,
                cidade=cidade,
                regiao_atendimento=regiao_atendimento,
                especialidades=especialidades,
                status=status,
                observacoes=observacoes,
            )
            db.session.add(parceiro)
            db.session.commit()

            write_audit(
                entity_type="EmpresaParceira",
                entity_id=parceiro.id,
                action="create",
                message=f"Empresa parceira {parceiro.razao_social} ({parceiro.cidade}/{parceiro.estado}) cadastrada.",
                after={
                    "id": parceiro.id,
                    "razao_social": parceiro.razao_social,
                    "estado": parceiro.estado,
                    "cidade": parceiro.cidade,
                    "responsavel": parceiro.responsavel,
                },
                commit=True,
            )
            flash(f"Empresa parceira '{parceiro.razao_social}' cadastrada com sucesso!", "success")
            return redirect(url_for("propostas_bp.parceiros_detalhe", parceiro_id=parceiro.id))
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Erro ao cadastrar parceiro")
            flash("Erro ao salvar parceiro no banco de dados.", "danger")

    return render_template(
        "propostas/parceiros_form.html",
        parceiro=None,
        ufs=UFS_BRASIL,
        action_url=url_for("propostas_bp.parceiros_novo"),
    )


@propostas_bp.route("/comercial/parceiros/<int:parceiro_id>", methods=["GET"])
@login_required
def parceiros_detalhe(parceiro_id: int):
    if not _can_access_parceiros():
        flash("Acesso restrito.", "warning")
        return redirect(url_for("home"))

    parceiro = EmpresaParceira.query.get_or_404(parceiro_id)
    parceiro.wa_clean = _clean_phone_for_whatsapp(parceiro.whatsapp or parceiro.telefone)

    servicos = parceiro.servicos.options(joinedload(ParceiroServicoHistorico.usuario_registro)).all()

    return render_template(
        "propostas/parceiros_detalhe.html",
        parceiro=parceiro,
        servicos=servicos,
        tipos_servico=TIPOS_SERVICO_PADRAO,
        can_manage=_can_manage_parceiros(),
        ufs=UFS_BRASIL,
    )


@propostas_bp.route("/comercial/parceiros/<int:parceiro_id>/editar", methods=["GET", "POST"])
@login_required
def parceiros_editar(parceiro_id: int):
    if not _can_manage_parceiros():
        flash("Permissão negada para editar parceiros.", "danger")
        return redirect(url_for("propostas_bp.parceiros_detalhe", parceiro_id=parceiro_id))

    parceiro = EmpresaParceira.query.get_or_404(parceiro_id)

    if request.method == "POST":
        parceiro.razao_social = (request.form.get("razao_social") or parceiro.razao_social).strip()
        parceiro.nome_fantasia = (request.form.get("nome_fantasia") or "").strip()
        parceiro.cnpj = (request.form.get("cnpj") or "").strip()
        parceiro.responsavel = (request.form.get("responsavel") or "").strip()
        parceiro.telefone = (request.form.get("telefone") or "").strip()
        parceiro.whatsapp = (request.form.get("whatsapp") or "").strip()
        parceiro.email = (request.form.get("email") or "").strip().lower()
        parceiro.estado = (request.form.get("estado") or parceiro.estado).strip().upper()
        parceiro.cidade = (request.form.get("cidade") or parceiro.cidade).strip()
        parceiro.regiao_atendimento = (request.form.get("regiao_atendimento") or "").strip()
        parceiro.especialidades = (request.form.get("especialidades") or "").strip()
        parceiro.status = (request.form.get("status") or parceiro.status).strip().lower()
        parceiro.observacoes = (request.form.get("observacoes") or "").strip()

        try:
            db.session.commit()
            write_audit(
                entity_type="EmpresaParceira",
                entity_id=parceiro.id,
                action="update",
                message=f"Dados cadastrais do parceiro #{parceiro.id} ({parceiro.razao_social}) atualizados.",
                commit=True,
            )
            flash("Dados do parceiro atualizados com sucesso.", "success")
            return redirect(url_for("propostas_bp.parceiros_detalhe", parceiro_id=parceiro.id))
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Erro ao editar parceiro")
            flash("Erro ao salvar alterações no banco.", "danger")

    return render_template(
        "propostas/parceiros_form.html",
        parceiro=parceiro,
        ufs=UFS_BRASIL,
        action_url=url_for("propostas_bp.parceiros_editar", parceiro_id=parceiro.id),
    )


@propostas_bp.route("/comercial/parceiros/<int:parceiro_id>/excluir", methods=["POST"])
@login_required
def parceiros_excluir(parceiro_id: int):
    if not _can_manage_parceiros():
        flash("Permissão negada.", "danger")
        return redirect(url_for("propostas_bp.parceiros_index"))

    parceiro = EmpresaParceira.query.get_or_404(parceiro_id)
    nome = parceiro.razao_social

    try:
        db.session.delete(parceiro)
        db.session.commit()
        write_audit(
            entity_type="EmpresaParceira",
            entity_id=parceiro_id,
            action="delete",
            message=f"Empresa parceira #{parceiro_id} ({nome}) excluída.",
            commit=True,
        )
        flash(f"Empresa parceira '{nome}' excluída com sucesso.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Erro ao excluir parceiro")
        flash("Erro ao excluir empresa parceira.", "danger")

    return redirect(url_for("propostas_bp.parceiros_index"))


@propostas_bp.route("/comercial/parceiros/<int:parceiro_id>/servicos/novo", methods=["POST"])
@login_required
def parceiros_servico_novo(parceiro_id: int):
    if not _can_access_parceiros():
        flash("Acesso não autorizado.", "danger")
        return redirect(url_for("home"))

    parceiro = EmpresaParceira.query.get_or_404(parceiro_id)

    cliente_nome = (request.form.get("cliente_nome") or "").strip()
    cliente_cidade = (request.form.get("cliente_cidade") or "").strip()
    cliente_uf = (request.form.get("cliente_uf") or parceiro.estado).strip().upper()
    data_servico_raw = (request.form.get("data_servico") or "").strip()
    tipo_servico = (request.form.get("tipo_servico") or "Instalação").strip()
    equipamento_modelo = (request.form.get("equipamento_modelo") or "").strip()
    os_codigo = (request.form.get("os_codigo") or "").strip()
    tecnico_parceiro = (request.form.get("tecnico_parceiro") or "").strip()
    valor_servico_raw = (request.form.get("valor_servico") or "").replace(".", "").replace(",", ".").strip()
    avaliacao_nota = request.form.get("avaliacao_nota", type=int)
    avaliacao_parecer = (request.form.get("avaliacao_parecer") or "").strip()

    if not cliente_nome or not data_servico_raw:
        flash("Nome do cliente e data do serviço são obrigatórios.", "warning")
        return redirect(url_for("propostas_bp.parceiros_detalhe", parceiro_id=parceiro_id))

    try:
        data_servico = datetime.strptime(data_servico_raw, "%Y-%m-%d").date()
    except ValueError:
        flash("Data do serviço inválida.", "warning")
        return redirect(url_for("propostas_bp.parceiros_detalhe", parceiro_id=parceiro_id))

    valor_servico = None
    if valor_servico_raw:
        try:
            valor_servico = Decimal(valor_servico_raw)
        except Exception:
            valor_servico = None

    if avaliacao_nota is not None:
        avaliacao_nota = max(1, min(5, avaliacao_nota))

    try:
        servico = ParceiroServicoHistorico(
            parceiro_id=parceiro.id,
            cliente_nome=cliente_nome,
            cliente_cidade=cliente_cidade,
            cliente_uf=cliente_uf,
            data_servico=data_servico,
            tipo_servico=tipo_servico,
            equipamento_modelo=equipamento_modelo,
            os_codigo=os_codigo,
            tecnico_parceiro=tecnico_parceiro,
            valor_servico=valor_servico,
            avaliacao_nota=avaliacao_nota,
            avaliacao_parecer=avaliacao_parecer,
            usuario_registro_id=current_user.id,
        )
        db.session.add(servico)
        db.session.flush()

        # Recalcula a nota média e o contador da parceira
        parceiro.recalcular_avaliacao()
        db.session.commit()

        write_audit(
            entity_type="ParceiroServicoHistorico",
            entity_id=servico.id,
            action="create",
            message=f"Serviço registrado para parceiro #{parceiro.id} ({parceiro.razao_social}) no cliente {cliente_nome}.",
            commit=True,
        )
        flash("Serviço registrado com sucesso no histórico do parceiro!", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Erro ao registrar serviço do parceiro")
        flash("Erro interno ao gravar serviço.", "danger")

    return redirect(url_for("propostas_bp.parceiros_detalhe", parceiro_id=parceiro_id))


@propostas_bp.route("/comercial/parceiros/servicos/<int:servico_id>/excluir", methods=["POST"])
@login_required
def parceiros_servico_excluir(servico_id: int):
    if not _can_manage_parceiros():
        flash("Permissão negada.", "danger")
        return redirect(url_for("home"))

    servico = ParceiroServicoHistorico.query.get_or_404(servico_id)
    parceiro_id = servico.parceiro_id
    parceiro = servico.parceiro

    try:
        db.session.delete(servico)
        db.session.flush()
        if parceiro:
            parceiro.recalcular_avaliacao()
        db.session.commit()

        write_audit(
            entity_type="ParceiroServicoHistorico",
            entity_id=servico_id,
            action="delete",
            message=f"Serviço #{servico_id} excluído do histórico do parceiro #{parceiro_id}.",
            commit=True,
        )
        flash("Registro de serviço removido do histórico.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Erro ao excluir serviço do parceiro")
        flash("Erro ao excluir registro de serviço.", "danger")

    return redirect(url_for("propostas_bp.parceiros_detalhe", parceiro_id=parceiro_id))


@propostas_bp.route("/comercial/api/parceiros/busca", methods=["GET"])
@login_required
def parceiros_api_busca():
    if not _can_access_parceiros():
        return jsonify({"items": []}), 403

    uf = (request.args.get("uf") or "").strip().upper()
    q = (request.args.get("q") or "").strip().lower()

    query = EmpresaParceira.query.filter(EmpresaParceira.status == "ativo")
    if uf:
        query = query.filter(EmpresaParceira.estado == uf)
    if q:
        query = query.filter(
            or_(
                EmpresaParceira.razao_social.ilike(f"%{q}%"),
                EmpresaParceira.nome_fantasia.ilike(f"%{q}%"),
                EmpresaParceira.cidade.ilike(f"%{q}%"),
                EmpresaParceira.especialidades.ilike(f"%{q}%"),
            )
        )

    parceiros = query.order_by(EmpresaParceira.avaliacao_media.desc()).limit(20).all()
    results = []
    for p in parceiros:
        results.append({
            "id": p.id,
            "razao_social": p.razao_social,
            "nome_fantasia": p.nome_fantasia or p.razao_social,
            "cidade": p.cidade,
            "estado": p.estado,
            "telefone": p.telefone,
            "whatsapp": p.whatsapp,
            "avaliacao_media": p.avaliacao_media,
            "total_atendimentos": p.total_atendimentos,
            "especialidades": p.especialidades or "",
        })

    return jsonify({"items": results})
