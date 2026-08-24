"""Utilidades para manipular anexos de atendimentos."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Optional

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


DEFAULT_DIRNAME = "os_suporte"


def _base_dir() -> Path:
    config_dir = current_app.config.get("SUPPORT_UPLOAD_DIR")
    if config_dir:
        base = Path(config_dir)
    else:
        base = Path(current_app.root_path).parent / DEFAULT_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def save_support_file(file_storage: FileStorage | None, os_code: str | None, suffix: str) -> Optional[str]:
    if not file_storage or not getattr(file_storage, "filename", None):
        return None

    filename = secure_filename(file_storage.filename or "")
    if not filename:
        return None

    ext = Path(filename).suffix or ""
    os_slug = secure_filename(str(os_code or "suporte")) or "suporte"
    stored_name = f"{os_slug}_{suffix}{ext}"

    target = _base_dir() / stored_name
    file_storage.save(target)

    rel_base = current_app.config.get("SUPPORT_UPLOAD_RELATIVE", DEFAULT_DIRNAME)
    rel_path = str(Path(rel_base) / stored_name)
    return rel_path


def delete_support_file(stored_path: str | None) -> None:
    if not stored_path:
        return
    try:
        candidate = Path(stored_path)
        if not candidate.is_absolute():
            candidate = _base_dir().parent / stored_path
        if candidate.exists():
            candidate.unlink()
    except Exception:
        # remoção é auxiliar, não quebra fluxo
        return


def resolve_support_file(stored_path: str | None) -> Optional[Path]:
    if not stored_path:
        return None
    
    # 1. Try as-is first (normalizing separators)
    path_str = str(stored_path).replace("\\", "/")
    candidate = Path(path_str)
    try:
        if candidate.is_file():
            return candidate.resolve()
    except Exception:
        pass

    base_dir = _base_dir()
    root = base_dir.parent
    
    # 2. Clean leading relative markers and try relative to root
    clean_path = path_str
    while clean_path.startswith("../") or clean_path.startswith("./"):
        if clean_path.startswith("../"):
            clean_path = clean_path[3:]
        else:
            clean_path = clean_path[2:]
    
    # Try relative to project root (usually one level up from platform_app)
    # This handles "os_suporte/filename.pdf" or "../../os_suporte/filename.pdf"
    resolved = root / clean_path
    try:
        if resolved.is_file():
            return resolved.resolve()
    except Exception:
        pass
            
    # 3. Try just the filename within _base_dir()
    # This handles paths like "C:/Temp/filename.pdf" where only the name matters
    filename = Path(clean_path).name
    fallback = base_dir / filename
    try:
        if fallback.is_file():
            return fallback.resolve()
    except Exception:
        pass
    
    # 4. Final attempt: search for the filename in base_dir (case-insensitive if needed)
    # Some legacy files might have different casing or extra spaces
    try:
        # Search for exact name first
        for f in base_dir.glob("*"):
            if f.name.strip().lower() == filename.strip().lower():
                return f.resolve()
    except Exception:
        pass

    return None


def find_support_file(os_code: str | None, suffix: str) -> Optional[str]:
    if not os_code:
        return None
    os_slug = secure_filename(str(os_code or ""))
    if not os_slug:
        return None
    base_dir = _base_dir()
    candidates = [os_slug]
    numeric = re.sub(r"[^0-9]", "", str(os_code))
    if numeric and numeric != os_slug:
        candidates.append(numeric)
    for candidate in candidates:
        pattern = f"{candidate}_{suffix}.*"
        matches = sorted(
            base_dir.glob(pattern),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if matches:
            rel_base = current_app.config.get("SUPPORT_UPLOAD_RELATIVE", DEFAULT_DIRNAME)
            return str(Path(rel_base) / matches[0].name)
    return None