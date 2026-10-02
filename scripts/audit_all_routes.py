import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Proposal, AgendaEntry, Birthday, VacationEntry
from modules.crm.models import CrmFunil, CrmNegociacao, CrmEmpresa, CrmContato
from modules.sollus_tickets.models import SollusTicket
from modules.chamados.models import SfPedido

def run_audit():
    app = create_app()
    with app.app_context():
        admin = User.query.filter_by(tipo='admin').first() or User.query.first()
        if not admin:
            print("Nenhum usuario encontrado no banco para autenticar.")
            return

        client = app.test_client()

        # Obter IDs de exemplo para rotas parametrizadas
        funil = CrmFunil.query.first()
        funil_id = funil.id if funil else 1

        deal = CrmNegociacao.query.first()
        deal_id = deal.id if deal else 1

        empresa = CrmEmpresa.query.first()
        empresa_id = empresa.id if empresa else 1

        contato = CrmContato.query.first()
        contato_id = contato.id if contato else 1

        proposta = Proposal.query.first()
        proposta_id = proposta.id if proposta else 1

        ticket = SollusTicket.query.first()
        ticket_id = ticket.id if ticket else 1

        pedido = SfPedido.query.first()
        pedido_id = pedido.id if pedido else 1

        birthday = Birthday.query.first()
        birthday_id = birthday.id if birthday else 1

        param_map = {
            "funil_id": funil_id,
            "negociacao_id": deal_id,
            "empresa_id": empresa_id,
            "contato_id": contato_id,
            "proposta_id": proposta_id,
            "proposal_id": proposta_id,
            "ticket_id": ticket_id,
            "pedido_id": pedido_id,
            "pid": pedido_id,
            "id": 1,
            "user_id": admin.id,
            "usuario_id": admin.id,
            "birthday_id": birthday_id,
            "ano": 2026,
            "region_slug": "rj",
            "slug": "rj",
            "code": "es",
        }

        routes_to_test = []
        for rule in app.url_map.iter_rules():
            if "GET" not in rule.methods:
                continue
            r_str = rule.rule
            if r_str.startswith("/static") or r_str.startswith("/_debug"):
                continue
            if "<path:filename>" in r_str or "/download/" in r_str or "/exportar_pdf" in r_str or "/export_pdf" in r_str:
                continue

            # Construir URL com parâmetros resolvidos
            url = r_str
            can_test = True
            for arg in rule.arguments:
                if arg in param_map:
                    url = url.replace(f"<{arg}>", str(param_map[arg]))
                    url = url.replace(f"<int:{arg}>", str(param_map[arg]))
                    url = url.replace(f"<string:{arg}>", str(param_map[arg]))
                else:
                    can_test = False
                    break

            if can_test:
                routes_to_test.append((url, rule.endpoint))

        print(f"Total de rotas GET elegiveis para teste: {len(routes_to_test)}")

        ok_count = 0
        redirect_count = 0
        client_error_count = 0
        server_error_count = 0
        errors_500 = []

        for url, endpoint in routes_to_test:
            with client.session_transaction() as sess:
                sess["_user_id"] = str(admin.id)
                sess["usuario_id"] = admin.id
                sess["usuario"] = admin.usuario
                sess["nome"] = admin.nome_completo
                sess["email"] = admin.email
                sess["tipo"] = "admin"
                sess["role_label"] = "Administrador"
                sess["permissions"] = {"*": True}

            try:
                res = client.get(url, follow_redirects=False)
                status = res.status_code
                if status == 200:
                    ok_count += 1
                elif status in (301, 302, 303, 307, 308):
                    redirect_count += 1
                elif status == 500:
                    server_error_count += 1
                    errors_500.append((url, endpoint, 500, res.get_data(as_text=True)[:600]))
                    print(f"  [500 ERRO] {url} ({endpoint})")
                else:
                    client_error_count += 1
            except Exception as exc:
                server_error_count += 1
                errors_500.append((url, endpoint, "EXCEPTION", str(exc)))
                print(f"  [EXCECAO] {url} ({endpoint}): {exc}")

        print("\n================ RESULTADO DA AUDITORIA ================")
        print(f"Rotas 200 OK: {ok_count}")
        print(f"Redirecionamentos 30x: {redirect_count}")
        print(f"Outros status (403/404): {client_error_count}")
        print(f"Erros de Servidor (500 / Exceções): {server_error_count}")
        print("========================================================\n")

        if errors_500:
            print("DETALHES DOS ERROS 500 ENCONTRADOS:")
            for item in errors_500:
                print(f"\nURL: {item[0]} | Endpoint: {item[1]}")
                print(f"Trace/Info: {item[3]}")
        else:
            print("NENHUM ERRO 500 ENCONTRADO! Todas as páginas responderam perfeitamente.")

if __name__ == "__main__":
    run_audit()
