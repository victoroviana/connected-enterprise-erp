from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class DeployError(RuntimeError):
    pass


@dataclass
class DeployResult:
    archive_name: str
    file_count: int
    backup_path: str
    steps: list[dict[str, Any]]


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "t", "yes", "y", "sim", "on"}


def deploy_enabled(config: dict[str, Any]) -> bool:
    return _truthy(config.get("DEPLOY_ENABLED"))


def deploy_config_summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": deploy_enabled(config),
        "host": config.get("DEPLOY_HOST") or "",
        "user": config.get("DEPLOY_USER") or "",
        "app_path": config.get("DEPLOY_APP_PATH") or "",
        "service": config.get("DEPLOY_SERVICE") or "",
        "remote_tmp": config.get("DEPLOY_REMOTE_TMP") or "",
        "backup_path": config.get("DEPLOY_BACKUP_PATH") or "",
        "restart_uses_password": bool(config.get("DEPLOY_SUDO_PASSWORD")),
        "restart_enabled": _truthy(config.get("DEPLOY_RESTART_ENABLED", True)),
    }


def apply_uploaded_deploy_zip(
    *,
    zip_file,
    original_filename: str,
    config: dict[str, Any],
    project_root: Path,
) -> DeployResult:
    if not deploy_enabled(config):
        raise DeployError("Deploy desativado. Configure DEPLOY_ENABLED=true para habilitar.")

    service = _required(config, "DEPLOY_SERVICE")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_root = project_root.resolve()
    backup_base = Path(
        str(config.get("DEPLOY_BACKUP_PATH") or f"{project_root}_deploy_backups")
    )
    backup_path = backup_base / stamp
    steps: list[dict[str, Any]] = []

    safe_name = Path(original_filename or "").name
    if not safe_name.lower().endswith(".zip"):
        raise DeployError("Envie um arquivo .zip válido.")

    with tempfile.TemporaryDirectory(prefix="sollus_upload_deploy_") as tmp_dir:
        archive_path = Path(tmp_dir) / safe_name
        zip_file.save(archive_path)
        file_count = _apply_archive_to_project(archive_path, project_root, backup_path)

    if file_count == 0:
        raise DeployError("O ZIP não contém arquivos para aplicar.")

    steps.append({
        "label": "Aplicar arquivos do ZIP",
        "returncode": 0,
        "stdout": f"{file_count} arquivo(s) aplicado(s). Backup: {backup_path}",
        "stderr": "",
    })

    if _truthy(config.get("DEPLOY_RESTART_ENABLED", True)):
        _schedule_local_restart(config, service, steps)
    else:
        steps.append({
            "label": "Reinício do serviço",
            "returncode": 0,
            "stdout": "Reinício desativado por DEPLOY_RESTART_ENABLED=false.",
            "stderr": "",
        })

    return DeployResult(
        archive_name=safe_name,
        file_count=file_count,
        backup_path=str(backup_path),
        steps=steps,
    )


def run_deploy_from_mudancas(config: dict[str, Any], project_root: Path) -> DeployResult:
    if not deploy_enabled(config):
        raise DeployError("Deploy desativado. Configure DEPLOY_ENABLED=true para habilitar.")

    host = _required(config, "DEPLOY_HOST")
    user = _required(config, "DEPLOY_USER")
    app_path = _required(config, "DEPLOY_APP_PATH").rstrip("/") + "/"
    service = _required(config, "DEPLOY_SERVICE")
    remote_tmp = str(config.get("DEPLOY_REMOTE_TMP") or "/tmp/sollus_connected_deploy").rstrip("/")
    backup_base = str(config.get("DEPLOY_BACKUP_PATH") or f"{app_path.rstrip('/')}_deploy_backups").rstrip("/")
    port = str(config.get("DEPLOY_SSH_PORT") or "22")

    mudancas_dir = project_root / "_mudancas"
    if not mudancas_dir.exists():
        raise DeployError("Pasta _mudancas não encontrada.")

    ssh = shutil.which(str(config.get("DEPLOY_SSH_BIN") or "ssh"))
    scp = shutil.which(str(config.get("DEPLOY_SCP_BIN") or "scp"))
    if not ssh or not scp:
        raise DeployError("Comandos ssh/scp não encontrados no Windows. Instale OpenSSH Client.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    remote_user_host = f"{user}@{host}"
    remote_archive = f"{remote_tmp}/mudancas_{stamp}.zip"
    remote_script = f"{remote_tmp}/apply_deploy_{stamp}.py"
    backup_path = f"{backup_base}/{stamp}"
    steps: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="sollus_deploy_") as tmp_dir:
        tmp = Path(tmp_dir)
        archive_path = tmp / f"mudancas_{stamp}.zip"
        script_path = tmp / f"apply_deploy_{stamp}.py"
        file_count = _build_archive(mudancas_dir, archive_path)
        if file_count == 0:
            raise DeployError("Nenhum arquivo de deploy encontrado em _mudancas.")
        script_path.write_text(_remote_apply_script(), encoding="utf-8")

        ssh_base = _ssh_base(ssh, port, config)
        scp_base = _scp_base(scp, port, config)

        _run_step(steps, "Criar pasta temporária remota", [*ssh_base, remote_user_host, f"mkdir -p { _sh_quote(remote_tmp) }"])
        _run_step(
            steps,
            "Enviar pacote _mudancas",
            [*scp_base, str(archive_path), str(script_path), f"{remote_user_host}:{remote_tmp}/"],
        )
        _run_step(
            steps,
            "Aplicar arquivos no servidor",
            [
                *ssh_base,
                remote_user_host,
                " ".join(
                    [
                        "python3",
                        _sh_quote(remote_script),
                        "--archive",
                        _sh_quote(remote_archive),
                        "--app-root",
                        _sh_quote(app_path),
                        "--backup-root",
                        _sh_quote(backup_path),
                    ]
                ),
            ],
        )
        _run_step(
            steps,
            "Reiniciar serviço",
            [*ssh_base, remote_user_host, f"sudo -n systemctl restart {_sh_quote(service)}"],
        )

    return DeployResult(
        archive_name=Path(remote_archive).name,
        file_count=file_count,
        backup_path=backup_path,
        steps=steps,
    )


