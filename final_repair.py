import os

def fix_content(text):
    # Correções de mojibake
    corrections = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú',
        'Ã£': 'ã', 'Ãµ': 'õ', 'Ã§': 'ç', 'Ãª': 'ê', 'Ã¢': 'â', 'Ã´': 'ô',
        'Ã\x81': 'Á', 'Ã\x89': 'É', 'Ã\x8d': 'Í', 'Ã\x93': 'Ó', 'Ã\x9a': 'Ú',
        'Ã\x83': 'Ã', 'Ã\x95': 'Õ', 'Ã\x87': 'Ç', 'Â·': '·'
    }
    for wrong, right in corrections.items():
        text = text.replace(wrong, right)
    
    # Corrige quebras de linha duplas (\r\r\n -> \r\n)
    text = text.replace('\r\r\n', '\n').replace('\r\n', '\n')
    return text

def final_repair(path):
    print(f"Reparando final {path}...")
    # Lê o arquivo de forma que ignore o encoding problemático inicialmente
    with open(path, 'rb') as f:
        raw = f.read()
    
    # Tenta UTF-8
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('latin1')
    
    repaired = fix_content(text)
    
    # Escreve com newline='\n' para evitar o comportamento de auto-conversão no Windows
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(repaired)
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
