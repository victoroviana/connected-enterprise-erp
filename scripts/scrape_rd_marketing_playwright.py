"""
Script de Scraping Automatizado do RD Station Marketing via Playwright.
Salva respostas de API, estrutura de automações, modelos e screenshots.
"""
import os
import sys
import json
import time
import winsound
from datetime import datetime
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "rd_station", "marketing")
SCREENSHOTS_DIR = os.path.join(OUTPUT_DIR, "screenshots")
SESSION_DIR = os.path.join(BASE_DIR, "data", "rd_station", "browser_session")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs(SESSION_DIR, exist_ok=True)

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

def save_json(category, filename, data):
    cat_dir = os.path.join(OUTPUT_DIR, category)
    os.makedirs(cat_dir, exist_ok=True)
    filepath = os.path.join(cat_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    stats[category] = stats.get(category, 0) + 1
    log(f"  [SALVO] {category}/{filename}")

def beep(freq=1000, dur=300):
    try:
        winsound.Beep(freq, dur)
    except Exception:
        pass

def main():
    log("=" * 65)
    log("  SOLLUS CONNECTED - EXTRATOR RD STATION MARKETING")
    log("=" * 65)
    log("\n>> Abrindo a janela do navegador Chromium na sua tela...")
    log(">> Aguarde alguns instantes...\n")

    with sync_playwright() as p:
        log("Driver Playwright iniciado. Abrindo o Google Chrome oficial...")
        context = p.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-sandbox",
                "--disable-infobars"
            ]
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        page = context.pages[0] if context.pages else context.new_page()

        # Interceptador de respostas JSON
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

        log("Navegando para https://app.rdstation.com.br/ ...")
        page.goto("https://app.rdstation.com.br/", timeout=60000)
        beep(800, 200)

        log("\n" + "#" * 65)
        log(">> ATENÇÃO: A JANELA DO CHROMIUM FOI ABERTA NA SUA TELA!")
        log(">> POR FAVOR, FAÇA SEU LOGIN NO RD STATION NESSA JANELA.")
        log(">> O ROBÔ DETECTARÁ O LOGIN AUTOMATICAMENTE ASSIM QUE ENTRAR.")
        log("#" * 65 + "\n")

        # Aguarda estar logado por até 10 minutos
        max_wait = 600
        start_time = time.time()
        is_logged = False

        while time.time() - start_time < max_wait:
            curr_url = page.url.lower()
            if "login" not in curr_url and "accounts.rdstation" not in curr_url and ("app.rdstation.com.br" in curr_url or "marketing.rdstation.com.br" in curr_url):
                is_logged = True
                beep(1200, 400)
                log("\n" + "=" * 65)
                log(" [SUCESSO] LOGIN DETECTADO NO RD STATION!")
                log(" INICIANDO A VARREDURA AUTOMÁTICA DE TODOS OS MENUS...")
                log("=" * 65 + "\n")
                break
            time.sleep(2)

        if not is_logged:
            log("\n[AVISO] Tempo limite de login atingido (10 minutos).")
            context.close()
            return

        time.sleep(3)

        # Seções para navegação e captura
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
            log(f"\n---> Varrendo seção: {section_name}...")
            for u in urls:
                try:
                    log(f"  Acessando: {u}")
                    page.goto(u, timeout=30000, wait_until="networkidle")
                    time.sleep(3)

                    # Tira print da tela para registro
                    shot_path = os.path.join(SCREENSHOTS_DIR, shot_name)
                    page.screenshot(path=shot_path, full_page=False)
                    stats["screenshots"] += 1
                    log(f"  [SCREENSHOT] Salvo: screenshots/{shot_name}")

                    # Scroll suave para disparar requisições
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                    time.sleep(1)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2)
                    break
                except Exception as e:
                    log(f"  Aviso ao acessar rota ({e})...")

        # Salva resumo da extração
        resumo_path = os.path.join(OUTPUT_DIR, "resumo_extracao.json")
        with open(resumo_path, "w", encoding="utf-8") as f:
            json.dump({
                "data_extracao": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "estatisticas": stats
            }, f, indent=2)

        beep(1500, 600)
        log("\n" + "=" * 65)
        log(" VARREDURA CONCLUÍDA COM TOTAL SUCESSO!")
        log(f" Dados salvos em: {OUTPUT_DIR}")
        log(f" Estatísticas: {stats}")
        log("=" * 65)
        log("\nVocê pode fechar a janela do navegador agora.")
        time.sleep(10)
        context.close()

if __name__ == "__main__":
    main()
