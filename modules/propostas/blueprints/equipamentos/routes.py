# blueprints/equipamentos/equipamentos.py

import os
import uuid
import unicodedata

from sqlalchemy import func, or_

from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    session,
    current_app,
)
from flask_login import current_user

from werkzeug.utils import secure_filename

from PIL import Image, UnidentifiedImageError



from . import equipamentos_bp

from ..auth import login_required
from ..auth.permissions_utils import normalize_role_key, raw_permissions, current_permissions

from extensions import db

from ...models import Equipment, Part

from ...forms import EquipmentForm, PartForm

from utils.helpers import (
    wants_json as _wants_json,
    normalize_dept_name as _normalize_dept_name,
)






def _dept_names() -> set[str]:
    names: set[str] = set()
    try:
        for name in getattr(current_user, "department_names", []) or []:
            normalized = _normalize_dept_name(name)
            if normalized:
                names.add(normalized)
    except Exception:
        return set()
    return names


def _format_currency(value: float | int | str | None) -> str:
    try:
        num = float(value or 0.0)
    except (TypeError, ValueError):
        num = 0.0
    return f"R$ {num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _get_static_root() -> str | None:
    try:
        static_root = current_app.static_folder
    except RuntimeError:
        static_root = None
    if static_root and os.path.isdir(static_root):
        return static_root
    fallback = os.path.join(os.getcwd(), "static")
    if os.path.isdir(fallback):
        return fallback
    return None


def _build_static_file_index() -> dict[str, str]:
    index: dict[str, str] = {}
    static_root = _get_static_root()
    if not static_root:
        return index
    for root, _, files in os.walk(static_root):
        rel_root = os.path.relpath(root, static_root)
        rel_root = "" if rel_root == "." else rel_root.replace("\\", "/")
        for filename in files:
            rel_path = f"{rel_root}/{filename}" if rel_root else filename
            index.setdefault(filename.lower(), rel_path)
    return index


def _static_file_exists(rel_path: str) -> bool:
    static_root = _get_static_root()
    if not static_root:
        return True
    return os.path.exists(os.path.join(static_root, rel_path))


def _resolve_equipment_image_src(*values: object, index: dict[str, str] | None = None) -> str | None:
    for value in values:
        if not value:
            continue
        text = str(value).strip()
        if not text:
            continue
        lowered_text = text.lower()
        if lowered_text.startswith(("http://", "https://")):
            return text
        if lowered_text.startswith("file://"):
            text = text[7:]
        text = text.replace("\\", "/").lstrip("/")
        parts = [p for p in text.split("/") if p and p not in (".", "..")]
        if not parts:
            continue
        lowered = [p.lower() for p in parts]
        if "static" in lowered:
            idx = len(lowered) - 1 - lowered[::-1].index("static")
            parts = parts[idx + 1 :]
        if not parts:
            continue
        rel_path = "/".join(parts)
        candidates = [rel_path]
        if "/" not in rel_path:
            candidates.extend(
                [
                    f"images/{rel_path}",
                    f"uploads/{rel_path}",
                    f"galeria/{rel_path}",
                ]
            )
        for candidate in candidates:
            if _static_file_exists(candidate):
                return url_for("static", filename=candidate)
        if "/" not in rel_path and index:
            found = index.get(rel_path.lower())
            if found and _static_file_exists(found):
                return url_for("static", filename=found)
        fallback = None
        if "/" not in rel_path:
            fallback = f"images/{rel_path}"
        elif candidates:
            fallback = candidates[0]
        if fallback:
            return url_for("static", filename=fallback)
    return None


def _deny_access():
    if _wants_json():
        return jsonify({"ok": False, "message": "Você não tem permissão para acessar esta área."}), 403
    flash("Você não tem permissão para acessar esta área.", "warning")
    return redirect(url_for("sem_permissao", area="Cadastros"))


@equipamentos_bp.before_request
def _check_cadastros_access():
    from flask import request
    if "/api/" in getattr(request, "path", ""):
        return
    endpoint = getattr(request, "endpoint", "") or ""
    if endpoint and not endpoint.startswith("equipamentos_bp."):
        return
    if not current_user.is_authenticated:
        return
    if endpoint == "equipamentos_bp.get_equipamento":
        return
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or session.get("tipo"))
    if role_key in ("admin", "gestor"):
        return
    perms = current_permissions()
    if perms.get("estoque"):
        return
    if "ESTOQUE" in _dept_names():
        return
    return _deny_access()



