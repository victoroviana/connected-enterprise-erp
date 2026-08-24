"""Central app factory for the Sollus platform."""
from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

import calendar
from datetime import date, datetime

from flask import Flask, redirect, render_template, request, url_for, flash, send_from_directory
from markupsafe import Markup
from sqlalchemy import func, text

from extensions import csrf, db, login_manager, mail, migrate
from utils.theme_calendar import get_active_theme
from utils.timezone import get_local_timezone


DEFAULT_CONFIG_OBJECT = "config.Config"


def _enforce_utf8_defaults() -> None:
    """Force UTF-8 locales/streams when the runtime allows it."""
    import locale
    import os
    import sys

    os.environ.setdefault("PYTHONUTF8", "1")

    for name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    try:
        locale.setlocale(locale.LC_ALL, "pt_BR.UTF-8")
    except locale.Error:
        try:
            locale.setlocale(locale.LC_ALL, "pt_BR")
        except locale.Error:
            pass

_enforce_utf8_defaults()


def _sanitize_mojibake(value: Any) -> Any:
    if value is None:
        return value
    if isinstance(value, Markup):
        fixed = _sanitize_mojibake(str(value))
        return Markup(fixed)
    if isinstance(value, str):
        try:
            fixed = value.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value
        return fixed
    if isinstance(value, (list, tuple)):
        fixed = [_sanitize_mojibake(item) for item in value]
        return type(value)(fixed)
    return value


GALLERY_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _list_gallery_images(root: Path, limit: int | None = None) -> list[str]:
    if not root.exists():
        return []
    files = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in GALLERY_EXTENSIONS]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if limit:
        files = files[:limit]
    return [p.name for p in files]


def _resolve_gallery_file(filename: str | None, root: Path) -> tuple[bool, str | None]:
    if not filename:
        return False, None
    try:
        base = Path(str(filename)).name
        if not base:
            return False, None
        if Path(base).suffix.lower() not in GALLERY_EXTENSIONS:
            return False, None
        target = root / base
        if not target.exists() or not target.is_file():
            return False, None
        return True, base
    except Exception:
        return False, None


def _can_view_gallery() -> bool:
    try:
        from flask_login import current_user

        return bool(current_user.is_authenticated)
    except Exception:
        return False



