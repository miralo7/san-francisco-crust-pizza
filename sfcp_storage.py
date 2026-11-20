"""Persistencia de los datos activos con actualización atómica y copias de seguridad.

Flujo de una actualización:
  1. Se escribe el nuevo conjunto en una carpeta temporal.
  2. Los datos activos actuales se mueven a `backups/<timestamp>`.
  3. La carpeta temporal pasa a ser la activa.
Si cualquier paso falla se restaura el estado anterior; los datos previos nunca se pierden.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

import sfcp_config as config
from sfcp_validation import ValidationReport, read_table, validate_bundle

NAMES = ("ventas", "clientes", "productos")
META = "metadata.json"


def _write_set(folder: Path, data: dict[str, pd.DataFrame]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for n in NAMES:
        data[n].to_parquet(folder / f"{n}.parquet", index=False)


def read_meta(folder: Path | None = None) -> dict | None:
    p = (folder or config.ACTIVE_DIR) / META
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_active() -> dict[str, pd.DataFrame] | None:
    d = config.ACTIVE_DIR
    if not all((d / f"{n}.parquet").exists() for n in NAMES):
        return None
    return {n: pd.read_parquet(d / f"{n}.parquet") for n in NAMES}


def _build_meta(data, report: ValidationReport, filenames: dict, action: str, prev: dict | None) -> dict:
    v = data["ventas"]
    now = datetime.now()
    event = {"fecha": now.strftime("%Y-%m-%d %H:%M:%S"), "accion": action,
             "archivos": filenames, "errores": len(report.errors), "advertencias": len(report.warnings)}
    history = ([event] + (prev or {}).get("history", []))[:15]
    return {
        "version": now.strftime("%Y%m%d%H%M%S%f"),
        "updated_at": event["fecha"],
        "files": filenames,
        "rows": {n: int(len(data[n])) for n in NAMES},
        "status": report.status,
        "n_errors": len(report.errors),
        "n_warnings": len(report.warnings),
        "period_start": v["Fecha"].min().strftime("%Y-%m-%d"),
        "period_end": v["Fecha"].max().strftime("%Y-%m-%d"),
        "warnings": [{"dataset": i.dataset, "message": i.message, "count": i.count} for i in report.warnings],
        "history": history,
    }


def apply_update(data: dict[str, pd.DataFrame], report: ValidationReport,
                 filenames: dict, action: str = "Actualización") -> dict:
    """Reemplaza los datos activos de forma atómica. Exige informe sin errores."""
    if not report.ok:
        raise ValueError("No se puede aplicar una actualización con errores de validación.")
    active, tmp = config.ACTIVE_DIR, config.DATA_DIR / ".tmp_active"
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    prev = read_meta()
    meta = _build_meta(data, report, filenames, action, prev)
    if tmp.exists():
        shutil.rmtree(tmp)
    backup = None
    try:
        _write_set(tmp, data)
        (tmp / META).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if active.exists():
            backup = config.BACKUP_DIR / (prev or {}).get("version", datetime.now().strftime("%Y%m%d%H%M%S"))
            if backup.exists():
                shutil.rmtree(backup)
            shutil.move(str(active), str(backup))
        shutil.move(str(tmp), str(active))
    except Exception:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        if backup is not None and backup.exists() and not active.exists():
            shutil.move(str(backup), str(active))   # restaurar estado previo
        raise
    _prune_backups()
    return meta


def _prune_backups() -> None:
    items = sorted([p for p in config.BACKUP_DIR.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    for old in items[config.MAX_BACKUPS:]:
        shutil.rmtree(old, ignore_errors=True)


def list_backups() -> list[dict]:
    if not config.BACKUP_DIR.exists():
        return []
    out = []
    for p in sorted(config.BACKUP_DIR.iterdir(), key=lambda p: p.name, reverse=True):
        m = read_meta(p)
        if m:
            out.append({"name": p.name, **{k: m[k] for k in ("updated_at", "rows", "period_start", "period_end")}})
    return out


def restore_backup(name: str) -> dict:
    src = config.BACKUP_DIR / name
    if not (src / META).exists():
        raise FileNotFoundError(f"No existe la copia «{name}».")
    data = {n: pd.read_parquet(src / f"{n}.parquet") for n in NAMES}
    rep = ValidationReport()
    meta_old = read_meta(src)
    for w in meta_old.get("warnings", []):
        rep.add("warning", w["dataset"], "RESTORED", w["message"], w.get("count", 0))
    return apply_update(data, rep, meta_old.get("files", {}), action=f"Restauración de copia {name}")


def bootstrap_from_seed() -> dict:
    """Carga inicial desde los Excel de `data/seed` (solo si no hay datos activos)."""
    raws = {}
    for n in NAMES:
        p = config.SEED_FILES[n]
        df, rep = read_table(str(p), p.name, n)
        if df is None:
            raise RuntimeError(f"No se pudo leer la base semilla {p.name}: {rep.errors[0].message}")
        raws[n] = df
    clean, rep = validate_bundle(raws["ventas"], raws["clientes"], raws["productos"])
    if clean is None:
        raise RuntimeError("La base semilla no supera la validación: " + "; ".join(i.message for i in rep.errors))
    return apply_update(clean, rep, {n: config.SEED_FILES[n].name for n in NAMES}, action="Carga inicial (semilla)")


def ensure_data() -> dict[str, pd.DataFrame]:
    data = load_active()
    if data is None:
        bootstrap_from_seed()
        data = load_active()
    return data
