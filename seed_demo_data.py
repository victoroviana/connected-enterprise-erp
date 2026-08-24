"""
Seed script for Connected Enterprise ERP & CRM.
Creates sample demonstration data (Users, Departments, Equipment, Tickets)
for local testing and portfolio showcase.
"""
import os
import sys
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

from app import create_app
from extensions import db
from modules.propostas.models import User, Department, Equipment
from modules.chamados.models import Ticket, TicketMessage

def run_seed():
    app = create_app()
    with app.app_context():
        print("🌱 Initializing database schema...")
        db.create_all()

        print("🏢 Creating Departments...")
        depts_data = [
            ("Suporte Técnico", "suporte-tecnico"),
            ("Comercial & Vendas", "comercial-vendas"),
            ("Financeiro", "financeiro"),
            ("Desenvolvimento", "desenvolvimento"),
        ]
        dept_map = {}
        for name, slug in depts_data:
            dept = Department.query.filter_by(slug=slug).first() or Department.query.filter_by(name=name).first()
            if not dept:
                dept = Department(name=name, slug=slug)
                db.session.add(dept)
                db.session.flush()
            dept_map[name] = dept

        print("👥 Creating Demo Users...")
        users_data = [
            {
                "usuario": "admin",
                "nome_completo": "Administrador do Sistema",
                "email": "admin@empresa.com.br",
                "password": "admin123",
                "role": "admin",
                "dept": "Desenvolvimento",
            },
            {
                "usuario": "gestor",
                "nome_completo": "Mariana Gestora",
                "email": "gestor@empresa.com.br",
                "password": "gestor123",
                "role": "gestor",
                "dept": "Suporte Técnico",
            },
            {
                "usuario": "atendente",
                "nome_completo": "Carlos Atendente",
                "email": "atendente@empresa.com.br",
                "password": "user123",
                "role": "usuario",
                "dept": "Suporte Técnico",
            },
            {
                "usuario": "cliente",
                "nome_completo": "Ana Silva (TechCorp)",
                "email": "cliente@exemplo.com.br",
                "password": "client123",
                "role": "usuario",
                "dept": "Comercial & Vendas",
            },
        ]

        user_map = {}
        for u in users_data:
            user = User.query.filter_by(usuario=u["usuario"]).first()
            if not user:
                user = User(
                    usuario=u["usuario"],
                    nome_completo=u["nome_completo"],
                    email=u["email"],
                    password_hash=generate_password_hash(u["password"]),
                    role=u["role"],
                    is_active=True,
                    department_id=dept_map[u["dept"]].id,
                )
                db.session.add(user)
                db.session.flush()
            else:
                user.password_hash = generate_password_hash(u["password"])
                user.is_active = True
                user.role = u["role"]
                db.session.flush()
            user_map[u["usuario"]] = user

        print("📦 Creating Sample Products & Equipment...")
        equip_data = [
            ("Relógio de Ponto Biométrico Touch", 1250.00, "Equipamento homologado Portaria 671/MTE com leitor biométrico e tela touch."),
            ("Terminal de Reconhecimento Facial AI", 2490.00, "Terminal de controle de acesso e ponto com validação facial anti-spoofing."),
            ("Cartões de Proximidade RFID 125kHz (Cento)", 150.00, "Pacote com 100 cartões RFID padrão Mifare/EM4100."),
            ("Comandas Eletrônicas em PVC Resistente", 85.00, "Comandas personalizadas para controle de consumo com código de barras."),
        ]
        for name, price, desc in equip_data:
            eq = Equipment.query.filter_by(name=name).first()
            if not eq:
                eq = Equipment(name=name, unit_price=price, description=desc)
                db.session.add(eq)

        print("🎫 Creating Demonstration Tickets...")
        sample_tickets = [
            {
                "title": "Instalação do novo Terminal Facial na Filial SP",
                "description": "Cliente solicita visita técnica para parametrização de rede e cadastro facial da equipe.",
                "priority": "high",
                "status": "in_progress",
                "user": user_map["cliente"],
                "assignee": user_map["atendente"],
                "messages": [
                    (user_map["cliente"], "Solicitamos o agendamento para a próxima terça-feira às 10h."),
                    (user_map["atendente"], "Agendamento confirmado! O técnico Carlos comparecerá no local."),
                ]
            },
            {
                "title": "Dúvida sobre exportação de espelho de ponto em PDF",
                "description": "Como gerar o relatório consolidado mensal com as assinaturas digitais dos colaboradores?",
                "priority": "medium",
                "status": "open",
                "user": user_map["cliente"],
                "assignee": user_map["gestor"],
                "messages": [
                    (user_map["cliente"], "Não estou localizando o botão de exportação em lote."),
                ]
            },
            {
                "title": "Configuração da integração com banco de dados em nuvem",
                "description": "Sincronização automática dos registros de ponto via Webhook concluída com sucesso.",
                "priority": "low",
                "status": "closed",
                "user": user_map["atendente"],
                "assignee": user_map["admin"],
                "messages": [
                    (user_map["atendente"], "Webhook configurado e testado com 100% de sucesso."),
                ]
            },
        ]

        for t_info in sample_tickets:
            ticket = Ticket.query.filter_by(title=t_info["title"]).first()
            if not ticket:
                ticket = Ticket(
                    title=t_info["title"],
                    description=t_info["description"],
                    priority=t_info["priority"],
                    status=t_info["status"],
                    user_id=t_info["user"].id,
                    assignee_id=t_info["assignee"].id if t_info["assignee"] else None,
                    created_at=datetime.utcnow() - timedelta(days=2),
                )
                db.session.add(ticket)
                db.session.flush()

                for author, msg_body in t_info["messages"]:
                    msg = TicketMessage(
                        ticket_id=ticket.id,
                        author_id=author.id,
                        body=msg_body,
                        created_at=datetime.utcnow() - timedelta(hours=5),
                    )
                    db.session.add(msg)

        db.session.commit()
        print("\n✨ Database successfully seeded with demo data!")
        print("=" * 60)
        print("🔐 DEMO CREDENTIALS:")
        print("   👑 Admin:    usuario='admin'    | senha='admin123'")
        print("   👔 Gestor:   usuario='gestor'   | senha='gestor123'")
        print("   🛠️ Atendente: usuario='atendente' | senha='user123'")
        print("   🏢 Cliente:  usuario='cliente'  | senha='client123'")
        print("=" * 60)
        os._exit(0)

if __name__ == "__main__":
    run_seed()
