"""Lectura, reconocimiento de columnas y validación de las tres bases de datos.

Principio: una carga con errores NUNCA modifica los datos activos. Los errores
bloquean; las advertencias se informan pero permiten continuar.
"""
from __future__ import annotations

import difflib
import io
import unicodedata
from dataclasses import dataclass, field
from typing import IO, Union

import numpy as np
import pandas as pd

from sfcp_config import SCHEMAS, DATASET_LABELS, TOLERANCE_USD

Source = Union[str, "os.PathLike", IO[bytes]]  # noqa: F821


def _n(x) -> str:
    """Entero con separador de miles estilo español (1.234)."""
    return f"{int(x):,}".replace(",", ".")


# ----------------------------------------------------------------------------
# Estructuras de informe
# ----------------------------------------------------------------------------
@dataclass
class Issue:
    severity: str            # "error" | "warning" | "info"
    dataset: str             # "ventas" | "clientes" | "productos" | "relaciones"
    code: str
    message: str
    count: int = 0
    fix: str = ""


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, severity, dataset, code, message, count=0, fix=""):
        self.issues.append(Issue(severity, dataset, code, message, int(count), fix))

    def extend(self, other: "ValidationReport"):
        self.issues.extend(other.issues)
        self.stats.update(other.stats)

    @property
    def errors(self): return [i for i in self.issues if i.severity == "error"]
    @property
    def warnings(self): return [i for i in self.issues if i.severity == "warning"]
    @property
    def infos(self): return [i for i in self.issues if i.severity == "info"]
    @property
    def ok(self): return not self.errors

    @property
    def status(self) -> str:
        if self.errors: return "Rechazada"
        return "Aprobada con advertencias" if self.warnings else "Aprobada"

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([i.__dict__ for i in self.issues],
                            columns=["severity", "dataset", "code", "message", "count", "fix"])


# ----------------------------------------------------------------------------
# Lectura de archivos (Excel / CSV)
# ----------------------------------------------------------------------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalnum())


def read_table(source: Source, filename: str, dataset: str) -> tuple[pd.DataFrame | None, ValidationReport]:
    """Lee un .xlsx/.xls/.csv. En Excel elige la hoja que mejor encaja con el esquema."""
    rep = ValidationReport()
    name = filename.lower()
    try:
        if name.endswith(".csv"):
            raw = source.read() if hasattr(source, "read") else open(source, "rb").read()
            for enc in ("utf-8-sig", "latin-1"):
                try:
                    df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError("No se pudo decodificar el CSV (use UTF-8 o Latin-1).")
        elif name.endswith((".xlsx", ".xlsm", ".xls")):
            sheets = pd.read_excel(source, sheet_name=None)
            if not sheets:
                raise ValueError("El libro no contiene hojas.")
            req = {_norm(c) for c in SCHEMAS[dataset]["required"]}
            best = max(sheets, key=lambda s: len(req & {_norm(c) for c in sheets[s].columns}))
            df = sheets[best]
            if len(sheets) > 1:
                rep.add("info", dataset, "SHEET", f"Libro con {len(sheets)} hojas; se usó «{best}».")
        else:
            rep.add("error", dataset, "FORMAT", f"Formato no soportado: «{filename}».",
                    fix="Use archivos .xlsx o .csv.")
            return None, rep
    except Exception as exc:  # archivo corrupto, contraseña, etc.
        rep.add("error", dataset, "READ", f"No se pudo leer el archivo «{filename}»: {exc}",
                fix="Verifique que el archivo no esté dañado ni protegido con contraseña.")
        return None, rep
    if df.empty:
        rep.add("error", dataset, "EMPTY", f"El archivo «{filename}» no contiene registros.")
        return None, rep
    return df, rep


