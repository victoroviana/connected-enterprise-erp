"""Constants shared across the proposals module."""

ISSUER_COMPANIES = [
  {
    'code': 'sollus',
    'name': 'Sollus Tecnologia - Rio de Janeiro/RJ',
    'cnpj': '14.129.133/0001-77',
    'email': 'comercial@sollusgroup.com',
    'phone': '21 2413-3203',
    'phones': ['21 2413-3203', '21 3245-6256'],
    'site': 'www.sollustecnologia.com',
    'address': 'Av. Brasil, 31.904 - Bangu - Rio de Janeiro/RJ - CEP: 21863-000',
  },
  {
    'code': 'technosollus_rj',
    'name': 'Technosollus RJ',
    'cnpj': '34.294.161/0001-57',
    'email': 'comercial@sollusgroup.com',
    'phone': '21 2413-3203',
    'phones': ['21 2413-3203', '21 3245-6256'],
    'site': 'www.sollustecnologia.com',
    'address': 'Av. Brasil, 31.904 - Bangu - Rio de Janeiro/RJ - CEP: 21863-000',
  },
  {
    'code': 'technosollus',
    'name': 'Technosollus - Vila Velha/ES',
    'cnpj': '34.294.161/0001-57',
    'email': 'comercial@sollusgroup.com',
    'phone': '27 3072-4863',
    'phones': ['27 3072-4863'],
    'site': 'www.sollustecnologia.com',
    'address': 'Rodovia do Sol, 2780 - SL 914 - Praia de Itaparica - Vila Velha/ES - CEP: 29102-020',
  },
  {
    'code': 'sssantos',
    'name': 'SS Santos - Campos dos Goytacazes/RJ',
    'cnpj': '24.242.818/0001-89',
    'email': 'comercial@sollusgroup.com',
    'phone': '22 2733-3722',
    'phones': ['22 2733-3722'],
    'site': 'www.sollustecnologia.com',
    'address': 'Rua Barão da Lagoa Dourada, 187 - Centro - Campos dos Goytacazes/RJ - CEP: 28035-211',
  },
  {
    'code': 'sollus_curitiba',
    'name': 'Sollus Tecnologia - Curitiba/PR',
    'cnpj': '34.294.161/0001-57',
    'email': 'comercial@sollusgroup.com',
    'phone': '41 3797-5093',
    'phones': ['41 3797-5093', '41 99800-0050'],
    'site': 'www.sollustecnologia.com',
    'address': 'Rua Carlos Dietzsch, 359 - Sala 05 - Portão - Curitiba/PR - CEP: 80330-000',
  },
  {
    'code': 'sollus_sp',
    'name': 'Sollus Tecnologia - São Paulo/SP',
    'cnpj': '14.129.133/0001-77',
    'email': 'comercial@sollusgroup.com',
    'phone': '11 4040-6767',
    'phones': ['11 4040-6767'],
    'site': 'www.sollustecnologia.com',
    'address': 'Av. Cipriano Rodrigues, 182/189 - Vila Formosa - São Paulo/SP - CEP: 03361-010',
  },
]

ISSUER_COMPANY_CHOICES = [(item["code"], item["name"]) for item in ISSUER_COMPANIES]

DEFAULT_ISSUER_CODE = ISSUER_COMPANIES[0]["code"] if ISSUER_COMPANIES else "sollus"
ISSUER_COMPANY_MAP = {item["code"]: item for item in ISSUER_COMPANIES}
DEFAULT_ISSUER_PHONE = next((item.get("phone") for item in ISSUER_COMPANIES if item.get("phone")), "21 2413-3203")
