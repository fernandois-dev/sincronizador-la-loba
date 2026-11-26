"""
Página "Productos ML": productos de la Tabla Base marcados con la casilla ML.

Muestra, por producto, el precio ML calculado con la comisión real de Mercado Libre,
el stock en Odoo, peso, fotos y lo que falta para publicar. Cuando CATEGORIA ML,
MARCA o TITULO ML están vacías en la planilla, muestra una propuesta (en ámbar);
la acción "Aprobar propuestas" la escribe en la planilla.
"""
import asyncio

import flet as ft
from utilities.flet_compat import abrir_unico, cerrar_dialogo, tarea_async
from utilities import servicios
from django.db import transaction

from components.custom_buttons import boton_cargar_datos
from components.estilos import RADIO_BOTON, RADIO_CHIP, RADIO_TARJETA
from components.loading import Loading
from logger_config import get_logger
from modules.ia import descripcion as descripcion_ia
from modules.mercadolibre import catalogo, publicador
from modules.servidor.google_sheet import GoogleService
from modules.servidor.components.datos_ml import FormularioDatosML
from modules.servidor.models import ProductoML
from pages.generic_page import GenericPage
from utilities.conditions import Conditions

logger = get_logger(__name__)

# Fondo sutil de las tarjetas de la vista previa; se adapta al tema claro/oscuro.
_FONDO_TARJETA = ft.Colors.with_opacity(0.35, ft.Colors.SURFACE_CONTAINER_HIGHEST)

_COLOR_ESTADO = {
    catalogo.ESTADO_LISTO: ft.Colors.GREEN_100,
    catalogo.ESTADO_REVISAR: ft.Colors.AMBER_100,
    catalogo.ESTADO_SIN_STOCK: ft.Colors.BLUE_GREY_100,
    catalogo.ESTADO_FALTAN: ft.Colors.RED_100,
    catalogo.ESTADO_PUBLICADO: ft.Colors.GREEN_300,
    catalogo.ESTADO_PAUSADO: ft.Colors.ORANGE_100,
    catalogo.ESTADO_EN_REVISION: ft.Colors.PURPLE_100,
}


def _propuesta(flag_attr):
    return lambda obj: {"bgcolor": ft.Colors.AMBER_100} if getattr(obj, flag_attr) else {}