def create_app(config_object: Any | None = None) -> Flask:
    """Create the Flask application with shared extensions and modules."""
    app = Flask(
        __name__,
        static_folder="../static",
        template_folder="../templates",
    )

    _load_config(app, config_object)
    
    # Clean up any leftover maintenance mode file on startup
    try:
        import os
        maintenance_file = os.path.join(app.instance_path, "maintenance.json")
        if os.path.exists(maintenance_file):
            os.remove(maintenance_file)
    except Exception:
        pass

    # Track online users in memory
    app.online_users_cache = {}

    @app.before_request
    def update_last_seen():
        from flask_login import current_user
        import time
        try:
            if current_user and current_user.is_authenticated:
                app.online_users_cache[current_user.id] = time.time()
        except Exception:
            pass
    
    
    def to_local(dt, fmt=None):
        if dt is None:
            return ""
        if isinstance(dt, str):
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            except Exception:
                return dt
        if not hasattr(dt, "astimezone"):
            return dt
        if dt.tzinfo is None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        
        local_dt = dt.astimezone(get_local_timezone())
        if fmt:
            return local_dt.strftime(fmt)
        return local_dt

    def urlize_html(value):
        if not value:
            return ""
        import html
        import re
        escaped_text = html.escape(html.unescape(str(value)))
        
        def replace_bracketed(m):
            raw_url = m.group(1)
            # Reconstruct URL by removing internal whitespaces/newlines/carriage returns
            clean_url = re.sub(r'[\r\n\s]+', '', raw_url)
            href = html.unescape(clean_url)
            return f'<a href="{href}" target="_blank" class="text-decoration-underline">{clean_url}</a>'

        escaped_text = re.sub(
            r'&lt;(https?://(?:(?!&gt;|&lt;)[^\s<>]|\r?\n)+)&gt;',
            replace_bracketed,
            escaped_text,
            flags=re.I
        )
        pattern = re.compile(
            r'(<a\s+[^>]*>.*?</a>)|(https?://(?:(?!&gt;|&lt;)[^\s<>])+?(?=[.,;:?!]*(?:\s|$)))',
            re.I
        )
        def repl(match):
            if match.group(1):
                return match.group(1)
            url = match.group(2)
            href = html.unescape(url)
            return f'<a href="{href}" target="_blank" class="text-decoration-underline">{url}</a>'
        return Markup(pattern.sub(repl, escaped_text))

    def _clean_mangled_bullets(text: str) -> str:
        if not text:
            return ""
        import re
        # Clean mangled bullet points starting with ?
        text = re.sub(r"(?m)^\s*\?\s+", "• ", text)
        # Add a blank line before list markers (•, -, *) if not already preceded by one
        text = re.sub(r'(?<!\n)\n\s*([•\-\*])\s+', r'\n\n\1 ', text)
        return text

    def split_email_history(text):
        if not text:
            return "", []
        import re
        lines = text.splitlines()
        primary_lines = []
        history_blocks = []
        
        current_header = []
        current_body = []
        in_history = False
        
        header_start_re = re.compile(
            r"^\s*(?:>\s*)*(?:"
            r"Em\s+.*,\s+\d+\s+de\s+.*\s+escreveu:|"
            r"On\s+.*,\s+.*wrote:|"
            r"\*?De:\*?\s+|"
            r"-----Original Message-----"
            r")",
            re.IGNORECASE
        )
        
        subject_line_re = re.compile(
            r"^\s*(?:>\s*)*(?:\*?Assunto:\*?|\*?Subject:\*?)\s+",
            re.IGNORECASE
        )

        def matches_header_start(idx):
            for num_lines in (1, 2, 3):
                if idx + num_lines > len(lines):
                    continue
                joined = " ".join(lines[idx:idx+num_lines])
                if header_start_re.match(joined):
                    return num_lines
            return 0
            
        i = 0
        while i < len(lines):
            num_header_lines = matches_header_start(i)
            if num_header_lines > 0:
                if in_history:
                    history_blocks.append({
                        'header': "\n".join(current_header).strip(),
                        'body': "\n".join(current_body).strip()
                    })
                    current_header = []
                    current_body = []
                else:
                    in_history = True
                
                joined_header_text = " ".join(lines[i:i+num_header_lines])
                if "De:" in joined_header_text or "*De:*" in joined_header_text or "From:" in joined_header_text or "*From:*" in joined_header_text:
                    for k in range(num_header_lines):
                        current_header.append(lines[i+k])
                    i += num_header_lines
                    
                    found_subject = False
                    if subject_line_re.match(joined_header_text):
                        found_subject = True
                    
                    while i < len(lines):
                        if found_subject:
                            break
                        line = lines[i]
                        if subject_line_re.match(line):
                            found_subject = True
                            current_header.append(line)
                            i += 1
                            continue
                        if len(current_header) > 15:
                            break
                        if matches_header_start(i) > 0:
                            break
                        current_header.append(line)
                        i += 1
                    continue
                else:
                    for k in range(num_header_lines):
                        current_header.append(lines[i+k])
                    i += num_header_lines
                    continue
                    
            if in_history:
                current_body.append(lines[i])
            else:
                primary_lines.append(lines[i])
            i += 1
            
        if in_history and (current_header or current_body):
            history_blocks.append({
                'header': "\n".join(current_header).strip(),
                'body': "\n".join(current_body).strip()
            })
            
        primary_body = "\n".join(primary_lines).strip()
        return primary_body, history_blocks

    def clean_quoted_lines(text):
        if not text:
            return ""
        import re
        lines = text.splitlines()
        cleaned = []
        for line in lines:
            m = re.match(r"^\s*>\s?(.*)$", line)
            if m:
                cleaned.append(m.group(1))
            else:
                cleaned.append(line)
        return "\n".join(cleaned).strip()

    def format_thread_body(value):
        if not value:
            return ""
        
        primary_body, history = split_email_history(value)
        primary_body = _clean_mangled_bullets(primary_body)
        
        html_out = []
        html_out.append(f'<div class="primary-message" style="white-space:pre-wrap; line-height: 1.6;">')
        html_out.append(urlize_html(primary_body))
        html_out.append(f'</div>')
        
        if history:
            unique_id = f"collapse-{abs(hash(value))}"
            html_out.append(f'<div class="email-history-container mt-4 pt-3 border-top border-secondary border-opacity-10">')
            html_out.append(f'  <button class="btn btn-xs btn-soft-secondary rounded-pill px-3 mb-3 d-flex align-items-center gap-1" type="button" data-bs-toggle="collapse" data-bs-target="#{unique_id}">')
            html_out.append(f'    <i class="bi bi-chevron-down"></i> Histórico de E-mails ({len(history)})')
            html_out.append(f'  </button>')
            html_out.append(f'  <div class="collapse" id="{unique_id}">')
            html_out.append(f'    <div class="d-flex flex-column gap-3 ms-3 ps-2 border-start border-primary border-opacity-25">')
            
            for idx, block in enumerate(history):
                cleaned_header = block['header']
                from markupsafe import escape
                header_lines = [str(escape(line)).strip() for line in cleaned_header.splitlines() if line.strip()]
                header_html = "<br>".join(header_lines)
                
                cleaned_body = clean_quoted_lines(block['body'])
                cleaned_body = _clean_mangled_bullets(cleaned_body)
                body_html = urlize_html(cleaned_body)
                
                html_out.append(f'      <div class="email-history-block p-3 rounded-4" style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04);">')
                html_out.append(f'        <div class="email-history-header small text-muted mb-2 pb-2 border-bottom border-secondary border-opacity-10" style="font-size: 0.8rem; line-height: 1.4;">')
                html_out.append(header_html)
                html_out.append(f'        </div>')
                html_out.append(f'        <div class="email-history-body text-body small" style="white-space:pre-wrap; line-height: 1.6;">')
                html_out.append(body_html)
                html_out.append(f'        </div>')
                html_out.append(f'      </div>')
                
            html_out.append(f'    </div>')
            html_out.append(f'  </div>')
            html_out.append(f'</div>')
            
        from markupsafe import Markup
        return Markup("\n".join(str(x) for x in html_out))

    app.jinja_env.filters["local"] = to_local
    app.jinja_env.filters["urlize_html"] = urlize_html
    app.jinja_env.filters["format_thread_body"] = format_thread_body
    app.jinja_env.finalize = _sanitize_mojibake
    _configure_logging(app)
    _init_extensions(app)
    _register_modules(app)
    _register_root_routes(app)
    _register_signal_handlers(app)
    _register_error_handlers(app)

    @app.context_processor
    def inject_ui_theme():  # pragma: no cover - simple context provider
        preview = request.args.get("preview_theme_date") or request.args.get("theme_date")
        override_theme = None
        if preview:
            try:
                parsed_date = datetime.strptime(preview, "%Y-%m-%d").date()
                override_theme = get_active_theme(parsed_date)
            except ValueError:
                override_theme = None
        return {"ui_theme": override_theme or get_active_theme(), "ui_theme_preview_date": preview}

    @app.context_processor
    def inject_current_permissions():  # pragma: no cover - simple context provider
        try:
            from flask import session
            from modules.propostas.blueprints.auth.permissions_utils import current_permissions

            perms = current_permissions()
        except Exception:
            perms = session.get("permissions") if "session" in locals() else {}
        return {"current_permissions": perms}

    app.wsgi_app = _DiagnosticMiddleware(app.wsgi_app)  # type: ignore[assignment]

    # _optimize_database_performance(app)

    return app