# ----------------------------------------------------------------------------
# Reconocimiento de columnas y tipos
# ----------------------------------------------------------------------------
def normalize_columns(df: pd.DataFrame, dataset: str, rep: ValidationReport) -> pd.DataFrame:
    sch = SCHEMAS[dataset]
    canon = sch["required"] + sch["optional"]
    lookup = {_norm(c): c for c in canon}
    for target, alts in sch["aliases"].items():
        for a in alts:
            lookup.setdefault(_norm(a), target)
    rename, used = {}, set()
    for col in df.columns:
        tgt = lookup.get(_norm(col))
        if tgt and tgt not in used:
            rename[col] = tgt
            used.add(tgt)
    renamed = {k: v for k, v in rename.items() if k != v}
    if renamed:
        rep.add("info", dataset, "RENAMED",
                "Columnas reconocidas por nombre equivalente: "
                + ", ".join(f"«{k}»→{v}" for k, v in renamed.items()) + ".")
    out = df.rename(columns=rename)
    ignored = [c for c in out.columns if c not in canon]
    if ignored:
        rep.add("info", dataset, "IGNORED",
                f"Columnas no utilizadas por el modelo (se ignoran): {', '.join(map(str, ignored[:10]))}"
                + ("…" if len(ignored) > 10 else "") + ".")
    missing = [c for c in sch["required"] if c not in out.columns]
    for m in missing:
        close = difflib.get_close_matches(_norm(m), [_norm(c) for c in df.columns], n=1, cutoff=0.6)
        hint = ""
        if close:
            orig = next(c for c in df.columns if _norm(c) == close[0])
            hint = f" ¿Quiso decir «{orig}»? Renombre esa columna a «{m}»."
        rep.add("error", dataset, "MISSING_COL",
                f"Falta la columna obligatoria «{m}».{hint}",
                fix=f"Agregue la columna «{m}» o renombre la equivalente. "
                    f"Obligatorias: {', '.join(sch['required'])}.")
    return out[[c for c in canon if c in out.columns]]


def coerce_types(df: pd.DataFrame, dataset: str, rep: ValidationReport) -> pd.DataFrame:
    sch = SCHEMAS[dataset]
    df = df.copy()
    for col in sch["numeric"]:
        if col in df.columns:
            before = df[col].notna().sum()
            conv = pd.to_numeric(df[col], errors="coerce")
            bad = int(before - conv.notna().sum())
            if bad:
                sev = "error" if col in sch["required"] else "warning"
                rep.add(sev, dataset, "BAD_NUMERIC",
                        f"La columna «{col}» tiene {_n(bad)} valores no numéricos.",
                        bad, "Corrija los valores de texto (p. ej. «N/A», «$12,5») por números.")
            df[col] = conv
    for col in sch["date"]:
        if col in df.columns:
            s = df[col]
            if pd.api.types.is_numeric_dtype(s):
                conv = pd.to_datetime(s, unit="D", origin="1899-12-30", errors="coerce")
            else:
                conv = pd.to_datetime(s, errors="coerce")
            bad = int(s.notna().sum() - conv.notna().sum())
            if bad:
                sev = "error" if col in sch["required"] else "warning"
                rep.add(sev, dataset, "BAD_DATE",
                        f"La columna «{col}» tiene {_n(bad)} fechas no válidas.",
                        bad, "Use un formato de fecha reconocible (AAAA-MM-DD).")
            df[col] = conv
    for col in df.columns:
        if col not in sch["numeric"] and col not in sch["date"]:
            df[col] = df[col].astype("object").where(df[col].isna(), df[col].astype(str).str.strip())
    return df


# ----------------------------------------------------------------------------
# Validación por base
# ----------------------------------------------------------------------------
def validate_dataset(df_raw: pd.DataFrame, dataset: str) -> tuple[pd.DataFrame | None, ValidationReport]:
    """Valida y limpia una base. Devuelve (df_limpio | None si hay errores, informe)."""
    rep = ValidationReport()
    sch, lab = SCHEMAS[dataset], DATASET_LABELS[dataset]
    df = normalize_columns(df_raw, dataset, rep)
    if rep.errors:
        return None, rep
    df = coerce_types(df, dataset, rep)

    # nulos en obligatorias
    for col in sch["required"]:
        empty = df[col].isna()
        if not (pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_datetime64_any_dtype(df[col])):
            empty = empty | df[col].astype(str).str.strip().isin(["", "nan", "None", "NaT"])
        n = int(empty.sum())
        if n:
            rep.add("error", dataset, "NULLS", f"«{col}» tiene {n} valores vacíos.", n,
                    f"Complete o elimine las filas sin «{col}».")

    # duplicados de clave
    key = sch["key"]
    dup = int(df[key].duplicated().sum())
    if dup:
        rep.add("error", dataset, "DUP_KEY", f"{dup} registros con «{key}» repetido en {lab}.", dup,
                f"«{key}» debe ser único. Elimine duplicados o use el modo «agregar solo nuevos» en Ventas.")
    full_dup = int(df.drop(columns=[key]).duplicated().sum())
    if full_dup and not dup:
        rep.add("warning", dataset, "DUP_ROWS",
                f"{full_dup} filas idénticas salvo por «{key}» (posible doble carga).", full_dup,
                "Revise si corresponden a ventas reales repetidas.")

    if dataset == "ventas":
        _check_ventas(df, rep)
    elif dataset == "productos":
        if "Activo" in df.columns:
            df["Activo"] = df["Activo"].map(_yes_no)
        if "Tamaño" not in df.columns:
            df["Tamaño"] = "Único"
    elif dataset == "clientes":
        if "ClienteActivo" in df.columns:
            df["ClienteActivo"] = df["ClienteActivo"].map(_yes_no)

    if rep.errors:
        return None, rep
    rep.stats[f"{dataset}_filas"] = len(df)
    return df, rep


