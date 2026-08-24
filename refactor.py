import sys
import re

path = 'modules/suporte/services/orcamentos.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove ORCAMENTO_DEFINITIONS completely
content = re.sub(r'ORCAMENTO_DEFINITIONS: dict\[str, dict\[str, Any\]\] = \{.*?\n\ndef list_orcamento_types', 'def list_orcamento_types', content, flags=re.DOTALL)

# Refactor list_orcamento_types
content = re.sub(
    r'def list_orcamento_types\(\) -> list\[tuple\[str, str\]\]:\n    return \[\(key, meta\.get\("label", key\.title\(\)\)\) for key, meta in ORCAMENTO_DEFINITIONS\.items\(\)\]',
    'def list_orcamento_types() -> list[tuple[str, str]]:\n    from modules.suporte.models import OrcamentoTemplate\n    templates = OrcamentoTemplate.query.filter_by(ativo=True).order_by(OrcamentoTemplate.id).all()\n    return [(t.chave, t.label or t.chave.title()) for t in templates]',
    content
)

# Refactor build_orcamento_items
content = content.replace(
    '    meta = ORCAMENTO_DEFINITIONS.get(tipo)\n    if not meta:',
    '    from modules.suporte.models import OrcamentoTemplate\n    template = OrcamentoTemplate.query.filter_by(chave=tipo, ativo=True).first()\n    if not template:\n        return [], 0.0\n    meta = template.to_dict()\n    if not meta:'
)

# Refactor build_orcamento_context
content = content.replace(
    '    meta = ORCAMENTO_DEFINITIONS.get(orcamento.tipo, {})',
    '    from modules.suporte.models import OrcamentoTemplate\n    template = OrcamentoTemplate.query.filter_by(chave=orcamento.tipo).first()\n    meta = template.to_dict() if template else {}'
)

# Refactor iter_orcamento_items
content = content.replace(
    '    meta = ORCAMENTO_DEFINITIONS.get(tipo, {})',
    '    from modules.suporte.models import OrcamentoTemplate\n    template = OrcamentoTemplate.query.filter_by(chave=tipo).first()\n    meta = template.to_dict() if template else {}'
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('orcamentos.py updated')
