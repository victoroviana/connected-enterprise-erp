"""Módulo de Webhooks e Central de Integrações do Sollus CRM."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import func, or_

from extensions import csrf, db
from modules.propostas.blueprints.auth import login_required
from modules.propostas.models import User
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmInteracao,
    CrmWebhook,
    CrmWebhookLog,
)
from modules.crm.services.crm_service import (
    distribute_deal_round_robin,
    check_and_trigger_stage_automations,
    dispatch_crm_webhook_event,
    _send_single_webhook,
)
from . import crm_bp


# ==============================================================================
# INBOUND WEBHOOK (Captura de Leads Externa Protegida por Token)
# ==============================================================================

@crm_bp.route("/api/webhooks/inbound", methods=["POST"])
@csrf.exempt
def api_webhook_inbound():
    """
    Endpoint de Inbound Webhook para captura instantânea de leads
    vindos de Landing Pages, WordPress/Elementor, RD Station e parceiros externos.
    """
    # 1. Autenticação via Token de API (X-API-Token ou Authorization: Bearer <token>)
    auth_header = request.headers.get("X-API-Token") or request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"success": False, "error": "Token de autenticação ausente"}), 401

    token = auth_header.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    expected_token = current_app.config.get("CRM_WEBHOOK_API_TOKEN", "sollus-test-token-secret-12345")
    if token != expected_token:
        return jsonify({"success": False, "error": "Token de autenticação inválido"}), 401

    # 2. Validação do Payload JSON
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return jsonify({"success": False, "error": "Payload JSON inválido ou malformado"}), 400

    # 3. Extração dos Campos e Suporte a Payload RD Station / Formulários
    lead_obj = data.get("lead") if isinstance(data.get("lead"), dict) else {}
    empresa_data = data.get("empresa") or {}
    contato_data = data.get("contato") or {}
    if isinstance(empresa_data, str):
        empresa_data = {"nome": empresa_data}
    if isinstance(contato_data, str):
        contato_data = {"nome": contato_data}

    # Se payload no formato RD Station com nó 'lead'
    if lead_obj:
        if not contato_data.get("nome"):
            contato_data["nome"] = lead_obj.get("name") or lead_obj.get("nome")
        if not contato_data.get("email"):
            contato_data["email"] = lead_obj.get("email")
        if not contato_data.get("telefone"):
            contato_data["telefone"] = lead_obj.get("personal_phone") or lead_obj.get("mobile_phone") or lead_obj.get("phone") or lead_obj.get("telefone")
        if not contato_data.get("celular"):
            contato_data["celular"] = lead_obj.get("mobile_phone") or lead_obj.get("personal_phone") or lead_obj.get("celular")
        if not contato_data.get("cargo"):
            contato_data["cargo"] = lead_obj.get("job_title") or lead_obj.get("cargo")
        if not contato_data.get("cidade"):
            contato_data["cidade"] = lead_obj.get("city") or lead_obj.get("cidade")
        if not contato_data.get("estado"):
            contato_data["estado"] = lead_obj.get("state") or lead_obj.get("uf")

        if not empresa_data.get("nome"):
            empresa_data["nome"] = lead_obj.get("company_name") or lead_obj.get("empresa")
        if not empresa_data.get("cnpj"):
            empresa_data["cnpj"] = lead_obj.get("company_cnpj") or lead_obj.get("cnpj")
        if not empresa_data.get("porte"):
            empresa_data["porte"] = lead_obj.get("company_size") or lead_obj.get("porte")
        if not empresa_data.get("numero_funcionarios"):
            empresa_data["numero_funcionarios"] = lead_obj.get("employees_count") or lead_obj.get("numero_funcionarios")
        if not empresa_data.get("cidade"):
            empresa_data["cidade"] = lead_obj.get("city") or lead_obj.get("cidade")
        if not empresa_data.get("estado"):
            empresa_data["estado"] = lead_obj.get("state") or lead_obj.get("uf")

    nome_negociacao = data.get("nome_negociacao") or data.get("nome") or lead_obj.get("subject") or lead_obj.get("need")
    valor = float(data.get("valor") or 0.0)
    funil_id = data.get("funil_id")
    etapa_id = data.get("etapa_id")
    origem = data.get("origem") or lead_obj.get("traffic_source") or "Webhook Inbound"
    consultor_id = data.get("consultor_id") or data.get("user_id")

    temperatura = str(lead_obj.get("lead_temperature") or data.get("temperatura") or "morno").strip().lower()
    canal_preferencial = str(lead_obj.get("preferred_contact_channel") or data.get("canal_preferencial") or "whatsapp").strip().lower()
    necessidade = lead_obj.get("need") or data.get("necessidade")
    conversion_identifier = data.get("conversion_identifier") or data.get("identificador") or ""
    tags = lead_obj.get("tags") or data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    canal_origem = data.get("canal_origem") or lead_obj.get("channel")
    if not canal_origem and origem:
        orig_lower = origem.lower()
        if "google" in orig_lower and ("paga" in orig_lower or "ads" in orig_lower):
            canal_origem = "google_ads"
        elif "facebook" in orig_lower or "face" in orig_lower:
            canal_origem = "facebook_ads"
        elif "google" in orig_lower or "org" in orig_lower:
            canal_origem = "organico"
        elif "indic" in orig_lower:
            canal_origem = "indicacao"
        else:
            canal_origem = "inbound_webhook"

    filial = (
        data.get("filial")
        or lead_obj.get("state")
        or lead_obj.get("uf")
        or data.get("estado")
        or data.get("uf")
        or (empresa_data.get("estado") if isinstance(empresa_data, dict) else None)
        or (empresa_data.get("uf") if isinstance(empresa_data, dict) else None)
        or (contato_data.get("estado") if isinstance(contato_data, dict) else None)
        or (contato_data.get("uf") if isinstance(contato_data, dict) else None)
    )
    campanha = data.get("campanha") or data.get("utm_campaign") or lead_obj.get("campaign_name")

    # Validação de identificação mínima do lead
    has_ident = bool(
        (nome_negociacao and str(nome_negociacao).strip()) or
        (isinstance(empresa_data, dict) and (empresa_data.get("nome") or empresa_data.get("cnpj"))) or
        (isinstance(contato_data, dict) and (contato_data.get("nome") or contato_data.get("email") or contato_data.get("telefone") or contato_data.get("celular"))) or
        (lead_obj and (lead_obj.get("name") or lead_obj.get("email") or lead_obj.get("company_name")))
    )
    if not has_ident:
        return jsonify({"success": False, "error": "Identificação mínima do lead necessária"}), 400

    # 4. Smart Lead Deduplication: Empresa por CNPJ (normalizado) ou Nome
    empresa = None
    cnpj_raw = empresa_data.get("cnpj") or ""
    empresa_nome = (empresa_data.get("nome") or "").strip()
    clean_cnpj = re.sub(r"\D", "", str(cnpj_raw)) if cnpj_raw else ""

    if clean_cnpj:
        # Busca direta indexada por igualdade exata ou dígitos limpos
        empresa = CrmEmpresa.query.filter(or_(CrmEmpresa.cnpj == cnpj_raw, CrmEmpresa.cnpj == clean_cnpj)).first()
        if not empresa:
            # Busca todas empresas com CNPJ e compara dígitos normalizados (independente de pontuação)
            candidatos = CrmEmpresa.query.filter(CrmEmpresa.cnpj.isnot(None)).all()
            for cand in candidatos:
                if cand.cnpj and re.sub(r"\D", "", cand.cnpj) == clean_cnpj:
                    empresa = cand
                    break

    if not empresa and empresa_nome:
        empresa = CrmEmpresa.query.filter(func.lower(CrmEmpresa.nome) == func.lower(empresa_nome)).first()

    if not empresa and (empresa_nome or clean_cnpj):
        endereco_val = empresa_data.get("endereco")
        if not endereco_val:
            partes_end = [p for p in [empresa_data.get("cidade"), empresa_data.get("estado")] if p]
            if partes_end:
                endereco_val = " - ".join(partes_end)

        empresa = CrmEmpresa(
            id=str(uuid.uuid4())[:24],
            nome=empresa_nome or f"Empresa CNPJ {clean_cnpj}",
            cnpj=cnpj_raw or None,
            telefone=empresa_data.get("telefone") or empresa_data.get("celular"),
            email=empresa_data.get("email"),
            endereco=endereco_val,
            porte=empresa_data.get("porte"),
            numero_funcionarios=empresa_data.get("numero_funcionarios"),
        )
        db.session.add(empresa)
        db.session.flush()
    elif empresa:
        if not empresa.porte and empresa_data.get("porte"):
            empresa.porte = empresa_data.get("porte")
        if not empresa.numero_funcionarios and empresa_data.get("numero_funcionarios"):
            empresa.numero_funcionarios = empresa_data.get("numero_funcionarios")

    # 5. Smart Lead Deduplication: Contato por E-mail (case-insensitive / normalizado)
    contato = None
    email_raw = (contato_data.get("email") or "").strip()
    clean_email = email_raw.lower() if email_raw else ""
    contato_nome = (contato_data.get("nome") or "").strip()
    telefone_raw = (contato_data.get("celular") or contato_data.get("telefone") or "").strip()

    if clean_email:
        contato = CrmContato.query.filter(func.lower(CrmContato.email) == clean_email).first()

    if not contato and (contato_nome or clean_email or telefone_raw):
        contato = CrmContato(
            id=str(uuid.uuid4())[:24],
            empresa_id=empresa.id if empresa else None,
            nome=contato_nome or (email_raw.split("@")[0].capitalize() if email_raw else "Contato Inbound"),
            email=clean_email or None,
            telefone=telefone_raw or None,
            celular=telefone_raw or None,
            cargo=contato_data.get("cargo"),
        )
        db.session.add(contato)
        db.session.flush()
    elif contato and empresa and not contato.empresa_id:
        contato.empresa_id = empresa.id

    # 6. Determinação de Funil e Etapa
    funil = None
    if funil_id:
        funil = CrmFunil.query.get(funil_id)
    if not funil:
        # Roteamento inteligente de funil baseado em palavras-chave
        search_terms = " ".join([
            str(conversion_identifier or ""),
            str(necessidade or ""),
            str(nome_negociacao or ""),
            " ".join(str(t) for t in tags),
            str(campanha or ""),
        ]).lower()

        if any(w in search_terms for w in ("assistencia", "assistência", "suporte", "manutencao", "manutenção", "conserto", "reparo")):
            funil = CrmFunil.query.filter(
                CrmFunil.ativo == True,
                or_(CrmFunil.tipo == "assistencia", CrmFunil.slug.ilike("%assist%"), CrmFunil.nome.ilike("%assist%"))
            ).first()
        elif any(w in search_terms for w in ("acesso", "catraca", "catracas", "torniquete", "facial", "leitor", "biometria", "porta")):
            funil = CrmFunil.query.filter(
                CrmFunil.ativo == True,
                or_(CrmFunil.tipo == "acesso", CrmFunil.slug.ilike("%acesso%"), CrmFunil.nome.ilike("%acesso%"))
            ).first()
        elif any(w in search_terms for w in ("ponto", "relogio", "relógio", "rep", "rh", "folha")):
            funil = CrmFunil.query.filter(
                CrmFunil.ativo == True,
                or_(CrmFunil.tipo == "ponto", CrmFunil.slug.ilike("%ponto%"), CrmFunil.nome.ilike("%ponto%"))
            ).first()

    if not funil:
        funil = CrmFunil.query.filter_by(ativo=True).order_by(CrmFunil.ordem).first()
    if not funil:
        return jsonify({"success": False, "error": "Nenhum funil ativo encontrado no CRM"}), 500

    etapa = None
    if etapa_id:
        etapa = CrmEtapa.query.get(etapa_id)
    if not etapa:
        etapa = CrmEtapa.query.filter_by(funil_id=funil.id, tipo="normal").order_by(CrmEtapa.ordem).first()
    if not etapa and funil.etapas:
        etapa = funil.etapas[0]

    # 7. Criação da Negociação
    if not nome_negociacao:
        nome_negociacao = f"Lead - {empresa.nome if empresa else (contato.nome if contato else 'Inbound Webhook')}"

    deal_id = str(uuid.uuid4())[:24]
    deal = CrmNegociacao(
        id=deal_id,
        nome=nome_negociacao,
        funil_id=funil.id,
        etapa_id=etapa.id if etapa else None,
        empresa_id=empresa.id if empresa else None,
        contato_id=contato.id if contato else None,
        valor_total=valor,
        valor_unico=valor,
        valor_mensal=0.0,
        origem=origem,
        canal_origem=canal_origem,
        temperatura=temperatura,
        canal_preferencial=canal_preferencial,
        necessidade=necessidade,
        filial=filial,
        campanha=campanha,
        status="aberto",
    )
    deal.empresa = empresa
    deal.contato = contato

    if consultor_id:
        try:
            cid = int(consultor_id)
            c_user = User.query.get(cid)
            if c_user:
                deal.user_id = c_user.id
                deal.user_name = c_user.nome_completo or c_user.usuario
        except (ValueError, TypeError):
            pass

    db.session.add(deal)
    db.session.flush()

    # 8. Registro na timeline da captura Inbound Webhook
    interacao = CrmInteracao(
        negociacao_id=deal.id,
        user_id=deal.user_id,
        user_name=deal.user_name or "Sistema",
        tipo="sistema",
        conteudo=f"📥 Oportunidade capturada via Inbound Webhook (Origem: {origem})."
    )
    db.session.add(interacao)
    db.session.flush()

    # 9. Roleta Comercial: distribui se não atribuído
    if not deal.user_id:
        distribute_deal_round_robin(deal)

    # 10. Automações de Etapa & Agendamento de Tarefas
    if etapa:
        tasks_created = check_and_trigger_stage_automations(deal, etapa, evento="deal_criado")
        if not tasks_created:
            task_id = str(uuid.uuid4())[:24]
            now_dt = datetime.utcnow()
            tipo_task = deal.canal_preferencial if deal.canal_preferencial in ("whatsapp", "ligacao", "email") else "whatsapp"
            tarefa = CrmTarefa(
                id=task_id,
                negociacao_id=deal.id,
                user_id=deal.user_id,
                titulo=f"1º Contato SDR - {deal.nome}",
                tipo=tipo_task,
                data_vencimento=now_dt,
                observacao=f"Lead recebido via Inbound Webhook ({origem})"
            )
            db.session.add(tarefa)
            deal.proxima_tarefa_id = task_id
            deal.proxima_tarefa_titulo = tarefa.titulo
            deal.proxima_tarefa_data = now_dt
            deal.proxima_tarefa_tipo = tipo_task

    # Sincronização inteligente com base de leads CrmLeadMarketing
    if clean_email:
        try:
            from modules.crm.models import CrmLeadMarketing
            lead_mkt = CrmLeadMarketing.query.filter_by(email=clean_email).first()
            if not lead_mkt:
                lead_mkt = CrmLeadMarketing(
                    email=clean_email,
                    nome=contato.nome if contato else contato_nome,
                    telefone=contato.telefone or contato.celular if contato else telefone_raw,
                    celular=contato.celular or contato.telefone if contato else telefone_raw,
                    empresa=empresa.nome if empresa else empresa_nome,
                    cidade=empresa.cidade if empresa else None,
                    estado=filial,
                    tags=",".join(tags) if tags else None,
                    origem_primeira=origem,
                    total_conversoes=1,
                    evento_conversao=conversion_identifier,
                )
                db.session.add(lead_mkt)
            else:
                lead_mkt.total_conversoes = (lead_mkt.total_conversoes or 1) + 1
                if conversion_identifier:
                    lead_mkt.evento_conversao = conversion_identifier
        except Exception:
            pass

    db.session.commit()

    # 10. Disparo de Webhook Outbound para deal.created
    dispatch_crm_webhook_event(
        "deal.created",
        deal_id=deal.id,
        payload={
            "deal_id": deal.id,
            "nome": deal.nome,
            "valor": deal.valor_total,
            "valor_total": deal.valor_total,
            "origem": deal.origem,
            "empresa": empresa.to_dict() if empresa else None,
            "contato": contato.to_dict() if contato else None,
            "consultor_id": deal.user_id,
            "status": deal.status,
        }
    )

    # 11. Log de Auditoria da Requisição Inbound
    try:
        inbound_log = CrmWebhookLog(
            tipo="inbound",
            evento="deal.created",
            status_code=201,
            request_payload=json.dumps(data, default=str),
            response_body=json.dumps({"success": True, "deal_id": deal.id, "consultor_id": deal.user_id, "created": True}),
            sucesso=True,
            tempo_ms=15,
            tempo_execucao_ms=15,
        )
        db.session.add(inbound_log)
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify({
        "success": True,
        "deal_id": deal.id,
        "consultor_id": deal.user_id,
        "created": True
    }), 201


def _is_admin_user() -> bool:
    """Verifica se o usuário autenticado possui perfil de administrador ou gestor."""
    role = (session.get("tipo") or getattr(current_user, "tipo", None) or getattr(current_user, "role", None) or "").lower()
    return role in ["admin", "gestor"]


# ==============================================================================
# WEBHOOK MANAGEMENT HUB (Visualização e Painel de Controle - Restrito a Admin)
# ==============================================================================

@crm_bp.route("/webhooks", methods=["GET"])
@login_required
def webhooks():
    """Painel de controle e monitoramento de webhooks do Sollus CRM (Restrito a Administradores)."""
    if not _is_admin_user():
        flash("Acesso restrito a administradores do sistema.", "warning")
        return redirect(url_for("crm.index"))

    webhooks_list = CrmWebhook.query.order_by(CrmWebhook.id.desc()).all()
    logs_list = CrmWebhookLog.query.order_by(CrmWebhookLog.criado_em.desc()).limit(50).all()

    total_webhooks = len(webhooks_list)
    active_webhooks = len([w for w in webhooks_list if w.ativo])
    total_logs = CrmWebhookLog.query.count()
    success_logs = CrmWebhookLog.query.filter_by(sucesso=True).count()
    success_rate = round((success_logs / total_logs * 100), 1) if total_logs > 0 else 100.0

    stats = {
        "total_webhooks": total_webhooks,
        "active_webhooks": active_webhooks,
        "total_deliveries": total_logs,
        "success_rate": success_rate,
    }

    return render_template(
        "crm/webhooks.html",
        webhooks=webhooks_list,
        logs=logs_list,
        stats=stats
    )


# ==============================================================================
# WEBHOOK CRUD & AUDIT API ENDPOINTS (Restrito a Admin)
# ==============================================================================

@crm_bp.route("/api/webhooks", methods=["GET"])
@login_required
def api_list_webhooks():
    """Retorna lista de todos os webhooks cadastrados."""
    if not _is_admin_user():
        return jsonify({"success": False, "error": "Acesso restrito a administradores"}), 403

    items = CrmWebhook.query.order_by(CrmWebhook.id.asc()).all()
    payload = [w.to_dict() for w in items]
    return jsonify({
        "success": True,
        "webhooks": payload,
        "data": payload
    })


@crm_bp.route("/api/webhooks", methods=["POST"])
@login_required
def api_create_webhook():
    """Cria uma nova configuração de webhook de entrada ou saída."""
    if not _is_admin_user():
        return jsonify({"success": False, "error": "Acesso restrito a administradores"}), 403

    data = request.get_json(force=True, silent=True) or request.form.to_dict()
    if not data:
        return jsonify({"success": False, "error": "Dados não informados"}), 400

    nome = data.get("nome", "").strip()
    url = (data.get("url") or data.get("url_destino") or "").strip()
    tipo = data.get("tipo", "outbound").strip().lower()
    eventos = data.get("eventos") or data.get("evento") or "*"
    secret_key = data.get("secret_key") or data.get("secret") or ""
    ativo = bool(data.get("ativo", True))

    if not nome:
        return jsonify({"success": False, "error": "Nome do webhook é obrigatório"}), 400

    if tipo == "outbound":
        if not url:
            return jsonify({"success": False, "error": "URL de destino é obrigatória para webhooks outbound"}), 400
        if not (url.startswith("http://") or url.startswith("https://")):
            return jsonify({"success": False, "error": "URL deve começar com http:// ou https://"}), 400

    wh = CrmWebhook(
        nome=nome,
        url=url if url else None,
        tipo=tipo,
        eventos=eventos.strip() if isinstance(eventos, str) else ",".join(eventos),
        secret_key=secret_key.strip() if secret_key else None,
        ativo=ativo,
    )
    db.session.add(wh)
    db.session.commit()

    wh_data = wh.to_dict()
    return jsonify({
        "success": True,
        "webhook": wh_data,
        "data": wh_data
    }), 201


@crm_bp.route("/api/webhooks/<int:webhook_id>/toggle", methods=["POST"])
@login_required
def api_toggle_webhook(webhook_id: int):
    """Ativa ou desativa um webhook."""
    if not _is_admin_user():
        return jsonify({"success": False, "error": "Acesso restrito a administradores"}), 403

    wh = CrmWebhook.query.get_or_404(webhook_id)
    wh.ativo = not wh.ativo
    db.session.commit()
    wh_data = wh.to_dict()
    return jsonify({
        "success": True,
        "id": wh.id,
        "ativo": wh.ativo,
        "data": wh_data
    })



@crm_bp.route("/api/webhooks/<int:webhook_id>/test", methods=["POST"])
@login_required
def api_test_webhook(webhook_id: int):
    """Dispara payload de teste para a URL cadastrada."""
    if not _is_admin_user():
        return jsonify({"success": False, "error": "Acesso restrito a administradores"}), 403

    wh = CrmWebhook.query.get_or_404(webhook_id)
    if not wh.url:
        return jsonify({"success": False, "error": "Webhook não possui URL configurada"}), 400

    test_payload = {
        "event": "test.ping",
        "webhook_id": wh.id,
        "webhook_nome": wh.nome,
        "timestamp": datetime.utcnow().isoformat(),
        "message": "Teste de conexão e integridade Sollus CRM Webhooks"
    }

    res = _send_single_webhook(
        url=wh.url,
        event_name="test.ping",
        payload_dict=test_payload,
        secret=wh.secret,
        webhook_id=wh.id,
        app=current_app._get_current_object()
    )

    return jsonify({
        "success": res.get("sucesso", False),
        "status_code": res.get("status_code"),
        "tempo_ms": res.get("tempo_ms"),
        "response_body": res.get("response_body")
    })


@crm_bp.route("/api/webhooks/<int:webhook_id>", methods=["DELETE"])
@login_required
def api_delete_webhook(webhook_id: int):
    """Exclui um webhook cadastrado."""
    if not _is_admin_user():
        return jsonify({"success": False, "error": "Acesso restrito a administradores"}), 403

    wh = CrmWebhook.query.get_or_404(webhook_id)
    db.session.delete(wh)
    db.session.commit()
    return jsonify({
        "success": True,
        "deleted_id": webhook_id
    })


@crm_bp.route("/api/webhooks/logs", methods=["GET"])
@login_required
def api_webhook_logs():
    """Retorna o histórico recente de logs de execução dos webhooks."""
    if not _is_admin_user():
        return jsonify({"success": False, "error": "Acesso restrito a administradores"}), 403

    limit = request.args.get("limit", 50, type=int)
    logs = CrmWebhookLog.query.order_by(CrmWebhookLog.criado_em.desc()).limit(limit).all()
    logs_data = [l.to_dict() for l in logs]
    return jsonify({
        "success": True,
        "logs": logs_data,
        "data": logs_data
    })