def _load_config(app: Flask, config_object: Any | None) -> None:
    """Load configuration from object, module or defaults."""
    loaded = False

    if config_object is not None:
        app.config.from_object(config_object)
        loaded = True
    else:
        try:
            from config import Config as DefaultConfig  # type: ignore import

            app.config.from_object(DefaultConfig)
            loaded = True
        except Exception:
            pass

        if not loaded:
            try:
                app.config.from_pyfile("config.py")
                loaded = True
            except Exception:
                pass

    app.config.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///app.db")
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    # Secure fallback: generate a random key so sessions are invalidated on restart
    # rather than using a predictable static string.  Set SECRET_KEY in .env for production.
    if not app.config.get("SECRET_KEY"):
        import secrets
        import sys
        _generated_key = secrets.token_hex(32)
        app.config["SECRET_KEY"] = _generated_key
        sys.stdout.write(
            "[SECURITY WARNING] SECRET_KEY not set — generated a random key for this session. "
            "All existing sessions will be invalidated on every restart. "
            "Set SECRET_KEY in your .env file for persistent sessions.\n"
        )
        sys.stdout.flush()

    app.config.setdefault("JSON_AS_ASCII", False)


def _init_extensions(app: Flask) -> None:
    """Initialise Flask extensions that are shared across modules."""
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth_bp.login"
    login_manager.login_message_category = "warning"
    csrf.init_app(app)

    try:
        mail.init_app(app)
    except Exception:
        pass


