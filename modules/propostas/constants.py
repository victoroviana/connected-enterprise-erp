"""Constants shared across the proposals module."""

ISSUER_COMPANIES = [
  {
    'code': 'matriz_sp',
    'name': 'Empresa Matriz - São Paulo/SP',
    'cnpj': '00.000.000/0001-00',
    'email': 'comercial@empresa.com.br',
    'phone': '11 3000-0000',
    'phones': ['11 3000-0000', '11 3000-0001'],
    'site': 'www.empresa.com.br',
    'address': 'Av. Paulista, 1000 - Bela Vista - São Paulo/SP - CEP: 01310-100',
  },
  {
    'code': 'filial_rj',
    'name': 'Empresa Filial - Rio de Janeiro/RJ',
    'cnpj': '00.000.000/0002-00',
    'email': 'comercial.rj@empresa.com.br',
    'phone': '21 3000-0000',
    'phones': ['21 3000-0000', '21 3000-0001'],
    'site': 'www.empresa.com.br',
    'address': 'Av. Rio Branco, 500 - Centro - Rio de Janeiro/RJ - CEP: 20040-002',
  },
  {
    'code': 'filial_pr',
    'name': 'Empresa Filial - Curitiba/PR',
    'cnpj': '00.000.000/0003-00',
    'email': 'comercial.pr@empresa.com.br',
    'phone': '41 3000-0000',
    'phones': ['41 3000-0000'],
    'site': 'www.empresa.com.br',
    'address': 'Rua das Flores, 300 - Centro - Curitiba/PR - CEP: 80020-000',
  },
  {
    'code': 'filial_es',
    'name': 'Empresa Filial - Vitória/ES',
    'cnpj': '00.000.000/0004-00',
    'email': 'comercial.es@empresa.com.br',
    'phone': '27 3000-0000',
    'phones': ['27 3000-0000'],
    'site': 'www.empresa.com.br',
    'address': 'Av. Beira Mar, 200 - Praia do Canto - Vitória/ES - CEP: 29055-000',
  },
]

ISSUER_COMPANY_CHOICES = [(item["code"], item["name"]) for item in ISSUER_COMPANIES]

DEFAULT_ISSUER_CODE = ISSUER_COMPANIES[0]["code"] if ISSUER_COMPANIES else "matriz_sp"
ISSUER_COMPANY_MAP = {item["code"]: item for item in ISSUER_COMPANIES}
DEFAULT_ISSUER_PHONE = next((item.get("phone") for item in ISSUER_COMPANIES if item.get("phone")), "11 3000-0000")
