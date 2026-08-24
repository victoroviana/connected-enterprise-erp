import os

def fix_mojibake_chars(text):
    # Dicionário de correções de mojibake (quando o caractere Unicode está errado no arquivo)
    corrections = {
        'Ã¡': 'á',
        'Ã©': 'é',
        'Ã­': 'í',
        'Ã³': 'ó',
        'Ãº': 'ú',
        'Ã£': 'ã',
        'Ãµ': 'õ',
        'Ã§': 'ç',
        'Ãª': 'ê',
        'Ã¢': 'â',
        'Ã´': 'ô',
        'Ã\x81': 'Á',
        'Ã\x89': 'É',
        'Ã\x8d': 'Í',
        'Ã\x93': 'Ó',
        'Ã\x9a': 'Ú',
        'Ã\x83': 'Ã',
        'Ã\x95': 'Õ',
        'Ã\x87': 'Ç',
        'Â·': '·',
        'Ã\xba': 'ú',
        'Ã\xa1': 'á',
        'Ã\xa9': 'é',
        'Ã\xad': 'í',
        'Ã\xb3': 'ó',
        'Ã\xba': 'ú',
        'Ã\xa3': 'ã',
        'Ã\xb5': 'õ',
        'Ã\xa7': 'ç',
        'Ã\xaa': 'ê',
        'Ã\xa2': 'â',
        'Ã\xb4': 'ô'
    }
    for wrong, right in corrections.items():
        text = text.replace(wrong, right)
    return text

def repair_file(path):
    print(f"Limpando caracteres em {path}...")
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    fixed = fix_mojibake_chars(content)
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(fixed)
    print(f"Sucesso: {path}")

files = [
    r'modules/suporte/blueprints/atendimentos.py',
    r'modules/suporte/blueprints/assistencia.py',
    r'modules/suporte/services/chamados.py',
    r'modules/suporte/services/assistencia.py',
    r'modules/suporte/services/uploads.py',
    r'templates/layout.html'
]

for f in files:
    full_path = os.path.join(r'c:\Users\User\Desktop\sollus_connected', f)
    if os.path.exists(full_path):
        repair_file(full_path)
