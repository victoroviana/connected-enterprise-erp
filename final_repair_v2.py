import os

def fix_mojibake_chars(text):
    corrections = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú',
        'Ã£': 'ã', 'Ãµ': 'õ', 'Ã§': 'ç', 'Ãª': 'ê', 'Ã¢': 'â', 'Ã´': 'ô',
        'Ã\x81': 'Á', 'Ã\x89': 'É', 'Ã\x8d': 'Í', 'Ã\x93': 'Ó', 'Ã\x9a': 'Ú',
        'Ã\x83': 'Ã', 'Ã\x95': 'Õ', 'Ã\x87': 'Ç', 'Â·': '·'
    }
    for wrong, right in corrections.items():
        text = text.replace(wrong, right)
    return text

def final_repair(path):
    print(f"Reparando final (v2) {path}...")
    with open(path, 'rb') as f:
        raw = f.read()
    
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('latin1')
    
    # Fix mojibake
    text = fix_mojibake_chars(text)
    
    # Force single newlines
    lines = text.splitlines()
    # Filtra linhas vazias extras se necessário? Não, splitlines() cuida disso.
    # Mas se houver \r\r\n, splitlines vai gerar ['line', '', '']? 
    # Não, \r\n is one line break. \r\r\n is \r + \r\n.
    
    clean_lines = []
    for line in lines:
        stripped = line.strip('\r\n')
        if stripped or line == '': # mantem linhas vazias intencionais
            clean_lines.append(stripped)
    
    # Se o número de linhas dobrou, é provável que existam strings vazias entre cada linha
    if len(lines) > 3000: # Heurística para atendimentos.py
        # Tenta remover linhas puramente vazias se elas forem alternadas
        new_lines = []
        for i, line in enumerate(lines):
            if i % 2 == 0 or line.strip():
                new_lines.append(line.strip('\r\n'))
        clean_lines = new_lines

    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(clean_lines))
    print(f"Sucesso: {path}")

files = [
    r'modules/suporte/blueprints/atendimentos.py',
    r'modules/suporte/blueprints/assistencia.py',
    r'modules/suporte/services/chamados.py',
    r'modules/suporte/services/assistencia.py',
    r'modules/suporte/services/uploads.py',
    r'modules/suporte/blueprints/shared_agenda.py',
    r'templates/layout.html'
]

for f in files:
    full_path = os.path.join(r'c:\Users\User\Desktop\sollus_connected', f)
    if os.path.exists(full_path):
        final_repair(full_path)
