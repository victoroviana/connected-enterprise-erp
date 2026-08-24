import os

def fix_content(content):
    try:
        return content.encode('latin1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return content

def repair_file(path):
    print(f"Reparando {path}...")
    with open(path, 'rb') as f:
        raw = f.read()
    
    try:
        text = raw.decode('utf-8')
        repaired = fix_content(text)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(repaired)
        print(f"Sucesso: {path}")
    except UnicodeDecodeError:
        print(f"Não é UTF-8. Lendo como Latin-1 e salvando como UTF-8: {path}")
        text = raw.decode('latin1')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)

files = [
    r'modules/suporte/services/chamados.py',
    r'modules/suporte/services/assistencia.py',
    r'modules/suporte/services/uploads.py'
]

for f in files:
    full_path = os.path.join(r'c:\Users\User\Desktop\sollus_connected', f)
    if os.path.exists(full_path):
        repair_file(full_path)
