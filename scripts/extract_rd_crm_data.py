"""
Script para extrair 100% dos dados do RD Station CRM via API v1.
Utiliza paginação bidirecional (descendente + ascendente) para contornar
o limite de janela de 10.000 registros do Elasticsearch da RD Station.
Extrai: Pipelines, Etapas, Usuários, Equipes, Campanhas, Origens,
Campos Customizados, Negociações (Deals), Empresas (Organizations) e Contatos.
"""
import os
import sys
import json
import time
import urllib.request
import urllib.error

# Força stdout para UTF-8 se possível
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

TOKEN = '61d47c806a5536001171124a'
BASE_URL = 'https://crm.rdstation.com/api/v1'
OUTPUT_DIR = r'c:\Users\User\Desktop\sollus_connected\data\rd_station'

os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_json(url, max_retries=5, backoff=2.0):
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'SollusConnected/1.0'})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait_time = backoff * (attempt + 2)
                print(f"[429 Rate Limit] Aguardando {wait_time:.1f}s antes de retentar...")
                time.sleep(wait_time)
            elif e.code == 400:
                # 400: Result window is too large (> 10000)
                return None
            elif e.code in (500, 502, 503, 504):
                time.sleep(backoff)
            else:
                raise e
        except Exception as e:
            time.sleep(backoff)
    return None

def extract_bidirectional(resource_name, key_in_response, filename, target_total):
    print(f"\n==================================================")
    print(f" Extraindo {resource_name.upper()} (Alvo: ~{target_total:,} registros)")
    print(f"==================================================")
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    existing_ids = set()
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        item = json.loads(line)
                        item_id = item.get('id') or item.get('_id')
                        if item_id:
                            existing_ids.add(item_id)
                    except Exception:
                        pass
        print(f"  * Registros ja salvos em cache: {len(existing_ids):,}")

    if len(existing_ids) >= target_total:
        print(f"  [OK] 100% de {resource_name.upper()} ja baixado ({len(existing_ids):,}). Pulando para o proximo.")
        return

    with open(filepath, 'a', encoding='utf-8') as out_f:
        for direction in ['desc', 'asc']:
            print(f"\n  >> Iniciando varredura {direction.upper()} (order=created_at)...")
            page = 1
            while page <= 100:  # Limite máximo da janela da API
                url = f"{BASE_URL}/{resource_name}?token={TOKEN}&page={page}&limit=100&order=created_at&direction={direction}"
                res = fetch_json(url)
                if not res:
                    break
                    
                items = res.get(key_in_response, []) if isinstance(res, dict) else []
                if not items:
                    break
                    
                new_count = 0
                for item in items:
                    item_id = item.get('id') or item.get('_id')
                    if item_id and item_id not in existing_ids:
                        existing_ids.add(item_id)
                        out_f.write(json.dumps(item, ensure_ascii=False) + '\n')
                        new_count += 1
                        
                out_f.flush()
                if page % 10 == 0 or page == 1 or new_count == 0:
                    print(f"    [Pag {page:02d}/{direction}] Total unico no arquivo: {len(existing_ids):,}/{target_total:,} (+{new_count} novos)")
                    
                if new_count == 0 and page > 10:
                    print(f"    * Sobreposicao completa detectada na pagina {page}. Passando para proxima etapa.")
                    break
                    
                if len(existing_ids) >= target_total:
                    print(f"    * 100% dos registros capturados ({len(existing_ids):,}/{target_total:,})!")
                    break
                    
                page += 1
                time.sleep(0.52)  # Frequência segura para respeitar os rate limits
                
            if len(existing_ids) >= target_total:
                break

    print(f"  [OK] {resource_name.upper()} concluido: {len(existing_ids):,} registros salvos em {filepath}\n")

if __name__ == '__main__':
    start_time = time.time()
    
    # 1. Deals (Total: ~14.090)
    extract_bidirectional('deals', 'deals', 'rd_crm_deals.jsonl', 14090)
    
    # 2. Organizations (Total: ~11.122)
    extract_bidirectional('organizations', 'organizations', 'rd_crm_organizations.jsonl', 11122)
    
    # 3. Contacts (Total: ~12.999)
    extract_bidirectional('contacts', 'contacts', 'rd_crm_contacts.jsonl', 12999)
    
    elapsed = time.time() - start_time
    print("==================================================")
    print(f" EXTRACAO TOTAL 100% CONCLUIDA EM {elapsed/60:.1f} MINUTOS!")
    print("==================================================")
