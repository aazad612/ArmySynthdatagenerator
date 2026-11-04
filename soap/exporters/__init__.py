"""
Multi-Format Synthetic Dataset Exporters for SOAP (CSV, JSONL, SQLite, PostgreSQL Seed SQL).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List

from soap.world.simulator import SimulationOutput


def export_simulation_output(
    result: SimulationOutput,
    output_dir: Path,
    formats: List[str],
) -> Dict[str, List[str]]:
    """Writes generated Army synthetic tables, state history, CDC stream, SQLite DB, and Postgres SQL to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written_files: Dict[str, List[str]] = {}

    if "csv" in formats:
        csv_dir = output_dir / "csv"
        csv_dir.mkdir(parents=True, exist_ok=True)
        written_files["csv"] = []
        for table_name, rows in result.tables.items():
            path = csv_dir / f"{table_name}.csv"
            _write_csv(path, rows)
            written_files["csv"].append(str(path))
        hist_path = csv_dir / "fsm_state_history.csv"
        _write_csv(hist_path, result.state_history)
        written_files["csv"].append(str(hist_path))

    if "jsonl" in formats:
        jsonl_dir = output_dir / "jsonl"
        jsonl_dir.mkdir(parents=True, exist_ok=True)
        written_files["jsonl"] = []
        for table_name, rows in result.tables.items():
            path = jsonl_dir / f"{table_name}.jsonl"
            _write_jsonl(path, rows)
            written_files["jsonl"].append(str(path))

        cdc_path = jsonl_dir / "raw_cdc_stream.jsonl"
        _write_jsonl(cdc_path, result.raw_cdc_stream)
        written_files["jsonl"].append(str(cdc_path))

        hist_path = jsonl_dir / "fsm_state_history.jsonl"
        _write_jsonl(hist_path, result.state_history)
        written_files["jsonl"].append(str(hist_path))

    if "sqlite" in formats:
        sqlite_dir = output_dir / "sqlite"
        sqlite_dir.mkdir(parents=True, exist_ok=True)
        db_path = sqlite_dir / "soap_army_synthetic.db"
        _write_sqlite_db(db_path, result)
        written_files["sqlite"] = [str(db_path)]

    if "postgres" in formats:
        pg_dir = output_dir / "postgres"
        pg_dir.mkdir(parents=True, exist_ok=True)
        pg_path = pg_dir / "seed_army_synthetic.sql"
        _write_postgres_seed_sql(pg_path, result)
        written_files["postgres"] = [str(pg_path)]

    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(result.metrics, f, indent=2)

    return written_files


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _write_sqlite_db(db_path: Path, result: SimulationOutput) -> None:
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    with conn:
        for table_name, rows in list(result.tables.items()) + [("fsm_state_history", result.state_history)]:
            if not rows:
                continue
            cols = list(rows[0].keys())
            col_defs = ", ".join(f"{c} TEXT" for c in cols)
            conn.execute(f"CREATE TABLE {table_name} ({col_defs});")
            placeholders = ", ".join(["?"] * len(cols))
            conn.executemany(
                f"INSERT INTO {table_name} VALUES ({placeholders});",
                [tuple(r.get(c) for c in cols) for r in rows],
            )
    conn.close()


def _write_postgres_seed_sql(pg_path: Path, result: SimulationOutput) -> None:
    lines: List[str] = [
        "-- SOAP Auto-Generated PostgreSQL Synthetic Data Seed Bundle",
        "BEGIN;",
    ]
    for table_name, rows in result.tables.items():
        if not rows:
            continue
        cols = list(rows[0].keys())
        col_list = ", ".join(cols)
        for r in rows:
            vals = [_pg_literal(r.get(c)) for c in cols]
            lines.append(f"INSERT INTO {table_name} ({col_list}) VALUES ({', '.join(vals)});")
    lines.append("COMMIT;")
    pg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pg_literal(val: Any) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"
