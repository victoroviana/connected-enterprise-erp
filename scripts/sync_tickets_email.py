import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from platform_app import create_app
from modules.sollus_tickets.email_ingest import sync_enabled_mailboxes
from modules.sollus_tickets.services import update_sla_overdue

def run_sync():
    app = create_app()
    with app.app_context():
        print(f"[{datetime.now()}] Starting Sollus Tickets background tasks...")
        
        # 1. Sync emails
        try:
            print("Syncing mailboxes...")
            stats = sync_enabled_mailboxes()
            print(f"Sync complete: {stats}")
        except Exception as e:
            print(f"Error syncing mailboxes: {e}")
            
        # 2. Update SLA Overdue
        try:
            print("Updating SLA overdue status...")
            update_sla_overdue()
            print("SLA update complete.")
        except Exception as e:
            print(f"Error updating SLAs: {e}")

if __name__ == "__main__":
    from datetime import datetime
    run_sync()
