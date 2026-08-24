import os

def fix_mojibake(text):
    if not text:
        return text
    try:
        # Caso 1: O arquivo está em UTF-8 mas sendo lido como Latin-1
        # Se tentarmos encodar como latin1 e decodar como utf8, corrigimos.
        return text.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

def process_file(path):
    print(f"Processando {path}...")
    with open(path, 'rb') as f:
        content = f.read()
    
    # Tenta ler como UTF-8 primeiro
    try:
        text = content.decode('utf-8')
        # Se ler como UTF-8 e tiver sequências como 'Ã¡', é mojibake.
        if 'Ã¡' in text or 'Ã©' in text or 'Ã­' in text or 'Ã³' in text or 'Ãº' in text or 'Ã£' in text or 'Ã§' in text:
            print(f"Detectado mojibake em {path}. Tentando corrigir...")
            fixed = fix_mojibake(text)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(fixed)
            print(f"Corrigido: {path}")
        else:
            print(f"Nenhum mojibake óbvio detectado em {path} (lido como UTF-8).")
    except UnicodeDecodeError:
        # Se não for UTF-8, tenta ler como Latin-1 e salvar como UTF-8
        print(f"Não é UTF-8 válido. Lendo como Latin-1...")
        text = content.decode('latin-1')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"Convertido de Latin-1 para UTF-8: {path}")

files = [
    r'modules/suporte/blueprints/atendimentos.py',
    r'modules/suporte/blueprints/assistencia.py',
    r'modules/suporte/blueprints/shared_agenda.py',
    r'templates/layout.html'
]

for f in files:
    full_path = os.path.join(r'c:\Users\User\Desktop\sollus_connected', f)
    if os.path.exists(full_path):
        process_file(full_path)
    else:
        print(f"Arquivo não encontrado: {full_path}")
