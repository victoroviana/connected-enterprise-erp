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
        print(f"File not found: {path}")
        continue
    
    content = path.read_text(encoding="utf-8")
    lines = content.split('\n')
    new_lines = []
    
    skip_next = False
    inside_hook = False
    
    for i, line in enumerate(lines):
        new_lines.append(line)
        
        if ".before_request" in line and "@" in line:
            inside_hook = True
            continue
            
        if inside_hook:
            # Detect where to insert
            if line.strip() == "return":
                # Check previous line
                prev_line = lines[i-1].strip()
                if "if not current_user.is_authenticated:" in prev_line or "if endpoint and not endpoint.startswith(" in prev_line:
                    # Insert here
                    indent = line[:len(line) - len(line.lstrip())]
                    outer_indent = indent[:-4] if len(indent) >= 4 else ""
                    
                    # Prevent double insertion
                    if i + 1 < len(lines) and '"/api/" in request.path' in lines[i+1]:
                        pass # already inserted
                    else:
                        new_lines.append(f'{outer_indent}if "/api/" in getattr(request, "path", ""):')
                        new_lines.append(f'{indent}return')
                        print(f"Inserted in {path.name}")
                    
                    inside_hook = False
            
            # Reset if we left the function (crude check: unindented def or class)
            if line.startswith("def ") or line.startswith("class ") or line.startswith("@") and not ".before_request" in line:
                inside_hook = False

    path.write_text('\n'.join(new_lines), encoding="utf-8")
