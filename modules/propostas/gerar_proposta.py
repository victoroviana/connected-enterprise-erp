# gerar_proposta.py


import html, io, json, os, re, uuid

from tempfile import TemporaryDirectory



from pathlib import Path
from types import SimpleNamespace


import unicodedata




from datetime import datetime

from typing import Any, Iterable



from flask import current_app



from modules.propostas.constants import (

 ISSUER_COMPANIES,

 ISSUER_COMPANY_MAP,

 DEFAULT_ISSUER_CODE,

 DEFAULT_ISSUER_PHONE,

)
from modules.propostas.utils.item_rules import is_one_time_acquisition_item



# aaa helpers PDF aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa



try:



 from playwright.sync_api import sync_playwright



 _PLAYWRIGHT_AVAILABLE = True



except Exception:



 sync_playwright = None



 _PLAYWRIGHT_AVAILABLE = False



# aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa



# Base do projeto (para resolver caminhos relativos de imagens)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, os.pardir, os.pardir))



ISSUER_COMPANY_NAME = os.getenv("ISSUER_COMPANY_NAME", "Sollus Tecnologia")

ISSUER_EMAIL = os.getenv("ISSUER_EMAIL", "comercial@sollusgroup.com")

ISSUER_PHONE = os.getenv("ISSUER_PHONE", DEFAULT_ISSUER_PHONE)

ISSUER_WEBSITE = os.getenv("ISSUER_WEBSITE", "sollustecnologia.com")

ISSUER_ADDRESS = os.getenv("ISSUER_ADDRESS", "")

ISSUER_CONTACT_NAME_DEFAULT = os.getenv("ISSUER_CONTACT_NAME", "")



_ISSUER_COMPANY_MAP = ISSUER_COMPANY_MAP





def _resolve_img_path(pth: str):

 """

 Resolve um caminho absoluto para a imagem do equipamento,

 normalizando separadores e tentando algumas pastas comuns

 (CWD, BASE_DIR, BASE_DIR/static[/images]).

 """

 if not pth:

  return None



 text = str(pth).strip()

 if not text:

  return None



 # Se ja for absoluto e existir, ok

 if os.path.isabs(text) and os.path.exists(text):

  return text



 # Normaliza separadores vindos de Windows e remove prefixos redundantes

 normalized = text.replace("\\", "/").lstrip("/")

 parts = [p for p in normalized.split("/") if p and p not in (".", "..")]



 trimmed = parts[:]

 if trimmed and trimmed[0].lower() == "static":

  trimmed = trimmed[1:]

 if trimmed and trimmed[0].lower() == "images":

  trimmed = trimmed[1:]



 joined = os.path.join(*parts) if parts else ""

 trimmed_joined = os.path.join(*trimmed) if trimmed else ""

 basename = trimmed[-1] if trimmed else (parts[-1] if parts else "")



 candidates = []

 seen_rel = set()

 for rel in (joined, trimmed_joined):

  if not rel or rel in seen_rel:

   continue

  seen_rel.add(rel)

  candidates.extend([

   rel,

   os.path.join(os.getcwd(), rel),

   os.path.join(BASE_DIR, rel),

  ])



 if trimmed_joined:

  candidates.extend([

   os.path.join(BASE_DIR, "static", trimmed_joined),

   os.path.join(BASE_DIR, "static", "images", trimmed_joined),

   os.path.join(os.getcwd(), "static", trimmed_joined),

   os.path.join(os.getcwd(), "static", "images", trimmed_joined),

   os.path.join(ROOT_DIR, "static", trimmed_joined),

   os.path.join(ROOT_DIR, "static", "images", trimmed_joined),

  ])



 if basename:

  candidates.extend([

   os.path.join(BASE_DIR, "static", "images", basename),

   os.path.join(os.getcwd(), "static", "images", basename),

   os.path.join(ROOT_DIR, "static", "images", basename),

  ])



 seen = set()

 for candidate in candidates:

  candidate_path = os.path.normpath(candidate)

  if candidate_path in seen:

   continue

  seen.add(candidate_path)

  if os.path.exists(candidate_path):

   return os.path.abspath(candidate_path)



 return None





_CLOCK_OBSERVATION_TARGETS = None





def _normalize_text(value: str) -> str:

 text = unicodedata.normalize("NFKD", value or "")

 text = "".join(ch for ch in text if not unicodedata.combining(ch))

 cleaned = []

 for ch in text:

  if ch.isalnum():

   cleaned.append(ch.lower())

  elif ch in {" ", "\n", "\t", "-", "/"}:

   cleaned.append(" ")

 normalized = "".join(cleaned)

 return " ".join(normalized.split())


def _system_image_fallback(label: str | None) -> str | None:
 if not label:
  return None
 normalized = _normalize_text(label)
 if not normalized:
  return None
 try:
  from modules.propostas.utils.systems import iter_system_options
 except Exception:
  return None
 for option in iter_system_options():
  if _normalize_text(option.label) == normalized:
   return option.image
 return None