def _register_modules(app: Flask) -> None:
    """Import and initialise all platform modules."""
    proposals = import_module("modules.propostas")
    proposals.init_app(app)

    from modules.propostas.models import User

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return User.query.get(int(user_id))
        except (TypeError, ValueError):
            return None

    try:
        chamados = import_module("modules.chamados")
        if hasattr(chamados, "init_app"):
            chamados.init_app(app)
    except Exception as exc:  # pragma: no cover - logged for visibility
        app.logger.exception("Failed to initialise chamados module: %s", exc)

    try:
        sollus_tickets = import_module("modules.sollus_tickets")
        if hasattr(sollus_tickets, "init_app"):
            sollus_tickets.init_app(app)
    except Exception as exc:  # pragma: no cover - logged for visibility
        app.logger.exception("Failed to initialise Sollus Tickets module: %s", exc)

    try:
        suporte = import_module("modules.suporte")
        if hasattr(suporte, "init_app"):
            suporte.init_app(app)
    except Exception as exc:  # pragma: no cover - logged for visibility
        app.logger.exception("Failed to initialise suporte module: %s", exc)

    try:
        financeiro = import_module("modules.financeiro")
        if hasattr(financeiro, "init_app"):
            financeiro.init_app(app)
    except Exception as exc:  # pragma: no cover - logged for visibility
        app.logger.exception("Failed to initialise financeiro module: %s", exc)

    try:
        contratos = import_module("modules.contratos")
        if hasattr(contratos, "init_app"):
            contratos.init_app(app)
    except Exception as exc:  # pragma: no cover - logged for visibility
        app.logger.exception("Failed to initialise contratos module: %s", exc)

    try:
        cracha = import_module("modules.cracha")
        if hasattr(cracha, "init_app"):
            cracha.init_app(app)
    except Exception as exc:  # pragma: no cover - logged for visibility
        app.logger.exception("Failed to initialise cracha module: %s", exc)

    # Ensure audit listeners are bound globally so CRUD em qualquer módulo
    # seja registrado, inclusive fora do contexto de chamados.
    try:
        import_module("modules.audit.listeners")
    except Exception as exc:  # pragma: no cover - tolerante
        app.logger.exception("Failed to initialise audit listeners: %s", exc)


