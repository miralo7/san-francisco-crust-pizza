"""Análisis estratégico: sucursales, productos, clientes, geografía y alertas.

Todas las funciones reciben DataFrames ya filtrados y devuelven tablas verificables.
Ninguna cifra se inventa: cada resultado proviene de agregaciones de la tabla de hechos.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import sfcp_config as config
from sfcp_model import group_kpis, kpis, delta, months_between


# ----------------------------------------------------------------------------
# Formato (estilo español: 1.234,56)
# ----------------------------------------------------------------------------
def _swap(s: str) -> str:
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def usd(x, dec=0) -> str:
    return "n/d" if x is None or x != x else _swap(f"${x:,.{dec}f}")


def pct(x, dec=1) -> str:
    return "n/d" if x is None or x != x else _swap(f"{x:,.{dec}f}%")


def num(x, dec=0) -> str:
    return "n/d" if x is None or x != x else _swap(f"{x:,.{dec}f}")


def signed_pct(x, dec=1, unit="%") -> str:
    return "n/d" if x is None or x != x else _swap(f"{x:+,.{dec}f}") + (" pp" if unit == "pp" else "%")


# ----------------------------------------------------------------------------
# A. Sucursales: ranking conjunto volumen + rentabilidad
# ----------------------------------------------------------------------------
def _rank_score(s: pd.Series) -> pd.Series:
    n = len(s)
    return pd.Series(50.0, index=s.index) if n < 2 else (s.rank(method="average") - 1) / (n - 1) * 100


def branch_table(df: pd.DataFrame) -> pd.DataFrame:
    """Tabla por sucursal con índice de desempeño.

    Índice = 30 % utilidad bruta + 30 % margen bruto + 20 % ticket + 20 % transacciones,
    cada componente expresado como posición relativa 0–100 entre las sucursales evaluadas.
    Es un ranking RELATIVO: informa el orden, no la magnitud de las diferencias.
    """
    t = group_kpis(df, ["Ciudad", "Sucursal"])
    if t.empty:
        return t
    t["idx_volumen"] = (0.5 * _rank_score(t["utilidad"]) + 0.5 * _rank_score(t["transacciones"]))
    t["idx_rentab"] = (0.6 * _rank_score(t["margen"]) + 0.4 * _rank_score(t["ticket"]))
    t["indice"] = 0.5 * t["idx_volumen"] + 0.5 * t["idx_rentab"]
    t = t.sort_values("indice", ascending=False).reset_index(drop=True)
    t["ranking"] = np.arange(1, len(t) + 1)
    return t


# ----------------------------------------------------------------------------
# B. Productos: rotación vs rentabilidad
# ----------------------------------------------------------------------------
PRODUCT_GROUPS = {
    "Estrella": "Alta rotación y margen sobre el promedio. Proteger disponibilidad y precio; usar como ancla de combos.",
    "Alta rotación, baja rentabilidad": "Mucho volumen pero margen bajo el promedio. Revisar coste de receta/proveedor, precio y descuentos aplicados.",
    "Baja rotación, alta rentabilidad": "Margen sobre el promedio pero poco volumen. Impulsar con visibilidad en menú, upselling y promociones focalizadas.",
    "Bajo desempeño": "Baja rotación y margen bajo el promedio. Evaluar reposicionar, rediseñar o retirar del menú.",
}


def product_table(df: pd.DataFrame) -> pd.DataFrame:
    """Clasificación 2×2. Umbrales: rotación = mediana de unidades; rentabilidad = margen ponderado global."""
    t = group_kpis(df, ["ProductoID", "ProductoLabel", "Categoria", "ProductoActivo"])
    if t.empty:
        return t
    mediana_u, margen_global = t["unidades"].median(), kpis(df)["margen"]
    alta_rot, alto_mg = t["unidades"] >= mediana_u, t["margen"] >= margen_global
    t["grupo"] = np.select(
        [alta_rot & alto_mg, alta_rot & ~alto_mg, ~alta_rot & alto_mg],
        ["Estrella", "Alta rotación, baja rentabilidad", "Baja rotación, alta rentabilidad"],
        default="Bajo desempeño")
    t.attrs.update(mediana_unidades=float(mediana_u), margen_global=float(margen_global))
    return t.sort_values("utilidad", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------------
# C. Clientes por segmento
# ----------------------------------------------------------------------------
def segment_table(df: pd.DataFrame, prev: pd.DataFrame | None, base_clientes: pd.DataFrame,
                  months: float) -> pd.DataFrame:
    """Desempeño ACTUAL por segmento (no se infiere potencial futuro).

    `base_clientes` = una fila por cliente (dimensión) para calcular tamaño de base, NPS y % activos.
    """
    t = group_kpis(df, "Segmento")
    if t.empty:
        return t
    t["ventas_por_cliente"] = t["ventas"] / t["clientes"].replace(0, np.nan)
    t["frecuencia_mensual"] = t["transacciones"] / t["clientes"].replace(0, np.nan) / months
    base = base_clientes.groupby("Segmento").agg(base=("ClienteID", "nunique"))
    if "NPS" in base_clientes.columns:
        base["nps_prom"] = base_clientes.groupby("Segmento")["NPS"].mean()
    if "ClienteActivo" in base_clientes.columns:
        base["pct_activos"] = base_clientes.groupby("Segmento")["ClienteActivo"].apply(lambda s: (s == "Sí").mean() * 100)
    t = t.merge(base.reset_index(), on="Segmento", how="left")
    t["pct_base"] = t["base"] / t["base"].sum() * 100
    if prev is not None and len(prev):
        pv = prev.groupby("Segmento")["VentaNeta"].sum().rename("ventas_prev")
        t = t.merge(pv.reset_index(), on="Segmento", how="left")
        t["crec_ventas"] = (t["ventas"] / t["ventas_prev"] - 1) * 100
    else:
        t["crec_ventas"] = np.nan
    return t.sort_values("ventas", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------------
# D. Geografía
# ----------------------------------------------------------------------------
def city_table(df: pd.DataFrame) -> pd.DataFrame:
    t = group_kpis(df, "Ciudad")
    nb = df.groupby("Ciudad")["Sucursal"].nunique().rename("sucursales").reset_index()
    t = t.merge(nb, on="Ciudad")
    t["ventas_por_sucursal"] = t["ventas"] / t["sucursales"]
    return t.sort_values("ventas", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------------
# Alertas automáticas (semáforo del dashboard)
# ----------------------------------------------------------------------------
def build_alerts(cur: pd.DataFrame, prev: pd.DataFrame | None) -> list[dict]:
    """Devuelve alertas {nivel, titulo, detalle}; nivel ∈ {critico, atencion, positivo}."""
    out: list[dict] = []
    if cur.empty:
        return [{"nivel": "atencion", "titulo": "Sin datos", "detalle": "Los filtros actuales no devuelven registros."}]
    k = kpis(cur)
    if prev is not None and len(prev):
        kp = kpis(prev)
        d_v, d_m = delta(k["ventas"], kp["ventas"]), delta(k["margen"], kp["margen"], "pp")
        d_d = delta(k["descuento_pct"], kp["descuento_pct"], "pp")
        if d_v is not None and d_v <= config.ALERT_SALES_DROP * 100:
            out.append({"nivel": "critico", "titulo": "Caída de ventas",
                        "detalle": f"Ventas {signed_pct(d_v)} vs período anterior ({usd(kp['ventas'])} → {usd(k['ventas'])})."})
        elif d_v is not None and d_v > 5:
            out.append({"nivel": "positivo", "titulo": "Crecimiento de ventas",
                        "detalle": f"Ventas {signed_pct(d_v)} vs período anterior."})
        if d_m is not None and d_m <= config.ALERT_MARGIN_DROP_PP:
            out.append({"nivel": "atencion", "titulo": "Margen en retroceso",
                        "detalle": f"Margen bruto {pct(k['margen'], 2)} ({signed_pct(d_m, 2, 'pp')} vs período anterior)."})
        if d_d is not None and d_d >= config.ALERT_DISCOUNT_RISE_PP:
            out.append({"nivel": "atencion", "titulo": "Mayor peso de descuentos",
                        "detalle": f"Descuento / venta bruta {pct(k['descuento_pct'], 2)} "
                                   f"({signed_pct(d_d, 2, 'pp')} vs período anterior)."})
    b = branch_table(cur)
    if len(b) >= 2:
        low = b.sort_values("margen").iloc[0]
        if k["margen"] - low["margen"] >= 1.0:
            out.append({"nivel": "atencion", "titulo": f"Margen bajo en {low['Sucursal']}",
                        "detalle": f"{pct(low['margen'], 2)} frente a {pct(k['margen'], 2)} del total filtrado "
                                   f"(descuento {pct(low['descuento_pct'], 2)} de la venta bruta)."})
    p = product_table(cur)
    if len(p) >= 4:
        n = int((p["grupo"] == "Alta rotación, baja rentabilidad").sum())
        if n:
            out.append({"nivel": "atencion", "titulo": "Productos de alta rotación y bajo margen",
                        "detalle": f"{n} productos venden sobre la mediana pero con margen bajo el promedio."})
    if not out:
        out.append({"nivel": "positivo", "titulo": "Sin alertas", "detalle": "Ningún umbral de alerta superado en el período."})
    return out
