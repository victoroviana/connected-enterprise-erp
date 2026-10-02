"""
Script de Ingestão e Migração de Dados do RD Station CRM & Marketing para o Sollus CRM.

Uso:
    python scripts/import_rd_crm_to_sollus.py [--recreate] [--skip-leads]
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime

# Garante que o diretório raiz esteja no sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from platform_app import create_app
from extensions import db
from modules.propostas.models import User
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmInteracao,
    CrmLeadMarketing
)

DATA_DIR = os.path.join(BASE_DIR, "data", "rd_station")
METADATA_PATH = os.path.join(DATA_DIR, "rd_crm_metadata.json")
ORGS_PATH = os.path.join(DATA_DIR, "rd_crm_organizations.jsonl")
CONTACTS_PATH = os.path.join(DATA_DIR, "rd_crm_contacts.jsonl")
DEALS_PATH = os.path.join(DATA_DIR, "rd_crm_deals.jsonl")
LEADS_CSV_PATH = os.path.join(DATA_DIR, "rd-sollus-tecnologia-leads-todos-os-contatos-da-base-de-leads.csv")


def parse_iso_datetime(dt_str):
    if not dt_str:
        return None
    try:
        # Truncate timezone offset or parse
        clean = dt_str.split("+")[0].split(".")[0].replace("Z", "")
        return datetime.fromisoformat(clean)
    except Exception:
        return None


def detect_filial(text):
    if not text:
        return None
    t = text.upper()
    if "TECHNOSOLLUS" in t or "RJ" in t or "RIO DE JANEIRO" in t:
        return "RJ"
    if "SP" in t or "SAO PAULO" in t or "SÃO PAULO" in t:
        return "SP"
    if "PR" in t or "PARANA" in t or "PARANÁ" in t:
        return "PR"
    if "ES" in t or "ESPIRITO SANTO" in t or "ESPÍRITO SANTO" in t:
        return "ES"
    if "SANTOS" in t:
        return "SANTOS"
    return None


def import_metadata():
    print("[INFO] Importando Funis e Etapas de rd_crm_metadata.json...")
    if not os.path.exists(METADATA_PATH):
        print(f"[ERRO] Arquivo de metadados nao encontrado: {METADATA_PATH}")
        return {}

    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        meta = json.load(f)

    stage_to_funil = {}
    pipelines = meta.get("deal_pipelines", [])

    for p in pipelines:
        p_id = p.get("id")
        p_name = p.get("name", "Funil")
        p_order = p.get("order", 1)

        slug = "padrao"
        tipo = "padrao"
        name_upper = p_name.upper()
        if "PONTO" in name_upper:
            slug = "funil_ponto"
            tipo = "ponto"
        elif "ACESSO" in name_upper:
            slug = "funil_acesso"
            tipo = "acesso"
        elif "ASSIST" in name_upper:
            slug = "assistencia_tecnica"
            tipo = "assistencia"

        funil = CrmFunil.query.get(p_id)
        if not funil:
            funil = CrmFunil(id=p_id, nome=p_name, slug=slug, tipo=tipo, ordem=p_order, ativo=True)
            db.session.add(funil)
        else:
            funil.nome = p_name
            funil.slug = slug
            funil.tipo = tipo
            funil.ordem = p_order

        # Importar etapas do funil
        for stage in p.get("deal_stages", []):
            s_id = stage.get("id")
            s_name = stage.get("name", "Etapa")
            s_order = stage.get("order", 1)
            stage_to_funil[s_id] = p_id

            s_tipo = "normal"
            s_upper = s_name.upper()
            if "VENDIDO" in s_upper or "GANH" in s_upper:
                s_tipo = "venda"
            elif "PERDIDO" in s_upper:
                s_tipo = "perda"

            etapa = CrmEtapa.query.get(s_id)
            if not etapa:
                etapa = CrmEtapa(id=s_id, funil_id=p_id, nome=s_name, ordem=s_order, tipo=s_tipo)
                db.session.add(etapa)
            else:
                etapa.nome = s_name
                etapa.ordem = s_order
                etapa.tipo = s_tipo

    db.session.commit()
    print(f"[OK] {len(pipelines)} funis e {len(stage_to_funil)} etapas importados/atualizados.")
    return stage_to_funil


def import_organizations():
    print("[INFO] Importando Empresas de rd_crm_organizations.jsonl...")
    if not os.path.exists(ORGS_PATH):
        print(f"[ERRO] Arquivo de organizacoes nao encontrado: {ORGS_PATH}")
        return set()

    existing_ids = set(r[0] for r in db.session.query(CrmEmpresa.id).all())
    orgs_to_add = []
    count = 0

    with open(ORGS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            org_id = item.get("id")
            if not org_id:
                continue

            if org_id in existing_ids:
                continue

            # Extrair contatos e dados da empresa
            contacts = item.get("contacts") or []
            first_c = contacts[0] if contacts else {}
            emails = first_c.get("emails") or []
            phones = first_c.get("phones") or []
            
            email = emails[0].get("email") if emails else None
            phone = phones[0].get("phone") if phones else None

            # CNPJ em custom fields
            cnpj = None
            for cf in item.get("custom_fields", []):
                label = (cf.get("custom_field") or {}).get("label", "").upper()
                if "CNPJ" in label:
                    cnpj = cf.get("value")
                    break

            segments = item.get("organization_segments") or []
            segmento = segments[0].get("name") if segments else None

            emp = CrmEmpresa(
                id=org_id,
                nome=item.get("name") or "Empresa Sem Nome",
                cnpj=cnpj,
                segmento=segmento,
                telefone=phone,
                email=email,
                created_at=parse_iso_datetime(item.get("created_at")) or datetime.utcnow()
            )
            orgs_to_add.append(emp)
            existing_ids.add(org_id)
            count += 1

            if len(orgs_to_add) >= 1000:
                db.session.bulk_save_objects(orgs_to_add)
                db.session.commit()
                orgs_to_add = []
                print(f"  -> Inseridas {count} empresas...")

    if orgs_to_add:
        db.session.bulk_save_objects(orgs_to_add)
        db.session.commit()

    print(f"[OK] Total de {count} novas empresas importadas.")
    return existing_ids


def import_contacts(org_ids_set):
    print("[INFO] Importando Contatos de rd_crm_contacts.jsonl...")
    if not os.path.exists(CONTACTS_PATH):
        print(f"[ERRO] Arquivo de contatos nao encontrado: {CONTACTS_PATH}")
        return set()

    existing_ids = set(r[0] for r in db.session.query(CrmContato.id).all())
    contacts_to_add = []
    count = 0

    with open(CONTACTS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            c_id = item.get("id")
            if not c_id or c_id in existing_ids:
                continue

            emails = item.get("emails") or []
            phones = item.get("phones") or []
            email = emails[0].get("email") if emails else None
            
            phone = None
            cell = None
            for p in phones:
                num = p.get("phone")
                if not num:
                    continue
                if p.get("whatsapp") or not cell:
                    cell = num
                if not phone:
                    phone = num

            org_id = item.get("organization_id")
            if org_id and org_id not in org_ids_set:
                org_id = None

            ct = CrmContato(
                id=c_id,
                empresa_id=org_id,
                nome=item.get("name") or "Contato Sem Nome",
                cargo=item.get("title"),
                email=email,
                telefone=phone,
                celular=cell,
                created_at=parse_iso_datetime(item.get("created_at")) or datetime.utcnow()
            )
            contacts_to_add.append(ct)
            existing_ids.add(c_id)
            count += 1

            if len(contacts_to_add) >= 1000:
                db.session.bulk_save_objects(contacts_to_add)
                db.session.commit()
                contacts_to_add = []
                print(f"  -> Inseridos {count} contatos...")

    if contacts_to_add:
        db.session.bulk_save_objects(contacts_to_add)
        db.session.commit()

    print(f"[OK] Total de {count} novos contatos importados.")
    return existing_ids


def import_deals(stage_to_funil, org_ids_set, contact_ids_set):
    print("[INFO] Importando Oportunidades/Negociacoes de rd_crm_deals.jsonl...")
    if not os.path.exists(DEALS_PATH):
        print(f"[ERRO] Arquivo de deals nao encontrado: {DEALS_PATH}")
        return

    # Mapear usuários cadastrados no Sollus Connected por e-mail e nome
    users = User.query.all()
    user_by_email = {u.email.lower(): u.id for u in users if u.email}
    user_by_name = {(u.nome_completo or u.usuario).lower(): u.id for u in users if (u.nome_completo or u.usuario)}

    existing_deal_ids = set(r[0] for r in db.session.query(CrmNegociacao.id).all())
    deals_to_add = []
    count = 0

    # Fallback para primeiro funil e etapa
    default_funil = CrmFunil.query.first()
    default_funil_id = default_funil.id if default_funil else "5f7caf407f2455001c2530ba"
    default_etapa = CrmEtapa.query.filter_by(funil_id=default_funil_id).first()
    default_etapa_id = default_etapa.id if default_etapa else "5f7caf407f2455001c2530bb"

    with open(DEALS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            deal_id = item.get("id")
            if not deal_id or deal_id in existing_deal_ids:
                continue

            stage_info = item.get("deal_stage") or {}
            etapa_id = stage_info.get("id")
            funil_id = stage_to_funil.get(etapa_id)

            if not funil_id:
                funil_id = default_funil_id
            if not etapa_id:
                etapa_id = default_etapa_id

            # Vínculo com Empresa e Contato
            contacts = item.get("contacts") or []
            contact_id = contacts[0].get("id") if contacts else None
            if contact_id and contact_id not in contact_ids_set:
                contact_id = None

            org_id = item.get("organization_id")
            if org_id and org_id not in org_ids_set:
                org_id = None

            # Vendedor / Consultor
            user_obj = item.get("user") or {}
            user_name = user_obj.get("name")
            user_email = user_obj.get("email", "").lower()
            matched_user_id = user_by_email.get(user_email)
            if not matched_user_id and user_name:
                matched_user_id = user_by_name.get(user_name.lower())

            # Status
            win = item.get("win")
            if win is True:
                status = "ganho"
            elif win is False:
                status = "perdido"
            else:
                status = "aberto"

            # Próxima Tarefa
            next_t = item.get("next_task") or {}
            prox_t_id = next_t.get("id")
            prox_t_titulo = next_t.get("subject")
            prox_t_data = parse_iso_datetime(next_t.get("date"))
            prox_t_tipo = next_t.get("type") or "whatsapp"

            # Campanha e Filial
            campanha_nome = (item.get("campaign") or {}).get("name")
            deal_source_nome = (item.get("deal_source") or {}).get("name")
            filial = detect_filial(campanha_nome) or detect_filial(item.get("name"))

            deal = CrmNegociacao(
                id=deal_id,
                nome=item.get("name") or "Negociação Sem Nome",
                funil_id=funil_id,
                etapa_id=etapa_id,
                empresa_id=org_id,
                contato_id=contact_id,
                user_id=matched_user_id,
                user_name=user_name,
                valor_unico=float(item.get("amount_unique") or 0.0),
                valor_mensal=float(item.get("amount_montly") or 0.0),
                valor_total=float(item.get("amount_total") or 0.0),
                status=status,
                motivo_perda=str(item.get("deal_lost_reason_id") or ""),
                origem=deal_source_nome,
                campanha=campanha_nome,
                filial=filial,
                proxima_tarefa_id=prox_t_id,
                proxima_tarefa_titulo=prox_t_titulo,
                proxima_tarefa_data=prox_t_data,
                proxima_tarefa_tipo=prox_t_tipo,
                created_at=parse_iso_datetime(item.get("created_at")) or datetime.utcnow(),
                updated_at=parse_iso_datetime(item.get("updated_at")) or datetime.utcnow(),
                closed_at=parse_iso_datetime(item.get("closed_at"))
            )
            deals_to_add.append(deal)
            existing_deal_ids.add(deal_id)
            count += 1

            if len(deals_to_add) >= 1000:
                db.session.bulk_save_objects(deals_to_add)
                db.session.commit()
                deals_to_add = []
                print(f"  -> Inseridas {count} negociações...")

    if deals_to_add:
        db.session.bulk_save_objects(deals_to_add)
        db.session.commit()

    print(f"[OK] Total de {count} novas negociacoes importadas.")


def import_marketing_leads():
    print("[INFO] Importando Leads de Marketing de rd-sollus-tecnologia-leads-todos-os-contatos-da-base-de-leads.csv...")
    if not os.path.exists(LEADS_CSV_PATH):
        print(f"[ERRO] Arquivo de leads CSV nao encontrado: {LEADS_CSV_PATH}")
        return

    existing_emails = set(r[0] for r in db.session.query(CrmLeadMarketing.email).all() if r[0])
    leads_to_add = []
    count = 0

    # Abre com encoding utf-16 (export padrao do RD Station)
    with open(LEADS_CSV_PATH, "r", encoding="utf-16", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            email = (row.get("Email") or "").strip()
            if not email or email in existing_emails:
                continue

            nome = (row.get("Nome") or "").strip()
            telefone = (row.get("Telefone") or "").strip()
            celular = (row.get("Celular") or "").strip()
            cargo = (row.get("Cargo") or "").strip()
            empresa = (row.get("Empresa") or "").strip()
            cidade = (row.get("Cidade") or "").strip()
            estado = (row.get("Estado") or "").strip()

            # Lead Scoring
            perfil = (row.get("Lead Scoring - Perfil") or "").strip().upper()
            if perfil not in ("A", "B", "C", "D"):
                perfil = None

            interesse_raw = (row.get("Lead Scoring - Interesse") or "").strip()
            try:
                interesse = int(float(interesse_raw)) if interesse_raw else 0
            except ValueError:
                interesse = 0

            tags = (row.get("Tags") or "").strip()
            evento = (
                (row.get("Origem da última conversão") or row.get("Origem da primeira conversão") or row.get("Qual formulário de origem?") or "").strip()
            )

            dt_conv_str = row.get("Data da última conversão") or row.get("Data da primeira conversão")
            dt_conv = None
            if dt_conv_str:
                try:
                    dt_conv = datetime.strptime(dt_conv_str.strip().split(" -")[0], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            lead = CrmLeadMarketing(
                nome=nome,
                email=email,
                empresa=empresa,
                cargo=cargo,
                telefone=telefone,
                celular=celular,
                cidade=cidade,
                estado=estado,
                lead_scoring_perfil=perfil,
                lead_scoring_interesse=interesse,
                tags=tags,
                evento_conversao=evento,
                data_conversao=dt_conv,
                created_at=dt_conv or datetime.utcnow()
            )
            leads_to_add.append(lead)
            existing_emails.add(email)
            count += 1

            if len(leads_to_add) >= 1000:
                db.session.bulk_save_objects(leads_to_add)
                db.session.commit()
                leads_to_add = []
                print(f"  -> Inseridos {count} leads de marketing...")

    if leads_to_add:
        db.session.bulk_save_objects(leads_to_add)
        db.session.commit()

    print(f"[OK] Total de {count} novos leads de marketing importados.")


def main():
    parser = argparse.ArgumentParser(description="Migracao RD Station CRM -> Sollus CRM")
    parser.add_argument("--recreate", action="store_true", help="Recria todas as tabelas crm_*")
    parser.add_argument("--skip-leads", action="store_true", help="Pula importacao de leads de marketing")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        print("=== INICIANDO MIGRACAO DO RD STATION PARA O SOLLUS CRM ===")
        if args.recreate:
            print("[AVISO] Recriando tabelas do CRM...")
            CrmInteracao.__table__.drop(db.engine, checkfirst=True)
            CrmTarefa.__table__.drop(db.engine, checkfirst=True)
            CrmNegociacao.__table__.drop(db.engine, checkfirst=True)
            CrmContato.__table__.drop(db.engine, checkfirst=True)
            CrmEmpresa.__table__.drop(db.engine, checkfirst=True)
            CrmEtapa.__table__.drop(db.engine, checkfirst=True)
            CrmFunil.__table__.drop(db.engine, checkfirst=True)
            CrmLeadMarketing.__table__.drop(db.engine, checkfirst=True)

        db.create_all()
        print("[OK] Tabelas do CRM verificadas/criadas no banco de dados.")

        # 1. Metadados (Funis e Etapas)
        stage_to_funil = import_metadata()

        # 2. Empresas
        org_ids_set = import_organizations()

        # 3. Contatos
        contact_ids_set = import_contacts(org_ids_set)

        # 4. Oportunidades / Negociações
        import_deals(stage_to_funil, org_ids_set, contact_ids_set)

        # 5. Leads de Marketing
        if not args.skip_leads:
            import_marketing_leads()

        print("=== MIGRACAO CONCLUIDA COM SUCESSO! ===")


if __name__ == "__main__":
    main()
