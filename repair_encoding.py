import os

def fix_content(content):
    # Procura por padrões de mojibake UTF-8 -> Latin-1
    # 'á' é 'Ã¡'
    # 'é' é 'Ã©'
    # 'í' é 'Ã­'
    # 'ó' é 'Ã³'
    # 'ú' é 'Ãº'
    # 'ã' é 'Ã£'
    # 'õ' é 'Ãµ'
    # 'ç' é 'Ã§'
    # 'ê' é 'Ãª'
    # 'â' é 'Ã¢'
    # 'ô' é 'Ã´'
    # 'Á' é 'Ã\x81'
    # 'É' é 'Ã\x89'
    # 'Í' é 'Ã\x8d'
    # 'Ó' é 'Ã\x93'
    # 'Ú' é 'Ã\x9a'
    # 'Ã' é 'Ã\x83'
    # 'Õ' é 'Ã\x95'
    # 'Ç' é 'Ã\x87'
    
    try:
        # Se o conteúdo foi lido como UTF-8 mas contém esses bytes errados,
        # encodar para latin1 e decodar para utf8 corrige.
        return content.encode('latin1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return content

def repair_file(path):
    print(f"Reparando {path}...")
    with open(path, 'rb') as f:
        raw = f.read()
    
    # Tenta ler como UTF-8
    try:
        text = raw.decode('utf-8')
        repaired = fix_content(text)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(repaired)
        print(f"Sucesso: {path}")
    except UnicodeDecodeError:
        # Se não for UTF-8, assume que é Latin-1 (CP1252)
        print(f"Não é UTF-8. Lendo como Latin-1 e salvando como UTF-8: {path}")
        text = raw.decode('latin1')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)

files = [
    r'modules/suporte/blueprints/atendimentos.py',
    r'modules/suporte/blueprints/assistencia.py',
    r'modules/suporte/blueprints/shared_agenda.py',
    r'templates/layout.html'
]

for f in files:
    full_path = os.path.join(r'c:\Users\User\Desktop\sollus_connected', f)
    if os.path.exists(full_path):
        repair_file(full_path)
