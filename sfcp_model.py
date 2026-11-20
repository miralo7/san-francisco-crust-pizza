"""Modelo de datos (hechos + dimensiones), filtros y cálculo de indicadores.

Decisiones metodológicas (ver README):
  * Ingresos y costes provienen de Ventas (VentaNeta, CostoTotal).
  * VentaNeta ya está neta de descuentos: no se vuelve a restar el descuento.
  * Transacción = un VentaID (una línea de producto).
  * Margen bruto % = Utilidad / Ventas (ponderado), nunca promedio de porcentajes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


class ModelIntegrityError(Exception):
    """Se lanza si el modelo duplicaría o perdería ingresos al integrar las bases."""


def safe_div(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(b != 0, a / b, np.nan)
    return out if out.ndim else float(out)


# ----------------------------------------------------------------------------
# Construcción del modelo
# ----------------------------------------------------------------------------
def build_fact(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Integra Ventas + Productos + Clientes en una tabla de hechos desnormalizada."""
    v, c, p = data["ventas"].copy(), data["clientes"].copy(), data["productos"].copy()
    n0, s0, c0 = len(v), v["VentaNeta"].sum(), v["CostoTotal"].sum()

    v["UtilidadBruta"] = (v["VentaNeta"] - v["CostoTotal"]).round(2)
    if "PrecioUnitario" in v.columns:
        v["VentaBruta"] = v["Cantidad"] * v["PrecioUnitario"]
    elif "DescuentoPct" in v.columns:
        v["VentaBruta"] = safe_div(v["VentaNeta"], 1 - v["DescuentoPct"].fillna(0) / 100)
    else:
        v["VentaBruta"] = v["VentaNeta"]
    v["VentaBruta"] = v["VentaBruta"].where(v["VentaBruta"] >= v["VentaNeta"], v["VentaNeta"])
    v["DescuentoUSD"] = (v["VentaBruta"] - v["VentaNeta"]).round(2)
    for col, default in (("Canal", "N/D"), ("FormaPago", "N/D")):
        if col not in v.columns:
            v[col] = default

    p["Tamaño"] = p.get("Tamaño", pd.Series("Único", index=p.index)).fillna("Único")
    p["ProductoLabel"] = np.where(p["Tamaño"].astype(str).isin(["Único", "", "nan"]),
                                  p["Producto"], p["Producto"] + " " + p["Tamaño"].astype(str))
    pcols = ["ProductoID", "Categoria", "Producto", "Tamaño", "ProductoLabel"]
    if "Activo" in p.columns:
        p["ProductoActivo"] = p["Activo"]
        pcols.append("ProductoActivo")
    ccols = ["ClienteID", "Segmento"]
    ren = {}
    if "Ciudad" in c.columns:
        ren["Ciudad"] = "CiudadCliente"
    c = c.rename(columns=ren)
    ccols += [x for x in ("CiudadCliente", "Edad", "Sexo", "NPS", "ClienteActivo", "MotivoPerdida") if x in c.columns]

    f = (v.merge(p[pcols], on="ProductoID", how="left", validate="m:1")
          .merge(c[ccols], on="ClienteID", how="left", validate="m:1"))
    if "ProductoActivo" not in f.columns:
        f["ProductoActivo"] = "Sí"
    f["Periodo"] = f["Fecha"].dt.to_period("M").dt.to_timestamp()

    # Controles de integridad: la integración no puede cambiar filas ni importes
    if len(f) != n0:
        raise ModelIntegrityError(f"La integración alteró el número de filas ({n0} → {len(f)}).")
    if not np.isclose(f["VentaNeta"].sum(), s0) or not np.isclose(f["CostoTotal"].sum(), c0):
        raise ModelIntegrityError("La integración alteró los importes de ventas o costes.")
    return f


# ----------------------------------------------------------------------------
# Filtros
# ----------------------------------------------------------------------------
@dataclass
class Filters:
    date_start: pd.Timestamp
    date_end: pd.Timestamp
    ciudades: list[str] = field(default_factory=list)
    sucursales: list[str] = field(default_factory=list)
    segmentos: list[str] = field(default_factory=list)
    categorias: list[str] = field(default_factory=list)
    productos: list[str] = field(default_factory=list)   # ProductoLabel

    def describe(self) -> dict:
        return {
            "periodo": f"{pd.Timestamp(self.date_start):%Y-%m-%d} a {pd.Timestamp(self.date_end):%Y-%m-%d}",
            "ciudades": self.ciudades or "todas", "sucursales": self.sucursales or "todas",
            "segmentos": self.segmentos or "todos", "categorias": self.categorias or "todas",
            "productos": self.productos or "todos",
        }


def apply_filters(fact: pd.DataFrame, f: Filters, start=None, end=None) -> pd.DataFrame:
    s, e = pd.Timestamp(start or f.date_start), pd.Timestamp(end or f.date_end)
    m = (fact["Fecha"] >= s) & (fact["Fecha"] < e + pd.Timedelta(days=1))
    for col, vals in (("Ciudad", f.ciudades), ("Sucursal", f.sucursales), ("Segmento", f.segmentos),
                      ("Categoria", f.categorias), ("ProductoLabel", f.productos)):
        if vals:
            m &= fact[col].isin(vals)
    return fact[m]