# Configuraes de imagem

ALLOWED_EXTS = {"png", "jpg", "jpeg"}

TARGET_W, TARGET_H = 120, 120

IMAGES_DIR = os.path.join("static", "images")





def _ensure_images_dir():

    os.makedirs(IMAGES_DIR, exist_ok=True)





def _save_image_letterbox(file_storage, filename_hint="eq"):

    """

    Valida a extenso, abre a imagem e a salva como PNG 120x120,

    usando letterbox (contain): sem cortes, centralizada e com

    preenchimento transparente (ou branco, se preferir).

    Retorna o caminho relativo "static/images/<arquivo>.png".

    """

    if not file_storage or not getattr(file_storage, "filename", ""):

        raise ValueError("Nenhuma imagem enviada.")



    # Extenso

    _, ext = os.path.splitext(file_storage.filename)

    ext = ext.lower().lstrip(".")

    if ext not in ALLOWED_EXTS:

        raise ValueError(

            "Formato de imagem no aceito. Use PNG, JPG ou JPEG."

        )



    # Abre com Pillow

    try:

        img = Image.open(file_storage.stream)

    except UnidentifiedImageError:

        raise ValueError("Arquivo de imagem invlido ou corrompido.")



    # Converte para RGBA para manter transparncia (se houver)

    if img.mode not in ("RGB", "RGBA"):

        img = img.convert("RGBA")



    # Redimensiona para CABER (contain), sem cortar

    img_copy = img.copy()

    img_copy.thumbnail((TARGET_W, TARGET_H), Image.LANCZOS)



    # Lona 120x120  escolha o fundo:

    # fundo transparente:

    canvas = Image.new("RGBA", (TARGET_W, TARGET_H), (255, 255, 255, 0))

    # (se preferir branco: (255,255,255,255))



    # Centraliza

    off_x = (TARGET_W - img_copy.width) // 2

    off_y = (TARGET_H - img_copy.height) // 2

    canvas.paste(img_copy, (off_x, off_y), img_copy if img_copy.mode == "RGBA" else None)



    # Nome do arquivo final (PNG, compatvel com Word/Docx)

    _ensure_images_dir()

    fname = f"{filename_hint}_{uuid.uuid4().hex}.png"

    rel_path = os.path.join("static", "images", fname)

    abs_path = os.path.join(IMAGES_DIR, fname)



    # Salva otimizado

    canvas.save(abs_path, format="PNG", optimize=True)

    return rel_path  # guardamos caminho relativo (resolvido no gerador)





# --------------------------------------------------------------------------- #

# Cadastro de equipamentos

# --------------------------------------------------------------------------- #

@equipamentos_bp.route("/cadastro_equipamentos", methods=["GET", "POST"])
@equipamentos_bp.route("/estoque", methods=["GET", "POST"], endpoint="estoque")

@login_required

def cadastro_equipamentos():

    page = request.args.get("page", 1, type=int)
    search_query = (request.args.get("q") or "").strip()

    per_page = 10


    def _render(form_obj):
        base_query = Equipment.query
        if search_query:
            like = f"%{search_query}%"
            base_query = base_query.filter(
                or_(Equipment.name.ilike(like), Equipment.description.ilike(like))
            )

        pagination = (

            base_query.order_by(Equipment.name.asc())

            .paginate(page=page, per_page=per_page, error_out=False)

        )

        total_quantity = (

            base_query.with_entities(func.coalesce(func.sum(Equipment.quantity), 0)).scalar() or 0

        )

        equipments = list(pagination.items)
        image_index = _build_static_file_index()
        for eq in equipments:
            eq.image_src = _resolve_equipment_image_src(
                getattr(eq, "_illustration_path", None),
                getattr(eq, "illustration_path", None),
                index=image_index,
            )
            eq.price_label = _format_currency(getattr(eq, "unit_price", 0))
        return render_template(
            "cadastro_equipamentos.html",
            equipments=equipments,
            pagination=pagination,
            total_equipments=pagination.total,
            total_quantity=total_quantity,
            form=form_obj,
            search_query=search_query,
        )


    form = EquipmentForm()

    if form.validate_on_submit():

        # Processa imagem (opcional)

        illustration = form.illustration.data

        saved_path = None

        if illustration and getattr(illustration, "filename", ""):

            try:

                saved_path = _save_image_letterbox(illustration, filename_hint="eq")

            except ValueError as e:

                flash(str(e), "danger")

                return _render(form)


        # Preo

        preco_str = str(form.unit_price.data).replace(".", "").replace(",", ".")

        try:

            preco_float = float(preco_str)

        except ValueError:

            preco_float = 0.0


        eq = Equipment(

            name=form.name.data,

            description=form.description.data,

            unit_price=preco_float,

            quantity=int(form.quantity.data),

            illustration_path=saved_path,  # j relativo a static/images

        )

        db.session.add(eq)

        db.session.commit()

        flash("Equipamento cadastrado com sucesso.", "success")

        return redirect(url_for("equipamentos_bp.estoque", page=page))


    return _render(form)