def _yes_no(v):
    s = _norm(v) if isinstance(v, str) else str(v)
    if s in {"si", "yes", "y", "true", "1", "s"}: return "Sí"
    if s in {"no", "false", "0", "n"}: return "No"
    return v


def _check_ventas(df: pd.DataFrame, rep: ValidationReport) -> None:
    d = "ventas"
    if (df["Cantidad"] <= 0).any():
        n = int((df["Cantidad"] <= 0).sum())
        rep.add("warning", d, "QTY", f"{n} registros con cantidad ≤ 0 (posibles devoluciones).", n,
                "Confirme si son devoluciones; se incluyen en los totales tal como vienen.")
    if (df["VentaNeta"] < 0).any():
        n = int((df["VentaNeta"] < 0).sum())
        rep.add("warning", d, "NEG_SALES", f"{n} registros con venta neta negativa.", n)
    if (df["CostoTotal"] < 0).any():
        n = int((df["CostoTotal"] < 0).sum())
        rep.add("error", d, "NEG_COST", f"{n} registros con coste negativo.", n, "El coste no puede ser negativo.")

    if "UtilidadBruta" not in df.columns:
        df["UtilidadBruta"] = (df["VentaNeta"] - df["CostoTotal"]).round(2)
        rep.add("info", d, "DERIVED", "UtilidadBruta no venía en el archivo: se calculó como VentaNeta − CostoTotal.")
    else:
        diff = (df["UtilidadBruta"] - (df["VentaNeta"] - df["CostoTotal"])).abs() > TOLERANCE_USD
        n = int(diff.sum())
        if n:
            rep.add("warning", d, "CONSIST_UTIL",
                    f"{n} registros donde UtilidadBruta ≠ VentaNeta − CostoTotal. "
                    "El modelo recalcula la utilidad desde esos dos campos.", n)
            df["UtilidadBruta"] = (df["VentaNeta"] - df["CostoTotal"]).round(2)
    if {"PrecioUnitario", "DescuentoPct"}.issubset(df.columns):
        calc = df["Cantidad"] * df["PrecioUnitario"] * (1 - df["DescuentoPct"].fillna(0) / 100)
        n = int(((calc - df["VentaNeta"]).abs() > TOLERANCE_USD).sum())
        if n:
            rep.add("warning", d, "CONSIST_NET",
                    f"{n} registros donde VentaNeta ≠ Cantidad × Precio × (1 − Descuento).", n)
    if "CostoUnitario" in df.columns:
        n = int(((df["Cantidad"] * df["CostoUnitario"] - df["CostoTotal"]).abs() > TOLERANCE_USD).sum())
        if n:
            rep.add("warning", d, "CONSIST_COST", f"{n} registros donde CostoTotal ≠ Cantidad × CostoUnitario.", n)
    if "DescuentoPct" in df.columns and ((df["DescuentoPct"] < 0) | (df["DescuentoPct"] > 100)).any():
        n = int(((df["DescuentoPct"] < 0) | (df["DescuentoPct"] > 100)).sum())
        rep.add("error", d, "DISC_RANGE", f"{n} registros con descuento fuera de 0–100 %.", n)
    # Sucursal debe pertenecer a una sola ciudad
    multi = df.groupby("Sucursal")["Ciudad"].nunique()
    bad = multi[multi > 1]
    if len(bad):
        rep.add("error", d, "BRANCH_CITY",
                f"Sucursales asignadas a más de una ciudad: {', '.join(bad.index[:5])}.", len(bad),
                "Cada sucursal debe pertenecer a una única ciudad.")
    fut = int((df["Fecha"] > pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).sum())
    if fut:
        rep.add("warning", d, "FUTURE", f"{fut} ventas con fecha futura.", fut)


