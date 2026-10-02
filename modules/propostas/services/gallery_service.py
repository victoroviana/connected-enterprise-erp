"""Service for managing gallery images and event categorization."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from flask import current_app

logger = logging.getLogger(__name__)

GALLERY_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
GALLERY_DIRNAME = "galeria"
METADATA_FILENAME = "gallery_metadata.json"


def get_gallery_root(static_folder: Path | str | None = None) -> Path:
    """Resolve the filesystem path for the gallery storage directory."""
    if static_folder:
        return Path(static_folder) / GALLERY_DIRNAME
    try:
        return Path(current_app.static_folder) / GALLERY_DIRNAME
    except Exception:
        return Path("static") / GALLERY_DIRNAME


def get_metadata_path(root: Path) -> Path:
    return root / METADATA_FILENAME


def load_gallery_metadata(root: Path) -> dict[str, Any]:
    """Load metadata from gallery_metadata.json or return default empty dict."""
    meta_path = get_metadata_path(root)
    if not meta_path.exists() or not meta_path.is_file():
        return {"active_event": None, "events": [], "images": {}}

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"active_event": None, "events": [], "images": {}}
            if "images" not in data or not isinstance(data["images"], dict):
                data["images"] = {}
            if "events" not in data or not isinstance(data["events"], list):
                data["events"] = []
            return data
    except Exception as exc:
        logger.warning("Error reading gallery metadata: %s", exc)
        return {"active_event": None, "events": [], "images": {}}


def save_gallery_metadata(root: Path, metadata: dict[str, Any]) -> bool:
    """Persist metadata to gallery_metadata.json safely."""
    try:
        root.mkdir(parents=True, exist_ok=True)
        meta_path = get_metadata_path(root)
        tmp_path = root / f".{METADATA_FILENAME}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        tmp_path.replace(meta_path)
        return True
    except Exception as exc:
        logger.error("Error saving gallery metadata: %s", exc)
        return False


def get_gallery_items(
    root: Path,
    limit: int | None = None,
    event_filter: str | None = None,
) -> dict[str, Any]:
    """
    Scan gallery folder and return structured items, unique events list, and active_event.
    """
    if not root.exists():
        return {"items": [], "events": [], "active_event": None}

    metadata = load_gallery_metadata(root)
    images_meta = metadata.get("images", {})
    known_events = list(metadata.get("events") or [])
    active_event = metadata.get("active_event")

    files = [
        p
        for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in GALLERY_EXTENSIONS
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    items = []
    found_events = set()

    for p in files:
        meta = images_meta.get(p.name, {})
        ev = (meta.get("event") or "").strip() or "Geral"
        found_events.add(ev)
        items.append({
            "filename": p.name,
            "event": ev,
            "created_at": meta.get("created_at"),
            "mtime": p.stat().st_mtime,
        })

    # Combine known events from metadata and found events on disk
    all_events_ordered = []
    for ev in known_events:
        if ev and ev not in all_events_ordered:
            all_events_ordered.append(ev)
    for ev in sorted(found_events):
        if ev and ev not in all_events_ordered:
            all_events_ordered.append(ev)

    # Filter items if event_filter specified
    filtered_items = items
    if event_filter and event_filter.strip() and event_filter.upper() != "ALL":
        filter_normalized = event_filter.strip().casefold()
        filtered_items = [
            i for i in items if i["event"].strip().casefold() == filter_normalized
        ]

    if limit and limit > 0:
        filtered_items = filtered_items[:limit]

    return {
        "items": filtered_items,
        "all_items_count": len(items),
        "events": all_events_ordered,
        "active_event": active_event,
    }


def add_gallery_image_metadata(
    root: Path,
    filename: str,
    event_name: str | None = None,
) -> bool:
    """Record metadata for a newly saved image."""
    metadata = load_gallery_metadata(root)
    clean_event = (event_name or "").strip() or "Geral"

    from datetime import datetime
    metadata["images"][filename] = {
        "event": clean_event,
        "created_at": datetime.now().isoformat(),
    }

    events = metadata.get("events") or []
    if clean_event not in events:
        events.append(clean_event)
    metadata["events"] = events

    return save_gallery_metadata(root, metadata)


def remove_gallery_image_metadata(root: Path, filename: str) -> bool:
    """Remove metadata for a deleted image."""
    metadata = load_gallery_metadata(root)
    if filename in metadata.get("images", {}):
        del metadata["images"][filename]
        return save_gallery_metadata(root, metadata)
    return True


def update_image_event(root: Path, filename: str, event_name: str) -> bool:
    """Update event category for a specific image."""
    metadata = load_gallery_metadata(root)
    clean_event = (event_name or "").strip() or "Geral"

    if filename not in metadata["images"]:
        metadata["images"][filename] = {}
    metadata["images"][filename]["event"] = clean_event

    events = metadata.get("events") or []
    if clean_event not in events:
        events.append(clean_event)
    metadata["events"] = events

    return save_gallery_metadata(root, metadata)


def set_active_event(root: Path, event_name: str | None) -> bool:
    """Set the default featured event for the home carousel (or None for all)."""
    metadata = load_gallery_metadata(root)
    clean_event = (event_name or "").strip()
    metadata["active_event"] = clean_event if clean_event and clean_event.upper() != "ALL" else None
    return save_gallery_metadata(root, metadata)
