"""Serviço de processamento e envio de alertas de lembretes do SollusFlow."""
from __future__ import annotations

from datetime import date, datetime
import logging
from typing import List, Optional

from flask import current_app
from extensions import db
from modules.chamados.models import SfChecklist, SfPedido, SF_FASES
from modules.chamados.services.notify import send_email

logger = logging.getLogger(__name__)


def gerar_html_lembrete(item: SfChecklist, tipo_alerta: str, dias: int) -> tuple[str, str, str]:
    """Gera assunto e corpo HTML estilizado para o alerta do lembrete."""
    pedido = item.pedido
    fase_info = SF_FASES.get(item.fase, {})
    fase_nome = fase_info.get("label", f"Etapa {item.fase}")

    base_url = current_app.config.get("MAIL_BASE_URL", "http://localhost:6001")
    link_flow = f"{base_url.rstrip('/')}/sollus-flow/?cnpj={pedido.cliente_cnpj or ''}"

    dt_br = item.data_lembrete.strftime("%d/%m/%Y") if item.data_lembrete else "N/D"

    if tipo_alerta == "5_dias":
        badge_cor = "#2563eb"
        badge_bg = "#eff6ff"
        badge_txt = "Faltam 5 dias para o vencimento"
        assunto = f"🔔 [SollusFlow] Lembrete em 5 dias: {item.titulo} ({pedido.cliente_nome})"
    elif tipo_alerta == "3_dias":
        badge_cor = "#d97706"
        badge_bg = "#fef3c7"
        badge_txt = "ATENÇÃO: Faltam 3 dias para o vencimento"
        assunto = f"⚠️ [SollusFlow] Lembrete em 3 dias: {item.titulo} ({pedido.cliente_nome})"
    else:  # hoje
        badge_cor = "#dc2626"
        badge_bg = "#fee2e2"
        badge_txt = "URGENTE: O lembrete vence HOJE!"
        assunto = f"🚨 [SollusFlow] Vence HOJE: {item.titulo} ({pedido.cliente_nome})"

    nomes = []
    if getattr(item, 'responsavel', None) and item.responsavel.nome_completo:
        nomes.append(item.responsavel.nome_completo.strip())
    if item.pedido.responsavel and item.pedido.responsavel.nome_completo and item.pedido.responsavel.nome_completo.strip() not in nomes:
        nomes.append(item.pedido.responsavel.nome_completo.strip())
    if item.criado_por and item.criado_por.nome_completo and item.criado_por.nome_completo.strip() not in nomes:
        nomes.append(item.criado_por.nome_completo.strip())
    resp_nome = ", ".join(nomes) if nomes else (pedido.responsavel.nome_completo if pedido.responsavel else "Colaborador(a)")

    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
      <meta charset="UTF-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
        .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }}
        .header {{ background: linear-gradient(135deg, #0f172a, #1e293b); padding: 28px 32px; color: #ffffff; text-align: left; }}
        .header-badge {{ display: inline-block; background: rgba(255,255,255,0.15); color: #93c5fd; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }}
        .header h1 {{ margin: 0; font-size: 20px; font-weight: 800; line-height: 1.3; color: #ffffff; }}
        .content {{ padding: 32px; }}
        .alert-box {{ background-color: {badge_bg}; border-left: 4px solid {badge_cor}; padding: 14px 18px; border-radius: 8px; margin-bottom: 24px; }}
        .alert-badge {{ color: {badge_cor}; font-weight: 800; font-size: 14px; text-transform: uppercase; }}
        .card-task {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin-bottom: 24px; }}
        .task-title {{ font-size: 17px; font-weight: 700; color: #0f172a; margin-bottom: 8px; }}
        .task-due {{ font-size: 14px; color: #64748b; display: flex; align-items: center; gap: 6px; }}
        .info-table {{ width: 100%; border-collapse: collapse; margin-bottom: 28px; font-size: 14px; }}
        .info-table td {{ padding: 10px 0; border-bottom: 1px solid #f1f5f9; }}
        .info-table td.label {{ color: #64748b; font-weight: 600; width: 40%; }}
        .info-table td.val {{ color: #0f172a; font-weight: 700; }}
        .btn {{ display: inline-block; background: linear-gradient(135deg, #1d4ed8, #2563eb); color: #ffffff !important; text-decoration: none; padding: 14px 28px; border-radius: 10px; font-weight: 700; font-size: 15px; text-align: center; }}
        .footer {{ padding: 20px 32px; background: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <span class="header-badge">SollusFlow • Notificação de Prazo</span>
          <h1>Lembrete de Tarefa do Pedido</h1>
        </div>
        <div class="content">
          <p style="margin-top:0; font-size:15px;">Olá, <strong>{resp_nome}</strong>,</p>
          
          <div class="alert-box">
            <span class="alert-badge">{badge_txt}</span>
          </div>

          <div class="card-task">
            <div class="task-title">📌 {item.titulo}</div>
            <div class="task-due">📅 <strong>Data Limite:</strong> {dt_br}</div>
          </div>

          <table class="info-table">
            <tr>
              <td class="label">Cliente:</td>
              <td class="val">{pedido.cliente_nome}</td>
            </tr>
            <tr>
              <td class="label">CNPJ:</td>
              <td class="val">{pedido.cliente_cnpj or 'Não informado'}</td>
            </tr>
            <tr>
              <td class="label">Nº Pedido:</td>
              <td class="val">{pedido.numero_pedido or f'#{pedido.id}'}</td>
            </tr>
            <tr>
              <td class="label">Etapa Atual:</td>
              <td class="val">Etapa {item.fase}: {fase_nome}</td>
            </tr>
            <tr>
              <td class="label">Prioridade:</td>
              <td class="val" style="text-transform: capitalize;">{pedido.prioridade}</td>
            </tr>
          </table>

          <div style="text-align: center; margin-top: 30px;">
            <a href="{link_flow}" class="btn">Acessar Pedido no SollusFlow</a>
          </div>
        </div>
        <div class="footer">
          Este é um e-mail automático enviado pelo SollusFlow — Sistema Integrado Sollus Connected.<br>
          Para concluir a tarefa e silenciar este alerta, marque-a como concluída no checklist.
        </div>
      </div>
    </body>
    </html>
    """

    texto = f"""[SollusFlow - Lembrete de Tarefa]
{badge_txt}

Tarefa: {item.titulo}
Data Limite: {dt_br}

Cliente: {pedido.cliente_nome}
CNPJ: {pedido.cliente_cnpj or 'N/D'}
Nº Pedido: {pedido.numero_pedido or f'#{pedido.id}'}
Etapa: Etapa {item.fase} ({fase_nome})

Acesse o sistema: {link_flow}
"""
    return assunto, html, texto


def processar_lembretes_sollusflow(app=None) -> dict:
    """Verifica e dispara alertas de 5 dias, 3 dias e do dia limite para itens de checklist pendentes."""
    ctx = app.app_context() if app else None
    if ctx:
        ctx.push()

    try:
        hoje = date.today()
        pendentes = (
            SfChecklist.query
            .join(SfPedido, SfChecklist.pedido_id == SfPedido.id)
            .filter(
                SfChecklist.concluido.is_(False),
                SfChecklist.data_lembrete.isnot(None),
                SfPedido.status == "ativo",
            )
            .all()
        )

        total_enviados = 0
        detalhes = []

        for item in pendentes:
            dias = (item.data_lembrete - hoje).days
            tipo_alerta = None

            if dias <= 0 and not item.alerta_0d_enviado:
                tipo_alerta = "hoje"
            elif dias <= 3 and dias > 0 and not item.alerta_3d_enviado:
                tipo_alerta = "3_dias"
            elif dias <= 5 and dias > 3 and not item.alerta_5d_enviado:
                tipo_alerta = "5_dias"

            if not tipo_alerta:
                continue

            destinatarios = []
            if getattr(item, 'responsavel', None) and item.responsavel.email:
                destinatarios.append(item.responsavel.email.strip())
            if item.pedido.responsavel and item.pedido.responsavel.email:
                destinatarios.append(item.pedido.responsavel.email.strip())
            if item.pedido.consultor and item.pedido.consultor.email:
                destinatarios.append(item.pedido.consultor.email.strip())
            if item.criado_por and item.criado_por.email:
                destinatarios.append(item.criado_por.email.strip())
            if item.fase == 16 and not any("mariana" in e.lower() for e in destinatarios):
                destinatarios.append("comercial6@sollusgroup.com")

            destinatarios = list(dict.fromkeys([e for e in destinatarios if "@" in e]))

            if not destinatarios:
                logger.warning(
                    "[sollusflow_lembretes] Item #%d sem destinatário válido (pedido #%d)",
                    item.id, item.pedido_id
                )
                continue

            assunto, html, texto = gerar_html_lembrete(item, tipo_alerta, dias)

            try:
                send_email(assunto, destinatarios, html, texto)
                total_enviados += 1

                if tipo_alerta == "5_dias":
                    item.alerta_5d_enviado = True
                elif tipo_alerta == "3_dias":
                    item.alerta_5d_enviado = True
                    item.alerta_3d_enviado = True
                elif tipo_alerta == "hoje":
                    item.alerta_5d_enviado = True
                    item.alerta_3d_enviado = True
                    item.alerta_0d_enviado = True

                db.session.commit()
                detalhes.append({
                    "item_id": item.id,
                    "titulo": item.titulo,
                    "tipo_alerta": tipo_alerta,
                    "destinatarios": destinatarios,
                })
                logger.info(
                    "[sollusflow_lembretes] Alerta '%s' enviado para item #%d (%s) -> %s",
                    tipo_alerta, item.id, item.titulo, destinatarios
                )
            except Exception as e:
                db.session.rollback()
                logger.exception(
                    "[sollusflow_lembretes] Erro ao enviar e-mail para item #%d: %s",
                    item.id, e
                )

        return {
            "ok": True,
            "itens_verificados": len(pendentes),
            "alertas_enviados": total_enviados,
            "detalhes": detalhes,
        }
    finally:
        if ctx:
            ctx.pop()


def gerar_html_relatorio_atrasados(pedidos: List[SfPedido], hoje: date) -> tuple[str, str, str]:
    """Gera assunto, corpo HTML e texto para o relatório diário das 08:30 de pedidos em atraso."""
    total = len(pedidos)
    dt_hoje_str = hoje.strftime("%d/%m/%Y")
    assunto = f"🚨 [SollusFlow] Alerta Diário: {total} Pedido{'s' if total > 1 else ''} em Atraso ({dt_hoje_str})"

    base_url = current_app.config.get("MAIL_BASE_URL", "http://localhost:6001")
    flow_url = f"{base_url.rstrip('/')}/sollus-flow/"

    cards_html = []
    itens_texto = []

    for idx, p in enumerate(pedidos, 1):
        dias_atraso = (hoje - p.data_prevista).days if p.data_prevista else 0
        dt_prev_str = p.data_prevista.strftime("%d/%m/%Y") if p.data_prevista else "N/D"
        fase_info = SF_FASES.get(p.fase_atual, {})
        fase_nome = fase_info.get("label", f"Etapa {p.fase_atual}")

        resp_nome = p.responsavel.nome_completo if p.responsavel else "Não atribuído"
        cons_nome = p.consultor.nome_completo if p.consultor else "Não informado"
        link_pedido = f"{flow_url}?cnpj={p.cliente_cnpj or ''}"

        # Cor e estilo do badge de prioridade
        prio = (p.prioridade or "normal").lower()
        if prio in ["urgente", "alta"]:
            prio_bg = "#fee2e2"
            prio_color = "#b91c1c"
            prio_border = "#fca5a5"
            prio_label = "Urgente" if prio == "urgente" else "Alta"
        else:
            prio_bg = "#f1f5f9"
            prio_color = "#475569"
            prio_border = "#cbd5e1"
            prio_label = prio.capitalize()

        # Destaque de dias de atraso
        if dias_atraso >= 15:
            atraso_bg = "#7f1d1d"
            atraso_color = "#ffffff"
        elif dias_atraso >= 7:
            atraso_bg = "#dc2626"
            atraso_color = "#ffffff"
        else:
            atraso_bg = "#ef4444"
            atraso_color = "#ffffff"

        card_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 16px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 6px rgba(0,0,0,0.03);">
          <tr>
            <td style="padding: 16px 20px; border-bottom: 1px solid #f1f5f9; background-color: #fafbfc;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td>
                    <span style="display: inline-block; font-size: 15px; font-weight: 800; color: #0f172a;">
                      #{p.numero_pedido or p.id} &bull; {p.cliente_nome}
                    </span>
                    {f'<div style="font-size: 12px; color: #64748b; margin-top: 2px;">CNPJ: {p.cliente_cnpj}</div>' if p.cliente_cnpj else ''}
                  </td>
                  <td align="right" valign="top">
                    <span style="display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; background-color: {prio_bg}; color: {prio_color}; border: 1px solid {prio_border}; text-transform: uppercase;">
                      {prio_label}
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding: 18px 20px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td width="50%" valign="top" style="padding-bottom: 10px;">
                    <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #64748b; letter-spacing: 0.05em; margin-bottom: 3px;">Etapa Atual</div>
                    <div style="font-size: 13px; font-weight: 700; color: #1e293b;">
                      Etapa {p.fase_atual}: {fase_nome}
                    </div>
                  </td>
                  <td width="50%" valign="top" style="padding-bottom: 10px;">
                    <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #64748b; letter-spacing: 0.05em; margin-bottom: 3px;">Atraso Acumulado</div>
                    <div>
                      <span style="display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 12px; font-weight: 800; background-color: {atraso_bg}; color: {atraso_color};">
                        ⚠ {dias_atraso} dia{'s' if dias_atraso != 1 else ''} de atraso
                      </span>
                      <span style="font-size: 12px; color: #64748b; margin-left: 6px;">(Previsto: {dt_prev_str})</span>
                    </div>
                  </td>
                </tr>
                <tr>
                  <td width="50%" valign="top">
                    <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #64748b; letter-spacing: 0.05em; margin-bottom: 3px;">Responsável</div>
                    <div style="font-size: 13px; color: #1e293b; font-weight: 600;">👤 {resp_nome}</div>
                  </td>
                  <td width="50%" valign="top">
                    <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #64748b; letter-spacing: 0.05em; margin-bottom: 3px;">Consultor(a)</div>
                    <div style="font-size: 13px; color: #1e293b;">💼 {cons_nome}</div>
                  </td>
                </tr>
              </table>
              <div style="margin-top: 14px; padding-top: 12px; border-top: 1px dashed #e2e8f0; text-align: right;">
                <a href="{link_pedido}" style="display: inline-block; font-size: 12px; font-weight: 700; color: #0077b6; text-decoration: none;">
                  Abrir este pedido no SollusFlow &rarr;
                </a>
              </div>
            </td>
          </tr>
        </table>
        """
        cards_html.append(card_html)

        itens_texto.append(
            f"- Pedido #{p.numero_pedido or p.id}: {p.cliente_nome}\n"
            f"  Etapa {p.fase_atual} ({fase_nome}) | Atraso: {dias_atraso} dias (Previsto: {dt_prev_str})\n"
            f"  Responsável: {resp_nome} | Consultor: {cons_nome}\n"
            f"  Link: {link_pedido}\n"
        )

    todos_cards_html = "\n".join(cards_html)
    todos_itens_texto = "\n".join(itens_texto)

    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{assunto}</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b1329; margin: 0; padding: 24px; color: #1e293b;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td align="center">
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width: 640px; background-color: #f8fafc; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.3); border: 1px solid #1e293b;">
              
              <!-- Header Sollus Dark Theme -->
              <tr>
                <td style="background: linear-gradient(135deg, #07172e 0%, #0a254a 50%, #004d7c 100%); padding: 32px 36px; border-bottom: 2px solid #00a4f5;">
                  <table width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                      <td>
                        <span style="display: inline-block; background: rgba(0, 164, 245, 0.2); color: #38bdf8; border: 1px solid rgba(0, 164, 245, 0.4); padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px;">
                          SollusFlow &bull; Relatório Diário de Gestão
                        </span>
                        <h1 style="margin: 0; font-size: 22px; font-weight: 800; line-height: 1.25; color: #ffffff;">
                          Alerta de Pedidos em Atraso
                        </h1>
                        <p style="margin: 8px 0 0 0; font-size: 13px; color: #94a3b8;">
                          Disparo automático diário das 08:30 &bull; {dt_hoje_str}
                        </p>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

              <!-- Banner de Destaque -->
              <tr>
                <td style="padding: 24px 32px 12px 32px;">
                  <div style="background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%); border-left: 5px solid #dc2626; border-radius: 10px; padding: 18px 22px;">
                    <table width="100%" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td width="48" valign="top">
                          <span style="font-size: 30px; line-height: 1;">⚠️</span>
                        </td>
                        <td valign="top" style="padding-left: 8px;">
                          <div style="font-size: 15px; font-weight: 800; color: #991b1b; margin-bottom: 4px;">
                            {'Existe 1 pedido' if total == 1 else f'Existem {total} pedidos'} com prazo de entrega/conclusão vencido
                          </div>
                          <div style="font-size: 13px; color: #7f1d1d; line-height: 1.4;">
                            Abaixo estão listados os pedidos que demandam acompanhamento prioritário junto aos clientes e responsáveis para regularização dos prazos.
                          </div>
                        </td>
                      </tr>
                    </table>
                  </div>
                </td>
              </tr>

              <!-- Lista de Pedidos em Atraso -->
              <tr>
                <td style="padding: 12px 32px 24px 32px;">
                  <div style="font-size: 13px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em; color: #475569; margin-bottom: 12px;">
                    📋 Relação de Pedidos Atrasados ({total})
                  </div>

                  {todos_cards_html}

                  <!-- Botão de Acesso Geral -->
                  <div style="text-align: center; margin-top: 28px; margin-bottom: 12px;">
                    <a href="{flow_url}" style="display: inline-block; background: linear-gradient(135deg, #0084c8 0%, #005696 100%); color: #ffffff !important; text-decoration: none; padding: 14px 32px; border-radius: 10px; font-weight: 800; font-size: 15px; box-shadow: 0 4px 14px rgba(0, 132, 200, 0.35);">
                      Abrir Quadro Geral do SollusFlow
                    </a>
                  </div>
                </td>
              </tr>

              <!-- Rodapé Institucional -->
              <tr>
                <td style="padding: 24px 32px; background-color: #07172e; border-top: 1px solid #1e293b; text-align: center;">
                  <p style="margin: 0 0 6px 0; font-size: 12px; font-weight: 700; color: #cbd5e1;">
                    SollusFlow &bull; Sistema Integrado Sollus Connected
                  </p>
                  <p style="margin: 0; font-size: 11px; color: #64748b; line-height: 1.4;">
                    Este e-mail é gerado automaticamente todos os dias às 08:30 para gestores e responsáveis.<br>
                    Suporte de TI: <a href="mailto:ti2@sollusgroup.com" style="color: #38bdf8; text-decoration: none;">ti2@sollusgroup.com</a> | WhatsApp: (21) 99229-7900
                  </p>
                </td>
              </tr>

            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    texto = f"""[SollusFlow - Relatório Diário de Pedidos em Atraso]
Data: {dt_hoje_str} às 08:30
Total de Pedidos Atrasados: {total}

Atenção: Os seguintes pedidos estão com data prevista vencida no SollusFlow:

{todos_itens_texto}

Acesse o sistema para atualizar os pedidos:
{flow_url}

---
Sollus Connected • Sistema Integrado Sollus Group
Dúvidas ou suporte: ti2@sollusgroup.com | (21) 99229-7900
"""
    return assunto, html, texto


def get_sollusflow_alert_config() -> dict:
    """Retorna as configurações do alerta diário do SollusFlow gravadas no banco (sf_config)."""
    from modules.chamados.models import SfConfig
    import json
    
    padrao = {
        "ativo": True,
        "horario": "08:30",
        "destinatarios_modo": "selecionados",  # 'selecionados' ou 'todos_gestores'
        "usuarios_ids": [],
        "emails_adicionais": "",
        "incluir_responsaveis": True,
        "apenas_dominio_corporativo": True,
        "incluir_ti": True,
    }
    
    try:
        cfg = SfConfig.query.filter_by(chave="alerta_pedidos_atrasados_config").first()
        if cfg and cfg.valor:
            data = json.loads(cfg.valor)
            if isinstance(data, dict):
                padrao.update(data)
                return padrao
    except Exception as e:
        logger.warning("[sollusflow_config] Erro ao carregar config de alerta: %s", e)
        
    # Se ainda não configurado, popula por padrão com gestores oficiais ativos da Sollus
    try:
        from modules.propostas.models import User
        gestores_oficiais = User.query.filter(
            User.is_active.is_(True),
            db.or_(
                User.tipo.in_(["admin", "gestor"]),
                User.role.in_(["admin", "gestor"]),
            )
        ).all()
        u_ids = []
        for u in gestores_oficiais:
            em = (u.email or "").strip().lower()
            if any(em.endswith(dom) for dom in ["@sollusgroup.com", "@sollustecnologia.com"]):
                if not any(dummy in em for dummy in ["admin@admin.com", "antigravity.ai", "test_admin@"]):
                    u_ids.append(u.id)
        padrao["usuarios_ids"] = u_ids
    except Exception:
        pass
        
    return padrao


def save_sollusflow_alert_config(data: dict) -> bool:
    """Salva as configurações do alerta diário no banco de dados (sf_config)."""
    from modules.chamados.models import SfConfig
    import json
    try:
        cfg = SfConfig.query.filter_by(chave="alerta_pedidos_atrasados_config").first()
        if not cfg:
            cfg = SfConfig(chave="alerta_pedidos_atrasados_config", valor=json.dumps(data, ensure_ascii=False))
            db.session.add(cfg)
        else:
            cfg.valor = json.dumps(data, ensure_ascii=False)
            cfg.updated_at = datetime.utcnow()
        db.session.commit()
        logger.info("[sollusflow_config] Configuração de alerta diário salva com sucesso: %s", data)
        return True
    except Exception as e:
        db.session.rollback()
        logger.exception("[sollusflow_config] Erro ao salvar config de alerta: %s", e)
        return False


def enviar_alerta_diario_pedidos_atrasados(app=None, force_email=None) -> dict:
    """Dispara alerta diário consolidado às 08:30 para gestores e responsáveis sobre pedidos em atraso."""
    ctx = app.app_context() if app else None
    if ctx:
        ctx.push()

    try:
        config = get_sollusflow_alert_config()
        if not config.get("ativo", True) and not force_email:
            logger.info("[sollusflow_atrasados] Alerta diário está desativado nas configurações.")
            return {
                "ok": True,
                "pedidos_atrasados": 0,
                "alertas_enviados": 0,
                "mensagem": "O alerta diário está desativado nas configurações do SollusFlow.",
            }

        hoje = date.today()
        # Busca pedidos ativos cuja data prevista seja anterior a hoje
        pedidos_atrasados = (
            SfPedido.query
            .filter(
                SfPedido.status == "ativo",
                SfPedido.data_prevista.isnot(None),
                SfPedido.data_prevista < hoje,
            )
            .order_by(SfPedido.data_prevista.asc())
            .all()
        )

        if not pedidos_atrasados:
            logger.info("[sollusflow_atrasados] Nenhum pedido em atraso encontrado hoje (%s).", hoje)
            return {
                "ok": True,
                "pedidos_atrasados": 0,
                "alertas_enviados": 0,
                "mensagem": "Nenhum pedido em atraso hoje.",
            }

        from modules.propostas.models import User
        destinatarios_candidatos = set()

        modo = config.get("destinatarios_modo", "selecionados")
        if modo == "todos_gestores":
            gestores = User.query.filter(
                User.is_active.is_(True),
                db.or_(
                    User.tipo.in_(["admin", "gestor"]),
                    User.role.in_(["admin", "gestor"]),
                ),
            ).all()
            for u in gestores:
                if u.email and "@" in u.email:
                    destinatarios_candidatos.add(u.email.strip().lower())
        else:
            # Modo selecionados por ID
            u_ids = config.get("usuarios_ids", [])
            if u_ids:
                selecionados = User.query.filter(
                    User.id.in_(u_ids),
                    User.is_active.is_(True)
                ).all()
                for u in selecionados:
                    if u.email and "@" in u.email:
                        destinatarios_candidatos.add(u.email.strip().lower())

        # E-mails adicionais cadastrados manualmente
        emails_add = config.get("emails_adicionais", "")
        if isinstance(emails_add, list):
            for em in emails_add:
                if em and "@" in em:
                    destinatarios_candidatos.add(em.strip().lower())
        elif isinstance(emails_add, str):
            for em in emails_add.replace(";", "\n").replace(",", "\n").splitlines():
                em_clean = em.strip().lower()
                if em_clean and "@" in em_clean:
                    destinatarios_candidatos.add(em_clean)

        # Sempre incluir TI se habilitado
        if config.get("incluir_ti", True):
            destinatarios_candidatos.add("ti2@sollusgroup.com")

        # Incluir responsáveis e consultores dos pedidos atrasados se habilitado
        if config.get("incluir_responsaveis", True):
            for p in pedidos_atrasados:
                if p.responsavel and p.responsavel.email and "@" in p.responsavel.email:
                    destinatarios_candidatos.add(p.responsavel.email.strip().lower())
                if p.consultor and p.consultor.email and "@" in p.consultor.email:
                    destinatarios_candidatos.add(p.consultor.email.strip().lower())
                if p.fase_atual == 16:
                    destinatarios_candidatos.add("comercial6@sollusgroup.com")

        # Filtro de Segurança por Domínio Corporativo
        restricao_dominio = config.get("apenas_dominio_corporativo", True)
        dominios_autorizados = ["@sollusgroup.com", "@sollustecnologia.com", "@sollus.com"]

        destinatarios_finais = set()
        for em in destinatarios_candidatos:
            # Ignora e-mails de teste conhecidos
            if any(dummy in em for dummy in ["admin@admin.com", "antigravity.ai", "test_admin@"]):
                continue

            if restricao_dominio:
                if any(em.endswith(dom) for dom in dominios_autorizados):
                    destinatarios_finais.add(em)
                else:
                    logger.warning("[sollusflow_atrasados] E-mail '%s' bloqueado pela restrição de domínio corporativo!", em)
            else:
                destinatarios_finais.add(em)

        if force_email:
            destinatarios_finais = {force_email.strip().lower()}

        lista_destinatarios = sorted(list(destinatarios_finais))
        if not lista_destinatarios:
            logger.warning("[sollusflow_atrasados] Nenhum destinatário válido para envio de alerta.")
            return {"ok": False, "mensagem": "Sem destinatários válidos após aplicação dos filtros e restrições de domínio."}

        assunto, html, texto = gerar_html_relatorio_atrasados(pedidos_atrasados, hoje)

        send_email(assunto, lista_destinatarios, html, texto)
        logger.info(
            "[sollusflow_atrasados] Alerta diário enviado com sucesso para %d destinatários (%d pedidos em atraso): %s",
            len(lista_destinatarios), len(pedidos_atrasados), lista_destinatarios
        )

        return {
            "ok": True,
            "pedidos_atrasados": len(pedidos_atrasados),
            "alertas_enviados": len(lista_destinatarios),
            "destinatarios": lista_destinatarios,
            "assunto": assunto,
        }
    except Exception as e:
        logger.exception("[sollusflow_atrasados] Erro ao processar alerta diário de pedidos atrasados: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        if ctx:
            ctx.pop()

