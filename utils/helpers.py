from __future__ import annotations
import math
import unicodedata
from datetime import date, datetime
from typing import Any
from flask import request

def normalize_dept_name(value: str | None) -> str:
    if not value:
        return ""
    text_value = unicodedata.normalize("NFKD", str(value))
    text_value = "".join(ch for ch in text_value if not unicodedata.combining(ch))
    return text_value.strip().upper()

def wants_json() -> bool:
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)
    )

def paginate(total: int, page: int, per_page: int) -> dict[str, Any]:
    pages = max(1, math.ceil(total / per_page)) if per_page else 1
    page = max(1, min(page, pages))
    return {
        "page": page,
        "pages": pages,
        "total": total,
        "has_prev": page > 1,
        "prev_num": page - 1,
        "has_next": page < pages,
        "next_num": page + 1,
    }

def format_date(value: Any) -> str:
    if not value or str(value).strip() in ("0000-00-00", "0000-00-00 00:00:00"):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    raw = str(value).strip()
    if not raw:
        return ""
    try:
        # Tenta parsear via ISO format
        parsed = datetime.fromisoformat(raw)
        return parsed.strftime("%d/%m/%Y")
    except ValueError:
        pass
    
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return raw

def format_datetime(value: Any) -> str:
    if not value or str(value).strip() in ("0000-00-00", "0000-00-00 00:00:00"):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    raw = str(value).strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed.strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            pass
    return raw


from html.parser import HTMLParser
import html as html_lib
import re

class HTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
        self.allowed_tags = {"li", "span", "br", "ul", "p", "b", "i", "strong", "em"}
        self.allowed_attrs = {
            "span": {"class"},
            "li": {"class"},
            "ul": {"class"},
            "p": {"class"}
        }

    def handle_starttag(self, tag, attrs):
        if tag in self.allowed_tags:
            cleaned_attrs = []
            allowed_for_tag = self.allowed_attrs.get(tag, set())
            for name, value in attrs:
                if name in allowed_for_tag:
                    if name == "class" and re.match(r'^[a-zA-Z0-9\s_-]+$', value):
                        cleaned_attrs.append(f'{name}="{html_lib.escape(value)}"')
            attr_str = f" {' '.join(cleaned_attrs)}" if cleaned_attrs else ""
            if tag == "br":
                self.result.append(f"<br{attr_str}/>")
            else:
                self.result.append(f"<{tag}{attr_str}>")

    def handle_endtag(self, tag):
        if tag in self.allowed_tags and tag != "br":
            self.result.append(f"</{tag}>")

    def handle_data(self, data):
        self.result.append(html_lib.escape(data))

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.handle_starttag(tag, attrs)

    def get_clean_html(self) -> str:
        return "".join(self.result)

def sanitize_html(text_value: str | None) -> str:
    if not text_value:
        return ""
    parser = HTMLSanitizer()
    parser.feed(text_value)
    return parser.get_clean_html()


def submit_bg_task(app, func, *args, max_retries=3, retry_delay=5, **kwargs) -> None:
    """Submete uma tarefa para execução em background usando ThreadPoolExecutor com controle de contexto do app e tentativas."""
    from extensions import executor
    import time

    def _wrapper():
        with app.app_context():
            retries = 0
            while True:
                try:
                    func(*args, **kwargs)
                    break
                except Exception as e:
                    retries += 1
                    app.logger.exception(f"Erro ao executar tarefa {func.__name__} (Tentativa {retries}/{max_retries})")
                    if retries >= max_retries:
                        app.logger.error(f"Tarefa {func.__name__} falhou permanentemente após {max_retries} tentativas.")
                        break
                    time.sleep(retry_delay)

    executor.submit(_wrapper)
