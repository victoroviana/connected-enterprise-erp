import os

path = 'modules/suporte/blueprints/assistencia.py'

routes_code = """
from modules.suporte.models import OrcamentoTemplate
import json

@assist_bp.route("/orcamento-templates")
@login_required
def listar_orcamento_templates():
    if not _is_admin_like():
        return _deny_access("Gerenciar Tipos de Orçamento")
    templates = OrcamentoTemplate.query.order_by(OrcamentoTemplate.label).all()
    return render_template("admin/assistencia/orcamento_templates.html", templates=templates)

@assist_bp.route("/orcamento-templates/salvar", methods=["POST"])
@login_required
def salvar_orcamento_template():
    if not _is_admin_like():
        return jsonify({"ok": False, "message": "Sem permissão"}), 403
    try:
        data = request.json
        template_id = data.get("id")
        chave = data.get("chave", "").strip()
        label = data.get("label", "").strip()
        table_title = data.get("table_title", "").strip()
        ativo = data.get("ativo", True)
        observacao = data.get("observacao", "")
        
        items = data.get("items", [])
        condicoes = data.get("condicoes", [])
        aceite = data.get("aceite", [])
        
        if not chave or not label:
            return jsonify({"ok": False, "message": "Chave e Label são obrigatórios."}), 400
            
        if template_id:
            template = OrcamentoTemplate.query.get_or_404(template_id)
        else:
            if OrcamentoTemplate.query.filter_by(chave=chave).first():
                return jsonify({"ok": False, "message": "Chave já existe."}), 400
            template = OrcamentoTemplate(chave=chave)
            db.session.add(template)
            
        template.label = label
        template.table_title = table_title
        template.items = items
        template.condicoes = condicoes
        template.observacao = observacao
        template.aceite = aceite
        template.ativo = ativo
        
        db.session.commit()
        return jsonify({"ok": True, "message": "Template salvo com sucesso."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(e)}), 500

@assist_bp.route("/orcamento-templates/<int:template_id>/excluir", methods=["POST"])
@login_required
def excluir_orcamento_template(template_id):
    if not _is_admin_like():
        return jsonify({"ok": False, "message": "Sem permissão"}), 403
    try:
        template = OrcamentoTemplate.query.get_or_404(template_id)
        db.session.delete(template)
        db.session.commit()
        return jsonify({"ok": True, "message": "Template excluído com sucesso."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(e)}), 500
"""

with open(path, 'a', encoding='utf-8') as f:
    f.write(routes_code)
print("Routes appended to assistencia.py")