def previous_window(start, end, data_min) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Período inmediatamente anterior de igual duración (calendario si son meses completos).

    Devuelve None si el período anterior no está completamente cubierto por los datos.
    """
    start, end, data_min = pd.Timestamp(start), pd.Timestamp(end), pd.Timestamp(data_min)
    if start.day == 1 and (end + pd.Timedelta(days=1)).day == 1:
        n = (end.year - start.year) * 12 + end.month - start.month + 1
        pstart = start - pd.DateOffset(months=n)
        pend = start - pd.Timedelta(days=1)
    else:
        days = (end - start).days + 1
        pend = start - pd.Timedelta(days=1)
        pstart = pend - pd.Timedelta(days=days - 1)
    return (pstart, pend) if pstart >= data_min else None


def valid_options(fact: pd.DataFrame, ciudades=(), categorias=()) -> dict[str, list[str]]:
    """Opciones de filtro coherentes entre sí (sucursales según ciudad; productos según categoría)."""
    d = fact
    if ciudades:
        d = d[d["Ciudad"].isin(ciudades)]
    suc = sorted(d["Sucursal"].unique())
    dp = fact[fact["Categoria"].isin(categorias)] if categorias else fact
    return {
        "ciudades": sorted(fact["Ciudad"].unique()), "sucursales": suc,
        "segmentos": sorted(fact["Segmento"].dropna().unique()),
        "categorias": sorted(fact["Categoria"].dropna().unique()),
        "productos": sorted(dp["ProductoLabel"].dropna().unique()),
    }


# ----------------------------------------------------------------------------
# Indicadores
# ----------------------------------------------------------------------------
def kpis(df: pd.DataFrame, months: float | None = None) -> dict:
    ventas, costo = float(df["VentaNeta"].sum()), float(df["CostoTotal"].sum())
    utilidad = ventas - costo
    tx, cli = int(df["VentaID"].nunique()), int(df["ClienteID"].nunique())
    bruta = float(df["VentaBruta"].sum())
    out = {
        "ventas": ventas, "costo": costo, "utilidad": utilidad,
        "margen": safe_div(utilidad, ventas) * 100,
        "transacciones": tx, "clientes": cli,
        "ticket": safe_div(ventas, tx), "unidades": int(df["Cantidad"].sum()),
        "descuento_usd": float(df["DescuentoUSD"].sum()),
        "descuento_pct": safe_div(df["DescuentoUSD"].sum(), bruta) * 100,
    }
    if months:
        out["frecuencia_mensual"] = safe_div(tx, cli) / months
    return out


def group_kpis(df: pd.DataFrame, by) -> pd.DataFrame:
    g = (df.groupby(by, observed=True, dropna=False)
           .agg(ventas=("VentaNeta", "sum"), costo=("CostoTotal", "sum"),
                transacciones=("VentaID", "nunique"), unidades=("Cantidad", "sum"),
                clientes=("ClienteID", "nunique"), bruta=("VentaBruta", "sum"),
                desc=("DescuentoUSD", "sum")).reset_index())
    g["utilidad"] = g["ventas"] - g["costo"]
    g["margen"] = safe_div(g["utilidad"], g["ventas"]) * 100
    g["ticket"] = safe_div(g["ventas"], g["transacciones"])
    g["descuento_pct"] = safe_div(g["desc"], g["bruta"]) * 100
    g["participacion"] = safe_div(g["ventas"], g["ventas"].sum()) * 100
    return g.drop(columns=["bruta", "desc"])


def timeseries(df: pd.DataFrame, freq: str = "MS") -> pd.DataFrame:
    g = (df.groupby(pd.Grouper(key="Fecha", freq=freq))
           .agg(ventas=("VentaNeta", "sum"), costo=("CostoTotal", "sum"),
                transacciones=("VentaID", "nunique")).reset_index())
    g = g[g["transacciones"] > 0].copy()
    g["utilidad"] = g["ventas"] - g["costo"]
    g["margen"] = safe_div(g["utilidad"], g["ventas"]) * 100
    return g


def months_between(start, end) -> float:
    return max(((pd.Timestamp(end) - pd.Timestamp(start)).days + 1) / 30.4375, 1 / 30.4375)


def delta(cur: float, prev: float | None, kind: str = "pct") -> float | None:
    """Variación relativa (pct) o en puntos porcentuales (pp)."""
    if prev is None or prev != prev or cur != cur:
        return None
    if kind == "pp":
        return cur - prev
    return None if prev == 0 else (cur - prev) / abs(prev) * 100


def consistency_report(fact: pd.DataFrame, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Controles de consistencia ventas–costes–utilidad y de integración (Fase 6)."""
    v = data["ventas"]
    rows = [
        ("Filas de la tabla de hechos = filas de Ventas", len(fact), len(v)),
        ("Σ VentaNeta (modelo) = Σ VentaNeta (original)", fact["VentaNeta"].sum(), v["VentaNeta"].sum()),
        ("Σ CostoTotal (modelo) = Σ CostoTotal (original)", fact["CostoTotal"].sum(), v["CostoTotal"].sum()),
        ("Utilidad = Ventas − Costes", fact["UtilidadBruta"].sum(), fact["VentaNeta"].sum() - fact["CostoTotal"].sum()),
        ("VentaID únicos = filas (sin duplicados)", fact["VentaID"].nunique(), len(fact)),
        ("Ventas sin cliente asignado", int(fact["Segmento"].isna().sum()), 0),
        ("Ventas sin producto asignado", int(fact["Categoria"].isna().sum()), 0),
    ]
    out = pd.DataFrame(rows, columns=["Control", "Modelo", "Esperado"])
    out["OK"] = [bool(np.isclose(a, b, atol=0.01)) for a, b in zip(out["Modelo"], out["Esperado"])]
    return out
