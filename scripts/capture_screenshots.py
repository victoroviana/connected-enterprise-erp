import os
import sys
import time
import subprocess
import urllib.request
from playwright.sync_api import sync_playwright

def wait_for_server(url, timeout=25):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            time.sleep(0.5)
    return False

def main():
    print("[+] Starting application server on port 6002...")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=r"c:\Users\User\Desktop\connected_erp_crm",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    base_url = "http://127.0.0.1:6002"
    screenshots_dir = r"c:\Users\User\Desktop\connected_erp_crm\docs\screenshots"
    os.makedirs(screenshots_dir, exist_ok=True)

    try:
        print("[+] Waiting for server to become ready...")
        if not wait_for_server(f"{base_url}/auth/login"):
            print("[-] Server failed to respond in time.")
            return

        with sync_playwright() as p:
            print("[+] Launching Playwright browser...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            # 1. Login Page
            print("[+] Capturing 01_login.png...")
            page.goto(f"{base_url}/auth/login", wait_until="networkidle")
            page.screenshot(path=os.path.join(screenshots_dir, "01_login.png"))

            # Log in as admin
            print("[+] Logging in as admin...")
            page.fill("input[name='usuario']", "admin")
            page.fill("input[name='senha']", "admin123")
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # 2. Main Executive Home / Dashboard
            print("[+] Capturing 02_dashboard.png...")
            page.goto(f"{base_url}/", wait_until="networkidle")
            time.sleep(1)
            page.screenshot(path=os.path.join(screenshots_dir, "02_dashboard.png"))

            # 3. Helpdesk / Sollus Tickets Dashboard
            print("[+] Capturing 03_helpdesk_tickets.png...")
            page.goto(f"{base_url}/sollus-tickets/", wait_until="networkidle")
            time.sleep(2)
            page.screenshot(path=os.path.join(screenshots_dir, "03_helpdesk_tickets.png"))

            # 4. Commercial Proposals (Nova Proposta)
            print("[+] Capturing 04_nova_proposta.png...")
            page.goto(f"{base_url}/nova_proposta", wait_until="networkidle")
            time.sleep(2)
            page.screenshot(path=os.path.join(screenshots_dir, "04_nova_proposta.png"))

            # 5. Proposal History & Tracking
            print("[+] Capturing 05_historico_propostas.png...")
            page.goto(f"{base_url}/historico_propostas", wait_until="networkidle")
            time.sleep(2)
            page.screenshot(path=os.path.join(screenshots_dir, "05_historico_propostas.png"))

            # 6. Central de Conhecimento / Kanban Board
            print("[+] Capturing 06_central_conhecimento.png...")
            page.goto(f"{base_url}/central-conhecimento", wait_until="networkidle")
            time.sleep(2)
            page.screenshot(path=os.path.join(screenshots_dir, "06_central_conhecimento.png"))

            browser.close()
            print("[+] ALL REAL SCREENSHOTS CAPTURED SUCCESSFULLY!")

    finally:
        proc.terminate()
        proc.kill()

if __name__ == "__main__":
    main()
