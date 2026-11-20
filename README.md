# San Francisco Crust Pizza · Sistema de Inteligencia de Negocios

Aplicación web (Streamlit) de apoyo a la toma de decisiones para la Dirección General: dashboard ejecutivo con KPI y
variaciones, análisis de sucursales, productos, clientes y geografía, asistente de IA y un módulo para **actualizar las
bases de datos sin modificar el código**.

## Tecnología (y por qué)
| Capa | Elección | Justificación |
|---|---|---|
| Interfaz y servidor | **Streamlit** | Un solo lenguaje (Python), despliegue gratuito en Streamlit Community Cloud, carga de archivos nativa, adaptable a móvil. |
| Datos | **pandas + pyarrow (Parquet)** | Modelo relacional en memoria; el conjunto activo se guarda en Parquet (carga en milisegundos). |
| Gráficos | **Plotly** | Interactivos, con unidades, etiquetas y formato en español. |
| IA | **Anthropic Claude (API)** | Se llama desde el servidor; la clave nunca llega al navegador. |
| Pruebas | **pytest + Streamlit AppTest** | 82 pruebas automáticas (ver `docs/EVIDENCIAS_PRUEBAS.md`). |

## Estructura
```
app.py                  Interfaz (7 secciones) y filtros globales
src/config.py           Esquemas de datos, alias de columnas, umbrales, paleta
src/validation.py       Lectura Excel/CSV, reconocimiento de columnas, validación y reglas de calidad
src/storage.py          Persistencia atómica, copias de seguridad, restauración
src/model.py            Tabla de hechos, filtros, período anterior, KPI
src/analysis.py         Ranking de sucursales, clasificación de productos, segmentos, ciudades, alertas
src/charts.py           Gráficos Plotly
src/insights.py         Diagnóstico automático por reglas (sin IA generativa)
src/ai_assistant.py     Contexto analítico + llamada a la API
tests/                  Pruebas automáticas
data/seed/              Bases originales (carga inicial)
docs/                   Instrucciones de actualización y evidencias de pruebas
```

## Ejecución local
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```
Python 3.11 o superior (probado con 3.12). La primera ejecución convierte los Excel de `data/seed/` a Parquet (~8 s).

## Despliegue público (Streamlit Community Cloud)
Debe hacerlo usted: requiere su cuenta de GitHub.
1. Cree un repositorio en GitHub y suba **todo el contenido** de esta carpeta (incluido `data/seed/`).
2. Entre en <https://share.streamlit.io>, **Create app** → elija el repositorio, rama `main`, archivo `app.py`.
3. En **Advanced settings** seleccione **Python 3.12** y pegue los *Secrets* (ver `.streamlit/secrets.toml.example`).
4. **Deploy.** Al terminar obtendrá un enlace `https://<nombre>.streamlit.app`.
5. En *Settings → Sharing* confirme que la app sea **pública** para que se abra sin iniciar sesión.

### Asistente de IA: proveedor, modelo y clave
- Proveedor: **Anthropic** (API Messages). Modelo por defecto: `claude-sonnet-5-5`, configurable con `ANTHROPIC_MODEL`.
- La clave se obtiene en <https://console.anthropic.com> y se guarda **solo** como secreto del servidor (`ANTHROPIC_API_KEY`).
  No está en el código ni se envía al navegador.
- El modelo recibe solo agregados de los filtros activos (sin nombres de clientes) y reglas que le prohíben inventar cifras
  o afirmar causalidad. **Sin clave** el asistente conversacional se desactiva, pero el *Diagnóstico automático* sigue funcionando.

### Seguridad de la carga de datos
Defina `ADMIN_PASSWORD` en los secretos: sin ella, cualquier visitante del enlace público podría reemplazar las bases.

## Actualizar las bases de datos
Ver `docs/INSTRUCCIONES_ACTUALIZACION.md`.

**Persistencia:** en Streamlit Community Cloud el disco es efímero. Los datos cargados desde la interfaz sobreviven mientras la
app siga activa, pero **se pierden si la app se reinicia o se vuelve a desplegar**; entonces vuelve a los datos de `data/seed/`.
Para que una actualización sea permanente, reemplace los archivos de `data/seed/` en el repositorio (mismo nombre) y haga *commit*.
El historial y las copias de seguridad también existen solo durante la vida de la instancia.

## Metodología (fórmulas)
- Ingresos y costes: base de **Ventas** (`VentaNeta`, `CostoTotal`). `VentaNeta` ya está neta de descuentos; no se resta de nuevo.
- Utilidad bruta = Ventas netas − Coste de ventas. Margen bruto % = Utilidad / Ventas × 100 (**ponderado**, nunca promedio de porcentajes).
- Transacción = un `VentaID` (línea de producto). Ticket promedio = Ventas / Transacciones. Clientes únicos = conteo distinto de `ClienteID`.
- Descuento % = Σ(Cantidad × Precio − VentaNeta) / Σ(Cantidad × Precio).
- Frecuencia = transacciones / clientes únicos / meses con datos.
- Variación = frente al período inmediatamente anterior de igual duración (meses calendario completos si el rango lo es); margen en puntos porcentuales.
- Índice de sucursales = 30 % utilidad + 30 % margen + 20 % ticket + 20 % transacciones, cada uno como posición relativa 0–100 (orden relativo, no mide magnitud).
- Clasificación de productos: rotación alta = unidades ≥ mediana; rentabilidad alta = margen ≥ margen global ponderado.

## Limitaciones conocidas de los datos de ejemplo
Se detectan y se muestran automáticamente como advertencias: precios/costes de Ventas distintos del catálogo (100 % de productos), campos acumulados de
Clientes no reconciliables con Ventas, ciudad del cliente sin relación con la ciudad de la venta, productos inactivos con ventas, ventas anteriores al
registro del cliente y fechas solo entre los días 1 y 28 de cada mes. No hay costes fijos: solo se calcula **margen bruto**.