def _build_clock_observation_targets() -> set[str]:

 texts = [

  "OBSERVAÇÕES SOBRE O RELÓGIO DE PONTO E SUA UTILIZAÇÃO:",
  "Equipamentos atendem a Portaria 671.",
  "Cada equipamento certificado pelo MTE (SREP) atende a 01 (UM) CNPJ.",
  "Uma vez cadastrado o CNPJ na memória do relógio de ponto, ele fica impossibilitado de ser reutilizado por outra empresa que não faça parte do mesmo grupo econômico, ou ainda ser devolvido a Sollus tecnologia.",

 ]

 return {_normalize_text(text) for text in texts}





def _get_clock_observation_targets() -> set[str]:

 global _CLOCK_OBSERVATION_TARGETS

 if _CLOCK_OBSERVATION_TARGETS is None:

  _CLOCK_OBSERVATION_TARGETS = _build_clock_observation_targets()

 return _CLOCK_OBSERVATION_TARGETS





def _format_cnpj(raw: str | None) -> str:

 digits = ''.join(filter(str.isdigit, raw or ''))

 if len(digits) != 14:

  return raw or ''

 return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"





def _format_cpf(raw: str | None) -> str:

 digits = ''.join(filter(str.isdigit, raw or ''))

 if len(digits) != 11:

  return raw or ''

 return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"









def _sanitize_mojibake(value):

 """Tenta corrigir sequências de mojibake comuns (ex: ç, ã) quando detectadas."""

 if value is None:

  return value



 if isinstance(value, str):

  try:

   # Tenta decodificar como UTF-8, se falhar, provavelmente não é mojibake

   value.encode('latin1').decode('utf-8')

   return value.encode('latin1').decode('utf-8')

  except (UnicodeEncodeError, UnicodeDecodeError):

   return value



 if isinstance(value, (list, tuple)):

  fixed = [_sanitize_mojibake(item) for item in value]

  return type(value)(fixed)



 return value



def _format_phone(raw: str | None) -> str:

 digits = ''.join(filter(str.isdigit, raw or ''))

 if digits.startswith('55') and len(digits) > 11:

  digits = digits[2:]

 if len(digits) == 11:

  return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"

 if len(digits) == 10:

  return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"

 if len(digits) == 9:

  return f"{digits[:5]}-{digits[5:]}"

 if len(digits) == 8:

  return f"{digits[:4]}-{digits[4:]}"

 return raw or ''








def _normalize_consultant_phones(values: str | Iterable[str] | None) -> list[str]:

 phones: list[str] = []

 if values is None:

  return phones

 if isinstance(values, str):

  cleaned = values.strip()

  return [cleaned] if cleaned else phones

 for entry in values or []:

  if entry is None:

   continue

  cleaned = str(entry).strip()

  if cleaned:

   phones.append(cleaned)

 return phones

















def _is_servico_ponto(proposta) -> bool:

 value = getattr(proposta, "servico_type", None)

 if value is None:

  return True

 name = getattr(value, "name", None)

 if isinstance(name, str):

  return name.upper() == "PONTO"

 text = str(value or "").upper()

 if "." in text:

  text = text.split(".", 1)[-1]

 return text == "PONTO"

# --------------------------------------------------------------------------- #

# Utilitarios de telefone / hyperlink

# --------------------------------------------------------------------------- #

def _clean_phone(raw: str) -> str:

 """Deixa so digitos."""

 return "".join(filter(str.isdigit, raw or ""))


def _normalize_photo_list(raw: object) -> list[dict[str, str]]:
 if not raw:
  return []

 def _append_item(items: list[dict[str, str]], value: object) -> None:
  if not value:
   return
  if isinstance(value, dict):
   src = value.get("src") or value.get("url") or value.get("path")
   if not src:
    return
   title = value.get("title") or ""
   items.append({"src": str(src), "title": str(title) if title else ""})
   return
  items.append({"src": str(value), "title": ""})

 items: list[dict[str, str]] = []
 if isinstance(raw, list):
  for item in raw:
   _append_item(items, item)
  return items
 if isinstance(raw, str):
  raw = raw.strip()
  if not raw:
   return []
  try:
   parsed = json.loads(raw)
  except (TypeError, ValueError):
   _append_item(items, raw)
   return items
  if isinstance(parsed, list):
   for item in parsed:
    _append_item(items, item)
   return items
  _append_item(items, parsed)
  return items
 return []





def _valid_phone(digits: str) -> bool:

 """Considera valido se possuir pelo menos 12 digitos (DDI+DDD+celular)."""

 return len(digits) >= 12












# --------------------------------------------------------------------------- #

# Tabela de equipamentos

# --------------------------------------------------------------------------- #




 # se no achou, a tabela ja ficou no fim do documento





def _fmt(num):

 return f"R$ {num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")





# --------------------------------------------------------------------------- #

# Geracao via HTML (templates em templates/propostas)

# --------------------------------------------------------------------------- #





def _is_system_row(eq_id: Any) -> bool:

 return isinstance(eq_id, str) and eq_id.startswith("system:")


def _is_one_time_acquisition_row(eq: Any) -> bool:

 return is_one_time_acquisition_item(
  getattr(eq, "name", None),
 )





