"""
Sincronização em tempo real das negociações do RD Station CRM com o Sollus Connected:
1. Puxa as negociações abertas (win=null, 45 páginas) e recentes da API v1 do RD Station CRM.
2. Atrela os consultores corretos (Luciana 5010, Ana Clara 5004, Gilson 5008, Hizael 5009, Ricardo 5006, etc.).
3. Garante a criação de Empresas e Contatos que foram cadastrados recentemente.
4. Preserva os timestamps exatos de created_at e updated_at do RD Station para manter a ordenação cronológica real.
5. Restaura as datas originais dos negócios fechados a partir de rd_crm_deals.jsonl.
"""
import os
import sys
import json
import time
import urllib.request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

if os.path.exists('/home/sollus/sollus_connected'):
    sys.path.insert(0, '/home/sollus/sollus_connected')
    os.chdir('/home/sollus/sollus_connected')

from app import app
from extensions import db
from modules.crm.models import CrmNegociacao, CrmFunil, CrmEtapa, CrmEmpresa, CrmContato
from modules.propostas.models import User

TOKEN = '61d47c806a5536001171124a'
BASE_URL = 'https://crm.rdstation.com/api/v1'

RD_USER_MAP = {
    "60773fcd2d0ed30018c20732": {"user_id": 5010, "user_name": "Luciana Claudino"},
    "6070a7648d7c38000c3df307": {"user_id": 5004, "user_name": "Ana Clara Barbosa"},
    "684acee2d31c87001e310f43": {"user_id": 5008, "user_name": "Gilson Freitas"},
    "670d39354328f80020733950": {"user_id": 5009, "user_name": "Hizael Ferreira"},
    "6070c28fb0dc54001ef5e90d": {"user_id": 5006, "user_name": "Ricardo Simões"},
    "64e7992995d79c002a37bec3": {"user_id": None, "user_name": "Gabriel Gralak"},
    "615de539a151ba000d6a1ebe": {"user_id": None, "user_name": "Adriele"},
    "666848f977a16f00146c88b3": {"user_id": 5005, "user_name": "Cristiano Silva"},
    "67486e6bf6dc26001ce099f7": {"user_id": None, "user_name": "Tecnica Sollus"},
}

def parse_iso_datetime(dt_str):
    if not dt_str:
        return None
    try:
        clean = dt_str.replace("Z", "")
        if "+" in clean:
            clean = clean.split("+")[0]
        elif "-" in clean and len(clean.split("-")) > 3:
            parts = clean.split("-")
            clean = "-".join(parts[:3])
        if "." in clean:
            return datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S.%f")
        return datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None

def detect_filial(text):
    if not text:
        return "RJ"
    t = text.upper()
    if "TECHNOSOLLUS ES" in t or " ES" in t or "- ES" in t:
        return "ES"
    if "SOLLUS SP" in t or " SP" in t or "- SP" in t or "SÃO PAULO" in t:
        return "SP"
    if "SOLLUS PR" in t or " PR" in t or "- PR" in t or "PARANÁ" in t:
        return "PR"
    if "SANTOS" in t:
        return "SANTOS"
    return "RJ"

def get_user_info(user_obj):
    if not user_obj:
        return None, "Sem Responsável"
    uid = user_obj.get("id") or user_obj.get("_id")
    if uid in RD_USER_MAP:
        return RD_USER_MAP[uid]["user_id"], RD_USER_MAP[uid]["user_name"]
    name = (user_obj.get("name") or "").strip()
    email = (user_obj.get("email") or "").strip().lower()
    if "luciana" in name.lower() or "comercial3" in email:
        return 5010, "Luciana Claudino"
    if "ana clara" in name.lower() or "clara" in name.lower() or "comercial2" in email:
        return 5004, "Ana Clara Barbosa"
    if "gilson" in name.lower() or "comercial1" in email:
        return 5008, "Gilson Freitas"
    if "hizael" in name.lower() or "comercial5" in email:
        return 5009, "Hizael Ferreira"
    if "ricardo" in name.lower() or "comercial@" in email:
        return 5006, "Ricardo Simões"
    if "gralak" in name.lower() or "comercial4" in email:
        return None, "Gabriel Gralak"
    if "adriele" in name.lower() or "comercial6" in email:
        return None, "Adriele"
    if "tecnica" in name.lower():
        return None, "Tecnica Sollus"
    return None, name or "Sem Responsável"

