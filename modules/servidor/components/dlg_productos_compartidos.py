import asyncio
"""
Sincronización de campos compartidos (descripción, precio venta, mín/máx)
cuando el producto se compra a más de un proveedor.

La sincronización siempre va de la planilla a Odoo, pero si el producto se
compra a varios proveedores está en varias hojas y cada una puede tener un
valor distinto. Esos productos se separan del lote y se pregunta cuál hoja
manda: su valor va a Odoo y a las hojas de los demás proveedores.

Las hojas candidatas son las de los proveedores registrados en la pestaña
Compra de Odoo; dentro de cada hoja la fila se ubica por REF (ver
hojas_hermanas.opciones_por_producto).
"""

import copy

import flet as ft

from utilities.flet_compat import PaginaFija, abrir_unico, cerrar_dialogo, tarea_async
from logger_config import get_logger
from modules.servidor.components.dlg_confirmacion_sincronizacion import DlgConfirmacionSincronizacion
from modules.servidor.hojas_hermanas import (CAMPOS_LOCALES, PropagadorHojas, motivo_no_elegible,
                                             opciones_por_producto, separar_en_conflicto, texto_conflicto,
                                             valor_opcion)
from modules.servidor.duplicados import valores_iguales
from modules.servidor.models import OdooTarifa

logger = get_logger(__name__)

# clave de campo compartido -> campo de Odoo en Comparativa
CAMPO_ODOO = {"producto": "odoo_producto", "precio": "odoo_precio", "min": "odoo_min", "max": "odoo_max"}


def cantidad_proveedores(producto_ids):
    """{producto_id: cantidad de proveedores distintos en su pestaña Compra}."""
    proveedores = {}
    for pid, partner_id in (OdooTarifa.objects.filter(product_tmpl_id__in=set(producto_ids))
                            .values_list("product_tmpl_id", "partner_id")):
        proveedores.setdefault(pid, set()).add(partner_id)
    return {pid: len(p) for pid, p in proveedores.items()}


def formato_valores(claves, valores):
    """Texto de los valores de una página: descripción, precio o mín/máx."""
    if claves == ["producto"]:
        return str(valores["producto"] or "")
    if claves == ["precio"]:
        try:
            return "$" + f"{float(valores['precio']):,.0f}".replace(",", ".")
        except (TypeError, ValueError):
            return str(valores["precio"])
    return " / ".join(f"{'mín' if c == 'min' else 'máx'} {_numero(valores[c])}" for c in claves)


def _numero(valor):
    try:
        numero = float(valor)
        return f"{numero:g}"
    except (TypeError, ValueError):
        return str(valor)


@tarea_async
async def sincronizar_con_consulta(pagina, filas, claves, etiqueta, fields, fn_a_odoo, fn_continuar):
    """
    Punto de entrada común de las páginas de Precio, Descripciones y Abastecimiento.

    Args:
        pagina: la página (se usan pagina.page, pagina.loading y pagina.propagador)
        filas (list[Comparativa]): filas con diferencia seleccionadas
        claves (list[str]): campos compartidos que sincroniza la página
        etiqueta (str): nombre del campo para los textos ("descripción", "precio de venta"...)
        fields (list[str]): columnas del diálogo de confirmación
        fn_a_odoo (callable): sincroniza una fila planilla → Odoo con sus valores tb_*
                              (y registra en pagina.propagador para las demás hojas)
        fn_continuar (callable): al cerrar el diálogo de confirmación
    """
    page = pagina.page
    filas, en_conflicto = separar_en_conflicto(filas, claves)
    aviso = texto_conflicto(en_conflicto, claves) if en_conflicto else None
    if not filas:
        texto = aviso or f"No hay diferencias de {etiqueta} para sincronizar."
        abrir_unico(page, ft.SnackBar(ft.Text(texto), duration=10000 if aviso else 4000))
        return

    cantidades = cantidad_proveedores([f.producto_id for f in filas])
    compartidas = [f for f in filas if cantidades.get(f.producto_id, 0) > 1]
    ids_compartidas = {f.id for f in compartidas}
    simples = [f for f in filas if f.id not in ids_compartidas]

    def confirmar(decisiones):
        """decisiones: {fila.id: opción elegida} para las compartidas; las demás se omiten."""
        a_procesar = simples + [f for f in compartidas if f.id in decisiones]
        if not a_procesar:
            abrir_unico(page, ft.SnackBar(ft.Text("No se sincronizó ningún producto.")))
            return
        logger.info("Sincronización de %s: %d con un proveedor, %d compartidos con hoja elegida.",
                    etiqueta, len(simples), len(a_procesar) - len(simples))
        pagina.propagador = PropagadorHojas()

        def sincronizar(fila):
            opcion = decisiones.get(fila.id)
            if not opcion:
                return fn_a_odoo(fila)
            # Se sincroniza como si la fila tuviera los valores de la hoja elegida:
            # van a Odoo y el propagador los copia a las demás hojas del producto.
            fuente = copy.copy(fila)
            for clave in claves:
                setattr(fuente, CAMPOS_LOCALES[clave][0], valor_opcion(opcion, clave))
            resultado = fn_a_odoo(fuente)
            origen = f"Desde {opcion['proveedor']} ('{opcion['fila']['hoja']}' fila {opcion['fila']['fila']})"
            return {**resultado, "msg": f"{origen}: {resultado.get('msg', '')}"}

        abrir_unico(page, DlgConfirmacionSincronizacion(
            page=page,
            filas_a_actualizar=a_procesar,
            fields=fields,
            fn_sincronizar=sincronizar,
            fn_continuar=fn_continuar,
            fn_finalizar=pagina.propagador.escribir,
            aviso=aviso,
        ))

    if not compartidas:
        confirmar({})
        return

    pagina.loading.show("Buscando las hojas de cada proveedor...")
    try:
        opciones = await asyncio.to_thread(opciones_por_producto, [f.producto_id for f in compartidas])
    except Exception as e:
        pagina.loading.hide()
        logger.error("Error ubicando las hojas de los proveedores.", exc_info=True)
        abrir_unico(page, ft.SnackBar(ft.Text(f"No se pudo leer la planilla: {e}", bgcolor=ft.Colors.ERROR)))
        return
    pagina.loading.hide()
    abrir_unico(page, DlgProductosCompartidos(page, compartidas, opciones, claves, etiqueta,
                                       cantidad_simples=len(simples), fn_continuar=confirmar))


