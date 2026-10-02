from pathlib import Path

SQL_FILE = Path(r"c:\Users\User\Desktop\sollus_connected\outputs\gestao_tarefas_depara.sql")

if SQL_FILE.exists():
    content = SQL_FILE.read_text(encoding="utf-8")
    # Replace all INSERT INTO with INSERT IGNORE INTO
    content = content.replace("INSERT INTO", "INSERT IGNORE INTO")
    SQL_FILE.write_text(content, encoding="utf-8")
    print("Replaced INSERT INTO with INSERT IGNORE INTO")