class MercadoLibrePage(GenericPage):
    def __init__(self, page: ft.Page, params={}, _model=ProductoML):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Productos Mercado Libre"
        self.solo_pendientes = False
        self.custom_queryset = self.get_queryset()
        self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self._restaurar_filtro()
        self.loading = Loading(self.page, open=False)
        self.conditions = Conditions(
            fields_order=["estado", "ml_item_id", "pendientes", "hoja", "ref_interna", "producto", "precio_local",
                          "recargo_ml", "precio_ml", "comision", "envio", "stock", "peso_gr", "medidas_paquete", "fotos", "categoria_id",
                          "categoria_nombre", "marca", "titulo"],
            fields_conditions_display={
                "estado": lambda obj: {"bgcolor": _COLOR_ESTADO.get(obj.estado, ft.Colors.TRANSPARENT)},
                "pendientes": lambda obj: {"bgcolor": ft.Colors.RED_50} if obj.pendientes else {},
                "categoria_id": _propuesta("categoria_propuesta"),
                "categoria_nombre": _propuesta("categoria_propuesta"),
                "marca": _propuesta("marca_propuesta"),
                "titulo": _propuesta("titulo_propuesta"),
                "stock": lambda obj: {"bgcolor": ft.Colors.RED_50} if (obj.stock or 0) <= 0 else {},
            },
        )
        self.custom_actions = self.build_custom_actions()
        self.page.update()
        self.build_page()

    # ── consultas ──
    def get_queryset(self):
        qs = ProductoML.objects.all()
        if self.solo_pendientes:
            qs = qs.exclude(estado=catalogo.ESTADO_LISTO)
        return qs

    def update_filtered_view(self):
        self.table.clear_cache()
        self.set_custom_queryset(self.get_queryset())

    # ── botones y acciones ──
    def build_custom_buttons(self):
        self.switch_pendientes = ft.Switch(
            value=self.solo_pendientes,
            on_change=lambda e: self.toggle_pendientes(),
            label_position=ft.LabelPosition.LEFT,
            thumb_icon=ft.Icons.FILTER_ALT,
            tooltip="Mostrar solo productos que aún no están listos para publicar",
        )
        return [
            boton_cargar_datos(lambda e: self.cargar_desde_tabla_base(), text="Cargar desde Tabla Base",
                               tooltip="Lee las filas con la casilla ML marcada, calcula precios y propuestas"),
            self.switch_pendientes,
        ]

    def build_custom_actions(self):
        return [
            {
                "text": "Vista previa",
                "icon": ft.Icons.PREVIEW,
                "function": lambda seleccion: self.vista_previa(seleccion),
            },
            {
                "text": "Abrir en Mercado Libre",
                "icon": ft.Icons.OPEN_IN_NEW,
                "function": lambda seleccion: self.abrir_en_ml(seleccion),
            },
            {
                "text": "Copiar SKU",
                "icon": ft.Icons.CONTENT_COPY,
                "function": lambda seleccion: servicios.copiar(
                    self.page, "\n".join(p.ref_interna for p in seleccion if p.ref_interna),
                    f"{len(seleccion)} SKU copiado(s)"),
            },
            {
                "text": "Generar descripción con IA",
                "icon": ft.Icons.AUTO_AWESOME,
                "function": lambda seleccion: self.generar_descripciones(seleccion),
            },
            {
                "text": "Aprobar propuestas (escribir en la planilla)",
                "icon": ft.Icons.FACT_CHECK,
                "function": lambda seleccion: self.aprobar_propuestas(seleccion),
            },
            {
                "text": "Actualizar descripción en Mercado Libre",
                "icon": ft.Icons.SYNC,
                "function": lambda seleccion: self._actualizar_descripcion_ml(seleccion),
            },
            {
                "text": "Pausar en Mercado Libre",
                "icon": ft.Icons.PAUSE_CIRCLE_OUTLINE,
                "function": lambda seleccion: self._cambiar_estado_ml(seleccion, "paused"),
            },
            {
                "text": "Reactivar en Mercado Libre",
                "icon": ft.Icons.PLAY_CIRCLE_OUTLINE,
                "function": lambda seleccion: self._cambiar_estado_ml(seleccion, "active"),
            },
            {
                "text": "Simular publicación (no publica)",
                "icon": ft.Icons.SCIENCE,
                "function": lambda seleccion: self.simular_publicacion(seleccion),
            },
        ]

    @tarea_async
    async def _restaurar_filtro(self):
        """Vuelve a dejar el filtro 'solo pendientes' como quedó la última vez."""
        if await servicios.leer_preferencia(self.page, "ml.solo_pendientes", False) and not self.solo_pendientes:
            self.switch_pendientes.value = True
            self.solo_pendientes = True
            self.custom_queryset = self.get_queryset()
            self.update_filtered_view()

    def toggle_pendientes(self):
        self.solo_pendientes = not self.solo_pendientes
        servicios.guardar_preferencia(self.page, "ml.solo_pendientes", self.solo_pendientes)
        self.update_filtered_view()
        abrir_unico(self.page, ft.SnackBar(ft.Text(
            "Mostrando solo productos pendientes" if self.solo_pendientes else "Mostrando todos los productos ML")))

    # ── carga ──
    @tarea_async
    async def cargar_desde_tabla_base(self):
        self.cancel_selection()
        self.loading.show("Leyendo la Tabla Base y consultando Mercado Libre...")
        try:
            productos, avisos = await asyncio.to_thread(catalogo.construir_catalogo)
            previas = {(p.hoja, p.ref_interna): p.descripcion
                       for p in ProductoML.objects.filter(descripcion_propuesta=True).exclude(descripcion="")}
            catalogo.conservar_descripciones(productos, previas)
            with transaction.atomic():
                ProductoML.objects.all().delete()
                ProductoML.objects.bulk_create([ProductoML(**p) for p in productos])
            self.update_filtered_view()
            self.loading.hide()
            resumen = {}
            for p in productos:
                resumen[p["estado"]] = resumen.get(p["estado"], 0) + 1
            texto = f"{len(productos)} productos ML. " + " · ".join(f"{k}: {v}" for k, v in resumen.items())
            if avisos:
                texto += "  ⚠ " + " ".join(avisos)
            abrir_unico(self.page, ft.SnackBar(ft.Text(texto), duration=8000))
        except Exception as e:
            self.loading.hide()
            logger.error("Error al cargar productos ML.", exc_info=True)
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error: {e}"), bgcolor=ft.Colors.ERROR))

    # ── aprobar propuestas ──
    def aprobar_propuestas(self, seleccion):
        if self.all_records_selected:
            seleccion = list(self.paginator.object_list) if self.paginator else []
        con_propuestas = [p for p in seleccion if p.tiene_propuestas]
        cambios = catalogo.cambios_por_aprobar(con_propuestas)
        if not cambios:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Los productos seleccionados no tienen propuestas para aprobar.")))
            return

        async def confirmar(e):
            cerrar_dialogo(self.page, dlg)
            self.loading.show("Escribiendo en la Tabla Base...")
            try:
                await asyncio.to_thread(GoogleService.actualizar_celdas_tabla_base, cambios)
                logger.info("Propuestas ML aprobadas: %d celdas en %d productos.", len(cambios), len(con_propuestas))
                self.loading.hide()
                self.cargar_desde_tabla_base()
            except Exception as ex:
                self.loading.hide()
                logger.error("Error al escribir propuestas ML.", exc_info=True)
                abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error: {ex}"), bgcolor=ft.Colors.ERROR))

        muestra = "\n".join(f"• {p.ref_interna}: {p.titulo}" for p in con_propuestas[:8])
        if len(con_propuestas) > 8:
            muestra += f"\n… y {len(con_propuestas) - 8} más"
        sin_col = [p for p in con_propuestas if p.descripcion_propuesta and not p.col_descripcion]
        if sin_col:
            muestra += (f"\n\n⚠ {len(sin_col)} con descripción IA no se guardarán: su pestaña no tiene "
                        f"columna {catalogo.COL_DESCRIPCION}.")
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Aprobar propuestas"),
            content=ft.Text(
                f"Se escribirán {len(cambios)} celdas (categoría, marca, título y/o descripción) en la Tabla Base "
                f"para {len(con_propuestas)} productos. Solo se completan celdas vacías.\n\n{muestra}"),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: cerrar_dialogo(self.page, dlg)),
                ft.TextButton("Aprobar", on_click=confirmar),
            ],
        )
        abrir_unico(self.page, dlg)

    # ── descripción con IA ──
    MAX_DESCRIBIR = 30

    def _selector_modo(self):
        modo = catalogo.config_ml()["descripcion_ia"]
        return ft.RadioGroup(
            value=modo if modo in descripcion_ia.MODOS else descripcion_ia.MODO_COMERCIAL,
            content=ft.Column([ft.Radio(value=k, label=v) for k, v in descripcion_ia.MODOS.items()], spacing=0),
        )

    def abrir_en_ml(self, seleccion, maximo=5):
        """Abre en el navegador las publicaciones de los productos seleccionados."""
        enlaces = [p.ml_link for p in seleccion if p.ml_link]
        if not enlaces:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Los productos seleccionados no están publicados en Mercado Libre.")))
            return
        for url in enlaces[:maximo]:
            servicios.abrir_url(self.page, url)
        if len(enlaces) > maximo:
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Se abrieron {maximo} de {len(enlaces)} publicaciones.")))

    @staticmethod
    def _guardar_descripcion(p, texto):
        """Deja la descripción como propuesta (pendiente de aprobar en la planilla)."""
        p.descripcion, p.descripcion_propuesta = texto, bool(texto)
        if p.estado == catalogo.ESTADO_LISTO:
            p.estado = catalogo.ESTADO_REVISAR
        p.save(update_fields=["descripcion", "descripcion_propuesta", "estado"])

    @staticmethod
    def _descripcion_aprobada(p, texto):
        """La descripción ya está en la planilla: deja de ser propuesta."""
        p.descripcion, p.descripcion_propuesta = texto, False
        if p.estado == catalogo.ESTADO_REVISAR and not p.tiene_propuestas:
            p.estado = catalogo.ESTADO_LISTO
        p.save(update_fields=["descripcion", "descripcion_propuesta", "estado"])

    def generar_descripciones(self, seleccion):
        """Propone descripción con IA para los seleccionados que no la tienen en la planilla."""
        if self.all_records_selected:
            seleccion = list(self.paginator.object_list) if self.paginator else []
        # Lo escrito en la planilla manda: solo se (re)generan las vacías o las que ya eran propuesta.
        objetivo = [p for p in seleccion if p.descripcion_propuesta or not p.descripcion]
        ya_tienen = len(seleccion) - len(objetivo)
        if not objetivo:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Los seleccionados ya tienen descripción en la planilla.")))
            return
        recortados = len(objetivo) > self.MAX_DESCRIBIR
        objetivo = objetivo[: self.MAX_DESCRIBIR]
        selector = self._selector_modo()

        def generar(e):
            cerrar_dialogo(self.page, dlg)
            self._ejecutar_generacion(objetivo, selector.value)

        notas = []
        if ya_tienen:
            notas.append(f"{ya_tienen} ya tienen descripción en la planilla y no se tocan.")
        if recortados:
            notas.append(f"Se generan los primeros {self.MAX_DESCRIBIR} (límite por vez).")
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Generar descripción con IA"),
            content=ft.Column([
                ft.Text(f"Se propondrá una descripción para {len(objetivo)} productos. "
                        "Quedan como propuesta (en ámbar) hasta aprobarlas en la planilla."),
                *[ft.Text(f"• {n}", size=12) for n in notas],
                ft.Text("Estilo:", weight=ft.FontWeight.BOLD),
                selector,
                ft.Text("Revisa siempre el texto antes de aprobar: la IA puede equivocarse.",
                        size=12, italic=True, color=ft.Colors.ON_SURFACE_VARIANT),
            ], tight=True, width=480),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: cerrar_dialogo(self.page, dlg)),
                ft.TextButton("Generar", on_click=generar),
            ],
        )
        abrir_unico(self.page, dlg)

    @tarea_async
    async def _ejecutar_generacion(self, productos, modo):
        self.loading.show(f"Generando descripciones con IA (0/{len(productos)})...")
        try:
            generador = descripcion_ia.GeneradorDescripciones(modo)
        except Exception as e:
            self.loading.hide()
            logger.error("No se pudo iniciar la IA.", exc_info=True)
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"IA no disponible: {e}"), bgcolor=ft.Colors.ERROR))
            return
        ok, errores = 0, []
        limite = asyncio.Semaphore(3)  # hasta 3 descripciones a la vez

        async def generar_una(p):
            async with limite:
                try:
                    return p, await asyncio.to_thread(generador.generar, p), None
                except Exception as e:
                    return p, None, e

        for i, tarea in enumerate(asyncio.as_completed([generar_una(p) for p in productos]), start=1):
            p, texto, error = await tarea
            if error is None:
                self._guardar_descripcion(p, texto)
                ok += 1
            else:
                logger.warning("No se pudo generar la descripción de %s: %s", p.ref_interna, error)
                errores.append(p.ref_interna)
            # Solo el texto: volver a llamar show() reabre el diálogo, y si justo después
            # viene hide() (último producto) Flet ignora el cierre y queda pegado.
            self.loading.txt_message.value = f"Generando descripciones con IA ({i}/{len(productos)})..."
            self.page.update()
        self.loading.hide()
        logger.info("Descripciones IA (%s): %d generadas, %d con error.", modo, ok, len(errores))
        self.update_filtered_view()
        texto = f"{ok} descripciones propuestas. Revísalas en 'Vista previa' y apruébalas."
        if errores:
            texto += f"  ⚠ Fallaron {len(errores)}: {', '.join(errores[:5])}"
        abrir_unico(self.page, ft.SnackBar(ft.Text(texto), duration=8000))

    # ── simular publicación ──
    MAX_SIMULAR = 10

    @tarea_async
    async def simular_publicacion(self, seleccion):
        """Arma cada publicación, sube las fotos y la valida en ML sin crearla."""
        if self.all_records_selected:
            seleccion = list(self.paginator.object_list) if self.paginator else []
        seleccion = list(seleccion)[: self.MAX_SIMULAR]
        if not seleccion:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Selecciona uno o más productos para simular.")))
            return
        resultados = []
        for i, p in enumerate(seleccion, start=1):
            self.loading.show(f"Simulando {i}/{len(seleccion)}: {p.ref_interna}...")
            resultados.append(await asyncio.to_thread(publicador.simular, p))
        self.loading.hide()

        filas = []
        for r in resultados:
            color = ft.Colors.GREEN_700 if r["ok"] else ft.Colors.RED_700
            icono = ft.Icons.CHECK_CIRCLE if r["ok"] else ft.Icons.ERROR
            detalle = [ft.Text(f"✖ {e}", color=ft.Colors.RED_700, size=12) for e in r["errores"]]
            detalle += [ft.Text(f"⚠ {a}", color=ft.Colors.AMBER_900, size=12) for a in r["avisos"]]
            item = r.get("item") or {}
            if item:
                detalle.append(ft.Text(
                    f"Nombre: {item.get('family_name') or item.get('title')} · Categoría {item.get('category_id')} · "
                    f"${item.get('price', 0):,} · Cantidad {item.get('available_quantity')} · "
                    f"{len(item.get('pictures', []))} fotos".replace(",", "."), size=12))
            filas.append(ft.Column([
                ft.Row([ft.Icon(icono, color=color),
                        ft.Text(f"{r['ref']} — {'Mercado Libre la aceptaría' if r['ok'] else 'Mercado Libre la rechazaría'}",
                                weight=ft.FontWeight.BOLD, color=color)]),
                *detalle,
                ft.Divider(),
            ], spacing=2))
        dlg = ft.AlertDialog(
            title=ft.Text("Simulación de publicación (no se publicó nada)"),
            content=ft.Container(ft.Column(filas, scroll=ft.ScrollMode.AUTO), width=700, height=420),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: cerrar_dialogo(self.page, dlg))],
        )
        abrir_unico(self.page, dlg)

    # ── vista previa ──
    @tarea_async
    async def vista_previa(self, seleccion):
        """Ficha de lo que se publicaría: fotos, nombre, precio desglosado, stock, envío y pendientes."""
        if self.all_records_selected and self.paginator:
            seleccion = list(self.paginator.object_list)
        seleccion = list(seleccion)
        if not seleccion:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Selecciona un producto para ver su vista previa.")))
            return
        p = seleccion[0]
        self.loading.show(f"Preparando vista previa de {p.ref_interna}...")
        try:
            fotos = await asyncio.to_thread(publicador.miniaturas, p.ref_interna)
        except Exception as e:
            logger.warning("No se pudieron cargar las fotos de %s: %s", p.ref_interna, e)
            fotos = []
        try:
            atributos_cat = await asyncio.to_thread(publicador.atributos_categoria, p.categoria_id) \
                if p.categoria_id else []
        except Exception as e:
            logger.warning("No se pudieron leer los datos de la categoría %s: %s", p.categoria_id, e)
            atributos_cat = []
        self.loading.hide()
        cfg = catalogo.config_ml()
        tenue = ft.Colors.ON_SURFACE_VARIANT

        def plata(n):
            return f"${n:,.0f}".replace(",", ".")

        def insignia(texto, bgcolor=ft.Colors.AMBER_100, color=ft.Colors.BLACK_87, icono=None):
            return ft.Container(
                ft.Row([*([ft.Icon(icono, size=14, color=color)] if icono else []),
                        ft.Text(texto, size=11, weight=ft.FontWeight.W_500, color=color)],
                       spacing=4, tight=True),
                bgcolor=bgcolor, border_radius=RADIO_CHIP, padding=ft.Padding.symmetric(vertical=3, horizontal=10))

        def propuesta(flag):
            return [insignia("propuesta", icono=ft.Icons.AUTO_AWESOME)] if flag else []

        def tarjeta(titulo, icono, controles, expand=True):
            return ft.Container(
                ft.Column([
                    ft.Row([ft.Icon(icono, size=18, color=ft.Colors.PRIMARY),
                            ft.Text(titulo, weight=ft.FontWeight.BOLD, size=14)], spacing=6),
                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    *controles,
                ], spacing=6),
                padding=14, border_radius=RADIO_TARJETA, bgcolor=_FONDO_TARJETA,
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), expand=expand)

        def boton_copiar(texto, que):
            return ft.IconButton(ft.Icons.CONTENT_COPY, icon_size=14, tooltip=f"Copiar {que}",
                                 on_click=lambda e: servicios.copiar(self.page, texto, f"{que} copiado"))

        def linea_precio(etiqueta, valor, negrita=False, color=None, tamano=13):
            peso = ft.FontWeight.BOLD if negrita else None
            return ft.Row([ft.Text(etiqueta, size=tamano, color=None if negrita else tenue, weight=peso),
                           ft.Text(valor, size=tamano, weight=peso, color=color)],
                          alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        # ── fotos: principal grande + miniaturas que la cambian ──
        if fotos:
            principal = ft.Image(src=fotos[0], width=280, height=280, fit=ft.BoxFit.CONTAIN)
            miniaturas = []

            def elegir(i):
                principal.src = fotos[i]
                for j, m in enumerate(miniaturas):
                    m.border = ft.Border.all(2 if j == i else 1,
                                             ft.Colors.PRIMARY if j == i else ft.Colors.OUTLINE_VARIANT)
                self.page.update()

            for i, b64 in enumerate(fotos):
                miniaturas.append(ft.Container(
                    ft.Image(src=b64, width=56, height=56, fit=ft.BoxFit.CONTAIN),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST, padding=3, border_radius=6, ink=True,
                    border=ft.Border.all(2 if i == 0 else 1, ft.Colors.PRIMARY if i == 0 else ft.Colors.OUTLINE_VARIANT),
                    on_click=lambda e, i=i: elegir(i)))
            galeria = ft.Column([
                ft.Container(principal, bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST, border_radius=RADIO_TARJETA, padding=10,
                             border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT)),
                ft.Row(miniaturas, wrap=True, spacing=6, width=300),
                ft.Text(f"{len(fotos)} foto{'s' if len(fotos) != 1 else ''} en Drive", size=11, color=tenue),
            ], spacing=8, width=300)
        else:
            galeria = ft.Container(
                ft.Column([ft.Icon(ft.Icons.HIDE_IMAGE, size=48, color=ft.Colors.RED_300),
                           ft.Text("Sin fotos", weight=ft.FontWeight.BOLD, color=ft.Colors.RED_700),
                           ft.Text("Súbelas a la carpeta de Drive como REF-1.jpg, REF-2.jpg…",
                                   size=11, color=tenue, text_align=ft.TextAlign.CENTER)],
                          horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER),
                width=300, height=300, border_radius=RADIO_TARJETA, bgcolor=_FONDO_TARJETA,
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), padding=20)

        # ── columna derecha: lo que vería el comprador ──
        recibe = p.precio_ml - p.comision - p.envio
        if p.precio_ml < cfg["umbral_envio_gratis"]:
            texto_envio, envio_desglose, color_envio = "Envío a cargo del comprador", "—", tenue
        elif p.envio:
            texto_envio, envio_desglose, color_envio = "Envío gratis", "+ " + plata(p.envio), ft.Colors.GREEN_700
        else:
            texto_envio, envio_desglose, color_envio = "Envío gratis obligatorio: falta MEDIDAS PAQUETE", "⚠ no incluido", ft.Colors.RED_700
        cantidad = max((p.stock or 0) - cfg["stock_reserva"], 0)
        tipo = "Clásica" if cfg["tipo_publicacion"] == "gold_special" else "Premium"

        def chip_estado():
            return ft.Container(ft.Text(p.estado, size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK_87),
                                bgcolor=_COLOR_ESTADO.get(p.estado, ft.Colors.GREY_200), border_radius=RADIO_CHIP,
                                padding=ft.Padding.symmetric(vertical=4, horizontal=12))

        def detalle(etiqueta, valor, alerta=False, copiable=False):
            """Par etiqueta / valor compacto para la grilla de detalles."""
            return ft.Container(ft.Column([
                ft.Text(etiqueta, size=11, color=tenue),
                ft.Row([ft.Text(str(valor), size=13, selectable=True, weight=ft.FontWeight.W_500,
                                color=ft.Colors.RED_700 if alerta else None),
                        *([ft.IconButton(ft.Icons.CONTENT_COPY, icon_size=13, tooltip=f"Copiar {etiqueta}",
                                         style=ft.ButtonStyle(padding=0), width=24, height=24,
                                         on_click=lambda e: servicios.copiar(self.page, str(valor),
                                                                             f"{etiqueta} copiado"))]
                          if copiable and valor not in (None, "", "—") else [])],
                       spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=0), width=165)

        # ── pestaña Resumen: lo que vería el comprador y lo que recibe La Loba ──
        resumen = ft.Column([
            ft.Row([ft.Text(p.titulo or p.producto, size=20, weight=ft.FontWeight.BOLD, selectable=True, expand=True),
                    boton_copiar(p.titulo or p.producto, "Título")], vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Row([*propuesta(p.titulo_propuesta),
                    ft.Text(f"{len(p.titulo or '')}/{catalogo.MAX_TITULO} caracteres · Nuevo · Publicación {tipo}",
                            size=11, color=tenue)], spacing=8),
            ft.Row([ft.Text(p.marca or "Sin marca", size=13, weight=ft.FontWeight.W_500), *propuesta(p.marca_propuesta),
                    ft.Text("·", color=tenue), ft.Text(p.categoria_nombre or "Sin categoría", size=13, color=tenue,
                                                       selectable=True),
                    *propuesta(p.categoria_propuesta)], spacing=6, wrap=True),
            ft.Row([
                ft.Text(plata(p.precio_ml), size=32, weight=ft.FontWeight.W_300),
                ft.Column([
                    ft.Row([ft.Icon(ft.Icons.LOCAL_SHIPPING_OUTLINED, size=16, color=color_envio),
                            ft.Text(texto_envio, size=12, color=color_envio, weight=ft.FontWeight.W_500)], spacing=6),
                    ft.Row([ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=16,
                                    color=ft.Colors.RED_700 if cantidad <= 0 else tenue),
                            ft.Text(f"{cantidad} disponibles" if cantidad > 0 else "Sin stock para publicar",
                                    size=12, color=ft.Colors.RED_700 if cantidad <= 0 else None)], spacing=6),
                ], spacing=2),
            ], spacing=24, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            tarjeta("Lo que recibe La Loba", ft.Icons.PAYMENTS_OUTLINED, [
                linea_precio("Precio en el local", plata(p.precio_local)),
                *([linea_precio("Recargo ML (embalaje u otros)", "+ " + plata(p.recargo_ml))] if p.recargo_ml else []),
                linea_precio("Comisión Mercado Libre", "+ " + plata(p.comision)),
                linea_precio("Envío", envio_desglose,
                             color=ft.Colors.RED_700 if envio_desglose.startswith("⚠") else None),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                linea_precio("Precio en Mercado Libre", plata(p.precio_ml), negrita=True),
                linea_precio("Recibe La Loba", plata(recibe), negrita=True, color=ft.Colors.GREEN_700, tamano=15),
            ], expand=False),
            ft.Text("Detalles", size=13, weight=ft.FontWeight.BOLD),
            ft.Row([
                detalle("SKU (REF INTERNA)", p.ref_interna, copiable=True),
                detalle("Código de barras", p.barcode or "—", copiable=True),
                detalle("Categoría ML", p.categoria_id or "falta", alerta=not p.categoria_id),
                detalle("Peso", f"{p.peso_gr} g" if p.peso_gr else "falta PESO GR", alerta=not p.peso_gr),
                detalle("Paquete", f"{p.medidas_paquete} cm" if p.medidas_paquete else "falta MEDIDAS PAQUETE",
                        alerta=not p.medidas_paquete),
                detalle("Stock en Odoo", "—" if p.stock is None else p.stock),
                detalle("Planilla", f"{p.hoja} · fila {p.fila}"),
            ], wrap=True, spacing=8, run_spacing=10),
        ], spacing=10, scroll=ft.ScrollMode.AUTO)

        # ── aviso de lo que falta (bajo el título; reemplaza la tarjeta "Para publicar") ──
        aviso = ft.Container(visible=False, border_radius=RADIO_TARJETA, padding=ft.Padding.symmetric(vertical=10, horizontal=14))

        def actualizar_aviso():
            base, _, faltan = (p.pendientes or "").partition(catalogo.PREFIJO_FALTAN_DATOS)
            pendientes = [x.strip(" ,") for x in base.split(", ") if x.strip(" ,")]
            faltan_ml = [x.strip() for x in faltan.split(",") if x.strip()]
            lineas = list(pendientes)
            if faltan_ml:
                lineas.append("datos para Mercado Libre: " + ", ".join(faltan_ml))
            if p.tiene_propuestas:
                lineas.append("hay propuestas (título, marca, categoría o descripción) por aprobar en la planilla")
            aviso.visible = bool(lineas)
            if not lineas:
                return
            grave = bool(pendientes or faltan_ml)
            color = ft.Colors.RED_800 if grave else ft.Colors.AMBER_900
            aviso.bgcolor = ft.Colors.with_opacity(0.08, color)
            aviso.border = ft.Border.all(1, ft.Colors.with_opacity(0.4, color))
            aviso.content = ft.Row([
                ft.Icon(ft.Icons.ERROR_OUTLINE if grave else ft.Icons.AUTO_AWESOME, color=color, size=20),
                ft.Column([
                    ft.Text("Antes de publicar falta:" if grave else "Para revisar:", size=13,
                            weight=ft.FontWeight.BOLD, color=color),
                    *[ft.Text(f"• {x}", size=12) for x in lineas],
                ], spacing=2, expand=True),
                *([ft.FilledTonalButton("Completar datos ML", icon=ft.Icons.EDIT_NOTE,
                                        on_click=lambda e: ir_a_pestana(1))] if faltan_ml else []),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START)

        actualizar_aviso()

        def etiqueta_datos_ml():
            faltan = (p.pendientes or "").partition(catalogo.PREFIJO_FALTAN_DATOS)[2]
            n = len([x for x in faltan.split(",") if x.strip()])
            return ft.Row([ft.Text("Datos ML"),
                           *([ft.Container(ft.Text(str(n), size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                                           bgcolor=ft.Colors.RED_700, border_radius=10,
                                           padding=ft.Padding.symmetric(vertical=1, horizontal=7))] if n else [])],
                          spacing=6, tight=True)

        chip = chip_estado()
        tab_datos = ft.Tab(label=etiqueta_datos_ml(), icon=ft.Icons.FACT_CHECK_OUTLINED)

        def tras_guardar_datos(faltan):
            actualizar_aviso()
            tab_datos.label = etiqueta_datos_ml()
            nuevo = chip_estado()
            chip.content, chip.bgcolor = nuevo.content, nuevo.bgcolor
            # el botón Publicar depende del estado: se rehace (acciones = [Simular, *publicar, Cerrar])
            dlg.actions = [dlg.actions[0], *self._acciones_publicar(p, cantidad, lambda: abrir_unico(self.page, dlg)),
                           dlg.actions[-1]]
            self.update_filtered_view()
            abrir_unico(self.page, dlg)

        datos_ml = FormularioDatosML(self.page, p, atributos_cat, None, al_guardar=tras_guardar_datos).control

        # ── descripción ──
        # El editor está siempre disponible (generar otra con IA, editar, guardar borrador, aprobar).
        # Si la descripción ya está aprobada en la planilla, aprobar reemplaza el texto de la celda.
        desde_planilla = bool(p.descripcion and not p.descripcion_propuesta)
        txt_desc = ft.TextField(
            value=p.descripcion, multiline=True, min_lines=6, max_lines=14, text_size=13, expand=True,
            hint_text="Sin descripción. Genérala con IA o escríbela aquí.", border_radius=RADIO_BOTON,
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.AMBER) if p.descripcion and p.descripcion_propuesta else None)
        modo_desc = ft.Dropdown(
            value=self._selector_modo().value, width=240, dense=True, text_size=12, label="Estilo",
            options=[ft.DropdownOption(k, v) for k, v in descripcion_ia.MODOS.items()])

        # El avance se muestra dentro de la tarjeta: abrir el diálogo de "cargando"
        # escondería la vista previa (Flet muestra un solo diálogo a la vez).
        estado_desc = ft.Row([], spacing=8, visible=False)

        def avisar(texto, color=None, cargando=False, icono=None):
            estado_desc.controls = [
                ft.ProgressRing(width=16, height=16, stroke_width=2) if cargando
                else ft.Icon(icono, size=16, color=color),
                ft.Text(texto, size=12, color=color, expand=True, selectable=True),
            ]
            estado_desc.visible = True
            self.page.update()

        def ocupado(si):
            for c in (txt_desc, modo_desc, btn_generar, btn_guardar, btn_aprobar):
                c.disabled = si

        async def generar_desc(e):
            ocupado(True)
            avisar("Generando descripción con IA… puede tardar unos segundos.", cargando=True)
            try:
                generador = descripcion_ia.GeneradorDescripciones(modo_desc.value)
                txt_desc.value = await asyncio.to_thread(generador.generar, p)
                self._guardar_descripcion(p, txt_desc.value)
                txt_desc.bgcolor = ft.Colors.with_opacity(0.08, ft.Colors.AMBER)
                ocupado(False)
                avisar("Descripción generada y guardada como propuesta. Revísala antes de aprobar.",
                       color=ft.Colors.GREEN_700, icono=ft.Icons.CHECK_CIRCLE_OUTLINE)
            except Exception as ex:
                logger.error("Error al generar descripción de %s.", p.ref_interna, exc_info=True)
                ocupado(False)
                avisar(f"Error de la IA: {ex}", color=ft.Colors.RED_700, icono=ft.Icons.ERROR_OUTLINE)

        def guardar_desc(e):
            self._guardar_descripcion(p, (txt_desc.value or "").strip())
            avisar("Borrador guardado en el Gestor (aún no está en la planilla).",
                   color=ft.Colors.GREEN_700, icono=ft.Icons.CHECK_CIRCLE_OUTLINE)

        async def aprobar_desc(e):
            texto = (txt_desc.value or "").strip()
            if not texto:
                avisar("No hay texto para aprobar.", color=ft.Colors.RED_700, icono=ft.Icons.ERROR_OUTLINE)
                return
            if not p.col_descripcion:
                avisar(f"La pestaña no tiene columna {catalogo.COL_DESCRIPCION}. Agrégala y vuelve a "
                       "cargar desde la Tabla Base.", color=ft.Colors.RED_700, icono=ft.Icons.ERROR_OUTLINE)
                return
            ocupado(True)
            avisar("Escribiendo en la planilla…", cargando=True)
            try:
                await asyncio.to_thread(GoogleService.actualizar_celdas_tabla_base,
                                        [(p.hoja, p.fila, p.col_descripcion, texto)])
                self._descripcion_aprobada(p, texto)
                logger.info("Descripción ML aprobada: %s (%s fila %s).", p.ref_interna, p.hoja, p.fila)
                txt_desc.bgcolor = None
                ocupado(False)
                avisar(f"Escrita en la planilla: {p.hoja}, fila {p.fila}, columna {catalogo.COL_DESCRIPCION}.",
                       color=ft.Colors.GREEN_700, icono=ft.Icons.CHECK_CIRCLE)
            except Exception as ex:
                logger.error("Error al escribir la descripción de %s.", p.ref_interna, exc_info=True)
                ocupado(False)
                avisar(f"No se pudo escribir en la planilla: {ex}", color=ft.Colors.RED_700,
                       icono=ft.Icons.ERROR_OUTLINE)

        btn_generar = ft.FilledTonalButton("Generar con IA", icon=ft.Icons.AUTO_AWESOME, on_click=generar_desc)
        btn_guardar = ft.OutlinedButton("Guardar borrador", icon=ft.Icons.SAVE_OUTLINED, on_click=guardar_desc)
        btn_aprobar = ft.FilledButton("Aprobar", icon=ft.Icons.FACT_CHECK, on_click=aprobar_desc,
                                      disabled=not p.col_descripcion,
                                      tooltip="Escribe esta descripción en la columna DESCRIPCION ML de la planilla")

        # ── pestaña Descripción: un solo aviso arriba ──
        if desde_planilla:
            nota_desc = ("Aprobada en la planilla. Si la editas o generas otra y apruebas, se reemplaza la de la planilla.",
                         ft.Icons.TABLE_CHART_OUTLINED, ft.Colors.GREEN_700)
        elif p.descripcion and p.descripcion_propuesta:
            nota_desc = ("Borrador sin aprobar (revísalo: la IA puede equivocarse). Se publica solo si lo apruebas.",
                         ft.Icons.AUTO_AWESOME, ft.Colors.AMBER_900)
        else:
            nota_desc = ("Sin descripción. Genérala con IA o escríbela aquí.", ft.Icons.INFO_OUTLINE, tenue)
        if not p.col_descripcion:
            nota_desc = (nota_desc[0] + f" La pestaña no tiene columna {catalogo.COL_DESCRIPCION}: no se podrá aprobar.",
                         ft.Icons.WARNING_AMBER, ft.Colors.AMBER_900)
        btn_generar.tooltip = "Revisa el texto antes de aprobar: la IA puede equivocarse."
        descripcion = ft.Column([
            ft.Row([ft.Icon(nota_desc[1], size=16, color=nota_desc[2]),
                    ft.Text(nota_desc[0], size=12, color=nota_desc[2], expand=True)], spacing=6),
            # En Flet 1.x el TextField dentro de un Column no toma todo el ancho: va en un Row
            ft.Row([txt_desc]),
            ft.Row([modo_desc, btn_generar, btn_guardar, btn_aprobar],
                   wrap=True, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            estado_desc,
        ], spacing=10, scroll=ft.ScrollMode.AUTO)

        async def simular(e):
            self.loading.show(f"Simulando publicación de {p.ref_interna}...")
            r = await asyncio.to_thread(publicador.simular, p)
            self.loading.hide()
            # el resultado se muestra de inmediato en su propia ventana
            self._resultado_simulacion(p, r, cantidad, lambda: abrir_unico(self.page, dlg))

        # ── pestañas ──
        pestanas = ft.Tabs(
            length=3, selected_index=0, expand=True,
            content=ft.Column([
                ft.TabBar(tabs=[ft.Tab(label="Resumen", icon=ft.Icons.STOREFRONT_OUTLINED), tab_datos,
                                ft.Tab(label="Descripción", icon=ft.Icons.NOTES)],
                          scrollable=False, tab_alignment=ft.TabAlignment.FILL),
                ft.TabBarView(expand=True, controls=[
                    ft.Container(resumen, padding=ft.Padding.only(top=12, right=8)),
                    ft.Container(datos_ml, padding=ft.Padding.only(top=12, right=8)),
                    ft.Container(descripcion, padding=ft.Padding.only(top=12, right=8)),
                ]),
            ], spacing=0, expand=True),
        )

        def ir_a_pestana(i):
            pestanas.selected_index = i
            pestanas.update()

        encabezado = ft.Row([
            ft.Icon(ft.Icons.STOREFRONT, color=ft.Colors.PRIMARY),
            ft.Text("Vista previa", size=18, weight=ft.FontWeight.BOLD),
            ft.Text(f"{p.ref_interna} · {p.producto}", size=13, color=tenue, expand=True,
                    overflow=ft.TextOverflow.ELLIPSIS),
            chip,
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        dlg = ft.AlertDialog(
            title=encabezado,
            content=ft.Container(ft.Column([
                aviso,
                ft.Row([galeria, pestanas], spacing=24, expand=True,
                       vertical_alignment=ft.CrossAxisAlignment.START),
            ], spacing=12), width=1080, height=600),
            actions=[
                ft.OutlinedButton("Simular publicación", icon=ft.Icons.SCIENCE_OUTLINED, on_click=simular),
                *self._acciones_publicar(p, cantidad, lambda: abrir_unico(self.page, dlg)),
                ft.TextButton("Cerrar", on_click=lambda e: cerrar_dialogo(self.page, dlg)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        abrir_unico(self.page, dlg)

    # ── publicar ──
    _PUBLICABLES = (catalogo.ESTADO_LISTO, catalogo.ESTADO_REVISAR)

    def _acciones_publicar(self, p, cantidad, volver):
        """Botones de la vista previa: 'Ver en Mercado Libre' si ya está publicado; si no, 'Publicar'."""
        if p.ml_item_id:
            botones = [ft.OutlinedButton("Copiar link", icon=ft.Icons.LINK, disabled=not p.ml_link,
                                         on_click=lambda e: servicios.copiar(self.page, p.ml_link, "Link copiado")),
                       ft.FilledButton("Ver en Mercado Libre", icon=ft.Icons.OPEN_IN_NEW, disabled=not p.ml_link,
                                       on_click=lambda e: servicios.abrir_url(self.page, p.ml_link),
                                       tooltip=f"{p.ml_item_id} · {p.ml_estado}")]
            botones.insert(0, ft.OutlinedButton(
                "Actualizar descripción", icon=ft.Icons.SYNC,
                tooltip="Envía a Mercado Libre la descripción de la planilla (la que se ve aquí)",
                on_click=lambda e: self._actualizar_descripcion_ml([p])))
            if p.estado == catalogo.ESTADO_PUBLICADO:
                botones.insert(0, ft.OutlinedButton("Pausar", icon=ft.Icons.PAUSE_CIRCLE_OUTLINE,
                                                    on_click=lambda e: self._cambiar_estado_ml([p], "paused")))
            elif p.estado == catalogo.ESTADO_PAUSADO:
                botones.insert(0, ft.OutlinedButton("Reactivar", icon=ft.Icons.PLAY_CIRCLE_OUTLINE,
                                                    on_click=lambda e: self._cambiar_estado_ml([p], "active")))
            return botones
        motivo = None
        if p.estado not in self._PUBLICABLES:
            motivo = f"No se puede publicar: {p.estado.lower()}"
        elif cantidad <= 0:
            motivo = "No se puede publicar: sin stock disponible"
        return [ft.FilledButton("Publicar", icon=ft.Icons.PUBLISH, disabled=bool(motivo),
                                tooltip=motivo or "Crea la publicación real en Mercado Libre",
                                on_click=lambda e: self._confirmar_publicar(p, cantidad, volver))]

    def _confirmar_publicar(self, p, cantidad, volver):
        def plata(n):
            return f"${n:,.0f}".replace(",", ".")

        avisos = []
        if p.tiene_propuestas:
            avisos.append("Hay propuestas sin aprobar: se publicará con los datos tal como se ven en la vista previa.")
        if p.descripcion_propuesta or not p.descripcion:
            avisos.append("La descripción no está aprobada en la planilla"
                          + (": se usará el borrador guardado." if p.descripcion else ": se usará un texto base."))

        def cancelar(e):
            cerrar_dialogo(self.page, conf)
            volver()

        async def confirmar(e):
            cerrar_dialogo(self.page, conf)
            self.loading.show(f"Publicando {p.ref_interna} en Mercado Libre...")
            r = await asyncio.to_thread(publicador.publicar, p)
            self.loading.hide()
            self._resultado_publicacion(p, r)

        conf = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.PUBLISH, color=ft.Colors.PRIMARY), ft.Text("Publicar en Mercado Libre")]),
            content=ft.Column([
                ft.Text("Esto crea una publicación REAL y visible para los compradores.", weight=ft.FontWeight.BOLD),
                ft.Text(f"{p.ref_interna} · {p.titulo or p.producto}"),
                ft.Text(f"Precio {plata(p.precio_ml)} · {cantidad} disponibles · categoría {p.categoria_id}"),
                *[ft.Text(f"⚠ {a}", size=12, color=ft.Colors.AMBER_900) for a in avisos],
                ft.Text("Después se puede pausar o cerrar desde Mercado Libre, pero no deshacer.",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ], tight=True, spacing=8, width=520),
            actions=[ft.TextButton("Cancelar", on_click=cancelar),
                     ft.FilledButton("Sí, publicar", icon=ft.Icons.PUBLISH, on_click=confirmar)],
        )
        abrir_unico(self.page, conf)

    def _resultado_simulacion(self, p, r, cantidad, volver):
        """Ventana con el veredicto de la simulación: si Mercado Libre la aceptaría, qué la
        bloquea y qué avisos hay. Si se puede, ofrece publicar desde ahí."""
        ok = r["ok"]
        color = ft.Colors.GREEN_700 if ok else ft.Colors.RED_700
        puede_publicar = ok and not p.ml_item_id and p.estado in self._PUBLICABLES and cantidad > 0

        def seccion(titulo, icono, color_txt, lineas):
            return ft.Column([
                ft.Row([ft.Icon(icono, size=16, color=color_txt),
                        ft.Text(titulo, size=13, weight=ft.FontWeight.BOLD, color=color_txt)], spacing=6),
                *[ft.Text(f"• {x}", size=12, selectable=True) for x in lineas],
            ], spacing=4)

        contenido = [ft.Container(
            ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE if ok else ft.Icons.CANCEL, color=color, size=36),
                    ft.Column([
                        ft.Text("Se puede publicar" if ok else "No se puede publicar todavía",
                                size=20, weight=ft.FontWeight.BOLD, color=color),
                        ft.Text("Mercado Libre la aceptaría tal como está (no se publicó nada)." if ok else
                                "Mercado Libre la rechazaría. Corrige lo que aparece abajo y vuelve a simular.",
                                size=12),
                    ], spacing=2, expand=True)], spacing=12),
            bgcolor=ft.Colors.with_opacity(0.08, color), border=ft.Border.all(1, color),
            border_radius=RADIO_TARJETA, padding=14)]
        if r["errores"]:
            contenido.append(seccion("Lo que impide publicar", ft.Icons.ERROR_OUTLINE, ft.Colors.RED_700,
                                     r["errores"]))
        if r["avisos"]:
            contenido.append(seccion("Avisos (no impiden publicar)", ft.Icons.WARNING_AMBER, ft.Colors.AMBER_900,
                                     r["avisos"]))
        if ok and not puede_publicar and not p.ml_item_id:
            motivo = "sin stock disponible" if cantidad <= 0 else p.estado.lower()
            contenido.append(ft.Text(f"Para publicar falta resolver: {motivo}.", size=12, italic=True))

        def volver_a_vista(e=None):
            cerrar_dialogo(self.page, res)
            volver()

        def publicar(e):
            cerrar_dialogo(self.page, res)
            self._confirmar_publicar(p, cantidad, volver)

        res = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Simulación · {p.ref_interna} · {p.titulo or p.producto}", size=16),
            content=ft.Column(contenido, tight=True, spacing=12, width=560, scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Volver a la vista previa", icon=ft.Icons.ARROW_BACK, on_click=volver_a_vista),
                *([ft.FilledButton("Publicar", icon=ft.Icons.PUBLISH, on_click=publicar)] if puede_publicar else []),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        abrir_unico(self.page, res)

    def _resultado_publicacion(self, p, r):
        color = ft.Colors.GREEN_700 if r["ok"] else ft.Colors.RED_700

        def cerrar(e):
            cerrar_dialogo(self.page, res)
            if r["ok"]:
                self.cargar_desde_tabla_base()  # para que la fila muestre la publicación

        contenido = [
            ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE if r["ok"] else ft.Icons.CANCEL, color=color),
                    ft.Text("¡Publicado en Mercado Libre!" if r["ok"] else "No se publicó",
                            weight=ft.FontWeight.BOLD, color=color, size=16)]),
        ]
        if r.get("item_id"):
            contenido.append(ft.Text(f"Publicación {r['item_id']}"
                                     + (f" · {publicador.ESTADOS_ML.get(r.get('status'), r.get('status'))}"
                                        if r.get("status") else ""), selectable=True))
        if r.get("titulo_ml"):
            contenido.append(ft.Text(f"Título que armó Mercado Libre: {r['titulo_ml']}", size=12, selectable=True))
        contenido += [ft.Text(f"✖ {x}", size=12, color=ft.Colors.RED_700) for x in r["errores"]]
        contenido += [ft.Text(f"⚠ {x}", size=12, color=ft.Colors.AMBER_900) for x in r["avisos"]]

        res = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"{p.ref_interna} · {p.titulo or p.producto}"),
            content=ft.Column(contenido, tight=True, spacing=6, width=520),
            actions=[*([ft.FilledButton("Ver en Mercado Libre", icon=ft.Icons.OPEN_IN_NEW, url=r["permalink"])]
                       if r.get("permalink") else []),
                     ft.TextButton("Cerrar", on_click=cerrar)],
        )
        abrir_unico(self.page, res)


    # ── actualizar descripción ──
    @tarea_async
    async def _actualizar_descripcion_ml(self, seleccion):
        """
        Envía a ML la descripción de la planilla (DESCRIPCION ML, tal como quedó en la última
        'Cargar desde Tabla Base') de los productos ya publicados. Los borradores sin aprobar no se envían.
        """
        if self.all_records_selected and self.paginator:
            seleccion = list(self.paginator.object_list)
        publicados = [p for p in seleccion if p.ml_item_id]
        if not publicados:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Los productos seleccionados no tienen publicación en Mercado Libre.")))
            return
        omitidos = [f"{p.ref_interna}: " + ("borrador sin aprobar" if p.descripcion_propuesta else "sin DESCRIPCION ML")
                    for p in publicados if p.descripcion_propuesta or not (p.descripcion or "").strip()]
        objetivo = [p for p in publicados if not p.descripcion_propuesta and (p.descripcion or "").strip()]
        self.loading.show(f"Actualizando la descripción de {len(objetivo)} publicación(es) en Mercado Libre...")
        cambiadas, iguales, fallas = 0, 0, []
        for p in objetivo:
            r = await asyncio.to_thread(publicador.actualizar_descripcion, p.ml_item_id, p.descripcion)
            if not r["ok"]:
                fallas.append(f"{p.ref_interna}: {r['error']}")
            elif r["cambio"]:
                cambiadas += 1
            else:
                iguales += 1
        self.loading.hide()
        partes = [f"{cambiadas} descripción(es) actualizada(s)"]
        if iguales:
            partes.append(f"{iguales} ya estaba(n) igual")
        texto = ", ".join(partes) + "."
        if omitidos:
            texto += "  Sin enviar: " + " · ".join(omitidos)
        if fallas:
            texto += "  ✖ " + " · ".join(fallas)
        abrir_unico(self.page, ft.SnackBar(ft.Text(texto), duration=12000,
                                           bgcolor=ft.Colors.ERROR if fallas and not cambiadas else None))

    # ── pausar / reactivar ──
    @tarea_async
    async def _cambiar_estado_ml(self, seleccion, estado):
        """Pausa (estado='paused') o reactiva ('active') en ML las publicaciones de los productos dados."""
        if self.all_records_selected and self.paginator:
            seleccion = list(self.paginator.object_list)
        objetivo = [p for p in seleccion if p.ml_item_id]
        verbo = "Pausando" if estado == "paused" else "Reactivando"
        if not objetivo:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Los productos seleccionados no tienen publicación en Mercado Libre.")))
            return
        self.loading.show(f"{verbo} {len(objetivo)} publicación(es) en Mercado Libre...")
        fallas = []
        for p in objetivo:
            r = await asyncio.to_thread(publicador.cambiar_estado, p.ml_item_id, estado)
            if not r["ok"]:
                fallas.append(f"{p.ref_interna}: {r['error'] or r['estado']}")
        self.loading.hide()
        hechas = len(objetivo) - len(fallas)
        texto = f"{hechas} publicación(es) {'pausada(s)' if estado == 'paused' else 'reactivada(s)'}."
        if fallas:
            texto += "  ✖ " + " · ".join(fallas)
        self.cargar_desde_tabla_base()
        abrir_unico(self.page, ft.SnackBar(ft.Text(texto), duration=10000,
                                    bgcolor=ft.Colors.ERROR if fallas and not hechas else None))