def _register_root_routes(app: Flask) -> None:
    """Register root-level routes shared across modules."""
    from modules.propostas.blueprints.auth import login_required
    from modules.propostas.models import Birthday, VacationEntry, User

    @app.route("/")
    @login_required
    def index() -> Any:
        today = date.today()
        month_start = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        month_end = today.replace(day=last_day)

        birthdays = (
            Birthday.query.filter(func.extract("month", Birthday.data_nascimento) == today.month)
            .order_by(func.extract("day", Birthday.data_nascimento))
            .all()
        )
        vacations = (
            VacationEntry.query.filter(
                VacationEntry.data_inicial <= month_end,
                VacationEntry.data_final >= month_start,
            ).all()
        )

        def _normalize_name(value: str | None) -> str:
            return (value or "").strip().casefold()

        name_keys = {_normalize_name(entry.nome) for entry in birthdays if entry.nome}
        vacation_name_keys = set()
        vacation_user_ids: set[int] = set()
        for entry in vacations:
            value = (entry.usuario_id or "").strip()
            if value.isdigit():
                vacation_user_ids.add(int(value))
            else:
                key = _normalize_name(value)
                if key:
                    vacation_name_keys.add(key)
        name_keys.update(vacation_name_keys)

        name_lookup: dict[str, User] = {}
        if name_keys:
            matched_users = (
                User.query.filter(func.lower(User.nome_completo).in_(list(name_keys))).all()
            )
            name_lookup = {_normalize_name(user.nome_completo): user for user in matched_users if user.nome_completo}

        id_lookup: dict[int, User] = {}
        if vacation_user_ids:
            id_users = User.query.filter(User.id.in_(list(vacation_user_ids))).all()
            id_lookup = {user.id: user for user in id_users}

        default_avatar = url_for("static", filename="images/sollus_logo.png")

        def _avatar_for_user(user: User | None) -> str:
            if user and user.avatar_path:
                return url_for("static", filename=user.avatar_path)
            return default_avatar

        filtered_birthdays = []
        if birthdays:
            today = date.today()
            for entry in birthdays:
                try:
                    if entry.data_nascimento and entry.data_nascimento.day < today.day and entry.data_nascimento.month == today.month:
                        continue
                except AttributeError:
                    pass
                filtered_birthdays.append(entry)
        else:
            filtered_birthdays = birthdays
        birthday_alerts = []
        for entry in filtered_birthdays:
            key = _normalize_name(entry.nome)
            user = name_lookup.get(key)
            is_today = False
            try:
                if entry.data_nascimento and entry.data_nascimento.day == today.day and entry.data_nascimento.month == today.month:
                    is_today = True
            except Exception:
                is_today = False
            birthday_alerts.append(
                {
                    "name": entry.nome,
                    "date_label": entry.data_nascimento.strftime("%d/%m"),
                    "avatar": _avatar_for_user(user),
                    "is_today": is_today,
                }
            )

        vacation_alerts = []
        today = date.today()
        for entry in vacations:
            if entry.data_final and entry.data_final < today:
                continue
            user = None
            identifier = (entry.usuario_id or "").strip()
            if identifier.isdigit():
                user = id_lookup.get(int(identifier))
            else:
                user = name_lookup.get(_normalize_name(identifier))

            display_name = (user.nome_completo if user and user.nome_completo else "").strip()
            if not display_name:
                display_name = identifier or entry.unidade

            vacation_alerts.append(
                {
                    "name": display_name,
                    "start_label": entry.data_inicial.strftime("%d/%m"),
                    "end_label": entry.data_final.strftime("%d/%m"),
                    "avatar": _avatar_for_user(user),
                    "unit": entry.unidade,
                }
            )

        # KPI counts
        open_tickets_count = 0
        pending_proposals_count = 0
        active_contracts_count = 0

        try:
            from modules.suporte.services.chamados import REGIONAL_BOARDS, _table_exists, _available_column_map
            for board in REGIONAL_BOARDS:
                try:
                    if _table_exists(board.table_name):
                        column_map = _available_column_map(board.table_name)
                        if 'retorno' in column_map:
                            retorno_col = column_map['retorno']
                            query = text(f"SELECT COUNT(*) FROM `{board.table_name}` WHERE `{retorno_col}` IN ('ABERTO', 'OFICINA')")
                            count = db.session.execute(query).scalar() or 0
                            open_tickets_count += count
                except Exception as e:
                    app.logger.warning(f"Error counting open tickets for board {board.slug}: {e}")
        except Exception as e:
            app.logger.warning(f"Error importing or querying regional boards: {e}")

        try:
            from modules.propostas.models import Proposal
            pending_proposals_count = Proposal.query.filter(Proposal.approved_at.is_(None)).count()
        except Exception as e:
            app.logger.warning(f"Error querying pending proposals: {e}")

        try:
            active_contracts_count = db.session.execute(
                text("SELECT COUNT(*) FROM contratos WHERE status = 'Ativo'")
            ).scalar() or 0
        except Exception as e:
            app.logger.warning(f"Error querying active contracts: {e}")

        gallery_root = Path(app.static_folder) / "galeria"
        gallery_images = _list_gallery_images(gallery_root, limit=10)

        return render_template(
            "home.html",
            birthday_alerts=birthday_alerts,
            vacation_alerts=vacation_alerts,
            today_label=today.strftime("%d/%m"),
            gallery_images=gallery_images,
            open_tickets_count=open_tickets_count,
            pending_proposals_count=pending_proposals_count,
            active_contracts_count=active_contracts_count,
        )

    @app.route("/favicon.ico")
    def favicon() -> Any:
        return send_from_directory(
            Path(app.static_folder) / "images",
            "favicon.ico",
            mimetype="image/vnd.microsoft.icon",
            max_age=86400,
        )

    @app.route("/tickets/dashboard")
    @login_required
    def tickets_dashboard() -> Any:
        return redirect(url_for("sollus_tickets.dashboard"))

    @app.route("/galeria")
    @login_required
    def galeria() -> Any:
        gallery_root = Path(app.static_folder) / "galeria"
        gallery_images = _list_gallery_images(gallery_root)
        return render_template(
            "galeria.html",
            gallery_images=gallery_images,
        )

    @app.route("/galeria/arquivo/<path:filename>", endpoint="serve_fotos")
    @login_required
    def serve_fotos(filename: str) -> Any:
        if not _can_view_gallery():
            return "Sem permissão", 403
        gallery_root = Path(app.static_folder) / "galeria"
        ok, resolved = _resolve_gallery_file(filename, gallery_root)
        if not ok or not resolved:
            return "Arquivo não encontrado", 404
        return send_from_directory(
            gallery_root,
            resolved,
            conditional=True,
            max_age=3600,
        )

    @app.route("/chamados")
    @login_required
    def chamados_home() -> Any:
        return redirect(url_for("sollus_tickets.dashboard"))

    @app.route("/sollus-tickets/dashboard")
    @login_required
    def sollus_tickets_dashboard_alias() -> Any:
        return redirect(url_for("sollus_tickets.dashboard"))

    @app.route("/sem-permissao")
    @login_required
    def sem_permissao() -> Any:
        area = request.args.get("area") or "esta área"
        return render_template("errors/403.html", area_label=area)

    @app.route("/__ping__")
    def ping():
        return {"status": "ok"}

    @app.route("/__diag__")
    @login_required
    def diag() -> Any:
        from flask import jsonify, session as flask_session
        from flask_login import current_user as _cu
        # Restrict to admin users only
        role = (getattr(_cu, "tipo", None) or flask_session.get("tipo") or "").lower()
        if not _cu.is_authenticated or role != "admin":
            return jsonify({"error": "Forbidden"}), 403
        info = {
            "debug": app.debug,
            "instance_path": app.instance_path,
            "template_folder": app.template_folder,
            "static_folder": app.static_folder,
            "has_login_template": False,
        }
        try:
            import os
            from pathlib import Path


            tpl = Path(app.root_path).parent / "templates" / "auth" / "login.html"
            info["login_template_path"] = str(tpl)
            info["has_login_template"] = os.path.exists(tpl)
        except Exception:
            pass
        return jsonify(info)

