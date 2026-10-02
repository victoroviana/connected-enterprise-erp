"""
Script para conectar ao Opera GX aberto com --remote-debugging-port=9222
e extrair 100% dos dados do RD Station Marketing aproveitando o login já ativo.
"""
import os
import sys
import json
import time
import urllib.request
import winsound
from datetime import datetime
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "rd_station", "marketing")
SCREENSHOTS_DIR = os.path.join(OUTPUT_DIR, "screenshots")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

stats = {
    "automations": 0,
    "segments": 0,
    "emails": 0,
    "forms": 0,
    "fields": 0,
    "scoring": 0,
    "analytics": 0,
    "screenshots": 0
}

def log(msg):
    print(msg, flush=True)

def beep(freq=1200, dur=300):
    try:
        winsound.Beep(freq, dur)
    except Exception:
        pass

def save_json(category, filename, data):
    cat_dir = os.path.join(OUTPUT_DIR, category)
    os.makedirs(cat_dir, exist_ok=True)
    filepath = os.path.join(cat_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    stats[category] = stats.get(category, 0) + 1
    log(f"  [SALVO] {category}/{filename}")

def main():
    log("=" * 65)
    log("  SOLLUS CONNECTED - EXTRATOR RD STATION (OPERA GX)")
    log("=" * 65)
    log("\nAguardando conexão com o seu Opera GX na porta 9222...")

    connected = False
    for attempt in range(15):
        try:
            with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2) as resp:
                data = json.loads(resp.read().decode())
                log(f"[OK] Conectado ao navegador: {data.get('Browser', 'Opera GX')}")
                connected = True
                break
        except Exception:
            time.sleep(1)

    if not connected:
        log("\n[ERRO] Não foi possível conectar ao Opera GX.")
        log("Certifique-se de que o Opera GX foi iniciado pelo atalho com a porta de depuração.")
        return

    with sync_playwright() as p:
        log("Anexando robô à sua sessão do Opera GX...")
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0] if browser.contexts else browser.new_context()

        # Procura aba que já esteja no RD Station ou cria uma nova
        page = None
        for p_tab in context.pages:
            if "rdstation" in p_tab.url:
                page = p_tab
                log(f"Aba do RD Station encontrada: {p_tab.url}")
                break

        if not page:
            log("Abrindo aba do RD Station no seu Opera GX...")
            page = context.new_page()
            page.goto("https://app.rdstation.com.br/")

        # Interceptador de respostas JSON da API do RD Station
        def on_response(response):
            try:
                url = response.url.lower()
                ct = response.headers.get("content-type", "").lower()
                if "application/json" not in ct:
                    return

                if "rdstation" in url:
                    try:
                        data = response.json()
                    except Exception:
                        return

                    ts = int(time.time() * 1000)
                    if any(k in url for k in ["automation", "flow", "workflow"]):
                        save_json("automations", f"auto_{ts}.json", {"url": response.url, "data": data})
                    elif "segment" in url:
                        save_json("segments", f"seg_{ts}.json", {"url": response.url, "data": data})
                    elif any(k in url for k in ["email", "template", "message"]):
                        save_json("emails", f"email_{ts}.json", {"url": response.url, "data": data})
                    elif any(k in url for k in ["form", "landing_page", "conversion"]):
                        save_json("forms", f"form_{ts}.json", {"url": response.url, "data": data})
                    elif any(k in url for k in ["field", "custom_field"]):
                        save_json("fields", f"field_{ts}.json", {"url": response.url, "data": data})
                    elif "scoring" in url:
                        save_json("scoring", f"scoring_{ts}.json", {"url": response.url, "data": data})
                    elif any(k in url for k in ["channel", "analytic", "report"]):
                        save_json("analytics", f"analytics_{ts}.json", {"url": response.url, "data": data})
            except Exception:
                pass

        page.on("response", on_response)

        log("\n" + "#" * 65)
        log(" SESSÃO DETECTADA NO SEU OPERA GX! INICIANDO VARREDURA...")
        log("#" * 65)
        beep(1200, 300)

        targets = [
            ("Automações de Marketing", [
                "https://app.rdstation.com.br/marketing/automacoes",
                "https://app.rdstation.com.br/automations"
            ], "automacoes.png"),
            ("Segmentações de Contatos", [
                "https://app.rdstation.com.br/marketing/segmentacoes",
                "https://app.rdstation.com.br/segments"
            ], "segmentacoes.png"),
            ("Modelos de E-mail", [
                "https://app.rdstation.com.br/marketing/emails",
                "https://app.rdstation.com.br/email_templates"
            ], "modelos_email.png"),
            ("Formulários", [
                "https://app.rdstation.com.br/marketing/formularios",
                "https://app.rdstation.com.br/forms"
            ], "formularios.png"),
            ("Landing Pages", [
                "https://app.rdstation.com.br/marketing/landing_pages",
                "https://app.rdstation.com.br/landing_pages"
            ], "landing_pages.png"),
            ("Campos Personalizados", [
                "https://app.rdstation.com.br/fields",
                "https://app.rdstation.com.br/marketing/campos_personalizados"
            ], "campos_personalizados.png"),
            ("Lead Scoring", [
                "https://app.rdstation.com.br/lead-scoring",
                "https://app.rdstation.com.br/marketing/lead_scoring"
            ], "lead_scoring.png"),
            ("Análise de Canais", [
                "https://app.rdstation.com.br/analytics/channels",
                "https://app.rdstation.com.br/marketing/analise_canais"
            ], "analise_canais.png")
        ]

        for section_name, urls, shot_name in targets:
            log(f"\n---> Varrendo: {section_name}...")
            for u in urls:
                try:
                    log(f"  Acessando: {u}")
                    page.goto(u, timeout=30000, wait_until="networkidle")
                    time.sleep(3)

                    shot_path = os.path.join(SCREENSHOTS_DIR, shot_name)
                    page.screenshot(path=shot_path, full_page=False)
                    stats["screenshots"] += 1
                    log(f"  [SCREENSHOT] Salvo: screenshots/{shot_name}")

                    page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                    time.sleep(1)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2)
                    break
                except Exception as e:
                    log(f"  Aviso ao acessar ({e})...")

        resumo_path = os.path.join(OUTPUT_DIR, "resumo_extracao.json")
        with open(resumo_path, "w", encoding="utf-8") as f:
            json.dump({
                "data_extracao": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "navegador": "Opera GX",
                "estatisticas": stats
            }, f, indent=2)

        beep(1600, 500)
        log("\n" + "=" * 65)
        log(" VARREDURA FINALIZADA COM SUCESSO NO SEU OPERA GX!")
        log(f" Resumo e arquivos salvos em: {OUTPUT_DIR}")
        log(f" Estatísticas: {stats}")
        log("=" * 65)

if __name__ == "__main__":
    main()
