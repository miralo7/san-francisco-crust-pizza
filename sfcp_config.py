"""Configuración central: esquemas de datos, alias de columnas, paleta y constantes."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SEED_DIR = ROOT   # versión plana: los Excel están junto a app.py
ACTIVE_DIR = DATA_DIR / "active"
BACKUP_DIR = DATA_DIR / "backups"
MAX_BACKUPS = 5

SEED_FILES = {
    "ventas": SEED_DIR / "San_Francisco_Crust_Pizza_Ventas.xlsx",
    "clientes": SEED_DIR / "San_Francisco_Crust_Pizza_Clientes.xlsx",
    "productos": SEED_DIR / "San_Francisco_Crust_Pizza_Productos.xlsx",
}

# Esquema por base. `required` bloquea la carga si falta; `numeric`/`date` fijan
# la conversión de tipo validada; `aliases` reconoce variantes de nombre.
SCHEMAS: dict[str, dict] = {
    "ventas": {
        "key": "VentaID",
        "required": ["VentaID", "Fecha", "Ciudad", "Sucursal", "ClienteID",
                     "ProductoID", "Cantidad", "VentaNeta", "CostoTotal"],
        "optional": ["UtilidadBruta", "PrecioUnitario", "CostoUnitario", "DescuentoPct",
                     "Canal", "FormaPago", "TiempoEntregaMin", "TiempoPreparacionMin"],
        "numeric": ["Cantidad", "VentaNeta", "CostoTotal", "UtilidadBruta", "PrecioUnitario",
                    "CostoUnitario", "DescuentoPct", "TiempoEntregaMin", "TiempoPreparacionMin"],
        "date": ["Fecha"],
        "aliases": {
            "VentaID": ["idventa", "id_venta", "transaccionid", "idtransaccion"],
            "Fecha": ["fechaventa", "date", "fecha_venta"],
            "Ciudad": ["city"],
            "Sucursal": ["tienda", "branch", "local"],
            "ClienteID": ["idcliente", "cliente_id", "cliente"],
            "ProductoID": ["idproducto", "producto_id", "sku"],
            "Cantidad": ["unidades", "qty", "cant"],
            "VentaNeta": ["ventas", "ingreso", "ingresos", "ventatotal", "ventas_netas", "importe"],
            "CostoTotal": ["costo", "costos", "cogs", "costodeventas"],
            "UtilidadBruta": ["utilidad", "gananciabruta"],
        },
    },
    "clientes": {
        "key": "ClienteID",
        "required": ["ClienteID", "Segmento"],
        "optional": ["Nombre", "Sexo", "Edad", "Ciudad", "FechaRegistro", "UltimaCompra",
                     "TotalCompras", "GastoAcumuladoUSD", "TicketPromedioUSD", "CanalFavorito",
                     "FrecuenciaCompraMensual", "ClienteActivo", "NPS", "MotivoPerdida"],
        "numeric": ["Edad", "TotalCompras", "GastoAcumuladoUSD", "TicketPromedioUSD",
                    "FrecuenciaCompraMensual", "NPS"],
        "date": ["FechaRegistro", "UltimaCompra"],
        "aliases": {
            "ClienteID": ["idcliente", "cliente_id", "id_cliente"],
            "Segmento": ["segmentodecliente", "tipocliente", "segment"],
        },
    },
    "productos": {
        "key": "ProductoID",
        "required": ["ProductoID", "Categoria", "Producto"],
        "optional": ["Tamaño", "CostoUSD", "PrecioVentaUSD", "MargenBrutoUSD",
                     "MargenPorcentaje", "Activo"],
        "numeric": ["CostoUSD", "PrecioVentaUSD", "MargenBrutoUSD", "MargenPorcentaje"],
        "date": [],
        "aliases": {
            "ProductoID": ["idproducto", "producto_id", "id_producto", "sku"],
            "Categoria": ["categoría", "category", "familia"],
            "Producto": ["nombreproducto", "nombre", "product"],
            "Tamaño": ["tamano", "size", "talla"],
        },
    },
}

DATASET_LABELS = {"ventas": "Ventas", "clientes": "Clientes", "productos": "Productos"}

# Umbrales de reglas de negocio (documentados en el README)
TOLERANCE_USD = 0.02          # tolerancia de redondeo en chequeos aritméticos
ALERT_SALES_DROP = -0.10      # alerta si las ventas caen más de 10 % vs período anterior
ALERT_MARGIN_DROP_PP = -0.5   # alerta si el margen cae más de 0,5 pp
ALERT_DISCOUNT_RISE_PP = 1.0  # alerta si el % de descuento sube más de 1 pp

# Paleta: tomate = marca/negativo, albahaca = positivo, corteza = advertencia
COLORS = {
    "ink": "#1E2328", "panel": "#FFFFFF", "bg": "#F4F6F7", "muted": "#5F6B73",
    "tomato": "#B8321F", "basil": "#2F7D4F", "crust": "#C98A1B", "slate": "#3E5C76",
    "line": "#D9DFE3",
}
SEQ = ["#3E5C76", "#B8321F", "#C98A1B", "#2F7D4F", "#7A5C8E", "#5F6B73", "#8FA9BD", "#D98B7B"]
