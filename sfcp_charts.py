"""Gráficos Plotly. Cada función recibe una tabla agregada y devuelve una figura."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from sfcp_config import COLORS, SEQ

FONT = "IBM Plex Sans, Segoe UI, Arial, sans-serif"
GROUP_COLORS = {
    "Estrella": COLORS["basil"], "Alta rotación, baja rentabilidad": COLORS["crust"],
    "Baja rotación, alta rentabilidad": COLORS["slate"], "Bajo desempeño": COLORS["tomato"],
}


def _style(fig: go.Figure, title: str, height: int = 380, legend: bool = True) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=COLORS["ink"]), x=0, xanchor="left"),
        height=height, margin=dict(l=10, r=10, t=55, b=10), font=dict(family=FONT, size=12, color=COLORS["ink"]),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", separators=",.",
        showlegend=legend, legend=dict(orientation="h", y=-0.18, x=0, title_text=""),
        hoverlabel=dict(font_family=FONT),
    )
    fig.update_xaxes(showgrid=False, linecolor=COLORS["line"], title_font_size=12)
    fig.update_yaxes(gridcolor=COLORS["line"], zeroline=False, title_font_size=12)
    return fig


def city_colors(cities) -> dict:
    return {c: SEQ[i % len(SEQ)] for i, c in enumerate(sorted(set(cities)))}


def empty_fig(msg="Sin datos para los filtros seleccionados") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font=dict(size=14, color=COLORS["muted"]))
    fig.update_xaxes(visible=False); fig.update_yaxes(visible=False)
    return _style(fig, "", 300, False)


# ---- Tendencias ----------------------------------------------------------
def sales_trend(ts: pd.DataFrame, freq_label: str) -> go.Figure:
    if ts.empty:
        return empty_fig()
    fig = go.Figure(go.Scatter(x=ts["Fecha"], y=ts["ventas"], mode="lines+markers", name="Ventas netas",
                               line=dict(color=COLORS["tomato"], width=2.5), marker=dict(size=6),
                               hovertemplate="%{x|%b %Y}<br>Ventas: $%{y:,.0f}<extra></extra>"))
    fig.update_yaxes(title="Ventas netas (USD)", tickprefix="$", tickformat=",.0f", rangemode="tozero")
    return _style(fig, f"Evolución de ventas netas ({freq_label.lower()})", legend=False)


def profit_trend(ts: pd.DataFrame, freq_label: str) -> go.Figure:
    if ts.empty:
        return empty_fig()
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=ts["Fecha"], y=ts["utilidad"], name="Utilidad bruta (USD)", marker_color=COLORS["slate"],
                hovertemplate="%{x|%b %Y}<br>Utilidad: $%{y:,.0f}<extra></extra>")
    fig.add_scatter(x=ts["Fecha"], y=ts["margen"], name="Margen bruto (%)", mode="lines+markers",
                    line=dict(color=COLORS["crust"], width=2.5),
                    hovertemplate="%{x|%b %Y}<br>Margen: %{y:.2f}%<extra></extra>", secondary_y=True)
    fig.update_yaxes(title="Utilidad bruta (USD)", tickprefix="$", tickformat=",.0f", rangemode="tozero", secondary_y=False)
    lo, hi = ts["margen"].min(), ts["margen"].max()
    fig.update_yaxes(title="Margen bruto (%)", ticksuffix="%", range=[max(0, lo - 3), min(100, hi + 3)],
                     showgrid=False, secondary_y=True)
    return _style(fig, f"Utilidad bruta y margen ({freq_label.lower()})")


# ---- Geografía / sucursales ---------------------------------------------
def city_sales(t: pd.DataFrame) -> go.Figure:
    if t.empty:
        return empty_fig()
    t = t.sort_values("ventas", ascending=False)
    fig = px.bar(t, x="Ciudad", y="ventas", color="Ciudad", color_discrete_map=city_colors(t["Ciudad"]),
                 text=t["ventas"].map(lambda v: f"${v:,.0f}"))
    fig.update_traces(textposition="outside", hovertemplate="%{x}<br>Ventas: $%{y:,.0f}<extra></extra>")
    fig.update_yaxes(title="Ventas netas (USD)", tickprefix="$", tickformat=",.0f", rangemode="tozero")
    return _style(fig, "Ventas netas por ciudad", legend=False)


def branch_sales(t: pd.DataFrame) -> go.Figure:
    if t.empty:
        return empty_fig()
    t = t.sort_values("ventas")
    fig = px.bar(t, y="Sucursal", x="ventas", color="Ciudad", orientation="h",
                 color_discrete_map=city_colors(t["Ciudad"]), text=t["ventas"].map(lambda v: f"${v:,.0f}"))
    fig.update_traces(textposition="outside", hovertemplate="%{y}<br>Ventas: $%{x:,.0f}<extra></extra>")
    fig.update_xaxes(title="Ventas netas (USD)", tickprefix="$", tickformat=",.0f", rangemode="tozero")
    return _style(fig, "Ventas netas por sucursal", 400)


def branch_profit(t: pd.DataFrame) -> go.Figure:
    """Utilidad (barras) y margen (puntos) por sucursal, ordenadas por margen."""
    if t.empty:
        return empty_fig()
    t = t.sort_values("margen")
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.04,
                        subplot_titles=("Utilidad bruta (USD)", "Margen bruto (%)"))
    fig.add_bar(y=t["Sucursal"], x=t["utilidad"], orientation="h", marker_color=COLORS["slate"],
                text=t["utilidad"].map(lambda v: f"${v:,.0f}"), textposition="outside", showlegend=False,
                hovertemplate="%{y}<br>Utilidad: $%{x:,.0f}<extra></extra>", row=1, col=1)
    fig.add_scatter(y=t["Sucursal"], x=t["margen"], mode="markers+text", showlegend=False,
                    marker=dict(size=13, color=COLORS["crust"]), text=t["margen"].map(lambda v: f"{v:.2f}%"),
                    textposition="middle right", hovertemplate="%{y}<br>Margen: %{x:.2f}%<extra></extra>", row=1, col=2)
    lo, hi = t["margen"].min(), t["margen"].max()
    fig.update_xaxes(range=[lo - 1.5, hi + 2.0], ticksuffix="%", row=1, col=2)
    fig.update_xaxes(tickprefix="$", tickformat=",.0f", rangemode="tozero", row=1, col=1)
    return _style(fig, "Rentabilidad por sucursal", 400, False)


def branch_scatter(t: pd.DataFrame) -> go.Figure:
    if t.empty:
        return empty_fig()
    fig = px.scatter(t, x="margen", y="utilidad", size="transacciones", color="Ciudad", text="Sucursal",
                     color_discrete_map=city_colors(t["Ciudad"]), size_max=38)
    fig.update_traces(textposition="top center",
                      hovertemplate="%{text}<br>Margen: %{x:.2f}%<br>Utilidad: $%{y:,.0f}<extra></extra>")
    fig.update_xaxes(title="Margen bruto (%)", ticksuffix="%")
    fig.update_yaxes(title="Utilidad bruta (USD)", tickprefix="$", tickformat=",.0f")
    return _style(fig, "Volumen vs rentabilidad (tamaño = transacciones)", 420)


# ---- Segmentos y categorías ---------------------------------------------
def segment_bars(t: pd.DataFrame) -> go.Figure:
    if t.empty:
        return empty_fig()
    fig = go.Figure()
    fig.add_bar(x=t["Segmento"], y=t["ventas"], name="Ventas netas", marker_color=COLORS["tomato"])
    fig.add_bar(x=t["Segmento"], y=t["utilidad"], name="Utilidad bruta", marker_color=COLORS["slate"])
    fig.update_layout(barmode="group")
    fig.update_yaxes(title="USD", tickprefix="$", tickformat=",.0f", rangemode="tozero")
    return _style(fig, "Ventas y utilidad por segmento de cliente")


def category_donut(t: pd.DataFrame) -> go.Figure:
    if t.empty:
        return empty_fig()
    fig = go.Figure(go.Pie(labels=t["Categoria"], values=t["ventas"], hole=0.55, sort=True,
                           marker=dict(colors=SEQ, line=dict(color="white", width=2)),
                           textinfo="label+percent", hovertemplate="%{label}<br>$%{value:,.0f} (%{percent})<extra></extra>"))
    return _style(fig, "Distribución de ventas por categoría", legend=False)


def category_stacked(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_fig()
    g = df.groupby(["Periodo", "Categoria"], as_index=False)["VentaNeta"].sum()
    fig = px.bar(g, x="Periodo", y="VentaNeta", color="Categoria", color_discrete_sequence=SEQ)
    fig.update_traces(hovertemplate="%{x|%b %Y}<br>%{fullData.name}: $%{y:,.0f}<extra></extra>")
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title="Ventas netas (USD)", tickprefix="$", tickformat=",.0f")
    fig.update_xaxes(title="")
    return _style(fig, "Ventas mensuales por categoría (apiladas)")


def segment_share_donut(t: pd.DataFrame) -> go.Figure:
    if t.empty:
        return empty_fig()
    fig = go.Figure(go.Pie(labels=t["Segmento"], values=t["ventas"], hole=0.55,
                           marker=dict(colors=SEQ, line=dict(color="white", width=2)), textinfo="label+percent"))
    return _style(fig, "Participación de ventas por segmento", legend=False)


# ---- Productos ------------------------------------------------------------
def top_products(t: pd.DataFrame, metric: str, n: int) -> go.Figure:
    if t.empty:
        return empty_fig()
    labels = {"unidades": "Unidades vendidas", "ventas": "Ventas netas (USD)", "utilidad": "Utilidad bruta (USD)"}
    d = t.nlargest(n, metric).sort_values(metric)
    money = metric != "unidades"
    fig = px.bar(d, y="ProductoLabel", x=metric, orientation="h", color="Categoria", color_discrete_sequence=SEQ,
                 text=d[metric].map(lambda v: f"${v:,.0f}" if money else f"{v:,.0f}"))
    fig.update_traces(textposition="outside")
    fig.update_xaxes(title=labels[metric], tickprefix="$" if money else "", tickformat=",.0f", rangemode="tozero")
    fig.update_yaxes(title="")
    return _style(fig, f"Top {len(d)} productos por {labels[metric].split(' (')[0].lower()}", max(360, 24 * len(d) + 120))


def revenue_vs_cost(t: pd.DataFrame, n: int) -> go.Figure:
    if t.empty:
        return empty_fig()
    d = t.nlargest(n, "ventas").sort_values("ventas", ascending=False)
    fig = go.Figure()
    fig.add_bar(x=d["ProductoLabel"], y=d["ventas"], name="Ingresos (ventas netas)", marker_color=COLORS["slate"])
    fig.add_bar(x=d["ProductoLabel"], y=d["costo"], name="Coste de ventas", marker_color=COLORS["tomato"])
    fig.update_layout(barmode="group")
    fig.update_yaxes(title="USD", tickprefix="$", tickformat=",.0f", rangemode="tozero")
    fig.update_xaxes(tickangle=-40)
    return _style(fig, f"Ingresos vs coste — top {len(d)} productos por ventas", 440)


def product_matrix(t: pd.DataFrame) -> go.Figure:
    if t.empty:
        return empty_fig()
    fig = px.scatter(t, x="unidades", y="margen", color="grupo", color_discrete_map=GROUP_COLORS,
                     size="utilidad", size_max=30, hover_name="ProductoLabel",
                     hover_data={"unidades": ":,.0f", "margen": ":.2f", "utilidad": ":$,.0f", "grupo": False})
    fig.add_vline(x=t.attrs.get("mediana_unidades", t["unidades"].median()), line_dash="dot", line_color=COLORS["muted"])
    fig.add_hline(y=t.attrs.get("margen_global", t["margen"].mean()), line_dash="dot", line_color=COLORS["muted"])
    fig.update_xaxes(title="Unidades vendidas (rotación)", tickformat=",.0f")
    fig.update_yaxes(title="Margen bruto (%)", ticksuffix="%")
    return _style(fig, "Matriz de productos: rotación vs rentabilidad (tamaño = utilidad)", 480)


def city_category_heat(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_fig()
    g = df.groupby(["Ciudad", "Categoria"])["VentaNeta"].sum().unstack(fill_value=0)
    share = g.div(g.sum(axis=1), axis=0) * 100
    fig = go.Figure(go.Heatmap(z=share.values, x=share.columns, y=share.index, colorscale="Blues",
                               text=share.round(1).astype(str) + "%", texttemplate="%{text}",
                               hovertemplate="%{y} · %{x}: %{z:.1f}% de las ventas de la ciudad<extra></extra>",
                               colorbar=dict(title="% ventas")))
    return _style(fig, "Mezcla de categorías por ciudad (% de ventas de cada ciudad)", 340, False)
