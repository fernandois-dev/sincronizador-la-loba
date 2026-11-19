import asyncio
import datetime
import flet as ft

from utilities.flet_compat import PaginaFija, cerrar_dialogo, tarea_async
from logger_config import get_logger
from modules.servidor.duplicados import ACTUAL, CAMPOS_COMPARTIDOS, EXISTENTE, FILA, NUEVO, PRESETS, DuplicadosManager, valores_iguales

logger = get_logger(__name__)


def _formato(clave, valor):
    if clave == "producto":
        return str(valor or "")
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        return str(valor)
    texto = f"{numero:,.0f}".replace(",", ".")
    return f"${texto}" if clave == "precio" else texto


def _codigo(tarifa):
    return f" · cód. {tarifa['product_code']}" if tarifa.get("product_code") else ""


def _ubicacion(fila_hoja):
    return f"hoja '{fila_hoja['hoja']}', fila {fila_hoja['fila']}"


def _texto_etiquetado(etiqueta, valor, color=None):
    return ft.Text(spans=[
        ft.TextSpan(f"{etiqueta}: ", ft.TextStyle(weight=ft.FontWeight.BOLD)),
        ft.TextSpan(valor, ft.TextStyle(color=color)),
    ], size=13, selectable=True)


def _aviso(texto):
    return ft.Container(
        content=ft.Row([ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.AMBER, size=18),
                        ft.Text(texto, size=12, expand=True)]),
        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.AMBER),
        border_radius=6,
        padding=6,
    )


def _info_conflicto(conflicto):
    """Bloque que explica qué se intenta sincronizar y dónde existe ya el producto."""
    fila = conflicto.fila
    existente = conflicto.existente

    origen = f"[{fila.ref_interna}] {fila.producto}"
    if conflicto.fila_hoja:
        origen += f"  ·  {_ubicacion(conflicto.fila_hoja)}"
    if fila.tb_proveedor:
        origen += f"  ·  proveedor {str(fila.tb_proveedor).strip()}"

    vendedores = ", ".join(
        f"{t['partner_id'][1]}{_codigo(t)} (compra {_formato('precio', t['price'])})" for t in conflicto.tarifas
    ) or "sin proveedores registrados"

    controles = [
        _texto_etiquetado("Intentas sincronizar", origen),
        _texto_etiquetado("Ya existe en Odoo", f"[{existente.get('default_code') or 's/ref'}] {existente.get('name')}"
                                               f"  ·  código {existente.get('barcode')}", ft.Colors.PRIMARY),
        _texto_etiquetado("Lo vende", vendedores),
    ]
    if conflicto.filas_vinculadas:
        controles.append(_texto_etiquetado("En la planilla", "; ".join(
            f"{_ubicacion(f)} ({DuplicadosManager.nombre_proveedor_hoja(f) or 'proveedor s/n'})"
            for f in conflicto.filas_vinculadas
        )))

    if conflicto.error_planilla:
        controles.append(_aviso(f"No se pudo leer la planilla ({conflicto.error_planilla}). Solo se actualizará Odoo."))
    elif not conflicto.fila_hoja:
        controles.append(_aviso(f"No se ubicó una única fila con REF {fila.ref_interna} y este código en la planilla; "
                                "esa fila no se modificará (sí las vinculadas y Odoo)."))
    if conflicto.otras_filas:
        controles.append(_aviso("El mismo código aparece también, con otra REF, en: " + "; ".join(
            f"{_ubicacion(f)} [{f['ref']}]" for f in conflicto.otras_filas
        ) + ". Esas filas no se modifican."))

    return ft.Container(
        content=ft.Column(controles, spacing=4),
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border_radius=8,
        padding=10,
    )


