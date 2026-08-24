"""Gerenciamento de parametros e configuracoes do Sistema de Ponto."""

import os
import re
import uuid
import unicodedata

from functools import wraps
from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    request,
    session,
    jsonify,
)
from flask_login import current_user
from werkzeug.utils import secure_filename

from ..auth import login_required
from ..auth.permissions_utils import normalize_role_key
from . import parametros_bp

from utils.helpers import (
    normalize_dept_name as _normalize_dept_name,
)

from extensions import db
from sqlalchemy.exc import IntegrityError
from ...models import (
    ParamOption,
    ParamCategory,
    User,
    SystemOptionCatalog,
    SystemOptionState,
    SystemOptionOverride,
)
from ...forms import ParamOptionForm, SystemOptionOverrideForm, SystemOptionCreateForm
from ...utils.systems import iter_system_options, DEFAULT_SYSTEM_OPTIONS

SYSTEM_IMAGE_DIR = "static/system_options"
SYSTEM_IMAGE_ALLOWED_EXTS = {"png", "jpg", "jpeg", "webp"}


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------
def _system_image_storage_dir() -> str:
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

    # Path stored in database uses forward slashes for compatibility with url_for
    return f"static/system_options/{unique}"


def _delete_system_image(rel_path: str | None) -> None:
    if not rel_path:
        return
    if not rel_path.startswith("static/system_options"):
        return
    abs_path = os.path.join(os.getcwd(), rel_path.replace('/', os.sep))
    if os.path.exists(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass




def _normalize_system_key(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text[:64].strip("_")


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


# ------------------------------------------------------------------
# Decorator: apenas administradores ou gestores
# ------------------------------------------------------------------
def gestor_ou_admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        role_key = normalize_role_key(getattr(current_user, "tipo", None) or session.get("tipo"))
        if role_key in ("admin", "gestor", "consultor"):
            return f(*args, **kwargs)
        if "COMERCIAL" in _dept_names():
            return f(*args, **kwargs)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": "Você não tem permissão para acessar esta área."}), 403
        flash("Você não tem permissão para acessar esta área.", "warning")
        return redirect(url_for("sem_permissao", area="Cadastros"))

    return wrapper


# ------------------------------------------------------------------
# Listar + criar parametros + gerenciar Sistema de Ponto
# ------------------------------------------------------------------
@parametros_bp.route('/parametros', methods=['GET', 'POST'])
@login_required
@gestor_ou_admin_required
def listar_parametros():
    form = ParamOptionForm()
    system_create_form = SystemOptionCreateForm()

    if form.validate_on_submit():
        user = User.query.get(session.get("usuario_id"))
        label_text = (form.label.data or '').strip()
        novo_valor = ParamOption(
            category=form.category.data,
            label=label_text,
            created_by=user,
        )
        db.session.add(novo_valor)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('J existe um parmetro com esse valor para a categoria selecionada.', 'warning')
        else:
            flash('Opcao criada com sucesso!', 'success')
        return redirect(url_for('.listar_parametros'))

    parametros = ParamOption.query.order_by(
        ParamOption.category,
        ParamOption.label,
    ).all()

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
            'is_custom': bool(custom),
        })

    return render_template(
        'admin_parametros.html',
        form=form,
        system_create_form=system_create_form,
        parametros=parametros,
        system_cards=system_cards,
    )


# ------------------------------------------------------------------
# Deletar parametro
# ------------------------------------------------------------------
@parametros_bp.route('/parametros/<int:id>/delete', methods=['POST'])
@login_required
@gestor_ou_admin_required
def deletar_parametro(id):
    opt = ParamOption.query.get_or_404(id)
    db.session.delete(opt)
    db.session.commit()
    flash('Opcao removida.', 'info')
    return redirect(url_for('.listar_parametros'))


