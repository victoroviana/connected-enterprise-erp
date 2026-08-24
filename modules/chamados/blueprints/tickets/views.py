from __future__ import annotations



from datetime import datetime, timedelta

from flask import render_template

from flask_login import login_required, current_user

from sqlalchemy import func



from . import tickets_bp

from extensions import db

from modules.propostas.models import User

from modules.chamados.models import Ticket





def _role() -> str:

    return (getattr(current_user, "role", "") or "").lower()





@tickets_bp.route("/dashboard", methods=["GET"], endpoint="dashboard")

@login_required

def dashboard():

    """

    Dashboard: lista de chamados recentes.

    - Equipe (agent/gestor/admin): v todos.

    - Usuário comum: v somente os prprios.

    """

    role = _role()

    q = Ticket.query



    if role in ("agent", "gestor", "admin"):

        tickets = (

            q.order_by(Ticket.created_at.desc())

             .limit(300)

             .all()

        )

    else:

        tickets = (

            q.filter(Ticket.user_id == current_user.id)

             .order_by(Ticket.created_at.desc())

             .limit(300)

             .all()

        )



    return render_template("chamados/tickets/dashboard.html", tickets=tickets)





@tickets_bp.route("/closed", methods=["GET"], endpoint="closed_list")

@login_required

def closed_list():

    """

    Lista apenas finalizados.

    - Equipe: todos finalizados

    - Usuário comum: finalizados do prprio usuário

    """

    role = _role()

    q = Ticket.query.filter(Ticket.status == "closed")



    if role not in ("agent", "gestor", "admin"):

        q = q.filter(Ticket.user_id == current_user.id)



    tickets = q.order_by(Ticket.created_at.desc()).limit(300).all()

    return render_template("chamados/tickets/closed_list.html", tickets=tickets)





@tickets_bp.route("/reports", methods=["GET"], endpoint="reports_overview")

@login_required

def reports_overview():

    """

    Relatrios simples:

      - Evoluo mensal ltimos 12 meses

      - Distribuio por status

      - Distribuio por prioridade

      - Top atendentes por fechamentos

    Mantm valores do banco em EN (open/in_progress/closed) e mostra PT-BR na UI.

    """

    # Perodo (ltimos 12 meses)

    end = datetime.utcnow().replace(day=1)

    start = (end - timedelta(days=365)).replace(day=1)



    # Base query conforme papel

    role = _role()

    base_q = Ticket.query

    if role not in ("agent", "gestor", "admin"):

        base_q = base_q.filter(Ticket.user_id == current_user.id)



    # Evoluo mensal

    monthly_rows = (

        db.session.query(

            func.date_format(Ticket.created_at, "%Y-%m").label("ym"),

            func.count(Ticket.id),

        )

        .filter(Ticket.created_at >= start)

        .group_by("ym")

        .order_by("ym")

        .all()

    )

    # Monta 12 labels seguidos do START->END

    month_labels = []

    month_values = []

    ym_cursor = start

    rows_map = {ym: c for ym, c in monthly_rows}

    for _ in range(12):

        ym_str = ym_cursor.strftime("%Y-%m")

        month_labels.append(ym_cursor.strftime("%m/%Y"))

        month_values.append(int(rows_map.get(ym_str, 0)))

        # avana um ms

        if ym_cursor.month == 12:

            ym_cursor = ym_cursor.replace(year=ym_cursor.year + 1, month=1)

        else:

            ym_cursor = ym_cursor.replace(month=ym_cursor.month + 1)



    # Por status

    status_rows = (

        db.session.query(Ticket.status, func.count(Ticket.id))

        .group_by(Ticket.status)

        .all()

    )

    status_map_pt = {

        "open": "Aberto",

        "in_progress": "Em andamento",

        "closed": "Finalizado",

    }

    chart_status_labels = [status_map_pt.get(s or "", s or "") for s, _ in status_rows]

    chart_status_values = [int(c) for _, c in status_rows]



    # Por prioridade

    pr_rows = (

        db.session.query(Ticket.priority, func.count(Ticket.id))

        .group_by(Ticket.priority)

        .all()

    )

    pr_map_pt = {

        "low": "Baixa",

        "medium": "Mdia",

        "high": "Alta",

        "urgent": "Urgente",

    }

    chart_prior_labels = [pr_map_pt.get(p or "", p or "") for p, _ in pr_rows]

    chart_prior_values = [int(c) for _, c in pr_rows]



    # Top atendentes por fechamentos

    top_rows = (

        db.session.query(User.id, User.nome_completo.label("name"), func.count(Ticket.id).label("cnt"))

        .join(User.assigned_tickets)  # relacionamento no models.py

        .filter(Ticket.status == "closed")

        .group_by(User.id, User.nome_completo)

        .order_by(func.count(Ticket.id).desc())

        .limit(10)

        .all()

    )

    top_agents = [{"id": uid, "name": (name or ""), "count": int(cnt)} for uid, name, cnt in top_rows]



    return render_template(

        "chamados/tickets/reports.html",

        month_labels=month_labels,

        month_values=month_values,

        chart_status_labels=chart_status_labels,

        chart_status_values=chart_status_values,

        chart_prior_labels=chart_prior_labels,

        chart_prior_values=chart_prior_values,

        top_agents=top_agents,

    )