# ----------------------------------------------------------------------------
# Validación entre bases (integridad referencial + hallazgos de calidad)
# ----------------------------------------------------------------------------
def validate_relations(ventas: pd.DataFrame, clientes: pd.DataFrame, productos: pd.DataFrame) -> ValidationReport:
    rep = ValidationReport()
    r = "relaciones"
    orf_c = ventas.loc[~ventas["ClienteID"].isin(clientes["ClienteID"]), "ClienteID"]
    if len(orf_c):
        rep.add("error", r, "ORPHAN_CLI",
                f"{len(orf_c)} ventas con ClienteID inexistente en Clientes "
                f"({orf_c.nunique()} IDs distintos, p. ej. {', '.join(orf_c.unique()[:3])}).", len(orf_c),
                "Cargue también la base de clientes actualizada que incluya esos IDs.")
    orf_p = ventas.loc[~ventas["ProductoID"].isin(productos["ProductoID"]), "ProductoID"]
    if len(orf_p):
        rep.add("error", r, "ORPHAN_PROD",
                f"{len(orf_p)} ventas con ProductoID inexistente en Productos "
                f"({orf_p.nunique()} IDs distintos, p. ej. {', '.join(orf_p.unique()[:3])}).", len(orf_p),
                "Cargue también la base de productos actualizada que incluya esos IDs.")
    if rep.errors:
        return rep

    sin_ventas_c = int((~clientes["ClienteID"].isin(ventas["ClienteID"])).sum())
    if sin_ventas_c:
        rep.add("info", r, "CLI_NO_SALES", f"{sin_ventas_c} clientes sin ventas en el período cargado.", sin_ventas_c)
    sin_ventas_p = int((~productos["ProductoID"].isin(ventas["ProductoID"])).sum())
    if sin_ventas_p:
        rep.add("info", r, "PROD_NO_SALES", f"{sin_ventas_p} productos sin ventas en el período cargado.", sin_ventas_p)

    # --- Advertencias de calidad (hallazgos de la auditoría, ahora automáticos) ---
    if "Activo" in productos.columns:
        inact = productos.loc[productos["Activo"] == "No", "ProductoID"]
        m = ventas["ProductoID"].isin(inact)
        if m.any():
            rep.add("warning", r, "INACTIVE_SOLD",
                    f"{_n(m.sum())} ventas corresponden a {ventas.loc[m, 'ProductoID'].nunique()} productos marcados "
                    f"como inactivos ({', '.join(sorted(ventas.loc[m, 'ProductoID'].unique()))}); se incluyen en los totales.",
                    int(m.sum()),
                    "Actualice el estado «Activo» en Productos o confirme el descontinuado.")
    if "FechaRegistro" in clientes.columns:
        j = ventas[["ClienteID", "Fecha"]].merge(clientes[["ClienteID", "FechaRegistro"]], on="ClienteID", how="left")
        n = int((j["Fecha"] < j["FechaRegistro"]).sum())
        if n:
            rep.add("warning", r, "SALE_BEFORE_REG",
                    f"{_n(n)} ventas ({n / len(ventas):.1%}) son anteriores a la fecha de registro del cliente.", n, "Revise FechaRegistro en Clientes.")
    if "Ciudad" in clientes.columns:
        j = ventas[["ClienteID", "Ciudad"]].merge(clientes[["ClienteID", "Ciudad"]], on="ClienteID",
                                                  how="left", suffixes=("", "_cli"))
        same = float((j["Ciudad"] == j["Ciudad_cli"]).mean())
        if same < 0.5:
            rep.add("warning", r, "CITY_MISMATCH",
                    f"Solo el {same:.0%} de las ventas ocurre en la ciudad del cliente. El análisis geográfico usa la "
                    "ciudad de la venta; la ciudad del cliente se trata como residencia.", 0)
    if {"PrecioUnitario"}.issubset(ventas.columns) and "PrecioVentaUSD" in productos.columns:
        p = ventas.groupby("ProductoID")["PrecioUnitario"].mean().rename("pv").reset_index().merge(
            productos[["ProductoID", "PrecioVentaUSD"]], on="ProductoID")
        mism = float((~np.isclose(p["pv"], p["PrecioVentaUSD"], atol=0.02)).mean())
        if mism > 0.5:
            rep.add("warning", r, "PRICE_MISMATCH",
                    f"El precio de venta registrado en Ventas difiere del catálogo en el {mism:.0%} de los productos. "
                    "Los ingresos y costes se calculan con los valores de Ventas.", 0,
                    "Concilie precios y costes del catálogo con los transaccionales.")
    if "UltimaCompra" in clientes.columns:
        n = int((clientes["UltimaCompra"] > ventas["Fecha"].max()).sum())
        if n:
            rep.add("info", r, "CLI_AFTER_SALES",
                    f"{n} clientes tienen «UltimaCompra» posterior a la última venta cargada "
                    f"({ventas['Fecha'].max():%Y-%m-%d}); Clientes parece una foto más reciente que Ventas.", n)
    if {"TotalCompras", "GastoAcumuladoUSD"}.issubset(clientes.columns):
        rep.add("info", r, "CRM_FIELDS",
                "Las columnas acumuladas de Clientes (TotalCompras, GastoAcumuladoUSD, FrecuenciaCompraMensual) "
                "no se usan en los KPI; compras, gasto y frecuencia se recalculan desde Ventas.")
    return rep


