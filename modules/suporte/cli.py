"""Comandos CLI para o modulo de suporte."""
from __future__ import annotations

from pathlib import Path

import re

import click
from flask import Flask
from sqlalchemy.exc import SQLAlchemyError

from extensions import db

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_DUMP_DEFAULT = PROJECT_ROOT / "outputs" / "gestao_tarefas_depara.sql"
ATESTADOS_DUMP_DEFAULT = PROJECT_ROOT / "Viva_Rio" / "vivarioweb.sql"


def _split_sql_text(sql_text: str) -> list[str]:
    delimiter = ";"
    statements: list[str] = []
    current_lines: list[str] = []

    def commit_statement(delim: str) -> None:
        text = "\n".join(current_lines).strip()
        if delim and text.endswith(delim):
            text = text[: -len(delim)].strip()
        if text:
            statements.append(text)
        current_lines.clear()

    for raw_line in sql_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER"):
            if current_lines:
                commit_statement(delimiter)
            parts = stripped.split(maxsplit=1)
            delimiter = parts[1] if len(parts) > 1 else ";"
            continue
        current_lines.append(line)
        joined = "\n".join(current_lines).rstrip()
        if not delimiter:
            continue
        if joined.endswith(delimiter):
            commit_statement(delimiter)

    if current_lines:
        commit_statement(delimiter)
    return statements