def _to_file_url(path: str | None) -> str | None:

 if not path:

  return None

 abs_path = _resolve_img_path(path) or path

 if not abs_path:

  return None

 # wkhtmltopdf aceita file:// URLs; no Windows, tres barras

 abs_path = os.path.abspath(abs_path)

 if os.name == "nt":

  normalized_path = abs_path.replace("\\", "/")
  return f"file:///{normalized_path}"

 return f"file://{abs_path}"





def _observacoes_ponto_list() -> list[str]:

 return [

  "REP C - SUA UTILIZACAO",
  "Equipamentos certificados pelo MTE - Portaria 671/2021.",
  "Cada equipamento certificado pelo MTE (SREP) atende a 01 (UM) CNPJ.",
  "Uma vez cadastrado o CNPJ na memória do relógio de ponto, ele fica impossibilitado de ser reutilizado por outra empresa que não faça parte do mesmo grupo econômico, ou ainda ser devolvida à Sollus Tecnologia.",

 ]



def _observacoes_rep_programa_list() -> list[str]:

 return [

  "REP P",
  "Equipamentos certificados pelo MTE - Portaria 671/2021 - REP P.",
  "Válida para EVO 40, IDFace e IDFlex.",

 ]



def _observacoes_acesso_list() -> list[str]:

 return [

  "Os equipamentos são bivolt, mas recomenda-se uma rede de energia dedicada a cada unidade de equipamento, sendo recomendável o uso em redes de energia devidamente aterradas.",

  "Recomenda-se a adequação da estrutura física com o uso de guarda-corpos e medidas específicas dos espaços onde cada equipamento irá ser posicionado.",

  "As adequaes de estrutura espaos (estrutura de parede, sustentao, batentes etc.), infraestrutura lgica e de energia so de responsabilidade do cliente. A Sollus pode auxiliar em orientaes, aconselhamentos técnicos e indicao de melhores prticas de mercado de acordo com a experincia da empresa no setor.",

 ]





