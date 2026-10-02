"""Rotas de login e logout."""
from __future__ import annotations

from urllib.parse import urlparse, urljoin

from flask import (
    render_template, redirect, url_for,
    flash, request, session, current_app, jsonify, make_response,
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from pathlib import Path
import time
from werkzeug.security import check_password_hash

from extensions import csrf
from . import auth_bp         # Blueprint criado em __init__.py
from .permissions_utils import (
    effective_permissions,
    normalize_role_key,
    normalize_permissions,
    resolve_role_meta,
)
from ...models import User

ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def _is_safe_url(target: str) -> bool:
    """Return True only when 'target' is a relative URL or matches the current host."""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def _avatar_upload_dir() -> Path:
    static_dir = Path(current_app.static_folder)
    target = static_dir / "uploads" / "avatars"
    target.mkdir(parents=True, exist_ok=True)
    return target



@auth_bp.route("/login", methods=["GET", "POST"])
@auth_bp.route("/login_ajax", methods=["POST"], endpoint="login_ajax")
@csrf.exempt
def login():
    current_app.logger.info("auth.login accessed method=%s", request.method)

    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.is_json
        or request.path.endswith("/login_ajax")
        or request.args.get("ajax") == "1"
    )

    if request.method == "POST":
        data = request.get_json(silent=True) or request.form.to_dict()
        login_identifier = (data.get("usuario") or data.get("email") or "").strip()
        senha_form = data.get("senha") or data.get("password")

        user = None
        if login_identifier:
            user = User.query.filter_by(usuario=login_identifier).first()
            if not user:
                user = User.query.filter(User.email.ilike(login_identifier)).first()

        if user and senha_form and check_password_hash(user.password_hash, senha_form):
            session.clear()
            login_user(user)

            role_key = normalize_role_key(user.tipo or user.role or "usuario")
            role_label, role_initials = resolve_role_meta(role_key)

            perms = effective_permissions(user)

            session.update(
                {
                    "usuario_id": user.id,
                    "usuario": user.usuario,
                    "nome": user.nome_completo,
                    "email": user.email,
                    "tipo": role_key,
                    "role_label": role_label,
                    "role_initials": role_initials,
                    "prox_num": user.prox_num or 1,
                    "avatar_path": user.avatar_path,
                    "signature_path": user.signature_path,
                    "signature_text": user.signature_text,
                    "phone": user.phone or '',
                    "extra_phones": user.extra_phones or [],
                    "permissions": perms,
                }
            )
            session.permanent = True

            next_url = request.args.get("next") or data.get("next")
            if not next_url or not _is_safe_url(next_url):
                next_url = url_for("index")

            if is_ajax:
                return jsonify({
                    "ok": True,
                    "msg": "Login realizado com sucesso!",
                    "redirect": next_url,
                })

            flash("Login realizado com sucesso!", "success")
            return redirect(next_url)

        if is_ajax:
            return jsonify({
                "ok": False,
                "msg": "Usuário ou senha inválidos.",
            }), 401

        flash("Usuário ou senha inválidos.", "danger")

    current_app.logger.info("Rendering auth/login.html template")
    resp = make_response(render_template("auth/login.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@auth_bp.route("/logout")
def logout():
    logout_user()
    session.clear()
    flash("Logout realizado com sucesso.", "info")
    return redirect(url_for("auth_bp.login"))


def _signature_upload_dir() -> Path:
    target = Path(current_app.static_folder) / "signatures"
    target.mkdir(parents=True, exist_ok=True)
    return target


@auth_bp.route("/profile/avatar", methods=["POST"])
@auth_bp.route("/profile/update", methods=["POST"])
@login_required
def update_avatar():
    from PIL import Image

    file = request.files.get("avatar")
    filename = (file.filename or "") if file else ""
    ext = filename.rsplit(".", 1)[-1].lower() if file and "." in filename else ""

    if file and not filename:
        file = None
        filename = ""
        ext = ""

    if file and ext not in ALLOWED_AVATAR_EXTENSIONS:
        flash("Formatos de avatar permitidos: png, jpg, jpeg, webp.", "danger")
        return redirect(request.referrer or url_for("index"))

    phone_raw = (request.form.get("phone") or "").strip()
    current_phone = current_user.phone or ""
    phone_changed = False
    if phone_raw != current_phone:
        current_user.phone = phone_raw or None
        session["phone"] = phone_raw
        phone_changed = True

    extra_submitted = [value.strip() for value in request.form.getlist("extra_phones[]") if value.strip()]
    extras_changed = extra_submitted != (current_user.extra_phones or [])
    if extras_changed:
        current_user.extra_phones = extra_submitted
        session["extra_phones"] = extra_submitted

    avatar_updated = False
    if file:
        safe_name = secure_filename(f"avatar_{current_user.id}_{int(time.time())}.{ext}")
        target_dir = _avatar_upload_dir()
        destination = target_dir / safe_name
        file.save(destination)

        if current_user.avatar_path:
            old = Path(current_app.static_folder) / current_user.avatar_path
            try:
                old.unlink(missing_ok=True)
            except Exception:
                pass

        relative_path = f"uploads/avatars/{safe_name}"
        current_user.avatar_path = relative_path
        session["avatar_path"] = relative_path
        avatar_updated = True

    # ── Assinatura em texto ──
    sig_text_raw = request.form.get("signature_text")
    sig_text_changed = False
    if sig_text_raw is not None:
        clean_sig = sig_text_raw.strip() or None
        if clean_sig != (current_user.signature_text or None):
            current_user.signature_text = clean_sig
            session["signature_text"] = clean_sig
            sig_text_changed = True

    # ── Remoção da imagem de assinatura ──
    remove_sig = request.form.get("remove_signature_image") == "1"
    sig_removed = False
    if remove_sig and current_user.signature_path:
        old_sig = Path(current_app.static_folder) / current_user.signature_path
        try:
            old_sig.unlink(missing_ok=True)
        except Exception:
            pass
        current_user.signature_path = None
        session["signature_path"] = None
        sig_removed = True

    # ── Upload de nova imagem de assinatura ──
    sig_file = request.files.get("signature_image")
    sig_filename = (sig_file.filename or "") if sig_file else ""
    sig_ext = sig_filename.rsplit(".", 1)[-1].lower() if sig_file and "." in sig_filename else ""
    if sig_file and not sig_filename:
        sig_file = None

    sig_updated = False
    if sig_file:
        if sig_ext not in {"png", "jpg", "jpeg", "webp"}:
            flash("Formato de assinatura inválido. Use PNG, JPG ou WEBP.", "danger")
            return redirect(request.referrer or url_for("index"))

        sig_dir = _signature_upload_dir()
        sig_name = f"user_{current_user.id}.png"
        sig_dest = sig_dir / sig_name

        try:
            sig_file.stream.seek(0)
            with Image.open(sig_file.stream) as img:
                img = img.convert('RGBA')
                img.thumbnail((800, 240), Image.LANCZOS)
                img.save(str(sig_dest), format='PNG', optimize=True)
            rel_sig_path = f"signatures/{sig_name}"
            current_user.signature_path = rel_sig_path
            session["signature_path"] = rel_sig_path
            sig_updated = True
        except Exception as exc:
            current_app.logger.warning("Falha ao salvar assinatura em imagem: %s", exc)
            flash("Erro ao processar imagem de assinatura.", "danger")
            return redirect(request.referrer or url_for("index"))

    if not phone_changed and not extras_changed and not avatar_updated and not sig_text_changed and not sig_removed and not sig_updated:
        flash("Nenhuma alteração realizada.", "info")
        return redirect(request.referrer or url_for("index"))

    from extensions import db  # import tardio para evitar ciclo

    db.session.commit()
    flash("Perfil e assinatura atualizados com sucesso!", "success")
    return redirect(request.referrer or url_for("index"))
