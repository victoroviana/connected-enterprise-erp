"""Cadastro e personalizacao dos sistemas de ponto."""
import os
import uuid

from flask import render_template, redirect, url_for, flash, request
from werkzeug.utils import secure_filename

from ..auth import login_required
from ..decorators import gestor_ou_admin_required
from . import sistemas_ponto_bp

from extensions import db
from ...models import SystemOptionCatalog, SystemOptionOverride
from ...forms import SystemOptionOverrideForm
from ...utils.systems import iter_system_options, DEFAULT_SYSTEM_OPTIONS
from ...constants import ISSUER_COMPANY_CHOICES

SYSTEM_IMAGE_DIR = "static/system_options"
SYSTEM_IMAGE_ALLOWED_EXTS = {"png", "jpg", "jpeg", "webp"}


def _system_image_storage_dir() -> str:
    try:
        from flask import current_app
        if current_app and current_app.static_folder:
            return os.path.join(current_app.static_folder, "system_options")
    except Exception:
        pass
    return os.path.join(os.getcwd(), SYSTEM_IMAGE_DIR.replace('/', os.sep))


def _save_system_image(file_storage, key: str) -> str:
    if not file_storage or not getattr(file_storage, "filename", ""):
        raise ValueError("Nenhuma imagem enviada.")

    filename = secure_filename(file_storage.filename)
    if not filename:
        raise ValueError("Nome de arquivo inválido.")

    _, ext = os.path.splitext(filename)
    ext = ext.lower().lstrip('.')
    if ext not in SYSTEM_IMAGE_ALLOWED_EXTS:
        raise ValueError("Formato de imagem não suportado. Use PNG, JPG, JPEG ou WEBP.")

    storage_dir = _system_image_storage_dir()
    os.makedirs(storage_dir, exist_ok=True)

    unique = f"{key}_{uuid.uuid4().hex}.{ext}"
    abs_path = os.path.join(storage_dir, unique)
    file_storage.save(abs_path)

    return f"static/system_options/{unique}"


def _delete_system_image(rel_path: str | None) -> None:
    if not rel_path:
        return
    if not rel_path.startswith("static/system_options"):
        return
    fname = os.path.basename(rel_path)
    storage_dir = _system_image_storage_dir()
    abs_path = os.path.join(storage_dir, fname)
    if os.path.exists(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass


@sistemas_ponto_bp.route('/sistemas_ponto', methods=['GET'])
@login_required
@gestor_ou_admin_required
def listar_sistemas_ponto():
    branch_code = (request.args.get('issuer_branch_code') or '').strip()
    branch_map = dict(ISSUER_COMPANY_CHOICES)
    if branch_code and branch_code not in branch_map:
        branch_code = ''
    branch_label = branch_map.get(branch_code, 'Todas as unidades')

    overrides = {ov.key: ov for ov in SystemOptionOverride.query.all()}
    custom_options = {opt.key: opt for opt in SystemOptionCatalog.query.all()}
    system_cards = []
    for option in iter_system_options():
        override = overrides.get(option.key)
        custom = custom_options.get(option.key)
        form_override = SystemOptionOverrideForm(prefix=option.key)
        if not form_override.is_submitted():
            if override and override.description:
                form_override.description.data = override.description
            elif custom and custom.description:
                form_override.description.data = custom.description
            else:
                form_override.description.data = ''
            form_override.remove_image.data = False

        if custom:
            image_path = custom.image_path or option.image
        else:
            image_path = override.image_path if override and override.image_path else option.image
        image_url = None
        if image_path:
            if image_path.startswith('static/'):
                image_url = url_for('static', filename=image_path.split('static/', 1)[1])
            elif image_path.startswith('/'):
                image_url = image_path
            else:
                image_url = url_for('static', filename=image_path)

        system_cards.append({
            'option': option,
            'form': form_override,
            'override': override,
            'image_url': image_url,
            'uses_default_image': not (custom.image_path if custom else (override and override.image_path)),
        })

    return render_template(
        'admin_sistemas_ponto.html',
        system_cards=system_cards,
        branch_choices=ISSUER_COMPANY_CHOICES,
        branch_sel=branch_code,
        branch_label=branch_label,
    )


@sistemas_ponto_bp.route('/sistemas_ponto/system-options/<key>', methods=['POST'])
@login_required
@gestor_ou_admin_required
def atualizar_sistema_de_ponto(key: str):
    custom = SystemOptionCatalog.query.filter_by(key=key).first()
    if key not in DEFAULT_SYSTEM_OPTIONS and not custom:
        flash('Sistema de Ponto desconhecido.', 'danger')
        return redirect(url_for('sistemas_ponto_bp.listar_sistemas_ponto'))

    form = SystemOptionOverrideForm(prefix=key)
    if not form.validate_on_submit():
        form_fallback = SystemOptionOverrideForm()
        if form_fallback.validate_on_submit():
            form = form_fallback

    raw_desc = form.description.data
    if raw_desc is None:
        raw_desc = request.form.get(f"{key}-description") or request.form.get("description")
    new_description = (raw_desc or "").strip()

    remove_image_val = bool(form.remove_image.data) or (
        request.form.get(f"{key}-remove_image") in ("1", "y", "true", "on") or
        request.form.get("remove_image") in ("1", "y", "true", "on")
    )

    image_file = form.image.data
    if not image_file or not getattr(image_file, "filename", ""):
        image_file = request.files.get(f"{key}-image") or request.files.get("image")

    if custom:
        new_image_path = custom.image_path
        if remove_image_val:
            _delete_system_image(new_image_path)
            new_image_path = None
        elif image_file and getattr(image_file, "filename", ""):
            try:
                uploaded_path = _save_system_image(image_file, key)
            except ValueError as exc:
                flash(str(exc), 'danger')
                return redirect(url_for('sistemas_ponto_bp.listar_sistemas_ponto'))
            _delete_system_image(new_image_path)
            new_image_path = uploaded_path

        custom.description = new_description or None
        custom.image_path = new_image_path
        db.session.commit()
        flash('Sistema de Ponto atualizado com sucesso.', 'success')
        redirect_params = {}
        branch_code = (request.form.get('issuer_branch_code') or '').strip()
        if branch_code:
            redirect_params['issuer_branch_code'] = branch_code
        return redirect(url_for('sistemas_ponto_bp.listar_sistemas_ponto', **redirect_params))

    override = SystemOptionOverride.query.filter_by(key=key).first()
    is_new = override is None
    if is_new:
        override = SystemOptionOverride(key=key)

    new_image_path = override.image_path

    if remove_image_val:
        _delete_system_image(new_image_path)
        new_image_path = None
    elif image_file and getattr(image_file, "filename", ""):
        try:
            uploaded_path = _save_system_image(image_file, key)
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('sistemas_ponto_bp.listar_sistemas_ponto'))
        _delete_system_image(new_image_path)
        new_image_path = uploaded_path

    override.description = new_description or None
    override.image_path = new_image_path

    if override.description or override.image_path:
        if is_new:
            db.session.add(override)
        db.session.commit()
        flash('Sistema de Ponto atualizado com sucesso.', 'success')
    else:
        if not is_new:
            db.session.delete(override)
            db.session.commit()
            flash('Registro personalizado removido; valores padrão restabelecidos.', 'info')
        else:
            flash('Nenhuma alteração aplicada.', 'info')

    redirect_params = {}
    branch_code = (request.form.get('issuer_branch_code') or '').strip()
    if branch_code:
        redirect_params['issuer_branch_code'] = branch_code

    return redirect(url_for('sistemas_ponto_bp.listar_sistemas_ponto', **redirect_params))