# ------------------------------------------------------------------
# Criar novo Sistema de Ponto
# ------------------------------------------------------------------
@parametros_bp.route('/parametros/system-options', methods=['POST'])
@login_required
@gestor_ou_admin_required
def criar_sistema_de_ponto():
    form = SystemOptionCreateForm()
    if not form.validate_on_submit():
        flash('Verifique os dados enviados para o Sistema de Ponto.', 'danger')
        return redirect(url_for('.listar_parametros'))

    label = (form.label.data or '').strip()
    raw_key = (form.key.data or '').strip()
    key = _normalize_system_key(raw_key or label)
    if not key:
        flash('Chave inválida para o Sistema de Ponto.', 'danger')
        return redirect(url_for('.listar_parametros'))
    if key in DEFAULT_SYSTEM_OPTIONS:
        flash('Chave ja usada por um sistema padrao.', 'danger')
        return redirect(url_for('.listar_parametros'))
    if SystemOptionCatalog.query.filter_by(key=key).first():
        flash('Ja existe um sistema com essa chave.', 'danger')
        return redirect(url_for('.listar_parametros'))

    image_path = None
    if form.image.data:
        try:
            image_path = _save_system_image(form.image.data, key)
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('.listar_parametros'))

    new_system = SystemOptionCatalog(
        key=key,
        label=label,
        description=(form.description.data or '').strip() or None,
        image_path=image_path,
        default_quantity=1,
        unit_price=0.0,
        created_by_id=session.get("usuario_id"),
    )
    db.session.add(new_system)
    db.session.commit()
    flash('Sistema de Ponto criado com sucesso.', 'success')
    return redirect(url_for('.listar_parametros'))


# ------------------------------------------------------------------
# Excluir Sistema de Ponto
# ------------------------------------------------------------------
@parametros_bp.route('/parametros/system-options/<key>/delete', methods=['POST'])
@login_required
@gestor_ou_admin_required
def deletar_sistema_de_ponto(key: str):
    custom = SystemOptionCatalog.query.filter_by(key=key).first()
    if custom:
        _delete_system_image(custom.image_path)
        override = SystemOptionOverride.query.filter_by(key=key).first()
        if override:
            _delete_system_image(override.image_path)
            db.session.delete(override)
        db.session.delete(custom)
        db.session.commit()
        flash('Sistema de Ponto removido com sucesso.', 'info')
        return redirect(url_for('.listar_parametros'))

    if key in DEFAULT_SYSTEM_OPTIONS:
        override = SystemOptionOverride.query.filter_by(key=key).first()
        if override:
            _delete_system_image(override.image_path)
            db.session.delete(override)
        state = SystemOptionState.query.filter_by(key=key).first()
        if not state:
            state = SystemOptionState(key=key, is_active=False)
            db.session.add(state)
        else:
            state.is_active = False
        db.session.commit()
        flash('Sistema de Ponto removido com sucesso.', 'info')
        return redirect(url_for('.listar_parametros'))

    flash('Sistema de Ponto não encontrado.', 'warning')
    return redirect(url_for('.listar_parametros'))


# ------------------------------------------------------------------
# Atualizar Sistema de Ponto (descricao + imagem)
# ------------------------------------------------------------------
@parametros_bp.route('/parametros/system-options/<key>', methods=['POST'])
@login_required
@gestor_ou_admin_required
def atualizar_sistema_de_ponto(key: str):
    custom = SystemOptionCatalog.query.filter_by(key=key).first()
    if key not in DEFAULT_SYSTEM_OPTIONS and not custom:
        flash('Sistema de Ponto desconhecido.', 'danger')
        return redirect(url_for('.listar_parametros'))

    form = SystemOptionOverrideForm()
    if not form.validate_on_submit():
        flash('Verifique os dados enviados para o Sistema de Ponto.', 'danger')
        return redirect(url_for('.listar_parametros'))

    new_description = (form.description.data or '').strip()
    if custom:
        new_image_path = custom.image_path
        if form.remove_image.data:
            _delete_system_image(new_image_path)
            new_image_path = None
        elif form.image.data:
            try:
                uploaded_path = _save_system_image(form.image.data, key)
            except ValueError as exc:
                flash(str(exc), 'danger')
                return redirect(url_for('.listar_parametros'))
            _delete_system_image(new_image_path)
            new_image_path = uploaded_path

        custom.description = new_description or None
        custom.image_path = new_image_path
        db.session.commit()
        flash('Sistema de Ponto atualizado com sucesso.', 'success')
        return redirect(url_for('.listar_parametros'))

    override = SystemOptionOverride.query.filter_by(key=key).first()
    is_new = override is None
    if is_new:
        override = SystemOptionOverride(key=key)

    new_image_path = override.image_path

    if form.remove_image.data:
        _delete_system_image(new_image_path)
        new_image_path = None
    elif form.image.data:
        try:
            uploaded_path = _save_system_image(form.image.data, key)
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('.listar_parametros'))
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
            flash('Registro personalizado removido; valores padro restabelecidos.', 'info')
        else:
            flash('Nenhuma alteracao aplicada.', 'info')

    return redirect(url_for('.listar_parametros'))