def _build_html_context(

 proposta,

 equipamentos: Iterable[Any],

 *,

 nome_colaborador: str = "",

 email_colaborador: str = "",

 proposta_cod: str = "",

 tel_raw: str | None = None,

 tel_clean: str | None = None,

 telefone_colaborador: str | Iterable[str] | None = None,

) -> dict[str, Any]:

 # Metadados basicos

 # Importa tipos de forma tardia para no exigir app durante import

 try: # lazy import para evitar dependencia forte em tempo de import

  from modules.propostas.models import ServicoType as _ServicoType, ModalidadeType as _ModalidadeType # type: ignore

 except Exception: # pragma: no cover

  _ServicoType = None # type: ignore

  _ModalidadeType = None # type: ignore



 servico_label = None

 try:

  st = getattr(proposta, "servico_type", None)

  if _ServicoType is not None and isinstance(st, _ServicoType):

   servico_label = st.label

  elif st is not None:

   # ex.: string 'PONTO'

   try:

    if _ServicoType is not None:

     servico_label = _ServicoType[str(st)].label

    else:

     servico_label = str(st)

   except Exception:

    servico_label = str(st)

 except Exception:

  servico_label = None



 modalidade_label = None
 is_locacao = False

 try:

  mt = getattr(proposta, "modalidade_type", None)

  if _ModalidadeType is not None and isinstance(mt, _ModalidadeType):

   modalidade_label = mt.label

   try:

    is_locacao = mt is getattr(_ModalidadeType, "LOCACAO", None)

   except Exception:

    is_locacao = False

  elif mt is not None:

   try:

    if _ModalidadeType is not None:

     mod_value = _ModalidadeType[str(mt)]

     modalidade_label = mod_value.label

     try:

      is_locacao = mod_value is getattr(_ModalidadeType, "LOCACAO", None)

     except Exception:

      is_locacao = False

    else:

     modalidade_label = str(mt)

   except Exception:

    modalidade_label = str(mt)

    is_locacao = str(mt).upper() == "LOCACAO"

 except Exception:

  modalidade_label = None



 data_criacao = getattr(proposta, "data_criacao", None)

 if isinstance(data_criacao, datetime):

  data_fmt = data_criacao.strftime("%d/%m/%Y")

 else:

  data_fmt = None



 # Itens formatados para o HTML
 equipment_rows = list(equipamentos or [])
 locacao_modelo_raw = (getattr(proposta, "locacao_modelo", None) or "").strip().lower()
 if locacao_modelo_raw not in {"sintetico", "analitico"}:
  locacao_modelo_raw = "sintetico"
 locacao_analitico = locacao_modelo_raw == "analitico"
 rep_mobile_valor = getattr(proposta, "rep_mobile_valor_mensal", None)
 try:
  rep_mobile_valor = float(rep_mobile_valor) if rep_mobile_valor is not None else 0.0
 except (TypeError, ValueError):
  rep_mobile_valor = 0.0
 rep_mobile_qtd = getattr(proposta, "rep_qtd_mobile", None)
 try:
  rep_mobile_qtd = int(rep_mobile_qtd) if rep_mobile_qtd is not None else None
 except (TypeError, ValueError):
  rep_mobile_qtd = None
 rep_tem_mobile = bool(
  getattr(proposta, "rep_tem_mobile", False)
  and getattr(proposta, "rep_categoria_programa", False)
 )
 if rep_tem_mobile and rep_mobile_valor:
  mobile_qtd = rep_mobile_qtd or 1
  mobile_qtd = max(1, int(mobile_qtd))
  unit_mobile = rep_mobile_valor / mobile_qtd if mobile_qtd else rep_mobile_valor
  mobile_item = SimpleNamespace(
   id="system:mobile",
   name="Mobiles",
   description="Acréscimo de mobiles",
   illustration_path=None,
   unit_price=unit_mobile,
  )
  mobile_item.quantity = mobile_qtd
  mobile_item.discount_percent = 0.0
  mobile_item.total_override = rep_mobile_valor
  mobile_item.is_mobile_addon = True
  equipment_rows.append(mobile_item)
 locacao_vigencia_override = getattr(proposta, "locacao_vigencia", None) or None
 locacao_qtd_cnpjs_override = getattr(proposta, "locacao_qtd_cnpjs", None)
 locacao_qtd_equipamentos_override = getattr(proposta, "locacao_qtd_equipamentos", None)
 try:
  locacao_qtd_cnpjs_override = int(locacao_qtd_cnpjs_override) if locacao_qtd_cnpjs_override is not None else None
 except (TypeError, ValueError):
  locacao_qtd_cnpjs_override = None
 try:
  locacao_qtd_equipamentos_override = int(locacao_qtd_equipamentos_override) if locacao_qtd_equipamentos_override is not None else None
 except (TypeError, ValueError):
  locacao_qtd_equipamentos_override = None
 eqs = []
 total_unico = 0.0
 total_mensal = 0.0
 total_system_qty = 0
 total_equipment_qty = 0
 locacao_has_acquisition = False
 first_equipment_image = None
 equipment_summaries: list[str] = []
 equipment_names: list[str] = []
 equipment_gallery: list[dict[str, str]] = []
 seen_gallery: set[tuple[str, str]] = set()
 all_images: list[str] = []
 system_descriptions: list[str] = []
 system_name: str | None = None
 system_desc: str | None = None
 system_image: str | None = None

 for eq in equipment_rows:
  pct = float(getattr(eq, "discount_percent", 0) or 0.0)
  cheio = float(getattr(eq, "unit_price", 0) or 0.0)
  qtd = int(getattr(eq, "quantity", 1) or 1)
  desc = cheio * (1 - pct / 100.0)
  override = getattr(eq, "total_override", None)
  sub = float(override) if override is not None else desc * qtd

  is_one_time_acquisition = _is_one_time_acquisition_row(eq)
  is_system = _is_system_row(getattr(eq, "id", "")) and not is_one_time_acquisition
  is_mobile_addon = bool(getattr(eq, "is_mobile_addon", False))
  is_fixo_row = bool(getattr(eq, "is_fixo", False))
  is_acquisition = is_one_time_acquisition or (bool(getattr(eq, "is_acquisition", False)) if not is_system else False)
  if is_mobile_addon:
   is_acquisition = False
  if is_locacao and is_acquisition:
   locacao_has_acquisition = True
  image_src = _to_file_url(getattr(eq, "illustration_path", None))
  if not image_src and is_system:
   fallback_path = _system_image_fallback(
    getattr(eq, "name", None) or getattr(eq, "description", None),
   )
   if fallback_path:
    image_src = _to_file_url(fallback_path)
  if image_src and image_src not in all_images:
   all_images.append(image_src)
  if is_system and image_src and system_image is None:
   system_image = image_src
  mensal_flag = is_system or (is_locacao and not is_acquisition)
  eq.is_monthly = mensal_flag
  if is_system and not is_mobile_addon:
   total_system_qty += qtd
   if system_name is None:
    system_name = getattr(eq, "name", None) or None
   if system_desc is None:
    system_desc = getattr(eq, "description", None) or getattr(eq, "name", None)
  else:
   if not (is_locacao and is_acquisition):
    total_equipment_qty += qtd
    if first_equipment_image is None and image_src:
     first_equipment_image = image_src
    label = getattr(eq, "description", None) or getattr(eq, "name", "") or "Equipamento"
    equipment_summaries.append(f"{qtd}x {label}")
    equipment_names.append(label)
  if is_system and not is_mobile_addon:
   system_label = getattr(eq, "description", None) or getattr(eq, "name", "") or "Sistema"
   if system_label:
    system_descriptions.append(system_label)
  else:
   if not (is_locacao and is_acquisition):
    name_label = getattr(eq, "name", None) or getattr(eq, "description", None) or "Equipamento"
    if is_locacao and not is_acquisition and not is_mobile_addon:
     locacao_rights = " - Com Direito a chamadas técnicas ilimitadas, reposição de peças e sistema para gerenciamento e tratamento do ponto on-line em nuvem"
     if locacao_rights not in name_label:
      name_label += locacao_rights
    key = (image_src or "", name_label)
    if key not in seen_gallery:
     seen_gallery.add(key)
     equipment_gallery.append({"image": image_src or "", "name": name_label})

  unit_display = _fmt(cheio)
  total_display = _fmt(sub)
  
  if is_system:
   if not is_fixo_row:
    unit_display = f"{unit_display} mensais"
   total_display = f"{total_display}" + ("" if is_fixo_row else " mensais")

  description_val = getattr(eq, "description", None) or getattr(eq, "name", "") or ""
  if is_locacao and not is_acquisition and not is_mobile_addon:
   locacao_rights = " - Com Direito a chamadas técnicas ilimitadas, reposição de peças e sistema para gerenciamento e tratamento do ponto on-line em nuvem"
   if locacao_rights not in description_val:
    description_val += locacao_rights

  eqs.append(
   {
    "description": description_val,
    "image": image_src,
    "quantity": qtd,
    "unit_price": unit_display,
    "total_price": total_display,
    "discount_percent": pct if pct else 0.0,
    "is_system": is_system,
    "is_acquisition": is_acquisition,
    "is_fixo": is_fixo_row,
    "include_in_total": bool(getattr(eq, "include_in_total", True)),
   }
  )

  if bool(getattr(eq, "include_in_total", True)):
   if mensal_flag:
    total_mensal += sub
   else:
    total_unico += sub

 locacao_meta: dict[str, Any] | None = None
 if is_locacao and equipment_rows and not locacao_analitico:
  acquisition_rows = [item for item in eqs if item.get("is_acquisition")]
  pessoas = getattr(proposta, "sistema_quantidade", None)
  try:
   pessoas = int(pessoas) if pessoas is not None else None
  except (TypeError, ValueError):
   pessoas = None
  cnpj_qtd = locacao_qtd_cnpjs_override
  if cnpj_qtd is None:
   cnpj_qtd = 1 if getattr(proposta, "cnpj", None) else 0
  equip_count = locacao_qtd_equipamentos_override if locacao_qtd_equipamentos_override is not None else (total_equipment_qty or total_system_qty)
  vigencia = locacao_vigencia_override or getattr(proposta, "validade", None)
  locacao_meta = {
   "pessoas": pessoas,
   "cnpjs": cnpj_qtd,
   "equipamentos": equip_count,
   "vigencia": vigencia,
   "mensal_unificado": _fmt(total_mensal) if total_mensal else None,
  }

  equip_list = ", ".join(equipment_summaries)
  if len(equipment_names) == 1:
   equip_list = equipment_names[0]
  vigencia_raw = str(vigencia).strip() if vigencia else ""
  vigencia_value = html.escape(vigencia_raw) if vigencia_raw else ""
  vigencia_has_mes = "mes" in vigencia_raw.lower()
  vigencia_label = ""
  if vigencia_value:
   vigencia_label = f"<span class=\"detail-value\">{vigencia_value}</span>"
   if not vigencia_has_mes:
    vigencia_label = f"{vigencia_label} meses"
  equip_count_label = f"<span class=\"detail-value\">{html.escape(str(equip_count or 0))}</span>"
  equip_word = "equipamento" if equip_count == 1 else "equipamentos"
  contract_bits = ["Contrato de Locação"]
  if vigencia_label:
   contract_bits.append(vigencia_label)
  contract_bits.append(f"para {equip_count_label} {equip_word}")
  contract_line = " ".join(contract_bits)
  if equip_list:
   contract_line = f"{contract_line} - {html.escape(equip_list)}"

  # Limpa prefixos redundantes como 'Contrato 24 meses...' do nome do sistema
  clean_system_name = system_name or ""
  if clean_system_name:
   clean_system_name = re.sub(
    r"^(?:contrato\s+(?:de\s+loca[çc][ãa]o\s+)?(?:\d+\s+meses\s+)?|sistema\s+)",
    "",
    clean_system_name,
    flags=re.IGNORECASE,
   ).strip()
   if not clean_system_name:
    clean_system_name = system_name

  system_desc_clean = system_desc or ""
  if system_desc_clean:
   if system_name:
    name_lower = system_name.lower().strip()
    desc_lower = system_desc_clean.lower().strip()
    if desc_lower.startswith(name_lower):
     system_desc_clean = system_desc_clean[len(system_name):].lstrip(" -:")
   if clean_system_name:
    cname_lower = clean_system_name.lower().strip()
    desc_lower = system_desc_clean.lower().strip()
    if desc_lower.startswith(cname_lower):
     system_desc_clean = system_desc_clean[len(clean_system_name):].lstrip(" -:")

   # Remove repetição de 'Contrato de locação de X meses...' no início da descrição
   system_desc_clean = re.sub(
    r"^(?:contrato\s+de\s+loca[çc][ãa]o\s+(?:de\s+\d+\s+meses\s+)?(?:renov[áa]veis\s+)?(?:para\s+)?|contrato\s+\d+\s+meses\s+para\s+)",
    "",
    system_desc_clean,
    flags=re.IGNORECASE,
   ).strip()

  system_bits = []
  if clean_system_name:
   system_bits.append(f"Sistema <span class=\"system-name\">{html.escape(clean_system_name)}</span>")
  elif system_desc_clean:
   system_bits.append("Sistema")
  if system_desc_clean:
   if system_bits and not system_desc_clean.startswith(("-", ":", ",")):
    system_bits.append(f"- {html.escape(system_desc_clean)}")
   else:
    system_bits.append(html.escape(system_desc_clean))
  system_line = " ".join(system_bits).strip()

  extras = []
  if pessoas is not None:
   extras.append(
    f"Pessoas: <span class=\"detail-value\">{html.escape(str(pessoas))}</span>"
   )
  if equip_count is not None:
   extras.append(
    f"Equipamentos: <span class=\"detail-value\">{html.escape(str(equip_count))}</span>"
   )
  if cnpj_qtd is not None:
   extras.append(
    f"CNPJs: <span class=\"detail-value\">{html.escape(str(cnpj_qtd))}</span>"
   )
  if vigencia_value:
   extras.append(f"Vigência: <span class=\"detail-value\">{vigencia_value}</span>")
  extras_line = " <span class=\"detail-sep\">|</span> ".join(extras)

  desc_parts = []
  if contract_line:
   desc_parts.append(f"<div class=\"item-desc fw-bold\">{contract_line}</div>")
  if system_line:
   desc_parts.append(f"<div class=\"item-desc\">{system_line}</div>")
  if extras_line:
   desc_parts.append(f"<div class=\"bundle-details\">{extras_line}</div>")

  description_html = "".join(desc_parts).strip()

  locacao_description_suffix = " - Com Direito a chamadas técnicas ilimitadas, reposição de peças e sistema para gerenciamento e tratamento do ponto on-line em nuvem"
  if is_locacao:
   desc_lower = description_html.lower()
   has_rights = "chamadas técnicas" in desc_lower or "reposição de peças" in desc_lower or "suporte remoto" in desc_lower
   if not has_rights:
    description_html += f"<div class=\"locacao-rights\"><small>{locacao_description_suffix}</small></div>"

  has_system = bool(system_name or system_desc or total_system_qty)
  primary_image = system_image if has_system and system_image else first_equipment_image
  if not primary_image and all_images:
   primary_image = all_images[0]

  bundle_total_label = _fmt(total_mensal)
  bundle_display = f"{bundle_total_label} mensais" if bundle_total_label else "Mensal"
  bundle_qty = int(equip_count or total_equipment_qty or 1)

  eqs = []
  if total_mensal > 0:
   eqs.append(
    {
     "description": description_html,
     "image": primary_image,
     "quantity": bundle_qty,
     "unit_price": bundle_display,
     "total_price": bundle_display,
     "discount_percent": 0.0,
     "is_system": False,
     "is_bundle": True,
    }
   )
  if acquisition_rows:
   eqs.extend(acquisition_rows)

 investimento_unico = _fmt(total_unico) if total_unico > 0 else None
 investimento_mensal = _fmt(total_mensal) if total_mensal > 0 else None

 # O investimento total para exibicao em texto simples deve ser apenas o valor unico (aquisicao)
 investimento_total = _fmt(total_unico)

 ambiente_fotos = []
 ambiente_incluir = bool(getattr(proposta, "ambiente_incluir", False))
 ambiente_raw = getattr(proposta, "ambiente_fotos", None)
 if ambiente_incluir:
  for item in _normalize_photo_list(ambiente_raw):
   src = item.get("src") if isinstance(item, dict) else None
   title = item.get("title") if isinstance(item, dict) else ""
   url = _to_file_url(src) if src else None
   if url:
    ambiente_fotos.append({"url": url, "title": title or ""})



 # WhatsApp link

 tel_raw = tel_raw if tel_raw is not None else (getattr(proposta, "telefone", "") or "")

 tel_clean = tel_clean if tel_clean is not None else _clean_phone(tel_raw)

 whatsapp_url = f"https://wa.me/{tel_clean}" if _valid_phone(tel_clean) else None

 telefone_cliente_formatado = _format_phone(tel_raw)



 # Imagens padrao (logo/assinatura) se existirem

 logo_light = _to_file_url("static/images/sollus_logo_white.png")

 logo_dark = _to_file_url("static/images/sollus_logo.png")

 logo_guess = logo_light or logo_dark

 signature_guess = _to_file_url("static/signatures/user_1.png")
 favicon_ico = _to_file_url("static/images/favicon.ico")
 favicon_png = _to_file_url("static/images/favicon.png")



 is_ponto = _is_servico_ponto(proposta)



 # Condicoes (pares rotulados), separaremos no template

 condicoes = [

  ("Condicoes de Pagamento (Equipamento)", getattr(proposta, "pagamento", None)),

  ("Prazo de Entrega", getattr(proposta, "prazo_entrega", None)),

  ("Frete", getattr(proposta, "frete", None)),

  ("Validade da Proposta", getattr(proposta, "validade", None)),

  ("Garantia de Equipamento", getattr(proposta, "garantia", None)),

  ("Garantia de Sistema", getattr(proposta, "garantia_sistema", None)),

 ]
 observacao_comercial = getattr(proposta, "observacao_comercial", None)
 if observacao_comercial:
  condicoes.append(("Observacoes complementares", observacao_comercial))



 client_company_display = getattr(proposta, "company", None) or "Empresa Teste"

 client_contact_display = getattr(proposta, "client_name", None) or "-"



 document_digits = getattr(proposta, "cnpj", None) or ""

 doc_type = (getattr(proposta, "client_document_type", None) or "").lower()

 if doc_type not in {"cpf", "cnpj"}:

  doc_type = "cnpj" if len(document_digits) == 14 else "cpf"

 if doc_type == "cpf":

  document_label = "CPF"

  client_document_value = _format_cpf(document_digits)

 else:

  document_label = "CNPJ"

  client_document_value = _format_cnpj(document_digits)



 issuer_code = getattr(proposta, "issuer_company_code", None) or DEFAULT_ISSUER_CODE

 issuer_default_meta = {
  "name": ISSUER_COMPANY_NAME,
  "cnpj": "",
  "email": ISSUER_EMAIL,
  "phone": ISSUER_PHONE,
  "phones": [],
  "site": ISSUER_WEBSITE,
  "address": ISSUER_ADDRESS,
 }

 issuer_meta_raw = _ISSUER_COMPANY_MAP.get(issuer_code, issuer_default_meta)

 issuer_meta = {key: _sanitize_mojibake(value) for key, value in issuer_meta_raw.items()}

 issuer_name = issuer_meta.get("name") or ISSUER_COMPANY_NAME

 issuer_cnpj_raw = issuer_meta.get("cnpj") or ""

 issuer_company_cnpj = _format_cnpj(issuer_cnpj_raw) if issuer_cnpj_raw else ""

 issuer_email = issuer_meta.get("email") or (email_colaborador or ISSUER_EMAIL)

 phones_raw = issuer_meta.get("phones") or []
 if isinstance(phones_raw, str):
  phones_raw = [phones_raw]
 phones_raw = [p for p in phones_raw if p]

 primary_phone_raw = issuer_meta.get("phone")
 if primary_phone_raw:
  phones_ordered = [primary_phone_raw] + [p for p in phones_raw if p != primary_phone_raw]
 else:
  phones_ordered = phones_raw[:]

 if not phones_ordered:
  phones_ordered = [issuer_meta.get("phone") or ISSUER_PHONE]

 formatted_phones = [_format_phone(phone) for phone in phones_ordered]
 issuer_phone = formatted_phones[0] if formatted_phones else _format_phone(ISSUER_PHONE)
 issuer_phone_display = " | ".join(formatted_phones)
 issuer_site = issuer_meta.get("site") or ISSUER_WEBSITE
 issuer_site_href = issuer_site
 if issuer_site and not issuer_site.startswith(("http://", "https://")):
  issuer_site_href = f"https://{issuer_site}"
 issuer_address = issuer_meta.get("address") or ISSUER_ADDRESS

 issuer_footer_lines = []
 if issuer_address:
  issuer_footer_lines.append(issuer_address)
 if issuer_phone_display:
  issuer_footer_lines.append(issuer_phone_display)
 if issuer_site:
  issuer_footer_lines.append(issuer_site)

 issuer_footer_lines = [_sanitize_mojibake(line) for line in issuer_footer_lines if line]

 cleaned_footer_lines: list[str] = []
 bullet_prefixes = ("-", "*", "\u2022", "\u00b7", "\u2013", "\u2014")
 for line in issuer_footer_lines:
  stripped = line.lstrip()
  if stripped.startswith(bullet_prefixes):
   stripped = stripped[1:].lstrip()
  cleaned_footer_lines.append(stripped)

 issuer_footer_lines = cleaned_footer_lines

 consultant_phone_values = _normalize_consultant_phones(telefone_colaborador)



 if consultant_phone_values:



  consultant_phone_display = [_format_phone(phone) for phone in consultant_phone_values]



  consultor_phone_raw = consultant_phone_values[0]



 else:



  consultant_phone_display = [issuer_phone]



  consultor_phone_raw = phones_ordered[0]



 consultor_phone = consultant_phone_display[0]



 consultor_phone_clean = _clean_phone(consultor_phone_raw or "")

 consultor_whatsapp_url = (

  f"https://wa.me/{consultor_phone_clean}"

  if consultor_phone_clean and _valid_phone(consultor_phone_clean)

  else None

 )





 client_phone_display = telefone_cliente_formatado or (tel_raw or "")

 client_whatsapp_url = whatsapp_url

 whatsapp_icon = _to_file_url("static/images/whatsapp.png")
 linkedin_icon = _to_file_url("static/images/linkedin.png")
 facebook_icon = _to_file_url("static/images/Facebook_Logo_2023.png")
 instagram_icon = _to_file_url("static/images/instagram.png")
 youtube_icon = _to_file_url("static/images/Youtube_logo.png")





 is_rep_programa = bool(getattr(proposta, "rep_categoria_programa", False)) and is_ponto
 rep_tem_mobile = bool(getattr(proposta, "rep_tem_mobile", False)) if is_rep_programa else False
 rep_qtd_mobile = getattr(proposta, "rep_qtd_mobile", None) if rep_tem_mobile else None

 if is_ponto:

  observacoes_tecnicas = _observacoes_rep_programa_list() if is_rep_programa else _observacoes_ponto_list()

 else:

  observacoes_tecnicas = _observacoes_acesso_list()

 ctx = {

  "company": client_company_display,

  "client_name": client_contact_display,

  "cnpj": client_document_value,

  "client_document_label": document_label,

  "client_document_value": client_document_value,

  "email": getattr(proposta, "email", None) or "-",

  "telefone": client_phone_display,

  "proposta_cod": proposta_cod or getattr(proposta, "filename", None) or "",

  "servico_label": servico_label,

  "modalidade_label": modalidade_label,

  "data_criacao": data_fmt,
  "validade": getattr(proposta, "validade", None),

  "equipamentos": eqs,

  "total_itens": len(eqs),

  "is_locacao": is_locacao,
  "locacao_meta": locacao_meta,
  "locacao_gallery": equipment_gallery if is_locacao and equipment_gallery else [],
  "locacao_modelo": locacao_modelo_raw,
  "locacao_analitico": locacao_analitico,
  "locacao_has_acquisition": locacao_has_acquisition,

  "investimento_unico": investimento_unico,

  "investimento_mensal": investimento_mensal,

  "investimento_total": investimento_total,

  "condicoes": condicoes,
  "ambiente_fotos": ambiente_fotos,

  "is_servico_ponto": is_ponto,

  "observacoes_tecnicas": observacoes_tecnicas,

  "is_rep_programa": is_rep_programa,
  "rep_tem_mobile": rep_tem_mobile,
  "rep_qtd_mobile": rep_qtd_mobile,

  "nome_colaborador": nome_colaborador or "",

  "email_colaborador": email_colaborador or issuer_email,

  "whatsapp_url": whatsapp_url,
  "whatsapp_icon": whatsapp_icon,
  "linkedin_icon": linkedin_icon,
  "facebook_icon": facebook_icon,
  "instagram_icon": instagram_icon,
  "youtube_icon": youtube_icon,

  "favicon_ico": favicon_ico,
  "favicon_png": favicon_png,
  "logo_image": logo_guess,

  "logo_image_light": logo_light or logo_guess,

  "logo_image_dark": logo_dark,

  "signature_image": signature_guess,

  "issuer_company": issuer_name,

  "issuer_company_cnpj": issuer_company_cnpj,

  "issuer_email": issuer_email,

  "issuer_phone": issuer_phone,

  "issuer_phone_numbers": formatted_phones,

  "issuer_phone_display": issuer_phone_display,

  "issuer_site": issuer_site,
  "issuer_site_href": issuer_site_href,

  "issuer_address": issuer_address,

  "issuer_footer_lines": issuer_footer_lines,

  "issuer_footer": " ".join(issuer_footer_lines) if issuer_footer_lines else "",

  "issuer_contact_name": nome_colaborador or ISSUER_CONTACT_NAME_DEFAULT or issuer_name,

  "issuer_company_code": issuer_code,

  "consultor_phone": consultor_phone,

  "consultor_phone_list": consultant_phone_display,
  "consultor_whatsapp_url": consultor_whatsapp_url,

  "client_phone_display": client_phone_display,

  "client_whatsapp_url": client_whatsapp_url,

 }

 return ctx





