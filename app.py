"""San Francisco Crust Pizza — Sistema Inteligente de Apoyo a la Toma de Decisiones (BI).

Ejecutar:  streamlit run app.py
"""
from __future__ import annotations

import hmac
import os

import pandas as pd
import streamlit as st

from src import ai_assistant as ai
from src import analysis as an
from src import charts as ch
from src import insights, storage
from src.config import DATASET_LABELS, SCHEMAS, COLORS
from src.model import (Filters, apply_filters, build_fact, consistency_report, delta, group_kpis,
                       kpis, months_between, previous_window, timeseries, valid_options)
from src.validation import ValidationReport, read_table, validate_update

st.set_page_config(page_title="SF Crust Pizza · BI", page_icon="🍕", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap');
html, body, [class*="st-"] {{ font-family: 'IBM Plex Sans', 'Segoe UI', Arial, sans-serif; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1400px; }}
h1 {{ font-size: 1.7rem !important; font-weight: 600 !important; margin-bottom: .1rem; }}
h2, h3 {{ font-weight: 600 !important; }}
[data-testid="stSidebar"] .brand {{ font-weight: 600; font-size: 1.05rem; color: {COLORS['tomato']}; line-height: 1.2; }}
[data-testid="stSidebar"] .brand small {{ display:block; color: {COLORS['muted']}; font-weight: 400; font-size: .8rem; }}
.note {{ color: {COLORS['muted']}; font-size: .85rem; }}
.pill {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:.78rem; font-weight:600; }}
.pill.ok {{ background:#E3F1E8; color:{COLORS['basil']}; }} .pill.warn {{ background:#F8EDD5; color:#8A5E0C; }}
.pill.err {{ background:#F6DDD9; color:{COLORS['tomato']}; }}
</style>
""", unsafe_allow_html=True)

PAGES = ["Dashboard ejecutivo", "Sucursales", "Productos", "Clientes", "Geografía",
         "Asistente de IA", "Datos y actualización"]
PLOT_CFG = {"displayModeBar": False}


def show(fig, key=None):
    st.plotly_chart(fig, width="stretch", config=PLOT_CFG, key=key)


# ----------------------------------------------------------------------------
# Carga de datos (cacheada por versión del conjunto activo)
# ----------------------------------------------------------------------------
def current_meta() -> dict:
    meta = storage.read_meta()
    if meta is None or storage.load_active() is None:
        with st.spinner("Preparando la base de datos inicial (solo la primera vez)…"):
            storage.bootstrap_from_seed()
        meta = storage.read_meta()
    return meta


@st.cache_data(show_spinner="Cargando y modelando datos…")
def get_bundle(version: str):
    data = storage.ensure_data()
    return data, build_fact(data)


meta = current_meta()
data, fact = get_bundle(meta["version"])

# ----------------------------------------------------------------------------
# Filtros globales (barra lateral)
# ----------------------------------------------------------------------------
FILTER_KEYS = ("f_ciudad", "f_sucursal", "f_segmento", "f_categoria", "f_producto")


def date_bounds(f: pd.DataFrame):
    dmin, dmax = f["Fecha"].min().normalize(), f["Fecha"].max().normalize()
    lo = dmin.replace(day=1)
    hi = (dmax + pd.offsets.MonthEnd(0)).normalize()
    start = max(lo, pd.Timestamp(year=dmax.year, month=1, day=1))
    return lo.date(), hi.date(), (start.date(), hi.date())


LO, HI, DEFAULT_DATES = date_bounds(fact)


def reset_filters():
    for k in FILTER_KEYS:
        st.session_state[k] = []
    st.session_state["f_dates"] = DEFAULT_DATES


if st.session_state.get("_ver") != meta["version"]:      # datos nuevos → filtros nuevos
    reset_filters()
    st.session_state["_ver"] = meta["version"]

with st.sidebar:
    st.markdown('<div class="brand">San Francisco Crust Pizza<small>Inteligencia de Negocios</small></div>',
                unsafe_allow_html=True)
    page = st.radio("Sección", PAGES, key="nav", label_visibility="collapsed")
    st.divider()
    st.markdown("**Filtros globales**")
    st.date_input("Período", min_value=LO, max_value=HI, key="f_dates", format="DD/MM/YYYY")
    opts = valid_options(fact)
    st.multiselect("Ciudad", opts["ciudades"], key="f_ciudad", placeholder="Todas")
    opts = valid_options(fact, st.session_state.f_ciudad, st.session_state.f_categoria)
    st.session_state.f_sucursal = [s for s in st.session_state.f_sucursal if s in opts["sucursales"]]
    st.multiselect("Sucursal", opts["sucursales"], key="f_sucursal", placeholder="Todas")
    st.multiselect("Segmento de cliente", opts["segmentos"], key="f_segmento", placeholder="Todos")
    st.multiselect("Categoría", opts["categorias"], key="f_categoria", placeholder="Todas")
    opts = valid_options(fact, st.session_state.f_ciudad, st.session_state.f_categoria)
    st.session_state.f_producto = [p for p in st.session_state.f_producto if p in opts["productos"]]
    st.multiselect("Producto", opts["productos"], key="f_producto", placeholder="Todos")
    st.button("Restablecer filtros", on_click=reset_filters, width="stretch")
    st.caption(f"Datos actualizados: {meta['updated_at']}")

dates = st.session_state.f_dates
if not isinstance(dates, (tuple, list)) or len(dates) != 2:
    st.info("Seleccione la fecha final del período en la barra lateral para continuar.")
    st.stop()

F = Filters(pd.Timestamp(dates[0]), pd.Timestamp(dates[1]), st.session_state.f_ciudad, st.session_state.f_sucursal,
            st.session_state.f_segmento, st.session_state.f_categoria, st.session_state.f_producto)
cur = apply_filters(fact, F)
pw = previous_window(F.date_start, F.date_end, fact["Fecha"].min())
prev = apply_filters(fact, F, *pw) if pw else None
if prev is not None and prev.empty:
    prev = None
months = max(cur["Periodo"].nunique(), 1) if len(cur) else 1
base_clientes = data["clientes"]


def header(title: str):
    st.title(title)
    f = F.describe()
    active = [f"{k}: {', '.join(v)}" for k, v in f.items() if k != "periodo" and isinstance(v, list)]
    cmp_txt = f"comparado con {pw[0]:%d/%m/%Y}–{pw[1]:%d/%m/%Y}" if (pw and prev is not None) else "sin período anterior comparable"
    st.markdown(f'<p class="note">Período {F.date_start:%d/%m/%Y} – {F.date_end:%d/%m/%Y} · {cmp_txt} · '
                f'{an.num(len(cur))} registros{(" · " + " · ".join(active)) if active else ""}</p>', unsafe_allow_html=True)


def need_data() -> bool:
    if cur.empty:
        st.warning("Los filtros seleccionados no devuelven registros. Amplíe el período o restablezca los filtros.")
        return True
    return False


# ----------------------------------------------------------------------------
# 1. Dashboard ejecutivo
# ----------------------------------------------------------------------------
def page_dashboard():
    header("Dashboard ejecutivo")
    if need_data():
        return
    k = kpis(cur, months)
    kp = kpis(prev) if prev is not None else None
    tip = "Variación frente al período anterior de igual duración." if kp else "No hay un período anterior completo dentro de los datos."

    def card(col, label, value, key, kind="pct", help_=None):
        d = delta(k[key], kp[key], kind) if kp else None
        txt = None if d is None else (an.signed_pct(d, 2, "pp") if kind == "pp" else an.signed_pct(d)) + " vs anterior"
        col.metric(label, value, txt, help=help_ or tip, border=True)

    c = st.columns(3)
    card(c[0], "Ventas totales", an.usd(k["ventas"]), "ventas", help_="Σ VentaNeta (ya neta de descuentos).")
    card(c[1], "Utilidad bruta", an.usd(k["utilidad"]), "utilidad", help_="Ventas − coste de lo vendido.")
    card(c[2], "Margen bruto", an.pct(k["margen"], 2), "margen", "pp", "Utilidad bruta / ventas × 100 (ponderado). Variación en puntos porcentuales.")
    c = st.columns(3)
    card(c[0], "Ticket promedio", an.usd(k["ticket"], 2), "ticket", help_="Ventas totales / transacciones.")
    card(c[1], "Clientes únicos", an.num(k["clientes"]), "clientes", help_="Clientes distintos con compras en el período.")
    card(c[2], "Transacciones", an.num(k["transacciones"]), "transacciones", help_="Número de VentaID (líneas de producto).")

    with st.expander("Alertas y señales del período", expanded=True):
        icon = {"critico": "🔴", "atencion": "🟡", "positivo": "🟢"}
        for a in an.build_alerts(cur, prev):
            st.markdown(f"{icon[a['nivel']]} **{a['titulo']}** — {a['detalle']}")

    g = st.radio("Granularidad temporal", ["Mensual", "Trimestral", "Semanal"], horizontal=True, key="gran")
    freq = {"Mensual": "MS", "Trimestral": "QS", "Semanal": "W-MON"}[g]
    ts = timeseries(cur, freq)
    a, b = st.columns(2)
    with a:
        show(ch.sales_trend(ts, g))
        st.caption("Cómo leerlo: cada punto suma las ventas netas del período; la línea muestra la dirección del negocio.")
    with b:
        show(ch.profit_trend(ts, g))
        st.caption("Barras = utilidad bruta en USD; línea = margen bruto %. Si las barras bajan y la línea no, el cambio es de volumen, no de rentabilidad.")
    a, b = st.columns(2)
    ciu, seg = group_kpis(cur, "Ciudad"), an.segment_table(cur, prev, base_clientes, months)
    with a:
        show(ch.city_sales(ciu))
        st.caption("Ventas netas acumuladas del período filtrado por ciudad de la venta.")
    with b:
        show(ch.segment_bars(seg))
        st.caption("Segmento tomado de la base de Clientes y unido a cada venta por ClienteID.")
    a, b = st.columns(2)
    with a:
        show(ch.category_donut(group_kpis(cur, "Categoria")))
        st.caption("Porcentaje de las ventas netas que aporta cada categoría.")
    with b:
        show(ch.category_stacked(cur))
        st.caption("Evolución mensual de la mezcla de categorías (apiladas).")


# ----------------------------------------------------------------------------
# 2. Sucursales
# ----------------------------------------------------------------------------
def page_sucursales():
    header("Análisis de sucursales")
    if need_data():
        return
    t = an.branch_table(cur)
    if len(t) >= 2:
        best, worst = t.iloc[0], t.iloc[-1]
        a, b = st.columns(2)
        a.success(f"**Mejor desempeño combinado: {best['Sucursal']}**  \n"
                  f"Ventas {an.usd(best['ventas'])} · margen {an.pct(best['margen'], 2)} · ticket {an.usd(best['ticket'], 2)} · índice {an.num(best['indice'])}/100")
        b.error(f"**Menor desempeño combinado: {worst['Sucursal']}**  \n"
                f"Ventas {an.usd(worst['ventas'])} · margen {an.pct(worst['margen'], 2)} · ticket {an.usd(worst['ticket'], 2)} · índice {an.num(worst['indice'])}/100")
    st.caption("El ranking no usa solo ventas: el índice combina volumen (utilidad y transacciones, 50 %) y rentabilidad (margen y ticket, 50 %). "
               "Es un orden relativo entre las sucursales filtradas; la tabla muestra las diferencias absolutas.")
    a, b = st.columns(2)
    with a:
        show(ch.branch_sales(t))
    with b:
        show(ch.branch_profit(t))
        st.caption("El eje del margen se acota para hacer visibles diferencias pequeñas; lea siempre los valores rotulados.")
    show(ch.branch_scatter(t))
    st.caption("Arriba a la derecha = más utilidad y mayor margen. Una sucursal puede vender más y quedar a la izquierda si concede más descuentos o vende una mezcla de menor margen.")
    st.subheader("Tabla comparativa")
    tab = t[["ranking", "Sucursal", "Ciudad", "ventas", "utilidad", "margen", "transacciones", "ticket", "descuento_pct", "indice"]]
    st.dataframe(tab, hide_index=True, width="stretch", column_config={
        "ranking": "Pos.", "ventas": st.column_config.NumberColumn("Ventas (USD)", format="dollar"),
        "utilidad": st.column_config.NumberColumn("Utilidad (USD)", format="dollar"),
        "margen": st.column_config.NumberColumn("Margen %", format="%.2f%%"),
        "transacciones": st.column_config.NumberColumn("Transacciones", format="localized"),
        "ticket": st.column_config.NumberColumn("Ticket (USD)", format="dollar"),
        "descuento_pct": st.column_config.NumberColumn("Descuento %", format="%.2f%%"),
        "indice": st.column_config.ProgressColumn("Índice (0-100)", min_value=0, max_value=100, format="%.0f")})


# ----------------------------------------------------------------------------
# 3. Productos
# ----------------------------------------------------------------------------
def page_productos():
    header("Análisis de productos")
    if need_data():
        return
    p = an.product_table(cur)
    a, b = st.columns([3, 1])
    n = a.slider("Cantidad de productos a mostrar en los rankings", 5, min(30, max(5, len(p))), min(10, len(p)))
    a, b = st.columns(2)
    with a:
        show(ch.top_products(p, "unidades", n), "tp_u")
        st.caption("Rotación: unidades vendidas.")
    with b:
        show(ch.top_products(p, "utilidad", n), "tp_ut")
        st.caption("Contribución: utilidad bruta en USD. Un producto muy vendido no siempre es el que más utilidad aporta.")
    show(ch.revenue_vs_cost(p, n))
    st.caption("La distancia entre la barra de ingresos y la de coste es la utilidad bruta del producto.")
    st.subheader("Clasificación por rotación y rentabilidad")
    if len(p) < 4:
        st.info("Se necesitan al menos 4 productos para clasificar. Amplíe los filtros.")
    else:
        st.caption(f"Rotación alta = unidades ≥ mediana ({an.num(p.attrs['mediana_unidades'])} uds). "
                   f"Rentabilidad alta = margen ≥ margen global ponderado ({an.pct(p.attrs['margen_global'], 2)}).")
        show(ch.product_matrix(p))
        cols = st.columns(2)
        for i, (g, accion) in enumerate(an.PRODUCT_GROUPS.items()):
            sub = p[p["grupo"] == g]
            with cols[i % 2].container(border=True):
                st.markdown(f"**{g}** · {len(sub)} productos")
                st.caption(f"Acción sugerida: {accion}")
                if len(sub):
                    st.write(", ".join(sub.sort_values("utilidad", ascending=False)["ProductoLabel"].head(8))
                             + ("…" if len(sub) > 8 else ""))
    st.subheader("Detalle por producto")
    st.dataframe(p[["ProductoLabel", "Categoria", "ProductoActivo", "unidades", "ventas", "costo", "utilidad", "margen", "participacion", "grupo"]],
                 hide_index=True, width="stretch", column_config={
        "ProductoLabel": "Producto", "ProductoActivo": "Activo en catálogo",
        "unidades": st.column_config.NumberColumn("Unidades", format="localized"),
        "ventas": st.column_config.NumberColumn("Ingresos (USD)", format="dollar"),
        "costo": st.column_config.NumberColumn("Coste (USD)", format="dollar"),
        "utilidad": st.column_config.NumberColumn("Utilidad (USD)", format="dollar"),
        "margen": st.column_config.NumberColumn("Margen %", format="%.2f%%"),
        "participacion": st.column_config.NumberColumn("% de ventas", format="%.2f%%"), "grupo": "Grupo"})


# ----------------------------------------------------------------------------
# 4. Clientes
# ----------------------------------------------------------------------------
def page_clientes():
    header("Análisis de clientes y segmentos")
    if need_data():
        return
    s = an.segment_table(cur, prev, base_clientes, months)
    st.caption("Describe el desempeño ACTUAL de cada segmento. Los datos no incluyen información de mercado ni de propensión de compra, "
               "por lo que no se estima potencial futuro; el crecimiento observado frente al período anterior es solo una señal.")
    a, b = st.columns(2)
    with a:
        show(ch.segment_bars(s))
    with b:
        show(ch.segment_share_donut(s))
    cols = ["Segmento", "ventas", "utilidad", "margen", "clientes", "transacciones", "ticket", "ventas_por_cliente",
            "frecuencia_mensual", "crec_ventas", "pct_base"]
    cfg = {"ventas": st.column_config.NumberColumn("Ventas (USD)", format="dollar"),
           "utilidad": st.column_config.NumberColumn("Utilidad (USD)", format="dollar"),
           "margen": st.column_config.NumberColumn("Margen %", format="%.2f%%"),
           "clientes": st.column_config.NumberColumn("Clientes compradores", format="localized"),
           "transacciones": st.column_config.NumberColumn("Transacciones", format="localized"),
           "ticket": st.column_config.NumberColumn("Ticket (USD)", format="dollar"),
           "ventas_por_cliente": st.column_config.NumberColumn("Venta por cliente (USD)", format="dollar"),
           "frecuencia_mensual": st.column_config.NumberColumn("Compras/cliente/mes", format="%.2f"),
           "crec_ventas": st.column_config.NumberColumn("Crec. ventas vs anterior", format="%.1f%%"),
           "pct_base": st.column_config.NumberColumn("% de la base de clientes", format="%.1f%%")}
    if "nps_prom" in s.columns:
        cols += ["nps_prom", "pct_activos"]
        cfg["nps_prom"] = st.column_config.NumberColumn("NPS prom. (CRM)", format="%.2f")
        cfg["pct_activos"] = st.column_config.NumberColumn("% activos (CRM)", format="%.1f%%")
    st.dataframe(s[cols], hide_index=True, width="stretch", column_config=cfg)
    st.caption("Compras, gasto y frecuencia se recalculan desde Ventas. NPS y % activos provienen de la base de Clientes (foto posterior a Ventas).")
    if "MotivoPerdida" in base_clientes.columns:
        st.subheader("Motivos de pérdida (CRM)")
        base = base_clientes[base_clientes["Segmento"].isin(F.segmentos)] if F.segmentos else base_clientes
        m = base.dropna(subset=["MotivoPerdida"])
        if len(m):
            c = m.groupby(["MotivoPerdida", "Segmento"]).size().reset_index(name="clientes")
            import plotly.express as px
            fig = px.bar(c, x="MotivoPerdida", y="clientes", color="Segmento", color_discrete_sequence=ch.SEQ)
            fig.update_yaxes(title="Clientes marcados como inactivos")
            fig.update_xaxes(title="")
            show(ch._style(fig, "Clientes inactivos por motivo de pérdida y segmento", 360))
            st.caption("Fuente: campo MotivoPerdida de Clientes. Úselo para priorizar acciones de fidelización; "
                       "no está ligado a transacciones individuales.")


# ----------------------------------------------------------------------------
# 5. Geografía
# ----------------------------------------------------------------------------
def page_geografia():
    header("Análisis geográfico")
    if need_data():
        return
    c = an.city_table(cur)
    a, b = st.columns(2)
    with a:
        show(ch.city_sales(c))
    with b:
        show(ch.city_category_heat(cur))
        st.caption("Cada fila suma 100 %: muestra qué parte de las ventas de la ciudad corresponde a cada categoría.")
    st.dataframe(c[["Ciudad", "sucursales", "ventas", "participacion", "utilidad", "margen", "transacciones", "ticket", "ventas_por_sucursal", "descuento_pct"]],
                 hide_index=True, width="stretch", column_config={
        "sucursales": "Sucursales", "ventas": st.column_config.NumberColumn("Ventas (USD)", format="dollar"),
        "participacion": st.column_config.NumberColumn("% de ventas", format="%.1f%%"),
        "utilidad": st.column_config.NumberColumn("Utilidad (USD)", format="dollar"),
        "margen": st.column_config.NumberColumn("Margen %", format="%.2f%%"),
        "transacciones": st.column_config.NumberColumn("Transacciones", format="localized"),
        "ticket": st.column_config.NumberColumn("Ticket (USD)", format="dollar"),
        "ventas_por_sucursal": st.column_config.NumberColumn("Ventas por sucursal", format="dollar"),
        "descuento_pct": st.column_config.NumberColumn("Descuento %", format="%.2f%%")})
    st.caption("La ciudad es la de la venta (donde ocurre la transacción). La ciudad de residencia del cliente no coincide con ella en la mayoría de los casos y no se usa aquí.")
    show(ch.branch_sales(an.branch_table(cur)))


# ----------------------------------------------------------------------------
# 6. Asistente de IA
# ----------------------------------------------------------------------------
def page_ia():
    header("Asistente de IA")
    tab_auto, tab_chat = st.tabs(["Diagnóstico automático", "Asistente conversacional"])
    with tab_auto:
        st.caption("Generado por reglas determinísticas sobre los datos filtrados (no usa IA generativa, funciona sin clave de API). "
                   "Cada hallazgo separa HECHOS de HIPÓTESIS.")
        if need_data():
            return
        pri = {"Alta": "🔴", "Media": "🟡", "Baja": "🟢"}
        for i, f in enumerate(insights.auto_findings(cur, prev, base_clientes, months), 1):
            with st.container(border=True):
                st.markdown(f"**{i}. {f['hallazgo']}**  ·  {pri[f['prioridad']]} Prioridad {f['prioridad']}")
                st.markdown(f"**Evidencia:** {f['evidencia']}")
                st.markdown(f"**Interpretación:** {f['interpretacion']}")
                st.markdown(f"**Recomendación:** {f['recomendacion']}")
                st.markdown(f"**Impacto esperado:** {f['impacto']}")
                st.markdown(f"**Indicador de seguimiento:** {f['kpi']}")
    with tab_chat:
        key, model = ai.get_credentials(st.secrets)
        if not key:
            st.info("El asistente conversacional necesita una clave de API configurada en el servidor "
                    "(`ANTHROPIC_API_KEY` en *Secrets* o como variable de entorno). Mientras tanto, use el diagnóstico automático.")
        st.caption("El asistente recibe únicamente los resultados agregados de los filtros activos (sin nombres de clientes) "
                   "y responde solo con esos datos. Distingue hechos, interpretaciones e hipótesis.")
        st.session_state.setdefault("chat", [])
        pending = None
        with st.expander("Preguntas sugeridas", expanded=not st.session_state["chat"]):
            cols = st.columns(2)
            for i, q in enumerate(ai.QUICK_QUESTIONS):
                if cols[i % 2].button(q, key=f"qq{i}", width="stretch", disabled=not key):
                    pending = q
        for m in st.session_state["chat"]:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
        typed = st.chat_input("Pregunte sobre el negocio…", disabled=not key)
        question = pending or typed
        if question and key:
            with st.chat_message("user"):
                st.markdown(question)
            ctx = ai.build_context(cur, prev, F, base_clientes, months, meta)
            with st.chat_message("assistant"):
                with st.spinner("Analizando los datos…"):
                    res = ai.ask(question, st.session_state["chat"], ctx, key, model)
                if res.error:
                    st.error(res.error)
                else:
                    st.markdown(res.text)
                    st.caption(f"Modelo: {model} · tokens entrada/salida: {res.input_tokens}/{res.output_tokens}")
                    st.session_state["chat"] += [{"role": "user", "content": question},
                                                 {"role": "assistant", "content": res.text}]
        if st.session_state["chat"] and st.button("Borrar conversación"):
            st.session_state["chat"] = []
            st.rerun()


# ----------------------------------------------------------------------------
# 7. Datos y actualización
# ----------------------------------------------------------------------------
def pill(text, kind):
    return f'<span class="pill {kind}">{text}</span>'


def admin_ok() -> bool:
    """Protege la carga/restauración de datos si hay ADMIN_PASSWORD (secrets o entorno). Sin ella, el acceso es libre."""
    pwd = None
    try:
        pwd = st.secrets.get("ADMIN_PASSWORD")
    except Exception:
        pass
    pwd = pwd or os.environ.get("ADMIN_PASSWORD")
    if not pwd or st.session_state.get("_admin"):
        return True
    st.info("La carga y restauración de datos está protegida. Ingrese la contraseña de administración.")
    entered = st.text_input("Contraseña de administración", type="password", key="admin_pwd")
    if entered:
        if hmac.compare_digest(entered.encode(), str(pwd).encode()):
            st.session_state["_admin"] = True
            st.rerun()
        st.error("Contraseña incorrecta.")
    return False


def page_datos():
    st.title("Datos y actualización")
    st.markdown('<p class="note">Cargue nuevas bases sin tocar el código. Toda carga se valida primero; si hay errores, '
                'los datos actuales se conservan intactos.</p>', unsafe_allow_html=True)
    kind = "err" if meta["n_errors"] else ("warn" if meta["n_warnings"] else "ok")
    c = st.columns(4)
    c[0].metric("Última actualización", meta["updated_at"], border=True)
    c[1].metric("Registros cargados", f"V {an.num(meta['rows']['ventas'])} · C {an.num(meta['rows']['clientes'])} · P {an.num(meta['rows']['productos'])}",
                help="V = Ventas, C = Clientes, P = Productos", border=True)
    c[2].metric("Período disponible", f"{meta['period_start']} → {meta['period_end']}", border=True)
    with c[3].container(border=True):
        st.caption("Estado de validación")
        st.markdown(pill(meta["status"], kind), unsafe_allow_html=True)
        st.caption(f"{meta['n_errors']} errores · {meta['n_warnings']} advertencias")

    if meta["warnings"]:
        with st.expander(f"Advertencias de calidad de datos ({len(meta['warnings'])})"):
            for w in meta["warnings"]:
                st.markdown(f"- **{DATASET_LABELS.get(w['dataset'], w['dataset'].title())}:** {w['message']}")

    is_admin = admin_ok()
    if is_admin:
        st.subheader("Cargar nuevos archivos")
        st.caption("Suba solo las bases que cambian (Excel o CSV). Las demás se conservan. "
                   "Si Ventas incluye clientes o productos nuevos, suba también las bases de Clientes/Productos actualizadas.")
        u = st.columns(3)
        files = {n: u[i].file_uploader(DATASET_LABELS[n], type=["xlsx", "xls", "csv"], key=f"up_{n}")
                 for i, n in enumerate(("ventas", "clientes", "productos"))}
        mode_lbl = st.radio("Modo de carga de Ventas", ["Reemplazar toda la base de ventas", "Agregar solo registros nuevos (por VentaID)"],
                            horizontal=True, disabled=files["ventas"] is None)
        mode = "replace" if mode_lbl.startswith("Reemplazar") else "append"

        if st.button("Validar archivos", type="primary", disabled=not any(files.values())):
            raw, rep_read = {}, ValidationReport()
            for n, f in files.items():
                if f is None:
                    continue
                df, r = read_table(f, f.name, n)
                rep_read.extend(r)
                if df is not None:
                    raw[n] = df
            if rep_read.errors:
                st.session_state["pending"] = {"clean": None, "report": rep_read}
            else:
                with st.spinner("Validando estructura, tipos y relaciones…"):
                    clean, rep = validate_update(raw, data, mode)
                rep_read.extend(rep)
                st.session_state["pending"] = {"clean": clean, "report": rep_read, "mode": mode,
                                               "files": {**meta["files"], **{n: f.name for n, f in files.items() if f}}}
        pend = st.session_state.get("pending")
        if pend:
            rep = pend["report"]
            k = "err" if rep.errors else ("warn" if rep.warnings else "ok")
            st.markdown(f"**Resultado de la validación:** {pill(rep.status, k)}", unsafe_allow_html=True)
            for i in rep.errors:
                st.error(f"**{DATASET_LABELS.get(i.dataset, i.dataset.title())}:** {i.message}" + (f"  \n*Cómo corregirlo:* {i.fix}" if i.fix else ""))
            for i in rep.warnings:
                st.warning(f"**{DATASET_LABELS.get(i.dataset, i.dataset.title())}:** {i.message}")
            for i in rep.infos:
                st.caption(f"ℹ️ {i.message}")
            if rep.ok and pend["clean"] is not None:
                new_f = build_fact(pend["clean"])
                ko, kn = kpis(fact), kpis(new_f)
                imp = pd.DataFrame({"Indicador": ["Registros de ventas", "Ventas netas (USD)", "Utilidad bruta (USD)", "Margen bruto %", "Clientes únicos", "Período"],
                                    "Antes": [an.num(len(fact)), an.usd(ko["ventas"], 2), an.usd(ko["utilidad"], 2), an.pct(ko["margen"], 2), an.num(ko["clientes"]),
                                              f"{fact['Fecha'].min():%Y-%m-%d} → {fact['Fecha'].max():%Y-%m-%d}"],
                                    "Después": [an.num(len(new_f)), an.usd(kn["ventas"], 2), an.usd(kn["utilidad"], 2), an.pct(kn["margen"], 2), an.num(kn["clientes"]),
                                                f"{new_f['Fecha'].min():%Y-%m-%d} → {new_f['Fecha'].max():%Y-%m-%d}"]})
                st.markdown("**Impacto de la actualización**")
                st.dataframe(imp, hide_index=True, width="stretch")
                if st.button("Aplicar actualización y recalcular", type="primary"):
                    try:
                        storage.apply_update(pend["clean"], rep, pend["files"], action=f"Carga de usuario ({', '.join(f.name for f in files.values() if f) or 'archivos'})")
                        st.cache_data.clear()
                        st.session_state.pop("pending", None)
                        st.success("Actualización aplicada. Todos los indicadores y gráficos se recalcularon.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"No se pudo aplicar la actualización; los datos anteriores se conservaron. Detalle: {exc}")
            else:
                st.info("La carga fue rechazada: los datos actuales no se modificaron. Corrija los errores indicados y vuelva a validar.")

    st.subheader("Plantillas de archivos")
    t = st.columns(3)
    for i, n in enumerate(("ventas", "clientes", "productos")):
        sch = SCHEMAS[n]
        cols = sch["required"] + sch["optional"]
        t[i].download_button(f"Plantilla {DATASET_LABELS[n]} (CSV)", ",".join(cols) + "\n", file_name=f"plantilla_{n}.csv",
                             mime="text/csv", width="stretch")
        t[i].caption("Obligatorias: " + ", ".join(sch["required"]))

    with st.expander("Controles de consistencia del modelo"):
        st.dataframe(consistency_report(fact, data), hide_index=True, width="stretch")
    with st.expander("Historial y copias de seguridad"):
        st.dataframe(pd.DataFrame(meta["history"]), hide_index=True, width="stretch")
        bks = storage.list_backups()
        if bks and is_admin:
            lab = {b["name"]: f"{b['updated_at']} · {an.num(b['rows']['ventas'])} ventas · {b['period_start']}→{b['period_end']}" for b in bks}
            sel = st.selectbox("Restaurar una versión anterior", list(lab), format_func=lab.get)
            if st.button("Restaurar versión seleccionada"):
                storage.restore_backup(sel)
                st.cache_data.clear()
                st.rerun()
        else:
            st.caption("Aún no hay copias de seguridad (se crean al actualizar).")
    with st.expander("Metodología y definiciones"):
        st.markdown("""
- **Fuente de ingresos y costes:** base de Ventas. `VentaNeta` ya está neta de descuentos; no se resta de nuevo.
- **Utilidad bruta** = Ventas netas − Coste de ventas. **Margen bruto %** = Utilidad / Ventas × 100 (ponderado, nunca promedio de porcentajes).
- **Transacción** = un `VentaID` (línea de producto). **Ticket promedio** = Ventas / Transacciones.
- **Frecuencia** = transacciones / clientes únicos / meses con datos.
- **Variación** = frente al período inmediatamente anterior de igual duración (meses completos si el rango lo es). Margen en puntos porcentuales.
- **Segmento, NPS, activo:** de la base de Clientes. Compras y gasto se recalculan desde Ventas.
- **Persistencia:** los datos cargados se guardan en el servidor de la aplicación; si el servidor se reinicia, vuelve a los datos del repositorio (ver README).
""")


{"Dashboard ejecutivo": page_dashboard, "Sucursales": page_sucursales, "Productos": page_productos,
 "Clientes": page_clientes, "Geografía": page_geografia, "Asistente de IA": page_ia,
 "Datos y actualización": page_datos}[page]()