# --------------------------------------------------------------------------- #

# CRUD via AJAX / Lista

# --------------------------------------------------------------------------- #

@equipamentos_bp.route("/equipamentos/<int:id>", methods=["GET"])

@login_required

def get_equipamento(id):

    eq = Equipment.query.get_or_404(id)

    return jsonify(

        {

            "id": eq.id,

            "nome": eq.name,

            "descricao": eq.description,

            "imagem": eq.illustration_path or "",

            "preco": eq.unit_price,

            "quantidade": eq.quantity,

        }

    )





@equipamentos_bp.route("/equipamentos/<int:id>", methods=["POST"])

@login_required

def editar_equipamento(id):

    eq = Equipment.query.get_or_404(id)

    data = request.json or {}

    eq.name = data.get("nome", eq.name)

    eq.description = data.get("descricao", eq.description)



    preco_str = str(data.get("preco", eq.unit_price)).replace(".", "").replace(",", ".")

    try:

        eq.unit_price = float(preco_str)

    except ValueError:

        pass



    eq.quantity = int(data.get("quantidade", eq.quantity))

    db.session.commit()

    return jsonify({"success": True})





@equipamentos_bp.route("/equipamentos/<int:id>/upload_imagem", methods=["POST"])

@login_required

def upload_imagem_equipamento(id):

    eq = Equipment.query.get_or_404(id)

    imagem = request.files.get("imagem")

    if not imagem:

        return jsonify({"success": False, "error": "Nenhuma imagem enviada."}), 400



    try:

        new_rel_path = _save_image_letterbox(imagem, filename_hint=f"eq{id}")

    except ValueError as e:

        return jsonify({"success": False, "error": str(e)}), 400



    # Remove a antiga (se estiver em static/images)

    old_rel = eq.illustration_path

    eq.illustration_path = new_rel_path

    db.session.commit()



    try:

        if old_rel and old_rel.startswith("static/images"):

            old_abs = os.path.join(os.getcwd(), old_rel)

            if os.path.exists(old_abs):

                os.remove(old_abs)

    except Exception:

        # falha de limpeza no deve quebrar o fluxo

        pass



    return jsonify({"success": True, "imagem": new_rel_path})





@equipamentos_bp.route("/equipamentos/<int:id>", methods=["DELETE"])

@login_required

def excluir_equipamento(id):

    eq = Equipment.query.get_or_404(id)



    # Apaga imagem associada

    try:

        if eq.illustration_path and eq.illustration_path.startswith("static/images"):

            abs_path = os.path.join(os.getcwd(), eq.illustration_path)

            if os.path.exists(abs_path):

                os.remove(abs_path)

    except Exception:

        pass



    db.session.delete(eq)

    db.session.commit()

    return jsonify({"success": True})


# --------------------------------------------------------------------------- #
# Cadastro de Peças
# --------------------------------------------------------------------------- #

