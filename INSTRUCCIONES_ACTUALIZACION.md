# Cómo actualizar las bases de datos (sin tocar el código)

1. Abra la sección **Datos y actualización** (si la app tiene contraseña de administración, ingrésela).
2. Suba **solo los archivos que cambian** (Excel `.xlsx` o CSV): Ventas, Clientes y/o Productos. Descargue las *plantillas* si necesita ver las columnas.
3. Para Ventas elija el modo:
   - **Reemplazar toda la base**: sustituye las ventas actuales por las del archivo.
   - **Agregar solo registros nuevos**: añade los `VentaID` que no existan; los repetidos se omiten.
4. Pulse **Validar archivos**. Se comprueba formato, columnas, tipos, nulos, duplicados, reglas aritméticas e integridad entre bases.
   - **Errores** (rojo): la carga se rechaza y los datos actuales no se modifican. Cada error indica cómo corregirlo.
   - **Advertencias** (amarillo): se informan pero permiten continuar.
5. Revise la tabla **Impacto de la actualización** (registros, ventas, utilidad, margen, período, antes y después).
6. Pulse **Aplicar actualización y recalcular**. Todos los indicadores y gráficos se recalculan; los filtros se restablecen al nuevo período.
7. Si algo no es lo esperado, use **Historial y copias de seguridad → Restaurar**.

## Columnas obligatorias
- **Ventas:** VentaID, Fecha, Ciudad, Sucursal, ClienteID, ProductoID, Cantidad, VentaNeta, CostoTotal.
  Opcionales: UtilidadBruta (se calcula si falta), PrecioUnitario, CostoUnitario, DescuentoPct, Canal, FormaPago, tiempos.
- **Clientes:** ClienteID, Segmento. Opcionales: Ciudad, Edad, Sexo, NPS, ClienteActivo, MotivoPerdida, FechaRegistro, UltimaCompra, …
- **Productos:** ProductoID, Categoria, Producto. Opcionales: Tamaño, Activo, CostoUSD, PrecioVentaUSD, …

Los nombres se reconocen sin distinguir mayúsculas ni acentos y con algunos sinónimos (p. ej. «Ventas» → VentaNeta). Las columnas adicionales se ignoran.

## Reglas importantes
- Toda venta debe tener su cliente y su producto en las bases correspondientes. Si sube ventas con clientes o productos nuevos, suba también esas bases actualizadas.
- `VentaID`, `ClienteID` y `ProductoID` deben ser únicos en su base.
- Cada sucursal debe pertenecer a una sola ciudad.
- Si cambian los nombres de columnas, el mensaje de error indica cuál falta y sugiere la columna parecida.

## Dos formas de actualizar (y cuál elegir)
1. **Desde la aplicación** (sección «Datos y actualización»): inmediato, con validación y vista previa. Dura mientras la app siga encendida; si
   se reinicia o se redespliega, vuelve a los Excel base del repositorio.
2. **Reemplazando los Excel base en GitHub** (permanente): en el repositorio use **Add file → Upload files** y suba los archivos con el **mismo nombre**
   (`San_Francisco_Crust_Pizza_Ventas.xlsx`, etc.). La app detecta sola que cambiaron, los valida y recalcula todos los indicadores y gráficos.
   Si el archivo nuevo tiene errores, **se rechaza y se conservan los datos anteriores**; la sección «Datos y actualización» muestra el motivo.