def _convert_html_to_pdf_playwright(html: str) -> bytes:
 '''Renderiza um PDF via Chromium headless com Playwright.'''
 if not _PLAYWRIGHT_AVAILABLE or sync_playwright is None:
  raise RuntimeError(
   'Playwright no esta disponivel. Instale as dependencias do projeto (pip install playwright) e execute "playwright install chromium".'
  )

 launch_args: list[str] = []
 if str(os.getenv('PLAYWRIGHT_NO_SANDBOX', '')).lower() in {'1', 'true', 'yes'}:
  launch_args.extend(['--no-sandbox', '--disable-setuid-sandbox'])

 with TemporaryDirectory() as tmp_dir:
  tmp_root = Path(tmp_dir)
  html_path = tmp_root / 'proposta.html'
  pdf_path = tmp_root / 'proposta.pdf'
  html_path.write_text(html, encoding='utf-8')

  try:
   with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=launch_args)
    try:
     page = browser.new_page()
     page.set_default_timeout(60000)
     page.goto(html_path.as_uri(), wait_until='networkidle')
     page.emulate_media(media='print')
     page.pdf(
      path=str(pdf_path),
      format='A4',
      print_background=True,
      margin={'top': '10mm', 'right': '10mm', 'bottom': '10mm', 'left': '10mm'},
     )
    finally:
     browser.close()
  except Exception as exc:
   raise RuntimeError('Falha ao gerar o PDF com Playwright.') from exc

  return pdf_path.read_bytes()


def _convert_html_to_pdf(html: str) -> bytes:
 '''Converte HTML em PDF usando Playwright/Chromium.'''
 return _convert_html_to_pdf_playwright(html)


def render_proposta_html(template_relpath: str, context: dict[str, Any]) -> str:

 """Renderiza um template Jinja2 relativo a pasta templates/ usando o app atual."""

 env = current_app.jinja_env # exige app context

 tpl = env.get_template(template_relpath)

 return tpl.render(**context)





def render_proposta_html_pdf(template_relpath: str, context: dict[str, Any]) -> bytes:

 html = render_proposta_html(template_relpath, context)

 return _convert_html_to_pdf(html)