@equipamentos_bp.route("/cadastro_pecas", methods=["GET", "POST"])
@equipamentos_bp.route("/pecas", methods=["GET", "POST"], endpoint="pecas")
@login_required
def cadastro_pecas():
    page = request.args.get("page", 1, type=int)
    search_query = (request.args.get("q") or "").strip()
    per_page = 10

    def _render_pecas(form_obj):
        base_query = Part.query
        if search_query:
            like = f"%{search_query}%"
            base_query = base_query.filter(
                or_(Part.name.ilike(like), Part.description.ilike(like))
            )

        pagination = (
            base_query.order_by(Part.name.asc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )

        total_quantity = (
            base_query.with_entities(func.coalesce(func.sum(Part.quantity), 0)).scalar() or 0
        )

        parts_list = list(pagination.items)
        image_index = _build_static_file_index()
        for pc in parts_list:
            pc.image_src = _resolve_equipment_image_src(
                getattr(pc, "_illustration_path", None),
                getattr(pc, "illustration_path", None),
                index=image_index,
            )
            pc.price_label = _format_currency(getattr(pc, "unit_price", 0))

        return render_template(
            "cadastro_pecas.html",
            parts=parts_list,
            pagination=pagination,
            total_parts=pagination.total,
            total_quantity=total_quantity,
            form=form_obj,
            search_query=search_query,
        )

    form = PartForm()
    if form.validate_on_submit():
        illustration = form.illustration.data
        saved_path = None
        if illustration and getattr(illustration, "filename", ""):
            try:
                saved_path = _save_image_letterbox(illustration, filename_hint="pc")
            except ValueError as e:
                flash(str(e), "danger")
                return _render_pecas(form)

        preco_str = str(form.unit_price.data).replace(".", "").replace(",", ".")
        try:
            preco_float = float(preco_str)
        except ValueError:
            preco_float = 0.0

        pc = Part(
            name=form.name.data,
            description=form.description.data,
            unit_price=preco_float,
            quantity=int(form.quantity.data),
            illustration_path=saved_path,
        )
        db.session.add(pc)
        db.session.commit()
        flash("Peça cadastrada com sucesso.", "success")
        return redirect(url_for("equipamentos_bp.pecas", page=page))

    return _render_pecas(form)


@equipamentos_bp.route("/pecas/<int:id>", methods=["GET"])
@login_required
def get_peca(id):
    pc = Part.query.get_or_404(id)
    return jsonify(
        {
            "id": pc.id,
            "nome": pc.name,
            "descricao": pc.description or "",
            "imagem": pc.illustration_path or "",
            "preco": pc.unit_price or 0.0,
            "quantidade": pc.quantity or 0,
        }
    )


@equipamentos_bp.route("/pecas/<int:id>", methods=["POST"])
@login_required
def editar_peca(id):
    pc = Part.query.get_or_404(id)
    data = request.json or {}
    pc.name = data.get("nome", pc.name)
    pc.description = data.get("descricao", pc.description)

    preco_str = str(data.get("preco", pc.unit_price)).replace(".", "").replace(",", ".")
    try:
        pc.unit_price = float(preco_str)
    except ValueError:
        pass

    pc.quantity = int(data.get("quantidade", pc.quantity))
    db.session.commit()
    return jsonify({"success": True})


@equipamentos_bp.route("/pecas/<int:id>/upload_imagem", methods=["POST"])
@login_required
def upload_imagem_peca(id):
    pc = Part.query.get_or_404(id)
    imagem = request.files.get("imagem")
    if not imagem:
        return jsonify({"success": False, "error": "Nenhuma imagem enviada."}), 400

    try:
        new_rel_path = _save_image_letterbox(imagem, filename_hint=f"pc{id}")
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    old_rel = pc.illustration_path
    pc.illustration_path = new_rel_path
    db.session.commit()

    try:
        if old_rel and old_rel.startswith("static/images"):
            old_abs = os.path.join(os.getcwd(), old_rel)
            if os.path.exists(old_abs):
                os.remove(old_abs)
    except Exception:
        pass

    return jsonify({"success": True, "imagem": new_rel_path})


@equipamentos_bp.route("/pecas/<int:id>", methods=["DELETE"])
@login_required
def excluir_peca(id):
    pc = Part.query.get_or_404(id)
    try:
        if pc.illustration_path and pc.illustration_path.startswith("static/images"):
            abs_path = os.path.join(os.getcwd(), pc.illustration_path)
            if os.path.exists(abs_path):
                os.remove(abs_path)
    except Exception:
        pass

    db.session.delete(pc)
    db.session.commit()
    return jsonify({"success": True})