def _fecha_compra(opcion):
    """Fecha de la última compra a ese proveedor, como texto dd-mm-aaaa."""
    fecha = opcion.get("ultima_compra")
    if not fecha:
        return "sin compras registradas"
    anio, mes, dia = fecha[:10].split("-")
    return f"{dia}-{mes}-{anio}"


def _dato_compra(opcion, destacada=False):
    return ft.Row([
        ft.Icon(ft.Icons.SHOPPING_CART_OUTLINED, size=14,
                color=ft.Colors.TEAL_700 if destacada else ft.Colors.GREY_500),
        ft.Text(f"Última compra: {_fecha_compra(opcion)}", size=11,
                color=ft.Colors.TEAL_800 if destacada else ft.Colors.GREY_600,
                weight=ft.FontWeight.W_600 if destacada else None),
    ], spacing=4)


def _insignia(texto, color):
    return ft.Container(
        content=ft.Text(texto, size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
        bgcolor=color,
        border_radius=10,
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
    )


class DlgProductosCompartidos(PaginaFija, ft.AlertDialog):
    """Pregunta, por cada producto con varios proveedores, cuál hoja manda."""

    def __init__(self, page, filas, opciones, claves, etiqueta, cantidad_simples, fn_continuar):
        super().__init__()
        self.modal = True
        self.page = page
        self.filas = filas
        self.opciones = opciones          # {producto_id: [opción por proveedor]}
        self.claves = claves
        self.etiqueta = etiqueta
        self.cantidad_simples = cantidad_simples
        self.fn_continuar = fn_continuar
        self.decisiones = {}              # fila.id -> opción elegida (sin entrada = se omite)

        self.title = ft.Row([
            ft.Icon(ft.Icons.GROUPS, color=ft.Colors.AMBER_700),
            ft.Text("Productos con más de un proveedor", expand=True),
            ft.Text(f"{len(filas)}", size=14, color=ft.Colors.OUTLINE),
        ])
        self.btn_continuar = ft.FilledButton("Continuar", icon=ft.Icons.ARROW_FORWARD,
                                             on_click=lambda e: self.continuar())
        self.actions = [
            ft.TextButton("Cancelar sincronización", icon=ft.Icons.CLOSE, on_click=lambda e: self.cerrar()),
            self.btn_continuar,
        ]
        self.actions_alignment = ft.MainAxisAlignment.SPACE_BETWEEN
        # El margen evita que la sombra de las tarjetas se corte en los bordes del scroll.
        self.content = ft.Container(width=860, height=600, padding=ft.Padding.symmetric(horizontal=6, vertical=4))
        self.render()

    def elegibles(self, fila):
        return [o for o in self.opciones.get(fila.producto_id, []) if not motivo_no_elegible(o, self.claves)]

    # ── Estado ─────────────────────────────────────────────────────────────

    def elegir(self, fila, opcion):
        # Clic sobre la hoja ya elegida la desmarca (vuelve a "se omite").
        actual = self.decisiones.get(fila.id)
        if actual and actual["partner_id"] == opcion["partner_id"]:
            del self.decisiones[fila.id]
        else:
            self.decisiones[fila.id] = opcion
        self.refrescar([fila])

    def elegir_proveedor_en_todos(self, partner_id):
        cambiadas = []
        for fila in self.filas:
            opcion = next((o for o in self.elegibles(fila) if o["partner_id"] == partner_id), None)
            if opcion:
                self.decisiones[fila.id] = opcion
                cambiadas.append(fila)
        self.refrescar(cambiadas)

    # ── Vista ──────────────────────────────────────────────────────────────

    def caja_opcion(self, fila, opcion):
        """Una fila de la lista de hojas dentro de la tarjeta (sin borde propio)."""
        motivo = motivo_no_elegible(opcion, self.claves)
        elegida = (self.decisiones.get(fila.id) or {}).get("partner_id") == opcion["partner_id"]
        padding = ft.Padding.symmetric(horizontal=16, vertical=10)
        if motivo:
            return ft.Container(
                padding=padding,
                content=ft.Row([
                    ft.Icon(ft.Icons.WARNING_AMBER, size=20, color=ft.Colors.AMBER_700),
                    ft.Column([
                        ft.Text(opcion["proveedor"], size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_600),
                        _dato_compra(opcion),
                        ft.Text(f"No se puede usar: {motivo}. Esta hoja no se modifica.", size=12,
                                italic=True, color=ft.Colors.GREY_600),
                    ], spacing=2, expand=True),
                ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=12),
            )

        f = opcion["fila"]
        valores = {clave: valor_opcion(opcion, clave) for clave in self.claves}
        insignias = []
        if f["ref"] == (fila.ref_interna or "").strip().upper() and opcion["partner_id"] == fila.tb_proveedor_id:
            insignias.append(_insignia("fila seleccionada", ft.Colors.BLUE_GREY_400))
        if all(valores_iguales(valores[c], getattr(fila, CAMPO_ODOO[c])) for c in self.claves):
            insignias.append(_insignia("= Odoo", ft.Colors.INDIGO_400))
        fechas = [o.get("ultima_compra") for o in self.opciones.get(fila.producto_id, []) if o.get("ultima_compra")]
        mas_reciente = bool(opcion.get("ultima_compra")) and len(fechas) > 1 and opcion["ultima_compra"] == max(fechas)
        if mas_reciente:
            insignias.append(_insignia("compra más reciente", ft.Colors.TEAL_600))

        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e: self.elegir(fila, opcion),
            content=ft.Container(
                padding=padding,
                bgcolor=ft.Colors.GREEN_50 if elegida else ft.Colors.SURFACE_CONTAINER_LOWEST,
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE if elegida else ft.Icons.RADIO_BUTTON_UNCHECKED, size=22,
                            color=ft.Colors.GREEN_700 if elegida else ft.Colors.GREY_500),
                    ft.Column([
                        ft.Row([
                            ft.Text(opcion["proveedor"], size=13, weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREEN_900 if elegida else ft.Colors.GREY_900),
                            ft.Text(f"'{f['hoja']}' fila {f['fila']} · REF {f['ref']}", size=11,
                                    color=ft.Colors.GREY_600, expand=True),
                            *insignias,
                        ], spacing=8),
                        ft.Text(formato_valores(self.claves, valores), size=14,
                                weight=ft.FontWeight.W_600 if elegida else ft.FontWeight.W_400,
                                color=ft.Colors.ON_SURFACE),
                        _dato_compra(opcion, destacada=mas_reciente),
                    ], spacing=3, expand=True),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
            ),
        )

    def tarjeta(self, numero, fila):
        elegida = self.decisiones.get(fila.id)
        color_estado = ft.Colors.GREEN_700 if elegida else ft.Colors.BLUE_GREY_400
        insignia = (_insignia(f"MANDA {elegida['proveedor']}", ft.Colors.GREEN_700) if elegida
                    else _insignia("SE OMITE", ft.Colors.BLUE_GREY_400))
        valores_odoo = {c: getattr(fila, CAMPO_ODOO[c]) for c in self.claves}

        cabecera = ft.Container(
            bgcolor=ft.Colors.GREEN_50 if elegida else ft.Colors.BLUE_GREY_50,
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            content=ft.Row([
                ft.Container(
                    content=ft.Text(str(numero), size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                    bgcolor=color_estado, width=26, height=26, border_radius=13, alignment=ft.Alignment.CENTER,
                ),
                ft.Column([
                    ft.Text(f"[{fila.ref_interna}]", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE),
                    ft.Text(fila.odoo_producto or fila.producto or "", size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=0, expand=True),
                insignia,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
        )
        odoo_hoy = ft.Container(
            padding=ft.Padding.symmetric(horizontal=16, vertical=8),
            bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.BLACK),
            content=ft.Row([
                ft.Icon(ft.Icons.CLOUD_OUTLINED, size=16, color=ft.Colors.INDIGO_400),
                ft.Text("Hoy en Odoo:", size=12, color=ft.Colors.ON_SURFACE_VARIANT, weight=ft.FontWeight.W_500),
                ft.Text(formato_valores(self.claves, valores_odoo), size=12, color=ft.Colors.ON_SURFACE, expand=True),
            ], spacing=6),
        )
        pregunta = ft.Container(
            padding=ft.Padding.only(left=16, right=16, top=10, bottom=2),
            content=ft.Text("¿Qué hoja manda? Su valor irá a Odoo y a las demás hojas:", size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT),
        )
        lista = []
        for i, opcion in enumerate(self.opciones.get(fila.producto_id, [])):
            if i:
                lista.append(ft.Divider(height=1, thickness=1, color=ft.Colors.GREY_200))
            lista.append(self.caja_opcion(fila, opcion))

        return ft.Container(
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border_radius=12,
            border=ft.Border.all(2 if elegida else 1, ft.Colors.GREEN_600 if elegida else ft.Colors.GREY_300),
            shadow=ft.BoxShadow(blur_radius=8, spread_radius=0, offset=ft.Offset(0, 2),
                                color=ft.Colors.with_opacity(0.12, ft.Colors.BLACK)),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=ft.Column([cabecera, odoo_hoy, pregunta, *lista, ft.Container(height=6)], spacing=0),
        )

    def render(self):
        proveedores = {}
        for fila in self.filas:
            for o in self.elegibles(fila):
                proveedores.setdefault(o["partner_id"], o["proveedor"])

        cabecera = [
            ft.Container(
                content=ft.Text(spans=[
                    ft.TextSpan("Estos productos se compran a más de un proveedor, así que su "),
                    ft.TextSpan(self.etiqueta, ft.TextStyle(weight=ft.FontWeight.BOLD)),
                    ft.TextSpan(" está en varias hojas. Elige en cada uno qué hoja manda; los que no "
                                "elijas se omiten."),
                ] + ([ft.TextSpan(f" Los otros {self.cantidad_simples} productos del lote tienen un solo "
                                  "proveedor y se sincronizan normalmente.")] if self.cantidad_simples else []),
                    size=13),
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.AMBER),
                border_radius=8,
                padding=10,
            ),
        ]
        if proveedores:
            cabecera.append(ft.Row(
                [ft.Text("Para todos, que mande:", size=13)] + [
                    ft.OutlinedButton(nombre, on_click=lambda e, p=pid: self.elegir_proveedor_en_todos(p))
                    for pid, nombre in proveedores.items()
                ],
                wrap=True,
            ))
        # Cada tarjeta vive en un contenedor fijo: al elegir se reemplaza solo su
        # contenido, sin reconstruir la lista, para no perder la posición del scroll.
        self.contenedores = {f.id: ft.Container(content=self.tarjeta(i, f)) for i, f in enumerate(self.filas, start=1)}
        self.content.content = ft.Column(
            cabecera + list(self.contenedores.values()),
            scroll=ft.ScrollMode.AUTO,
            spacing=16,
        )
        self.actualizar_boton()

    def refrescar(self, filas):
        """Redibuja solo las tarjetas indicadas y el botón Continuar."""
        for numero, fila in enumerate(self.filas, start=1):
            if fila in filas:
                self.contenedores[fila.id].content = self.tarjeta(numero, fila)
        self.actualizar_boton()
        self.page.update()

    def actualizar_boton(self):
        n_elegidos = len(self.decisiones)
        n_omitidos = len(self.filas) - n_elegidos
        partes = [f"{n} con hoja elegida" for n in [n_elegidos] if n] + [f"{n} omitidos" for n in [n_omitidos] if n]
        self.btn_continuar.content = "Continuar (" + ", ".join(partes) + ")"

    # ── Navegación ─────────────────────────────────────────────────────────

    def cerrar(self):
        cerrar_dialogo(self.page, self)
        self.page.update()

    def continuar(self):
        self.cerrar()
        self.fn_continuar(dict(self.decisiones))
