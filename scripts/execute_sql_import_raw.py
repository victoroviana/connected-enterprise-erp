import sys
import traceback
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from config import Config
from sqlalchemy import create_engine

SQL_FILE = project_root / "outputs" / "gestao_tarefas_depara.sql"

def main():
    if not SQL_FILE.exists():
        print(f"File not found: {SQL_FILE}")
        return 1
        
    print(f"Connecting to database...")
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    
    statements = []
    with open(SQL_FILE, "r", encoding="utf-8") as f:
        buffer = []
        for line in f:
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            buffer.append(line)
            if line.endswith(";"):
                statements.append(" ".join(buffer))
                buffer = []
                
    if not statements:
        print("No statements found.")
        return 0
        
    print(f"Found {len(statements)} statements to execute.")
    
    success = 0
    errors = 0
    
    with engine.connect() as conn:
        connection = conn.connection
        cursor = connection.cursor()
        for i, stmt in enumerate(statements, 1):
            try:
                cursor.execute(stmt)
                success += 1
                if i % 50 == 0:
                    print(f"Executed {i}/{len(statements)}...")
            except Exception as e:
                errors += 1
                print(f"Error on statement {i}: {str(e)[:200]}...")
        connection.commit()
        cursor.close()
                
    print(f"Import complete! Success: {success}, Errors: {errors}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
