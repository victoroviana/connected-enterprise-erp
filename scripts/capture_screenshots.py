import os
import sys
import time
import subprocess
import urllib.request
from playwright.sync_api import sync_playwright

def wait_for_server(url, timeout=20):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            time.sleep(0.5)
    return False

def main():
    print("[+] Starting application server...")
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
        print("[+] Waiting for server to become ready on port 6002...")
        if not wait_for_server(f"{base_url}/auth/login"):
            print("[-] Server did not start in time. Aborting.")
            return

        with sync_playwright() as p:
            print("[+] Launching Playwright browser...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            # 1. Login Page
            print("[+] Navigating to Login...")
            page.goto(f"{base_url}/auth/login", wait_until="networkidle")
            page.screenshot(path=os.path.join(screenshots_dir, "01_login.png"))
            print("[+] Captured 01_login.png")

            # Fill credentials
            page.fill("input[name='usuario']", "admin")
            page.fill("input[name='senha']", "admin123")
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # 2. Main Dashboard / Home
            print("[+] Capturing 02_dashboard.png...")
            page.screenshot(path=os.path.join(screenshots_dir, "02_dashboard.png"))

            # 3. Helpdesk / Chamados Tickets List
            print("[+] Capturing 03_tickets.png...")
            try:
                page.goto(f"{base_url}/chamados/tickets", wait_until="networkidle", timeout=8000)
            except Exception:
                page.goto(f"{base_url}/sollus_tickets/dashboard", wait_until="networkidle", timeout=8000)
            time.sleep(2)
            page.screenshot(path=os.path.join(screenshots_dir, "03_tickets.png"))

            # 4. Commercial Proposals
            print("[+] Capturing 04_proposals.png...")
            try:
                page.goto(f"{base_url}/nova", wait_until="networkidle", timeout=8000)
            except Exception:
                page.goto(f"{base_url}/propostas/nova", wait_until="networkidle", timeout=8000)
            time.sleep(2)
            page.screenshot(path=os.path.join(screenshots_dir, "04_proposals.png"))

            # 5. Knowledge Base / Kanban Board
            print("[+] Capturing 05_knowledge_kanban.png...")
            try:
                page.goto(f"{base_url}/central-conhecimento", wait_until="networkidle", timeout=8000)
            except Exception:
                pass
            time.sleep(2)
            page.screenshot(path=os.path.join(screenshots_dir, "05_knowledge_kanban.png"))

            browser.close()
            print("[+] ALL SCREENSHOTS CAPTURED SUCCESSFULLY!")

    finally:
        proc.terminate()
        proc.kill()

if __name__ == "__main__":
    main()
