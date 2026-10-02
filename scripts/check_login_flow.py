"""Quick diagnostics for the auth login flow."""
from __future__ import annotations

import re
from dataclasses import dataclass

import requests

BASE_URL = "http://127.0.0.1:6000"
LOGIN_URL = f"{BASE_URL}/auth/login"

TOKEN_RE = re.compile(r'name="csrf_token"\s+value="([^"]+)"')


@dataclass
class StepResult:
    label: str
    status_code: int
    preview: str


def _fetch_csrf(session: requests.Session) -> StepResult:
    resp = session.get(LOGIN_URL, timeout=10)
    match = TOKEN_RE.search(resp.text)
    preview = resp.text[:120]
    if not match:
        raise RuntimeError("CSRF token not found in login form")
    session.headers.update({"Referer": LOGIN_URL})
    session.cookies.set("debug_token", match.group(1))
    return StepResult("GET /auth/login", resp.status_code, preview)


def _perform_login(session: requests.Session, username: str, password: str) -> StepResult:
    token = session.cookies.pop("debug_token")
    resp = session.post(
        LOGIN_URL,
        data={
            "usuario": username,
            "senha": password,
            "csrf_token": token,
        },
        allow_redirects=False,
        timeout=10,
    )
    preview = resp.text[:200]
    return StepResult("POST /auth/login", resp.status_code, preview)


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "login-debugger"})

    results = []
    try:
        results.append(_fetch_csrf(session))
        results.append(_perform_login(session, "admin", "admin"))
    except Exception as exc:
        print("ERROR:", exc)
    else:
        for step in results:
            print(f"{step.label}: status={step.status_code}")
            print("preview:", step.preview.replace("\n", " ")[:120], "...\n")


if __name__ == "__main__":
    main()