def _register_error_handlers(app: Flask) -> None:
    """Provide friendly responses for expected platform errors."""
    from flask import jsonify, flash, redirect, url_for, request, render_template
    from flask_wtf.csrf import CSRFError

    @app.errorhandler(403)
    def _handle_forbidden(exc):  # pragma: no cover - UI feedback only
        wants_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)
        )
        if wants_json:
            return jsonify({"ok": False, "message": "Você não tem permissão para acessar esta área."}), 403
        area = request.args.get("area") or "esta área"
        return render_template("errors/403.html", area_label=area), 403

    @app.errorhandler(CSRFError)
    def _handle_csrf_error(exc: CSRFError):  # pragma: no cover - UI feedback only
        message = exc.description or "Sua sessão expirou. Recarregue a página e tente novamente."
        wants_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)
        )
        if wants_json:
            return jsonify({"ok": False, "reason": "csrf", "message": message}), 400
        flash(message, "warning")
        target = request.headers.get("Referer") or url_for("auth_bp.login")
        return redirect(target)

    @app.errorhandler(404)
    def _handle_not_found(exc):  # pragma: no cover - UI feedback only
        wants_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)
        )
        if wants_json:
            return jsonify({"ok": False, "message": "Página não encontrada."}), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(409)
    def _handle_conflict(exc):  # pragma: no cover - UI feedback only
        wants_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)
        )
        if wants_json:
            return jsonify({"ok": False, "message": "O recurso está sendo modificado por outro usuário."}), 409

        import re
        from sqlalchemy import text
        from extensions import db
        from modules.sollus_tickets.models import SollusTicket, SollusTicketLock

        match = re.search(r'/sollus-tickets/(\d+)', request.path)
        lock_owner = None
        expires_at_str = None

        if match:
            try:
                ticket_id = int(match.group(1))
                ticket = SollusTicket.query.get(ticket_id)
                if ticket:
                    lock = SollusTicketLock.query.filter_by(ticket_id=ticket.id).first()
                    if lock and lock.user_id:
                        user = db.session.execute(
                            text("SELECT nome_completo, email FROM users WHERE id = :uid"),
                            {"uid": lock.user_id}
                        ).fetchone()
                        if user:
                            lock_owner = user[0] or user[1]
                        if lock.expires_at:
                            expires_at_str = lock.expires_at.strftime("%H:%M:%S")
            except Exception:
                pass

        return render_template(
            "errors/409.html",
            lock_owner=lock_owner,
            expires_at=expires_at_str
        ), 409

    @app.errorhandler(500)
    def _handle_internal_error(exc):  # pragma: no cover - UI feedback only
        wants_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)
        )
        if wants_json:
            return jsonify({"ok": False, "message": "Erro interno no servidor."}), 500
        return render_template("errors/500.html"), 500