def _required(config: dict[str, Any], key: str) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise DeployError(f"Configuração ausente: {key}.")
    return value


def _ssh_base(ssh_bin: str, port: str, config: dict[str, Any]) -> list[str]:
    cmd = [
        ssh_bin,
        "-p",
        port,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
    ]
    key = str(config.get("DEPLOY_SSH_KEY") or "").strip()
    if key:
        cmd.extend(["-i", key])
    return cmd


def _scp_base(scp_bin: str, port: str, config: dict[str, Any]) -> list[str]:
    cmd = [
        scp_bin,
        "-P",
        port,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
    ]
    key = str(config.get("DEPLOY_SSH_KEY") or "").strip()
    if key:
        cmd.extend(["-i", key])
    return cmd


def _build_archive(mudancas_dir: Path, archive_path: Path) -> int:
    skip = {"LEIA-ME.md", "LIMPAR_MUDANCAS.bat"}
    count = 0
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(mudancas_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(mudancas_dir).as_posix()
            if rel in skip:
                continue
            zf.write(path, rel)
            count += 1
    return count


def _apply_archive_to_project(archive_path: Path, project_root: Path, backup_path: Path) -> int:
    count = 0
    backup_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path) as zf:
        members = [member for member in zf.infolist() if not member.is_dir()]
        for member in members:
            rel = Path(member.filename)
            if rel.is_absolute() or ".." in rel.parts:
                raise DeployError(f"Caminho inválido no ZIP: {member.filename}")
            if rel.parts and rel.parts[0] == "_mudancas":
                rel = Path(*rel.parts[1:])
            if not rel.parts:
                continue
            if rel.as_posix() in {"LEIA-ME.md", "LIMPAR_MUDANCAS.bat"}:
                continue

            target = (project_root / rel).resolve()
            if not _is_relative_to(target, project_root):
                raise DeployError(f"Caminho fora do projeto no ZIP: {member.filename}")

            if target.exists():
                backup_target = backup_path / rel
                backup_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup_target)

            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1

    return count


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _schedule_local_restart(config: dict[str, Any], service: str, steps: list[dict[str, Any]]) -> None:
    delay = int(config.get("DEPLOY_RESTART_DELAY_SECONDS") or 2)
    password = str(config.get("DEPLOY_SUDO_PASSWORD") or "")
    service_arg = _sh_quote(service)

    if password:
        command = f"sleep {delay}; printf '%s\\n' \"$DEPLOY_SUDO_PASSWORD\" | sudo -S -p '' systemctl restart {service_arg}"
        env = os.environ.copy()
        env["DEPLOY_SUDO_PASSWORD"] = password
    else:
        command = f"sleep {delay}; sudo -n systemctl restart {service_arg}"
        env = None

    subprocess.Popen(
        ["sh", "-c", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )
    steps.append({
        "label": "Agendar reinício do serviço",
        "returncode": 0,
        "stdout": f"Reinício de {service} agendado em {delay}s.",
        "stderr": "",
    })


def _run_step(steps: list[dict[str, Any]], label: str, command: list[str]) -> None:
    proc = subprocess.run(command, capture_output=True, text=True, timeout=180)
    step = {
        "label": label,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }
    steps.append(step)
    if proc.returncode != 0:
        message = step["stderr"] or step["stdout"] or f"Comando falhou com código {proc.returncode}."
        raise DeployError(f"{label}: {message}")


def _sh_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def _remote_apply_script() -> str:
    return textwrap.dedent(
        r"""
        from __future__ import annotations

        import argparse
        import shutil
        import zipfile
        from pathlib import Path


        def inside(child: Path, parent: Path) -> bool:
            try:
                child.resolve().relative_to(parent.resolve())
                return True
            except ValueError:
                return False


        parser = argparse.ArgumentParser()
        parser.add_argument("--archive", required=True)
        parser.add_argument("--app-root", required=True)
        parser.add_argument("--backup-root", required=True)
        args = parser.parse_args()

        archive = Path(args.archive)
        app_root = Path(args.app_root).resolve()
        backup_root = Path(args.backup_root).resolve()

        backup_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            for member in members:
                rel = Path(member.filename)
                if rel.is_absolute() or ".." in rel.parts:
                    raise RuntimeError(f"Invalid archive path: {member.filename}")

                target = (app_root / rel).resolve()
                if not inside(target, app_root):
                    raise RuntimeError(f"Path escapes app root: {member.filename}")

                if target.exists():
                    backup_target = backup_root / rel
                    backup_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup_target)

                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

        print(f"Applied {len(members)} file(s) to {app_root}")
        print(f"Backup: {backup_root}")
        """
    ).strip() + os.linesep
