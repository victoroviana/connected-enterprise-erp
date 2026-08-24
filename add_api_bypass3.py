import os
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
    lines = content.split('\n')
    new_lines = []
    
    inside_hook = False
    updated = False
    
    for i, line in enumerate(lines):
        new_lines.append(line)
        
        if ".before_request" in line and "@" in line:
            inside_hook = True
            continue
            
        if inside_hook and line.strip().startswith("def "):
            # We found the def line. Let's insert our code here.
            indent = "    "
            
            # check if we already inserted it
            if '"/api/" in getattr(request, "path", "")' not in content:
                new_lines.append(f'{indent}from flask import request')
                new_lines.append(f'{indent}if "/api/" in getattr(request, "path", ""):')
                new_lines.append(f'{indent}    return')
                updated = True
            
            inside_hook = False
            
    if updated:
        path.write_text('\n'.join(new_lines), encoding="utf-8")
        print(f"Updated {path.name}")
