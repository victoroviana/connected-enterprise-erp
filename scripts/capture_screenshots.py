import os
import sys
import time
import threading

sys.path.insert(0, r"c:\Users\User\Desktop\connected_erp_crm")

from platform_app import create_app
from playwright.sync_api import sync_playwright

app = create_app()

def run_app():
    app.run(host="127.0.0.1", port=6002, threaded=True, debug=False, use_reloader=False)

def main():
    t = threading.Thread(target=run_app, daemon=True)
    t.start()
    time.sleep(3)

    base_url = "http://127.0.0.1:6002"
    screenshots_dir = r"c:\Users\User\Desktop\connected_erp_crm\docs\screenshots"
    os.makedirs(screenshots_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # 1. Login Page
        print("[+] 1. Login")
        page.goto(f"{base_url}/auth/login")
        page.screenshot(path=os.path.join(screenshots_dir, "01_login.png"))

        # Log in
        print("[+] Logging in...")
        page.fill("input[name='usuario']", "admin")
        page.fill("input[name='senha']", "admin123")
        page.click("button[type='submit']")
        page.wait_for_load_state("domcontentloaded")
        time.sleep(1)
        print(f"    Logged in! Current URL: {page.url}")

        pages_to_capture = [
            ("02_dashboard.png", f"{base_url}/"),
            ("03_nova_proposta.png", f"{base_url}/nova_proposta"),
            ("04_historico_propostas.png", f"{base_url}/historico_propostas"),
            ("05_central_conhecimento.png", f"{base_url}/central-conhecimento/"),
            ("06_estoque_equipamentos.png", f"{base_url}/estoque"),
            ("07_cracha_recibos.png", f"{base_url}/cracha/recibos"),
            ("08_parametros.png", f"{base_url}/parametros"),
        ]

        for filename, url in pages_to_capture:
            print(f"[+] Capturing {filename} from {url}...")
            page.goto(url)
            time.sleep(1.5)
            target_path = os.path.join(screenshots_dir, filename)
            page.screenshot(path=target_path)
            size = os.path.getsize(target_path)
            print(f"    -> Saved {filename} ({size} bytes) | Title: {page.title()}")

        browser.close()
        print("\n🎉 ALL SCREENSHOTS CAPTURED PERFECTLY!")
        os._exit(0)

if __name__ == "__main__":
    main()
