"""Diagnóstico automático por reglas (sin IA generativa).

Cada hallazgo usa la estructura exigida: hallazgo, evidencia numérica, interpretación,
recomendación, impacto esperado, prioridad e indicador de seguimiento. Las cifras salen
exclusivamente de los datos filtrados; las hipótesis se rotulan como tales.
"""
from __future__ import annotations

import pandas as pd

from sfcp_analysis import branch_table, city_table, product_table, segment_table, usd, pct, num, signed_pct
from sfcp_model import kpis, delta, group_kpis


def _f(hallazgo, evidencia, interpretacion, recomendacion, impacto, prioridad, kpi):
    return dict(hallazgo=hallazgo, evidencia=evidencia, interpretacion=interpretacion,
                recomendacion=recomendacion, impacto=impacto, prioridad=prioridad, kpi=kpi)


def auto_findings(cur: pd.DataFrame, prev: pd.DataFrame | None, base_clientes: pd.DataFrame, months: float) -> list[dict]:
    if cur.empty:
        return []
    out: list[dict] = []
    k = kpis(cur)
    kp = kpis(prev) if prev is not None and len(prev) else None

    # 1) Situación comercial: volumen vs ticket
    if kp:
        dv, dt, dk = delta(k["ventas"], kp["ventas"]), delta(k["transacciones"], kp["transacciones"]), delta(k["ticket"], kp["ticket"])
        dm = delta(k["margen"], kp["margen"], "pp")
        driver = "el volumen de transacciones" if abs(dt or 0) > abs(dk or 0) else "el ticket promedio"
        out.append(_f(
            f"Ventas {'en caída' if (dv or 0) < 0 else 'en crecimiento'} frente al período anterior",
            f"Ventas {usd(kp['ventas'])} → {usd(k['ventas'])} ({signed_pct(dv)}); transacciones {signed_pct(dt)}; "
            f"ticket {usd(kp['ticket'], 2)} → {usd(k['ticket'], 2)} ({signed_pct(dk)}); margen {pct(kp['margen'], 2)} → {pct(k['margen'], 2)} ({signed_pct(dm, 2, 'pp')}).",
            f"HECHO: la variación se explica principalmente por {driver}. Los datos no contienen las causas "
            "(tráfico, precios de competencia, estacionalidad), por lo que cualquier causa es HIPÓTESIS.",
            "Priorizar un diagnóstico de causas del cambio en transacciones (por sucursal, canal y segmento) antes de decidir acciones de precio.",
            "Cualitativo: recuperar el nivel de transacciones del período anterior. No se cuantifica en USD sin un supuesto de recuperación.",
            "Alta" if (dv or 0) <= -10 else "Media", "Transacciones mensuales; ventas netas mensuales"))

    # 2) Sucursal de menor margen
    b = branch_table(cur)
    if len(b) >= 2:
        low, top = b.sort_values("margen").iloc[0], b.sort_values("margen").iloc[-1]
        gap = top["margen"] - low["margen"]
        rest = cur[cur["Sucursal"] != low["Sucursal"]]
        dsc_rest = kpis(rest)["descuento_pct"]
        ilus = low["ventas"] * gap / 100
        out.append(_f(
            f"{low['Sucursal']} tiene el menor margen bruto",
            f"Margen {pct(low['margen'], 2)} vs {pct(top['margen'], 2)} de {top['Sucursal']} (brecha {num(gap, 2)} pp); "
            f"descuento/venta bruta {pct(low['descuento_pct'], 2)} vs {pct(dsc_rest, 2)} en el resto; ticket {usd(low['ticket'], 2)}.",
            "HECHO: menor margen y mayor peso de descuentos coexisten en esta sucursal. HIPÓTESIS: la política de descuentos explica la brecha "
            "(el análisis es descriptivo; no prueba causalidad).",
            f"Auditar la política y el uso de descuentos en {low['Sucursal']} y comparar con las sucursales de mayor margen.",
            f"Ilustrativo (supuesto: mismas ventas de {usd(low['ventas'])} y margen igual al de {top['Sucursal']}): ≈ {usd(ilus)} adicionales de utilidad en el período.",
            "Alta" if gap >= 1 else "Media", "Margen bruto por sucursal; descuento % de la venta bruta"))

    # 3) Productos de alta rotación y baja rentabilidad
    p = product_table(cur)
    if len(p) >= 4:
        cand = p[p["grupo"] == "Alta rotación, baja rentabilidad"].nlargest(3, "unidades")
        if len(cand):
            ev = "; ".join(f"{r.ProductoLabel}: {num(r.unidades)} uds, margen {pct(r.margen, 1)}" for r in cand.itertuples())
            out.append(_f(
                "Productos que venden mucho pero con margen bajo el promedio",
                f"{ev}. Margen global del conjunto: {pct(p.attrs['margen_global'], 2)}.",
                "HECHO: estos productos superan la mediana de unidades y quedan bajo el margen global. HIPÓTESIS: hay espacio para ajustar precio o coste.",
                "Revisar precio y coste de receta/proveedor de estos productos; evaluar excluirlos de promociones de descuento.",
                "Cualitativo: elevar el margen de los productos de mayor volumen tiene el mayor efecto sobre la utilidad total.",
                "Media", "Margen % por producto; utilidad por unidad"))
        top5 = p.nlargest(5, "utilidad")
        out.append(_f(
            "Concentración de la utilidad en pocos productos",
            f"Los 5 productos con mayor utilidad ({', '.join(top5['ProductoLabel'])}) aportan {pct(top5['utilidad'].sum() / p['utilidad'].sum() * 100, 1)} "
            f"de la utilidad bruta sobre {len(p)} productos.",
            "HECHO descriptivo. Un reparto cercano a lo proporcional (5/{} = {}) indica baja dependencia de pocos productos.".format(
                len(p), pct(5 / len(p) * 100, 1)),
            "Proteger disponibilidad y precio de los productos líderes; usarlos como ancla de combos.",
            "Cualitativo: reduce el riesgo de perder utilidad por desabastecimiento de los productos clave.",
            "Baja", "Participación de utilidad del top 5"))

    # 4) Descuentos
    if "DescuentoUSD" in cur.columns and cur["DescuentoUSD"].sum() > 0:
        con, sin = cur[cur["DescuentoUSD"] > 0], cur[cur["DescuentoUSD"] == 0]
        share = len(con) / len(cur) * 100
        extra = f" Período anterior: {pct(kp['descuento_pct'], 2)}." if kp else ""
        out.append(_f(
            "Los descuentos reducen el margen de las líneas en que se aplican",
            f"{pct(share, 1)} de las líneas tiene descuento; total descontado {usd(k['descuento_usd'])} ({pct(k['descuento_pct'], 2)} de la venta bruta). "
            f"Margen con descuento {pct(kpis(con)['margen'], 2)} vs sin descuento {pct(kpis(sin)['margen'], 2)}.{extra}",
            "HECHO: a coste fijo, un descuento reduce mecánicamente el margen de la línea. No se puede afirmar si los descuentos generaron ventas adicionales (no hay grupo de control).",
            "Definir reglas de tope y vigencia de descuentos y medir su efecto en transacciones con un piloto controlado.",
            "Cualitativo: contener el costo de descuentos; el efecto en ventas requiere piloto.",
            "Media", "Descuento % de la venta bruta; transacciones en periodos con y sin promoción"))

    # 5) Segmentos
    seg = segment_table(cur, prev, base_clientes, months)
    if len(seg) >= 2:
        s_top, s_mg = seg.iloc[0], seg.sort_values("margen").iloc[-1]
        s_vpc = seg.sort_values("ventas_por_cliente").iloc[-1]
        ev = f"Mayores ventas: {s_top['Segmento']} ({usd(s_top['ventas'])}, {pct(s_top['participacion'], 1)}). Mayor margen: {s_mg['Segmento']} ({pct(s_mg['margen'], 2)}). " \
             f"Mayor venta por cliente: {s_vpc['Segmento']} ({usd(s_vpc['ventas_por_cliente'])})."
        if seg["crec_ventas"].notna().any():
            g = seg.sort_values("crec_ventas").iloc[-1]
            ev += f" Mayor crecimiento observado: {g['Segmento']} ({signed_pct(g['crec_ventas'])})."
        out.append(_f(
            "Desempeño actual por segmento de cliente",
            ev,
            "HECHO sobre desempeño actual. El potencial futuro NO puede inferirse: no hay datos de mercado ni de propensión de compra por segmento.",
            "Diseñar fidelización para el segmento de mayor venta por cliente y pruebas de captación en el de mayor crecimiento observado.",
            "Cualitativo: foco comercial por segmento; cuantificar requiere un supuesto de conversión.",
            "Media", "Ventas por cliente; frecuencia mensual; crecimiento por segmento"))

    # 6) Geografía
    c = city_table(cur)
    if len(c) >= 2:
        out.append(_f(
            "Distribución geográfica de las ventas",
            f"Mayor ciudad: {c.iloc[0]['Ciudad']} ({pct(c.iloc[0]['participacion'], 1)}); menor: {c.iloc[-1]['Ciudad']} ({pct(c.iloc[-1]['participacion'], 1)}). "
            f"Margen por ciudad entre {pct(c['margen'].min(), 2)} y {pct(c['margen'].max(), 2)}.",
            "HECHO descriptivo. Diferencias pequeñas entre ciudades sugieren un negocio equilibrado; las diferencias de margen merecen revisión puntual.",
            "Concentrar el análisis en las ciudades con menor margen antes que en las de menor venta.",
            "Cualitativo.", "Baja", "Participación de ventas y margen por ciudad"))
    return out