def register_commands(app: Flask):
    """Registra os comandos CLI do modulo de suporte."""

    @app.cli.command("clean-legacy-dates")
    def clean_legacy_dates():
        """Substitui datas '0000-00-00' por NULL nas tabelas de suporte."""
        tables_and_columns = {
            "agenda": ["data_atendimento"],
            "tarefas": ["data_criacao", "data_fim", "data_envio", "data_retorno"],
        }

        with db.engine.connect() as connection:
            click.echo("Iniciando limpeza de datas legadas...")
            total_affected = 0

            for table, columns in tables_and_columns.items():
                for column in columns:
                    try:
                        query = f"UPDATE {table} SET {column} = NULL WHERE {column} = '0000-00-00';"
                        result = connection.execute(db.text(query))
                        connection.commit()
                        affected = result.rowcount
                        if affected > 0:
                            click.echo(
                                f"  - {affected} registros atualizados em '{table}.{column}'."
                            )
                            total_affected += affected
                    except SQLAlchemyError as exc:
                        click.secho(
                            f"Erro ao atualizar a tabela '{table}', coluna '{column}': {exc}",
                            fg="red",
                        )
                        connection.rollback()

            if total_affected > 0:
                click.secho(
                    f"\nLimpeza concluida! {total_affected} registros foram corrigidos.",
                    fg="green",
                )
            else:
                click.secho(
                    "\nNenhum registro com data '0000-00-00' encontrado.", fg="yellow"
                )

    @app.cli.command("support-import-legacy")
    @click.option(
        "--dump-path",
        type=click.Path(exists=True, dir_okay=False, file_okay=True),
        default=None,
        help="Caminho para o dump SQL legado.",
    )
    @click.option(
        "--truncate/--no-truncate",
        default=False,
        help="Desativa verificações de chave estrangeira durante a importação.",
    )
    def support_import_legacy(dump_path: str | None, truncate: bool):
        """Importa o dump legado de gestao_tarefas sobre o esquema atual."""
        candidate = dump_path or app.config.get("SUPPORT_LEGACY_DUMP_PATH")
        source = Path(candidate) if candidate else LEGACY_DUMP_DEFAULT

        if not source.exists():
            raise click.FileError(
                str(source), hint="Arquivo de dump legado não encontrado."
            )

        click.echo(f"Iniciando importação do dump legado: {source}")
        try:
            sql = source.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            raise click.FileError(str(source), hint=str(exc))

        sanitized_sql = re.sub(r"DEFINER=`[^`]+`@`[^`]+`", "", sql, flags=re.IGNORECASE)
        statements = _split_sql_text(sanitized_sql)
        if not statements:
            click.secho("Nenhuma instrução SQL encontrada no arquivo.", fg="yellow")
            return

        raw_conn = None
        cursor = None
        try:
            raw_conn = db.engine.raw_connection()
            cursor = raw_conn.cursor()
            if truncate:
                click.echo("Desativando verificações de chave estrangeira.")
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

            had_errors = False
            for statement in statements:
                try:
                    cursor.execute(statement)
                except Exception as exc:
                    had_errors = True
                    click.secho(f"Erro ao executar statement: {exc}", fg="yellow")

            if truncate:
                click.echo("Reativando verificações de chave estrangeira.")
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

            raw_conn.commit()
            if had_errors:
                click.secho(
                    "A importação terminou com advertências. Consulte os logs acima.",
                    fg="yellow",
                )
        except Exception as exc:
            if raw_conn:
                raw_conn.rollback()
            click.secho(f"Erro durante a importação: {exc}", fg="red")
            raise click.Abort()
        finally:
            if cursor:
                cursor.close()
            if raw_conn:
                raw_conn.close()

        click.secho("Importação concluída com sucesso.", fg="green")

    @app.cli.command("atestados-import-viva-rio")
    @click.option(
        "--dump-path",
        type=click.Path(exists=True, dir_okay=False, file_okay=True),
        default=None,
        help="Caminho para o dump SQL do Viva Rio.",
    )
    @click.option(
        "--truncate/--no-truncate",
        default=False,
        help="Limpa as tabelas de atestados antes de importar.",
    )
    @click.option(
        "--data-only/--full",
        default=True,
        help="Importa apenas INSERTs (ignora CREATE/ALTER).",
    )
    def atestados_import_viva_rio(dump_path: str | None, truncate: bool, data_only: bool):
        """Importa o dump de atestados (Viva Rio) no banco atual."""
        candidate = dump_path or app.config.get("ATESTADOS_LEGACY_DUMP_PATH")
        source = Path(candidate) if candidate else ATESTADOS_DUMP_DEFAULT

        if not source.exists():
            raise click.FileError(
                str(source), hint="Arquivo de dump do Viva Rio não encontrado."
            )

        click.echo(f"Iniciando importação do dump Viva Rio: {source}")
        statements = None
        if data_only:
            def _iter_insert_lines():
                with source.open("rb") as handle:
                    for raw_line in handle:
                        line = raw_line.rstrip(b"\r\n")
                        stripped = line.lstrip()
                        if not stripped:
                            continue
                        if stripped.startswith(b"--") or stripped.startswith(b"/*"):
                            continue
                        if not stripped.upper().startswith(b"INSERT"):
                            continue
                        yield line
            statements = _iter_insert_lines()
        else:
            try:
                sql = source.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                raise click.FileError(str(source), hint=str(exc))
            statements = _split_sql_text(sql)
            if not statements:
                click.secho("Nenhuma instrução SQL encontrada no arquivo.", fg="yellow")
                return

        raw_conn = None
        cursor = None
        try:
            raw_conn = db.engine.raw_connection()
            cursor = raw_conn.cursor()

            if truncate:
                click.echo("Desativando verificações de chave estrangeira.")
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                for table in ("log_envio", "email", "task", "arquivo"):
                    try:
                        cursor.execute(f"DELETE FROM {table}")
                    except Exception:
                        pass
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

            had_errors = False
            statement_count = 0
            for statement in statements:
                statement_count += 1
                try:
                    cursor.execute(statement)
                except Exception as exc:
                    had_errors = True
                    click.secho(f"Erro ao executar statement: {exc}", fg="yellow")

            raw_conn.commit()
            if statement_count == 0:
                click.secho("Nenhuma instrução SQL encontrada no arquivo.", fg="yellow")
                return
            if had_errors:
                click.secho(
                    "A importação terminou com advertências. Consulte os logs acima.",
                    fg="yellow",
                )
        except Exception as exc:
            if raw_conn:
                raw_conn.rollback()
            click.secho(f"Erro durante a importação: {exc}", fg="red")
            raise click.Abort()
        finally:
            if cursor:
                cursor.close()
            if raw_conn:
                raw_conn.close()

        click.secho("Importação concluída com sucesso.", fg="green")