def validate_bundle(ventas_raw, clientes_raw, productos_raw) -> tuple[dict | None, ValidationReport]:
    """Valida las tres bases ya leídas y su integridad referencial."""
    rep = ValidationReport()
    clean = {}
    for name, raw in (("ventas", ventas_raw), ("clientes", clientes_raw), ("productos", productos_raw)):
        df, r = validate_dataset(raw, name)
        rep.extend(r)
        clean[name] = df
    if any(v is None for v in clean.values()):
        return None, rep
    rel = validate_relations(clean["ventas"], clean["clientes"], clean["productos"])
    rep.extend(rel)
    if rep.errors:
        return None, rep
    v = clean["ventas"]
    rep.stats.update({
        "periodo_inicio": v["Fecha"].min(), "periodo_fin": v["Fecha"].max(),
        "ventas_filas": len(v), "clientes_filas": len(clean["clientes"]),
        "productos_filas": len(clean["productos"]),
    })
    return clean, rep


def validate_update(new_raw: dict, current: dict, ventas_mode: str = "replace") -> tuple[dict | None, ValidationReport]:
    """Valida una carga parcial: las bases nuevas se validan; las no cargadas se toman de los datos activos.

    ventas_mode: "replace" sustituye toda la base de ventas; "append" agrega solo VentaID nuevos.
    Devuelve (conjunto limpio | None si hay errores, informe).
    """
    rep = ValidationReport()
    clean: dict = {}
    for name in ("ventas", "clientes", "productos"):
        if new_raw.get(name) is not None:
            df, r = validate_dataset(new_raw[name], name)
            rep.extend(r)
            clean[name] = df
        else:
            clean[name] = current[name]
    if any(v is None for v in clean.values()):
        return None, rep

    if new_raw.get("ventas") is not None and ventas_mode == "append":
        old, new = current["ventas"], clean["ventas"]
        dup = new["VentaID"].isin(old["VentaID"])
        added = new[~dup]
        if dup.any():
            rep.add("info", "ventas", "APPEND_DUP",
                    f"{_n(dup.sum())} registros del archivo ya existían (mismo VentaID) y se omitieron.", int(dup.sum()))
        if added.empty:
            rep.add("warning", "ventas", "APPEND_NONE", "El archivo no aporta registros nuevos: no hay nada que agregar.")
        clean["ventas"] = pd.concat([old, added], ignore_index=True)
        rep.add("info", "ventas", "APPEND", f"Se agregarán {_n(len(added))} registros nuevos a los {_n(len(old))} existentes.")

    rep.extend(validate_relations(clean["ventas"], clean["clientes"], clean["productos"]))
    if rep.errors:
        return None, rep
    v = clean["ventas"]
    rep.stats.update({"periodo_inicio": v["Fecha"].min(), "periodo_fin": v["Fecha"].max(),
                      "ventas_filas": len(v), "clientes_filas": len(clean["clientes"]),
                      "productos_filas": len(clean["productos"])})
    return clean, rep