def fetch_rd_page(endpoint_params):
    url = f"{BASE_URL}/deals?token={TOKEN}&{endpoint_params}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data.get('deals', [])
        except Exception as e:
            time.sleep(1.5 * (attempt + 1))
    return []

def run_sync():
    with app.app_context():
        print("=== 1. MAPEAMENTO DE PIPELINES E ETAPAS DO RD STATION CRM ===")
        req_pipes = urllib.request.Request(f"{BASE_URL}/deal_pipelines?token={TOKEN}", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_pipes) as resp:
            pipelines = json.loads(resp.read().decode('utf-8'))
        
        stage_to_funil = {}
        for p in pipelines:
            pid = p.get("id")
            for s in p.get("deal_stages", []):
                stage_to_funil[s.get("id")] = pid
        print(f"Mapeadas {len(stage_to_funil)} etapas em {len(pipelines)} funis.")

        print("\n=== 2. BAIXANDO NEGOCIAÇÕES ABERTAS DIRETAMENTE DO RD STATION CRM ===")
        # Total de 45 páginas para ~4.445 abertas
        open_pages_params = [f"win=null&page={p}&limit=100" for p in range(1, 46)]
        
        print("Executando download paralelo das 45 páginas de negociações abertas...")
        t0 = time.time()
        open_deals = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(fetch_rd_page, open_pages_params)
            for page_deals in results:
                open_deals.extend(page_deals)
        print(f"Total de negociações abertas baixadas: {len(open_deals)} em {time.time() - t0:.1f}s")

        print("\n=== 3. BAIXANDO NEGOCIAÇÕES RECENTEMENTE ATUALIZADAS/FECHADAS DO RD STATION ===")
        recent_pages_params = [f"order=updated_at&direction=desc&page={p}&limit=100" for p in range(1, 16)]
        recent_deals = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(fetch_rd_page, recent_pages_params)
            for page_deals in results:
                recent_deals.extend(page_deals)
        print(f"Total de negociações recentes baixadas: {len(recent_deals)}")

        # Unificar por ID (priorizando o mais recente)
        all_deals_map = {}
        for d in open_deals:
            did = d.get("id") or d.get("_id")
            if did:
                all_deals_map[did] = d
        for d in recent_deals:
            did = d.get("id") or d.get("_id")
            if did:
                all_deals_map[did] = d

        print(f"\nTotal único de negociações ativas/recentes a sincronizar: {len(all_deals_map)}")

        print("\n=== 4. PROCESSANDO EMPRESAS, CONTATOS E NEGOCIAÇÕES NO BANCO DE DADOS ===")
        existing_org_ids = set(r[0] for r in db.session.query(CrmEmpresa.id).all())
        existing_contact_ids = set(r[0] for r in db.session.query(CrmContato.id).all())
        existing_deal_ids = set(r[0] for r in db.session.query(CrmNegociacao.id).all())

        new_orgs = []
        new_contacts = []
        
        for did, d in all_deals_map.items():
            # Empresa
            org = d.get("organization")
            if org:
                oid = org.get("id") or org.get("_id")
                if oid and oid not in existing_org_ids:
                    empresa = CrmEmpresa(
                        id=oid,
                        nome=org.get("name") or "Empresa sem nome",
                        cnpj=org.get("cnpj"),
                        created_at=parse_iso_datetime(org.get("created_at")) or datetime.utcnow(),
                        updated_at=parse_iso_datetime(org.get("updated_at")) or datetime.utcnow()
                    )
                    new_orgs.append(empresa)
                    existing_org_ids.add(oid)

            # Contato
            contacts = d.get("contacts") or []
            if contacts:
                c0 = contacts[0]
                cid = c0.get("id") or c0.get("_id")
                if cid and cid not in existing_contact_ids:
                    emails = c0.get("emails") or []
                    phones = c0.get("phones") or []
                    email_str = emails[0].get("email") if emails else None
                    phone_str = phones[0].get("phone") if phones else None
                    oid = (d.get("organization") or {}).get("id") or (d.get("organization") or {}).get("_id")
                    contato = CrmContato(
                        id=cid,
                        empresa_id=oid if oid in existing_org_ids else None,
                        nome=c0.get("name") or "Contato sem nome",
                        email=email_str,
                        telefone=phone_str,
                        celular=phone_str,
                        cargo=c0.get("title")
                    )
                    new_contacts.append(contato)
                    existing_contact_ids.add(cid)

        if new_orgs:
            db.session.bulk_save_objects(new_orgs)
            db.session.commit()
            print(f"  -> Inseridas {len(new_orgs)} novas Empresas.")

        if new_contacts:
            db.session.bulk_save_objects(new_contacts)
            db.session.commit()
            print(f"  -> Inseridos {len(new_contacts)} novos Contatos.")

        print("Sincronizando registros na tabela crm_negociacoes...")
        inserted_count = 0
        updated_count = 0

        # Para performance máxima, fazemos upsert direto via raw SQL ou objetos
        for did, item in all_deals_map.items():
            stage_info = item.get("deal_stage") or {}
            etapa_id = stage_info.get("id") or stage_info.get("_id")
            funil_id = stage_to_funil.get(etapa_id) or "5f7caf407f2455001c2530ba"

            # Vínculos
            contacts = item.get("contacts") or []
            contact_id = (contacts[0].get("id") or contacts[0].get("_id")) if contacts else None
            if contact_id not in existing_contact_ids:
                contact_id = None

            org_id = (item.get("organization") or {}).get("id") or (item.get("organization") or {}).get("_id")
            if org_id not in existing_org_ids:
                org_id = None

            # Usuário / Consultor correto
            user_obj = item.get("user") or {}
            user_id, user_name = get_user_info(user_obj)

            # Status
            win = item.get("win")
            if win is True:
                status = "ganho"
            elif win is False:
                status = "perdido"
            else:
                status = "aberto"

            # Campanha e Filial
            campanha_nome = (item.get("campaign") or {}).get("name")
            deal_source_nome = (item.get("deal_source") or {}).get("name")
            filial = detect_filial(campanha_nome) or detect_filial(item.get("name"))

            # Próxima Tarefa
            next_t = item.get("next_task") or {}
            prox_t_id = next_t.get("id") or next_t.get("_id")
            prox_t_titulo = next_t.get("subject")
            prox_t_data = parse_iso_datetime(next_t.get("date"))
            prox_t_tipo = next_t.get("type") or "whatsapp"

            created_at = parse_iso_datetime(item.get("created_at")) or datetime.utcnow()
            updated_at = parse_iso_datetime(item.get("updated_at")) or datetime.utcnow()
            closed_at = parse_iso_datetime(item.get("closed_at"))

            # Se for da Tecnica Sollus, manter no funil de Assistência Técnica
            if user_name == "Tecnica Sollus":
                funil_id = "67126b4e220f7e0028e35346"

            if did in existing_deal_ids:
                # Atualiza com SQL raw para não disparar onupdate datetime.utcnow!
                db.session.execute(
                    db.text("""
                        UPDATE crm_negociacoes
                        SET nome = :nome, funil_id = :funil_id, etapa_id = :etapa_id,
                            empresa_id = :empresa_id, contato_id = :contato_id,
                            user_id = :user_id, user_name = :user_name,
                            valor_unico = :valor_unico, valor_mensal = :valor_mensal, valor_total = :valor_total,
                            status = :status, origem = :origem, campanha = :campanha, filial = :filial,
                            proxima_tarefa_id = :prox_id, proxima_tarefa_titulo = :prox_titulo,
                            proxima_tarefa_data = :prox_data, proxima_tarefa_tipo = :prox_tipo,
                            created_at = :created_at, updated_at = :updated_at, closed_at = :closed_at
                        WHERE id = :id
                    """),
                    {
                        "id": did, "nome": item.get("name") or "Negociação Sem Nome",
                        "funil_id": funil_id, "etapa_id": etapa_id,
                        "empresa_id": org_id, "contato_id": contact_id,
                        "user_id": user_id, "user_name": user_name,
                        "valor_unico": float(item.get("amount_unique") or 0.0),
                        "valor_mensal": float(item.get("amount_montly") or 0.0),
                        "valor_total": float(item.get("amount_total") or 0.0),
                        "status": status, "origem": deal_source_nome, "campanha": campanha_nome, "filial": filial,
                        "prox_id": prox_t_id, "prox_titulo": prox_t_titulo, "prox_data": prox_t_data, "prox_tipo": prox_t_tipo,
                        "created_at": created_at, "updated_at": updated_at, "closed_at": closed_at
                    }
                )
                updated_count += 1
            else:
                # Insere nova negociação
                deal = CrmNegociacao(
                    id=did,
                    nome=item.get("name") or "Negociação Sem Nome",
                    funil_id=funil_id,
                    etapa_id=etapa_id,
                    empresa_id=org_id,
                    contato_id=contact_id,
                    user_id=user_id,
                    user_name=user_name,
                    valor_unico=float(item.get("amount_unique") or 0.0),
                    valor_mensal=float(item.get("amount_montly") or 0.0),
                    valor_total=float(item.get("amount_total") or 0.0),
                    status=status,
                    origem=deal_source_nome,
                    campanha=campanha_nome,
                    filial=filial,
                    proxima_tarefa_id=prox_t_id,
                    proxima_tarefa_titulo=prox_t_titulo,
                    proxima_tarefa_data=prox_t_data,
                    proxima_tarefa_tipo=prox_t_tipo,
                    created_at=created_at,
                    updated_at=updated_at,
                    closed_at=closed_at
                )
                db.session.add(deal)
                existing_deal_ids.add(did)
                inserted_count += 1

            if (inserted_count + updated_count) % 500 == 0:
                db.session.commit()
                print(f"  -> Processados {inserted_count + updated_count} registros...")

        db.session.commit()
        print(f"\n>>> SUCESSO: {inserted_count} novas negociações inseridas, {updated_count} atualizadas com dados reais do RD!")

        print("\n=== 5. RESTAURANDO TIMESTAMPS ORIGINAIS DE NEGOCIAÇÕES HISTÓRICAS ===")
        deals_jsonl = "data/rd_station/rd_crm_deals.jsonl"
        if os.path.exists(deals_jsonl):
            print(f"Lendo {deals_jsonl} para recuperar created_at/updated_at históricos...")
            batch_updates = []
            with open(deals_jsonl, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip(): continue
                    it = json.loads(line)
                    jid = it.get("id") or it.get("_id")
                    if jid not in all_deals_map: # Só os que não acabamos de atualizar via API
                        u_obj = it.get("user") or {}
                        uid, uname = get_user_info(u_obj)
                        c_at = parse_iso_datetime(it.get("created_at"))
                        u_at = parse_iso_datetime(it.get("updated_at"))
                        if jid and c_at and u_at:
                            batch_updates.append({
                                "id": jid,
                                "user_id": uid,
                                "user_name": uname,
                                "c_at": c_at,
                                "u_at": u_at
                            })
                            if len(batch_updates) >= 1000:
                                db.session.execute(
                                    db.text("""
                                        UPDATE crm_negociacoes 
                                        SET user_id = :user_id, user_name = :user_name,
                                            created_at = :c_at, updated_at = :u_at
                                        WHERE id = :id
                                    """),
                                    batch_updates
                                )
                                db.session.commit()
                                batch_updates = []
            if batch_updates:
                db.session.execute(
                    db.text("""
                        UPDATE crm_negociacoes 
                        SET user_id = :user_id, user_name = :user_name,
                            created_at = :c_at, updated_at = :u_at
                        WHERE id = :id
                    """),
                    batch_updates
                )
                db.session.commit()
            print(">>> Timestamps históricos restaurados com sucesso!")

        print("\n=== 6. CONFERÊNCIA FINAL DOS DADOS EM PRODUÇÃO ===")
        print(f"Total de negociações abertas em crm_negociacoes: {CrmNegociacao.query.filter_by(status='aberto').count()}")
        commercial_ids = [5004, 5006, 5008, 5009, 5010, 6847]
        for cid in commercial_ids:
            u = User.query.get(cid)
            abertas = CrmNegociacao.query.filter_by(user_id=cid, status='aberto').count()
            total = CrmNegociacao.query.filter_by(user_id=cid).count()
            print(f"Consultor: {u.nome_completo if u else 'Desconhecido'} (ID {cid}) -> Abertas: {abertas} | Total: {total}")

        # Gabriel Gralak e Adriele
        gg_open = CrmNegociacao.query.filter_by(user_name='Gabriel Gralak', status='aberto').count()
        ad_open = CrmNegociacao.query.filter_by(user_name='Adriele', status='aberto').count()
        print(f"Gabriel Gralak (nome original RD) -> Abertas: {gg_open}")
        print(f"Adriele (nome original RD) -> Abertas: {ad_open}")

if __name__ == "__main__":
    run_sync()
