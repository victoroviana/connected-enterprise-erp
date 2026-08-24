import re
from pathlib import Path

target_files = [
    r"c:\Users\User\Desktop\sollus_connected\modules\suporte\blueprints\atendimentos.py",
    r"c:\Users\User\Desktop\sollus_connected\modules\suporte\blueprints\assistencia.py",
    r"c:\Users\User\Desktop\sollus_connected\modules\suporte\blueprints\atestados.py",
    r"c:\Users\User\Desktop\sollus_connected\modules\propostas\blueprints\propostas\propostas.py",
    r"c:\Users\User\Desktop\sollus_connected\modules\propostas\blueprints\equipamentos\routes.py",
    r"c:\Users\User\Desktop\sollus_connected\modules\propostas\blueprints\admin_tools\routes.py",
    r"c:\Users\User\Desktop\sollus_connected\modules\financeiro\blueprints\financeiro.py",
    r"c:\Users\User\Desktop\sollus_connected\modules\contratos\blueprints\contratos.py",
    r"c:\Users\User\Desktop\sollus_connected\modules\cracha\blueprints\cracha.py",
    r"c:\Users\User\Desktop\sollus_connected\modules\chamados\blueprints\tickets\routes.py",
    r"c:\Users\User\Desktop\sollus_connected\modules\chamados\blueprints\central_conhecimento\routes.py",
    r"c:\Users\User\Desktop\sollus_connected\modules\sollus_tickets\blueprints\tickets\routes.py"
]

for file_path in target_files:
    path = Path(file_path)
    if not path.exists():
        continue
    content = path.read_text(encoding="utf-8")
    
    # Check if request is imported
    if "from flask import" in content and "request" not in content:
        content = re.sub(r'(from flask import [^\)]*)', r'\1, request', content, count=1)
    
    # We want to insert the check after the def line
    def insert_api_check(match):
        func_def = match.group(0)
        indent = match.group(2)
        # Avoid double insert
        if '"/api/" in getattr(request, "path", "")' in content:
            return func_def
            
        insertion = f"""
{indent}from flask import request
{indent}if "/api/" in getattr(request, "path", ""):
{indent}    return"""
        return func_def + insertion

    # regex to match:
    # @xxx.before_request
    # def _xxx():
    pattern = r'(@[\w_]+\.before_request\s*\n( +)def\s+[\w_]+\(\s*\)\s*:)'
    
    new_content = re.sub(pattern, insert_api_check, content)
    
    if new_content != content:
        path.write_text(new_content, encoding="utf-8")
        print(f"Updated {path.name}")