def _register_signal_handlers(app: Flask) -> None:
    """Attach diagnostics for unexpected request errors."""
    from flask import got_request_exception

    @got_request_exception.connect_via(app)
    def _log_exception(sender, exception, **extra):  # type: ignore[arg-type]
        sender.logger.exception(
            "Unhandled exception during request",
            exc_info=exception,
        )


class _DiagnosticMiddleware:
    """Emit stdout diagnostics for every request, capturing unhandled errors."""

    def __init__(self, app):
        self._app = app

    def __call__(self, environ, start_response):  # pragma: no cover - diagnostics only
        import sys

        path = environ.get("PATH_INFO", "<unknown>")
        method = environ.get("REQUEST_METHOD", "<unknown>")
        sys.stdout.write(f"[diagnostic] {method} {path}\n")
        sys.stdout.flush()
        try:
            return self._app(environ, start_response)
        except Exception as exc:
            sys.stdout.write(f"[diagnostic] exception: {exc}\n")
            sys.stdout.flush()
            raise


def _configure_logging(app: Flask) -> None:
    """Ensure application logs are emitted both to stdout and file."""
    import logging
    from logging.handlers import RotatingFileHandler

    try:
        logs_dir = Path(app.instance_path) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / "platform.log"

        handler = RotatingFileHandler(
            log_file,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

        # Avoid duplicating handlers if flask reloads
        if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
            app.logger.addHandler(handler)

        app.logger.setLevel(logging.INFO)

        # Emit logs to stdout so they appear no terminal when rodando via app.py
        if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
            console = logging.StreamHandler()
            console.setLevel(logging.INFO)
            console.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            )
            app.logger.addHandler(console)
    except Exception:
        # Logging should never break app boot
        app.logger.warning("Failed to configure file logging", exc_info=True)


def _optimize_database_performance(app: Flask) -> None:
    """Automatically creates indexes for performance-critical columns across all tables."""
    try:
        from sqlalchemy import text, inspect
        from extensions import db
        with app.app_context():
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            for table_name in tables:
                columns = [c['name'] for c in inspector.get_columns(table_name)]
                # Target columns that benefit most from indexing
                target_suffixes = ['_id', 'status', 'created_at', 'updated_at', 'date', 'data', 'tipo', 'category']
                for col in columns:
                    if any(suffix in col.lower() for suffix in target_suffixes):
                        idx_name = f"idx_{table_name}_{col}"
                        if len(idx_name) > 64: idx_name = idx_name[:64]
                        try:
                            db.session.execute(text(f"CREATE INDEX {idx_name} ON {table_name}({col})"))
                            db.session.commit()
                        except Exception:
                            db.session.rollback()
    except Exception:
        pass