class DlgResolucionDuplicados(PaginaFija, ft.AlertDialog):
    """
    Recorre uno a uno los productos cuyo código de barras ya existe en Odoo y
    permite elegir, campo a campo, si se conservan los valores actuales o se
    reemplazan por los de la fila nueva. Al terminar llama a fn_continuar.
    """

    def __init__(self, page: ft.Page, conflictos: list, fn_continuar: callable) -> None:
        super().__init__()
        self.modal = True
        self.page = page
        self.conflictos = conflictos
        self.fn_continuar = fn_continuar
        self.indice = 0
        self.resultados = []

        self.btn_omitir = ft.TextButton("Omitir", on_click=lambda e: self.siguiente())
        self.btn_aplicar = ft.FilledButton("Aplicar", icon=ft.Icons.CHECK, on_click=lambda e: self.aplicar())
        self.btn_continuar = ft.FilledButton("Continuar", on_click=lambda e: self.continuar(), visible=False)
        self.actions = [self.btn_omitir, self.btn_aplicar, self.btn_continuar]
        self.actions_alignment = ft.MainAxisAlignment.END

        self.content = ft.Container(width=780, height=560)
        self.mostrar_conflicto()

    @property
    def conflicto(self):
        return self.conflictos[self.indice]

    # ── Vista de un conflicto ──────────────────────────────────────────────

    def mostrar_conflicto(self):
        conflicto = self.conflicto
        self.title = ft.Text(f"Producto ya existe en Odoo ({self.indice + 1} de {len(self.conflictos)})")

        # Por defecto se mantiene lo existente: es la opción que no pisa datos.
        self.elecciones = dict(PRESETS["Mantener existentes"])
        self.grupos = {}
        filas_tabla = []
        for clave, etiqueta, _ in CAMPOS_COMPARTIDOS:
            actual, nuevo = conflicto.valor_actual(clave), conflicto.valor_nuevo(clave)
            distinto = not valores_iguales(actual, nuevo)
            grupo = ft.RadioGroup(
                value=self.elecciones[clave],
                on_change=lambda e, c=clave: self.elegir(c, e.control.value),
                content=ft.Row([ft.Radio(value=ACTUAL, label="Actual"), ft.Radio(value=NUEVO, label="Nuevo")],
                               spacing=0),
            )
            grupo.disabled = not distinto
            self.grupos[clave] = grupo
            fondo = ft.Colors.with_opacity(0.12, ft.Colors.AMBER) if distinto else None
            filas_tabla.append(ft.DataRow(color=fondo, cells=[
                ft.DataCell(ft.Text(etiqueta, weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(_formato(clave, actual), width=230, max_lines=2, tooltip=str(actual))),
                ft.DataCell(ft.Text(_formato(clave, nuevo), width=230, max_lines=2, tooltip=str(nuevo))),
                ft.DataCell(grupo if distinto else ft.Text("igual", italic=True, color=ft.Colors.OUTLINE)),
            ]))

        presets = ft.Row(
            [ft.Text("Opciones rápidas:", size=13)] + [
                ft.OutlinedButton(nombre, on_click=lambda e, n=nombre: self.aplicar_preset(n))
                for nombre in PRESETS
            ],
            wrap=True,
        )

        tabla = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Campo")),
                ft.DataColumn(ft.Text("Actual (Odoo)")),
                ft.DataColumn(ft.Text(f"Nuevo ({conflicto.fila.tb_proveedor or 'fila nueva'})")),
                ft.DataColumn(ft.Text("Usar")),
            ],
            rows=filas_tabla,
            column_spacing=16,
            data_row_max_height=56,
        )

        self.txt_resumen = ft.Column(spacing=2)
        self.actualizar_resumen()

        self.content.content = ft.Column(
            controls=[
                _info_conflicto(conflicto),
                presets,
                tabla,
                ft.Container(self.txt_resumen, padding=ft.Padding.only(left=4)),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
        )

    def elegir(self, clave, valor):
        self.elecciones[clave] = valor
        self.actualizar_resumen()
        self.page.update()

    def aplicar_preset(self, nombre):
        self.elecciones = dict(PRESETS[nombre])
        for clave, grupo in self.grupos.items():
            grupo.value = self.elecciones[clave]
        self.actualizar_resumen()
        self.page.update()

    def actualizar_resumen(self):
        """Describe en lenguaje simple qué va a cambiar con las elecciones actuales."""
        conflicto = self.conflicto
        fila = conflicto.fila
        lineas = []
        cambios_odoo = [etiqueta for clave, etiqueta, _ in CAMPOS_COMPARTIDOS
                        if self.elecciones[clave] == NUEVO
                        and not valores_iguales(conflicto.valor_actual(clave), conflicto.valor_nuevo(clave))]
        lineas.append("• Odoo: " + (f"se actualiza {', '.join(cambios_odoo).lower()}." if cambios_odoo
                                    else "el producto se mantiene sin cambios."))
        if fila.tb_proveedor_id:
            accion = "se completa la línea de" if conflicto.tarifa_proveedor_nuevo() else "se agrega"
            lineas.append(f"• Odoo (pestaña Compra): {accion} {str(fila.tb_proveedor).strip()} como proveedor, "
                          f"con código {fila.ref_interna} y precio compra {_formato('precio', fila.tb_precio_compra)}.")
        if conflicto.fila_hoja:
            lineas.append(f"• Planilla: la fila de {_ubicacion(conflicto.fila_hoja)} mantiene su REF "
                          f"{fila.ref_interna} y toma los valores elegidos.")
        if conflicto.filas_vinculadas and cambios_odoo:
            lineas.append("• Planilla: " + ", ".join(_ubicacion(f) for f in conflicto.filas_vinculadas)
                          + f" se actualiza con los valores nuevos ({', '.join(cambios_odoo).lower()}).")
        self.txt_resumen.controls = [ft.Text("Qué se hará:", weight=ft.FontWeight.BOLD, size=13)] + [
            ft.Text(linea, size=12) for linea in lineas
        ]

    # ── Navegación ─────────────────────────────────────────────────────────

    @tarea_async
    async def aplicar(self):
        self.btn_aplicar.disabled = True
        self.btn_omitir.disabled = True
        self.content.content = ft.Column(
            [ft.ProgressRing(), ft.Text(f"Aplicando cambios a '{self.conflicto.fila.producto}'...")],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        )
        self.page.update()
        try:
            resultado = await asyncio.to_thread(DuplicadosManager.resolver, self.conflicto, self.elecciones)
        except Exception as e:
            logger.error("Error al resolver duplicado '%s'.", self.conflicto.fila.producto, exc_info=True)
            resultado = {"state": "E", "msg": f"Error inesperado: {e}"}
        self.resultados.append((self.conflicto.fila.producto, resultado))
        self.btn_aplicar.disabled = False
        self.btn_omitir.disabled = False
        self.siguiente(registrar_omitido=False)

    def siguiente(self, registrar_omitido=True):
        if registrar_omitido:
            self.resultados.append((self.conflicto.fila.producto, {"state": "W", "msg": "Omitido, no se hicieron cambios."}))
        self.indice += 1
        if self.indice < len(self.conflictos):
            self.mostrar_conflicto()
        else:
            self.mostrar_resultados()
        self.page.update()

    def mostrar_resultados(self):
        self.title = ft.Text("Resultado de duplicados")
        colores = {"S": ft.Colors.with_opacity(0.2, ft.Colors.GREEN),
                   "W": ft.Colors.with_opacity(0.2, ft.Colors.YELLOW),
                   "E": ft.Colors.RED_900}
        fecha = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        self.content.content = ft.Column(
            [ft.Container(
                content=ft.Text(f"{fecha} - {producto}\n{r['msg']}", size=11, selectable=True),
                bgcolor=colores.get(r["state"], colores["E"]),
                border_radius=6,
                padding=6,
            ) for producto, r in self.resultados],
            scroll=ft.ScrollMode.AUTO,
            spacing=6,
        )
        self.btn_omitir.visible = False
        self.btn_aplicar.visible = False
        self.btn_continuar.visible = True

    def continuar(self):
        cerrar_dialogo(self.page, self)
        self.page.update()
        self.fn_continuar()


def _dato(icono, etiqueta, valor):
    return ft.Row([
        ft.Icon(icono, size=16, color=ft.Colors.OUTLINE),
        ft.Text(etiqueta, size=12, color=ft.Colors.OUTLINE, width=100),
        # No seleccionable: vive dentro de tarjetas clicables y la selección de texto se "come" el clic.
        ft.Text(valor, size=13, expand=True),
    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START)


def _insignia(texto, color):
    return ft.Container(
        content=ft.Text(texto, size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
        bgcolor=color,
        border_radius=10,
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
    )


class DlgUnificarDuplicados(PaginaFija, ft.AlertDialog):
    """
    Al sincronizar códigos de barra: el código ya lo tiene OTRO producto de
    Odoo, es decir, el mismo artículo está creado dos veces (uno por proveedor).
    Muestra ambos lado a lado para elegir cuál conservar; el otro se archiva y
    su stock, proveedores y filas de planilla pasan al conservado.
    """

    def __init__(self, page: ft.Page, conflictos: list, cantidad_limpias: int,
                 fn_continuar: callable, fn_cancelar: callable) -> None:
        super().__init__()
        self.modal = True
        self.page = page
        self.conflictos = conflictos
        self.cantidad_limpias = cantidad_limpias
        self.fn_continuar = fn_continuar
        self.fn_cancelar = fn_cancelar
        self.indice = 0
        self.resultados = []

        self.btn_cancelar = ft.TextButton("Cancelar sincronización", icon=ft.Icons.CLOSE,
                                          on_click=lambda e: self.cancelar())
        self.btn_saltar = ft.OutlinedButton("Saltar este código", icon=ft.Icons.SKIP_NEXT,
                                            on_click=lambda e: self.siguiente())
        self.btn_unificar = ft.FilledButton(icon=ft.Icons.MERGE_TYPE, on_click=lambda e: self.unificar())
        # Flet exige texto o ícono aunque el botón esté oculto; el texto final se pone en mostrar_resultados.
        self.btn_continuar = ft.FilledButton("Continuar", on_click=lambda e: self.continuar(), visible=False)
        self.actions = [
            self.btn_cancelar,
            ft.Row([self.btn_saltar, self.btn_unificar, self.btn_continuar], tight=True),
        ]
        self.actions_alignment = ft.MainAxisAlignment.SPACE_BETWEEN

        self.content = ft.Container(width=860, height=600)
        self.nuevo_conflicto()

    @property
    def conflicto(self):
        return self.conflictos[self.indice]

    def ref(self, cual):
        return self.conflicto.lado(cual)["producto"].get("default_code") or "s/ref"

    @staticmethod
    def otro(cual):
        return EXISTENTE if cual == FILA else FILA

    # ── Estado ─────────────────────────────────────────────────────────────

    def nuevo_conflicto(self):
        # Sin selección por defecto: archivar un producto debe ser una decisión explícita.
        self.conservar = None
        self.elecciones = {}
        self.traspasar_stock = True
        self.render()

    def elegir_conservar(self, cual):
        self.conservar = cual
        self.elecciones = {clave: cual for clave, _, _ in CAMPOS_COMPARTIDOS}
        self.render()
        self.page.update()

    def elegir_campo(self, clave, cual):
        self.elecciones[clave] = cual
        self.render()
        self.page.update()

    def cambiar_traspaso(self, valor):
        self.traspasar_stock = valor
        self.render()
        self.page.update()

    # ── Vista ──────────────────────────────────────────────────────────────

    def tarjeta(self, cual):
        lado = self.conflicto.lado(cual)
        producto = lado["producto"]
        seleccionado = self.conservar == cual
        archivado = self.conservar is not None and not seleccionado

        if seleccionado:
            insignia = _insignia("SE CONSERVA", ft.Colors.GREEN_700)
        elif archivado:
            insignia = _insignia("SE ARCHIVA", ft.Colors.RED_700)
        else:
            insignia = ft.Container()

        if seleccionado:
            boton = ft.FilledButton("Se conserva este", icon=ft.Icons.CHECK_CIRCLE, width=10_000,
                                    style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE),
                                    on_click=lambda e: self.elegir_conservar(cual))
        else:
            boton = ft.OutlinedButton("Conservar este", icon=ft.Icons.RADIO_BUTTON_UNCHECKED, width=10_000,
                                      on_click=lambda e: self.elegir_conservar(cual))

        ubicacion = "; ".join(f"'{f['hoja']}' fila {f['fila']}" for f in lado["filas_hoja"]) or "no encontrada"
        proveedores = ", ".join(
            f"{t['partner_id'][1]}{_codigo(t)} (compra {_formato('precio', t['price'])})" for t in lado["tarifas"]
        ) or "sin proveedor"
        ruta = lado["ruta"] or {}

        # GestureDetector en vez de Container.on_click: muestra la manito sobre
        # toda la tarjeta y toma el clic aunque caiga sobre un texto.
        return ft.GestureDetector(
            expand=True,
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e: self.elegir_conservar(cual),
            content=self._contenido_tarjeta(cual, producto, seleccionado, archivado, insignia, boton,
                                            ubicacion, proveedores, ruta),
        )

    def _contenido_tarjeta(self, cual, producto, seleccionado, archivado, insignia, boton, ubicacion, proveedores, ruta):
        return ft.Container(
            border_radius=10,
            padding=14,
            opacity=0.55 if archivado else 1,
            border=ft.Border.all(3 if seleccionado else 1,
                                 ft.Colors.GREEN_700 if seleccionado else ft.Colors.OUTLINE_VARIANT),
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.GREEN) if seleccionado else ft.Colors.with_opacity(0.4, ft.Colors.SURFACE_CONTAINER_HIGHEST),
            content=ft.Column([
                ft.Row([
                    ft.Text("Producto de esta fila" if cual == FILA else "Ya tiene el código",
                            size=12, color=ft.Colors.OUTLINE),
                    insignia,
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Text(f"[{self.ref(cual)}]", size=17, weight=ft.FontWeight.BOLD),
                ft.Text(producto.get("name") or "", size=13, max_lines=2, height=38),
                ft.Divider(height=8),
                _dato(ft.Icons.TABLE_CHART_OUTLINED, "Planilla", ubicacion),
                _dato(ft.Icons.LOCAL_SHIPPING_OUTLINED, "Proveedor", proveedores),
                _dato(ft.Icons.SELL_OUTLINED, "Precio venta", _formato("precio", producto.get("list_price"))),
                _dato(ft.Icons.INVENTORY_2_OUTLINED, "Stock", _formato("stock", producto.get("qty_available"))),
                _dato(ft.Icons.TUNE, "Mín / Máx", f"{_formato('min', ruta.get('product_min_qty'))} / "
                                                  f"{_formato('max', ruta.get('product_max_qty'))}"),
                _dato(ft.Icons.QR_CODE, "Código barras", producto.get("barcode") or "sin código"),
                ft.Container(boton, padding=ft.Padding.only(top=6)),
            ], spacing=6),
        )

    def opcion_valor(self, clave, cual):
        """Caja seleccionable con el valor de un campo; el texto hace wrap en vez de cortarse."""
        seleccionada = self.elecciones[clave] == cual
        color = ft.Colors.GREEN_700 if seleccionada else ft.Colors.OUTLINE_VARIANT
        return ft.GestureDetector(
            expand=True,
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e: self.elegir_campo(clave, cual),
            content=self._contenido_opcion(clave, cual, seleccionada, color),
        )

    def _contenido_opcion(self, clave, cual, seleccionada, color):
        return ft.Container(
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            border=ft.Border.all(2 if seleccionada else 1, color),
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.GREEN) if seleccionada else None,
            content=ft.Row([
                ft.Icon(ft.Icons.RADIO_BUTTON_CHECKED if seleccionada else ft.Icons.RADIO_BUTTON_UNCHECKED,
                        size=18, color=color if seleccionada else ft.Colors.OUTLINE),
                ft.Column([
                    ft.Text(_formato(clave, self.conflicto.valor_lado(cual, clave)), size=13,
                            weight=ft.FontWeight.W_500 if seleccionada else None),
                    ft.Text(f"de [{self.ref(cual)}]", size=11, color=ft.Colors.OUTLINE),
                ], spacing=2, expand=True),
            ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=8),
        )

    def tabla_valores(self):
        c = self.conflicto
        filas = []
        for clave, etiqueta, _ in CAMPOS_COMPARTIDOS:
            if valores_iguales(c.valor_lado(FILA, clave), c.valor_lado(EXISTENTE, clave)):
                continue
            # Mismo orden que las tarjetas de arriba: fila a la izquierda, existente a la derecha.
            filas.append(ft.Row([
                ft.Text(etiqueta, weight=ft.FontWeight.BOLD, size=13, width=100),
                self.opcion_valor(clave, FILA),
                self.opcion_valor(clave, EXISTENTE),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10))
        if not filas:
            return ft.Text("Ambos productos tienen la misma descripción, precio y mín/máx.", size=13, italic=True)
        return ft.Column([
            ft.Text("¿Con qué valores queda el producto conservado?", weight=ft.FontWeight.BOLD, size=14),
            ft.Text("Haz clic en el valor que quieres usar en cada campo.", size=12, color=ft.Colors.OUTLINE),
            ft.Column(filas, spacing=8),
        ], spacing=4)

    def resumen(self):
        c = self.conflicto
        k, d = self.conservar, self.otro(self.conservar)
        ref_k, ref_d = self.ref(k), self.ref(d)
        stock_d = c.lado(d)["producto"].get("qty_available") or 0

        lineas = [f"Odoo: [{ref_d}] se archiva y el código {c.barcode} queda en [{ref_k}]."]
        if stock_d:
            lineas.append(f"Odoo: el stock de [{ref_d}] ({_formato('stock', stock_d)} uds) " + (
                f"se suma a [{ref_k}]." if self.traspasar_stock
                else "NO se traspasa y deja de verse al archivar el producto."))
        traspasos = [f"{linea['nombre']} (código {linea['codigo']})"
                     for linea in DuplicadosManager.lineas_a_traspasar(c, k) if not linea["tarifa_k"]]
        if traspasos:
            lineas.append(f"Odoo (pestaña Compra): se agrega a [{ref_k}] como proveedor: {', '.join(traspasos)}, "
                          "con su precio de compra.")
        filas_d = c.lado(d)["filas_hoja"]
        if filas_d:
            lineas.append("Planilla: " + "; ".join(f"'{f['hoja']}' fila {f['fila']}" for f in filas_d)
                          + f" mantiene su REF y queda vinculada a [{ref_k}] por su proveedor.")
        toma = [etiqueta.lower() for clave, etiqueta, _ in CAMPOS_COMPARTIDOS
                if self.elecciones[clave] == d and not valores_iguales(c.valor_lado(k, clave), c.valor_lado(d, clave))]
        if toma:
            lineas.append(f"Odoo y planilla: [{ref_k}] toma de [{ref_d}]: {', '.join(toma)}.")

        return ft.Container(
            content=ft.Column(
                [ft.Text("Qué se hará", weight=ft.FontWeight.BOLD, size=14)] + [
                    ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=16, color=ft.Colors.PRIMARY),
                            ft.Text(linea, size=13, expand=True)],
                           spacing=6, vertical_alignment=ft.CrossAxisAlignment.START)
                    for linea in lineas
                ],
                spacing=4,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=8,
            padding=12,
        )

    def render(self):
        c = self.conflicto
        self.title = ft.Row([
            ft.Icon(ft.Icons.CONTENT_COPY, color=ft.Colors.AMBER_700),
            ft.Text("Producto duplicado en Odoo", expand=True),
            ft.Text(f"{self.indice + 1} de {len(self.conflictos)}", size=14, color=ft.Colors.OUTLINE),
        ])

        controles = [
            ft.Container(
                content=ft.Text(spans=[
                    ft.TextSpan("El código de barras "),
                    ft.TextSpan(c.barcode, ft.TextStyle(weight=ft.FontWeight.BOLD)),
                    ft.TextSpan(" está en dos productos distintos de Odoo (uno por proveedor). "),
                    ft.TextSpan("Haz clic en el que quieres conservar", ft.TextStyle(weight=ft.FontWeight.BOLD)),
                    ft.TextSpan("; el otro se archivará y su stock, proveedores y filas de la planilla "
                                "pasarán al conservado."),
                ], size=13),
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.AMBER),
                border_radius=8,
                padding=10,
            ),
            ft.Row(
                [self.tarjeta(FILA),
                 ft.Container(ft.Icon(ft.Icons.COMPARE_ARROWS, color=ft.Colors.OUTLINE), padding=ft.Padding.only(top=120)),
                 self.tarjeta(EXISTENTE)],
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        ]
        if c.error_planilla:
            controles.append(_aviso(f"No se pudo leer la planilla ({c.error_planilla}). Solo se actualizará Odoo."))
        if c.otras_filas:
            controles.append(_aviso("El mismo código aparece también con otra REF en: " + "; ".join(
                f"'{f['hoja']}' fila {f['fila']} [{f['ref']}]" for f in c.otras_filas
            ) + ". Esas filas no se modifican."))

        if self.conservar:
            archivar = self.otro(self.conservar)
            stock_d = c.lado(archivar)["producto"].get("qty_available") or 0
            controles.append(self.tabla_valores())
            if stock_d:
                controles.append(ft.Checkbox(
                    label=f"Sumar el stock de [{self.ref(archivar)}] ({_formato('stock', stock_d)} uds) al producto conservado",
                    value=self.traspasar_stock,
                    on_change=lambda e: self.cambiar_traspaso(e.control.value),
                ))
            controles.append(self.resumen())
            self.btn_unificar.content = f"Conservar [{self.ref(self.conservar)}] y archivar [{self.ref(archivar)}]"
            self.btn_unificar.disabled = False
        else:
            self.btn_unificar.content = "Elige qué producto conservar"
            self.btn_unificar.disabled = True

        self.content.content = ft.Column(controles, scroll=ft.ScrollMode.AUTO, spacing=12)

    # ── Navegación ─────────────────────────────────────────────────────────

    @tarea_async
    async def unificar(self):
        for boton in (self.btn_unificar, self.btn_saltar, self.btn_cancelar):
            boton.disabled = True
        self.content.content = ft.Column(
            [ft.ProgressRing(), ft.Text(f"Unificando en [{self.ref(self.conservar)}]...")],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        )
        self.page.update()
        try:
            resultado = await asyncio.to_thread(DuplicadosManager.resolver_unificacion, 
                self.conflicto, self.conservar, self.elecciones, self.traspasar_stock,
            )
        except Exception as e:
            logger.error("Error al unificar '%s'.", self.conflicto.fila.producto, exc_info=True)
            resultado = {"state": "E", "msg": f"Error inesperado: {e}"}
        self.resultados.append((self.conflicto.barcode, resultado))
        self.btn_saltar.disabled = False
        self.btn_cancelar.disabled = False
        self.siguiente(registrar_omitido=False)

    def siguiente(self, registrar_omitido=True):
        if registrar_omitido:
            self.resultados.append((self.conflicto.barcode, {"state": "W", "msg": "Saltado, no se hicieron cambios."}))
        self.indice += 1
        if self.indice < len(self.conflictos):
            self.nuevo_conflicto()
        else:
            self.mostrar_resultados()
        self.page.update()

    def mostrar_resultados(self):
        self.title = ft.Text("Resultado de la unificación")
        colores = {"S": ft.Colors.with_opacity(0.2, ft.Colors.GREEN),
                   "W": ft.Colors.with_opacity(0.2, ft.Colors.YELLOW),
                   "E": ft.Colors.with_opacity(0.3, ft.Colors.RED)}
        self.content.content = ft.Column(
            [ft.Container(
                content=ft.Text(f"Código {barcode}\n{r['msg']}", size=12, selectable=True),
                bgcolor=colores.get(r["state"], colores["E"]),
                border_radius=6,
                padding=8,
            ) for barcode, r in self.resultados],
            scroll=ft.ScrollMode.AUTO,
            spacing=6,
        )
        self.btn_cancelar.visible = False
        self.btn_saltar.visible = False
        self.btn_unificar.visible = False
        self.btn_continuar.content = (f"Continuar con los otros {self.cantidad_limpias} códigos"
                                   if self.cantidad_limpias else "Terminar")
        self.btn_continuar.visible = True

    def cancelar(self):
        cerrar_dialogo(self.page, self)
        self.page.update()
        self.fn_cancelar()

    def continuar(self):
        cerrar_dialogo(self.page, self)
        self.page.update()
        self.fn_continuar()


