"""
Página "Asistente IA": el chat de scripts/ia_preguntar.py dentro de la app.

La parte de "Integración con el agente" es la que tienes que poder explicar.

Idea clave: una pregunta tarda entre 3 y 15 segundos (varias llamadas al modelo,
búsquedas y Odoo). Si eso corre en el loop de la interfaz, la app se congela.
Por eso, igual que en las otras páginas (Flet 1.x), el handler es ``async`` y lo
lento corre con ``await asyncio.to_thread(...)``; la pantalla solo se toca desde
el loop principal. Los avisos de herramientas que llegan desde el hilo del agente
se devuelven al loop con ``call_soon_threadsafe``.
"""
import asyncio
import json

import flet as ft

from logger_config import get_logger
from utilities.flet_compat import PaginaFija, tarea_async
from utilities.servicios import copiar

logger = get_logger(__name__)

# Accesos rápidos de la pantalla de inicio: (texto que se pregunta, ícono, color de fondo).
ACCESOS = [
    ("¿Qué debería comprar esta semana?", ft.Icons.SHOPPING_CART, ft.Colors.RED_600),
    ("¿Qué favoritos están sin stock?", ft.Icons.STAR, ft.Colors.DEEP_ORANGE_600),
    ("¿Qué favoritos están bajo el mínimo?", ft.Icons.TRENDING_DOWN, ft.Colors.AMBER_700),
    ("¿Qué compramos este mes, por proveedor?", ft.Icons.RECEIPT_LONG, ft.Colors.BLUE_600),
    ("¿Cuánto stock hay de espuma 2 cm densidad 15?", ft.Icons.INVENTORY_2, ft.Colors.TEAL_600),
]

# Colores de situación: los mismos del reporte "Bajo stock".
ROJO, AMBAR, GRIS, VERDE = ft.Colors.RED_600, ft.Colors.AMBER_700, ft.Colors.BLUE_GREY_400, ft.Colors.GREEN_600
PALETA_BARRAS = [ft.Colors.BLUE_600, ft.Colors.TEAL_600, ft.Colors.PURPLE_500, ft.Colors.ORANGE_600,
                 ft.Colors.PINK_500, ft.Colors.INDIGO_500, ft.Colors.GREEN_600, ft.Colors.BROWN_500]


def _clp(n) -> str:
    return f"${(n or 0):,.0f}".replace(",", ".")


def _num(n) -> str:
    return f"{(n or 0):,.0f}".replace(",", ".") if float(n or 0).is_integer() else f"{n:g}"


class AsistentePage(PaginaFija, ft.Container):
    titulo = "Asistente IA"

    def __init__(self, page: ft.Page, params={}, al_ocultar=None, al_ampliar=None):
        super().__init__()
        self.page = page
        self.expand = True
        self.bgcolor = ft.Colors.GREY_100
        self.padding = ft.Padding.all(12)
        # Cuando vive en el panel flotante, el panel le pasa sus botones de ocultar y ampliar.
        self._al_ocultar = al_ocultar
        self._al_ampliar = al_ampliar

        self.agente = None          # se crea al enviar la primera pregunta (ver _obtener_agente)
        self.ocupado = False        # True mientras el agente está respondiendo

        self._build_ui()

    # ── Construcción UI (completa) ─────────────────────────────────────────────

    def _build_ui(self):
        self._titulo_modelo = ft.Text("", size=12, color=ft.Colors.GREY_600)
        self._btn_nueva = ft.TextButton(
            "Nueva conversación", icon=ft.Icons.RESTART_ALT, on_click=self._nueva_conversacion
        )
        encabezado = ft.Row(
            [
                ft.Icon(ft.Icons.FACE_2, color=ft.Colors.AMBER_800),
                ft.Column(
                    [ft.Text("Asistente La Loba", size=20, weight=ft.FontWeight.BOLD), self._titulo_modelo],
                    spacing=0,
                    expand=True,
                ),
                self._btn_nueva,
            ] + self._botones_panel(),
        )

        self._chat = ft.ListView(expand=True, spacing=10, auto_scroll=True, padding=ft.Padding.only(right=8))
        self._chat.controls.append(self._bienvenida())

        self._entrada = ft.TextField(
            hint_text="Pregunta por productos, precios, stock o ventas…",
            expand=True,
            shift_enter=True,          # Enter envía; Shift+Enter hace salto de línea
            min_lines=1,
            max_lines=4,
            on_submit=self._enviar,
            border_radius=8,
            bgcolor=ft.Colors.WHITE,
        )
        self._btn_enviar = ft.IconButton(icon=ft.Icons.SEND, tooltip="Enviar", on_click=self._enviar)
        self._estado = ft.Text("", size=12, color=ft.Colors.GREY_600, italic=True)

        self.content = ft.Column(
            [
                encabezado,
                ft.Container(self._chat, expand=True, bgcolor=ft.Colors.WHITE, border_radius=8, padding=12),
                self._estado,
                ft.Row([self._entrada, self._btn_enviar]),
            ],
            expand=True,
        )

    def _botones_panel(self) -> list:
        botones = []
        if self._al_ampliar:
            self._btn_ampliar = ft.IconButton(icon=ft.Icons.OPEN_IN_FULL, tooltip="Ampliar / reducir",
                                              on_click=lambda e: self._al_ampliar())
            botones.append(self._btn_ampliar)
        if self._al_ocultar:
            botones.append(ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Ocultar (la conversación se conserva)",
                                         on_click=lambda e: self._al_ocultar()))
        return botones

    def _bienvenida(self):
        tarjetas = [
            ft.Container(
                ft.Row([ft.Icon(icono, color=ft.Colors.WHITE, size=28),
                        ft.Text(texto, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, size=14, expand=True)],
                       spacing=10),
                bgcolor=color, border_radius=12, padding=ft.Padding.symmetric(horizontal=16, vertical=14),
                width=250, ink=True, tooltip="Preguntar", on_click=lambda e, t=texto: self._usar_ejemplo(t),
            )
            for texto, icono, color in ACCESOS
        ]
        return ft.Column(
            [
                ft.Text("¿Qué necesitas saber hoy?", size=18, weight=ft.FontWeight.BOLD),
                ft.Text("Toca una pregunta o escribe la tuya: productos, stock, favoritos, compras o ventas.",
                        color=ft.Colors.GREY_700),
                ft.Row(tarjetas, wrap=True, spacing=10, run_spacing=10),
            ],
            spacing=8,
        )

    def _burbuja(self, texto: str, de_usuario: bool):
        """Mensaje en el chat. Las respuestas del asistente se muestran como Markdown (tablas, negritas)."""
        if de_usuario:
            contenido = ft.Text(texto, selectable=True)
        else:
            contenido = ft.Markdown(texto, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)
        # Sin anchos fijos: el chat vive en un panel que se puede ampliar o reducir.
        return ft.Container(
            contenido,
            padding=12,
            border_radius=10,
            bgcolor=ft.Colors.AMBER_50 if de_usuario else ft.Colors.GREY_50,
            border=ft.Border.all(1, ft.Colors.GREY_300),
            margin=ft.Margin.only(left=60) if de_usuario else ft.Margin.only(right=12),
        )

    def _linea_paso(self, texto: str):
        """Línea pequeña y gris para mostrar qué herramienta usó el agente (como '->' en la consola)."""
        return ft.Text(f"   ⚙ {texto}", size=12, color=ft.Colors.GREY_600, font_family="Consolas")

    def _linea_error(self, texto: str):
        return ft.Text(texto, color=ft.Colors.RED_700)

    def _usar_ejemplo(self, texto: str):
        self._entrada.value = texto
        self._enviar(None)

    def _bloquear(self, ocupado: bool, mensaje: str = ""):
        """Deshabilita la entrada mientras el agente responde."""
        self.ocupado = ocupado
        self._entrada.disabled = ocupado
        self._btn_enviar.disabled = ocupado
        self._btn_nueva.disabled = ocupado
        self._estado.value = mensaje
        self.page.update()

    # ── Integración con el agente ──────────────────────────────────────────────

    def _obtener_agente(self):
        """Crea el agente la primera vez que se usa y lo reutiliza después (creación diferida).

        El import va aquí dentro y no arriba del archivo: así la app abre aunque falte
        numpy, el .env o la configuración de IA. Si falta configuración, Agente() lanza
        ConfigIAError, que atrapa _responder. Corre en un hilo (to_thread): no toca la pantalla.
        """
        if self.agente is None:
            from modules.ia.agente import Agente

            self.agente = Agente()
        return self.agente

    def _enviar(self, e):
        """Muestra la pregunta y lanza la respuesta como tarea async.

        La entrada se bloquea mientras el agente responde porque el agente guarda UN solo
        historial: dos preguntas a la vez mezclarían sus mensajes y resultados de herramientas.
        self.ocupado se marca ANTES de lanzar la tarea, para que un doble Enter no alcance a
        enviar dos veces.
        """
        pregunta = (self._entrada.value or "").strip()
        if not pregunta or self.ocupado:
            return
        self._chat.controls.append(self._burbuja(pregunta, de_usuario=True))
        self._entrada.value = ""
        self._bloquear(True, "Pensando…")
        self._responder(pregunta)

    @tarea_async
    async def _responder(self, pregunta: str):
        """Corre en el loop de Flet; lo lento (modelo, búsquedas, Odoo) va en un hilo con to_thread."""
        largo_historial = None
        loop = asyncio.get_running_loop()

        def al_usar_herramienta(paso):
            # La llama el agente desde su hilo: se devuelve al loop para tocar la pantalla.
            loop.call_soon_threadsafe(self._mostrar_paso, paso)

        try:
            agente = await asyncio.to_thread(self._obtener_agente)
            cfg = agente.cfg
            self._titulo_modelo.value = f"{cfg.proveedor} · {cfg.modelo}"
            largo_historial = len(agente.historial)
            r = await asyncio.to_thread(agente.preguntar, pregunta, al_usar_herramienta=al_usar_herramienta)

            self._chat.controls.append(self._burbuja(r.texto or "(El asistente no devolvió texto.)", de_usuario=False))
            for panel in self._paneles(r):
                self._chat.controls.append(panel)
            productos = self._productos_mencionados(r)
            if productos:
                self._chat.controls.append(self._tarjeta_codigos(productos))
            u = r.uso
            consumo = (
                f"{len(r.pasos)} herramientas · {u.llamadas} llamadas al modelo · "
                f"{u.tokens_entrada:,} tokens entrada / {u.tokens_salida:,} salida · {r.segundos_total:.1f}s"
                + (f" · vía {u.proveedores}" if u.proveedores else "")
            ).replace(",", ".")
            if r.llego_al_limite:
                consumo += " · se alcanzó el límite de pasos"
            self._chat.controls.append(ft.Text(consumo, size=11, color=ft.Colors.GREY_500))
        except Exception as exc:  # noqa: BLE001 - cualquier falla se muestra en el chat, la app sigue
            logger.error("Error del asistente IA con la pregunta %r", pregunta, exc_info=True)
            # Si falló a mitad de camino, el historial puede quedar con un pedido de herramienta
            # sin su resultado, y el proveedor rechazaría TODAS las preguntas siguientes.
            # Se devuelve el historial a como estaba antes de esta pregunta.
            if self.agente is not None and largo_historial is not None:
                del self.agente.historial[largo_historial:]
            self._chat.controls.append(self._linea_error(self._mensaje_error(exc)))
        finally:
            self._bloquear(False)

    @staticmethod
    def _mensaje_error(exc: Exception) -> str:
        """Traduce el error a algo que entienda quien usa la app. Se compara por nombre de clase
        para no importar openai aquí (la app debe abrir aunque no esté instalado)."""
        tipo = type(exc).__name__
        if tipo == "ConfigIAError":
            return f"No se pudo iniciar el asistente: {exc}"
        if tipo == "AuthenticationError":
            return "El proveedor rechazó la API key. Revisa IA_API_KEY en el archivo .env."
        if tipo == "RateLimitError":
            return "Se alcanzó el límite de consultas del proveedor. Espera un minuto y vuelve a intentar."
        if tipo in ("APITimeoutError", "APIConnectionError"):
            return "El proveedor del modelo no respondió. Revisa la conexión o prueba de nuevo en un rato."
        if getattr(exc, "status_code", None) == 413:
            return ("La conversación se hizo muy larga para el plan gratuito del modelo. "
                    "Toca «Nueva conversación» y vuelve a preguntar.")
        if tipo == "NotFoundError":
            return "El proveedor no reconoce el modelo configurado. Revisa IA_MODELO en el archivo .env."
        return f"El asistente tuvo un error ({tipo}). El detalle quedó en el log."

    def _mostrar_paso(self, paso):
        """El agente la llama cada vez que usa una herramienta: se muestra en vivo en el chat."""
        argumentos = ", ".join(f"{k}={v!r}" for k, v in paso.argumentos.items())
        self._chat.controls.append(self._linea_paso(f"{paso.nombre}({argumentos})  [{paso.segundos:.1f}s]"))
        self._estado.value = f"Usando {paso.nombre}…"
        self.page.update()

    # ── Paneles visuales (se dibujan desde los DATOS de las herramientas) ──────
    # Decisión de diseño: los colores y números no salen del texto del modelo, sino de los
    # resultados estructurados de las herramientas. El texto puede variar; el panel no miente.

    def _paneles(self, respuesta) -> list:
        ultimos = {}
        for paso in respuesta.pasos:              # si una herramienta se usó dos veces, vale la última
            try:
                ultimos[paso.nombre] = json.loads(paso.resultado)
            except (json.JSONDecodeError, TypeError):
                continue
        paneles = []
        try:
            if "error" not in ultimos.get("sugerencias_compra", {"error": 1}):
                paneles.append(self._panel_sugerencias(ultimos["sugerencias_compra"]))
            if "error" not in ultimos.get("consultar_favoritos", {"error": 1}):
                paneles.append(self._panel_favoritos(ultimos["consultar_favoritos"]))
            if "error" not in ultimos.get("consultar_compras", {"error": 1}):
                paneles.append(self._panel_compras(ultimos["consultar_compras"]))
        except Exception:  # noqa: BLE001 - un panel que falla no debe tapar la respuesta
            logger.error("No se pudo dibujar un panel del asistente", exc_info=True)
        return [p for p in paneles if p is not None]

    @staticmethod
    def _chip(texto: str, color, tamano: int = 12):
        return ft.Container(
            ft.Text(texto, color=ft.Colors.WHITE, size=tamano, weight=ft.FontWeight.BOLD),
            bgcolor=color, border_radius=12, padding=ft.Padding.symmetric(horizontal=10, vertical=3),
        )

    @staticmethod
    def _cifra(valor: str, etiqueta: str, color):
        return ft.Container(
            ft.Column([ft.Text(valor, size=26, weight=ft.FontWeight.BOLD, color=color),
                       ft.Text(etiqueta, size=12, color=ft.Colors.GREY_700)], spacing=0),
            padding=ft.Padding.symmetric(horizontal=14, vertical=8), border_radius=10,
            bgcolor=ft.Colors.WHITE, border=ft.Border.all(1, ft.Colors.GREY_300),
        )

    def _boton_copiar(self, codigo: str):
        return ft.IconButton(icon=ft.Icons.CONTENT_COPY, icon_size=15, tooltip=f"Copiar {codigo}",
                             disabled=not codigo, on_click=lambda e, c=codigo: self._copiar(c))

    @staticmethod
    def _marco(titulo: str, icono, color, controles: list):
        return ft.Container(
            ft.Column([ft.Row([ft.Icon(icono, color=color), ft.Text(titulo, size=15, weight=ft.FontWeight.BOLD, color=color)])]
                      + controles, spacing=8),
            padding=12, border_radius=12, bgcolor=ft.Colors.GREY_50,
            border=ft.Border.all(2, color),
        )

    def _panel_sugerencias(self, datos: dict):
        resumen = datos.get("por_proveedor", [])
        if not resumen:
            return None
        criticos = sum(p["criticos"] for p in resumen)
        solicitar = sum(p.get("solicitar", 0) for p in resumen)
        descuadres = sum(p.get("stock_negativo", 0) for p in resumen)
        cifras = ft.Row([
            self._cifra(_num(datos.get("total_productos")), "productos por reponer", ft.Colors.GREY_900),
            self._cifra(_num(criticos), "críticos (bajo el mínimo)", ROJO),
            self._cifra(_num(solicitar), "por solicitar", AMBAR),
            self._cifra(_num(descuadres), "con stock negativo", GRIS),
        ], wrap=True, spacing=8)
        tarjetas = []
        for p in resumen:
            chips = [self._chip(f"{p['criticos']} críticos", ROJO)]
            if p.get("solicitar"):
                chips.append(self._chip(f"{p['solicitar']} solicitar", AMBAR))
            if p.get("stock_negativo"):
                chips.append(self._chip(f"{p['stock_negativo']} descuadre", GRIS))
            tarjetas.append(ft.Container(
                ft.Column([
                    ft.Text(p["proveedor"], weight=ft.FontWeight.BOLD, size=13, max_lines=2),
                    ft.Row(chips, wrap=True, spacing=4, run_spacing=4),
                    ft.Text(f"{_clp(p['monto_estimado'])} estimado", size=13, color=ft.Colors.GREY_800),
                ], spacing=6),
                width=235, padding=10, border_radius=10, bgcolor=ft.Colors.WHITE,
                border=ft.Border.all(1, ROJO if p["criticos"] else AMBAR),
            ))
        nota = []
        if datos.get("total_proveedores", 0) > len(resumen):
            nota.append(ft.Text(f"Se muestran {len(resumen)} de {datos['total_proveedores']} proveedores "
                                "(primero los con más críticos).", size=12, color=ft.Colors.GREY_600))
        if descuadres:
            nota.append(ft.Text("Gris = stock negativo: probable descuadre de inventario; la cantidad sugerida "
                                "puede estar inflada.", size=12, color=ft.Colors.GREY_600, italic=True))
        return self._marco("Qué comprar (criterio del reporte Bajo stock)", ft.Icons.SHOPPING_CART, ROJO,
                           [cifras, ft.Row(tarjetas, wrap=True, spacing=8, run_spacing=8)] + nota)

    def _panel_favoritos(self, datos: dict):
        r = datos.get("resumen_todos_los_favoritos", {})
        cifras = ft.Row([
            self._cifra(_num(r.get("favoritos")), "favoritos", ft.Colors.GREY_900),
            self._cifra(_num(r.get("sin_stock")), "sin stock", ROJO),
            self._cifra(_num(r.get("bajo_minimo")), "bajo el mínimo", AMBAR),
        ], wrap=True, spacing=8)
        color_situacion = {"SIN STOCK": ROJO, "BAJO MÍNIMO": AMBAR, "OK": VERDE}
        filas = []
        for f in datos.get("productos", []):
            color = color_situacion.get(f["situacion"], GRIS)
            filas.append(ft.Container(
                ft.Row([
                    self._boton_copiar(f["codigo"]),
                    ft.Text(f["codigo"], weight=ft.FontWeight.BOLD, font_family="Consolas", width=115, size=12),
                    ft.Text(f["producto"], expand=True, size=13, max_lines=2),
                    ft.Text(f"stock {_num(f['stock'])}" + (f" / mín {_num(f['minimo'])}" if f["minimo"] else ""),
                            size=12, weight=ft.FontWeight.BOLD, color=color, width=105),
                    self._chip(f["situacion"], color, 11),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=ft.Colors.RED_50 if f["situacion"] == "SIN STOCK" else
                        ft.Colors.AMBER_50 if f["situacion"] == "BAJO MÍNIMO" else ft.Colors.WHITE,
                border_radius=8, padding=ft.Padding.symmetric(horizontal=6, vertical=2),
            ))
        controles = [cifras] + filas
        if datos.get("encontrados", 0) > len(filas):
            controles.append(ft.Text(f"Se muestran {len(filas)} de {datos['encontrados']}.", size=12,
                                     color=ft.Colors.GREY_600))
        return self._marco("Favoritos", ft.Icons.STAR, ft.Colors.DEEP_ORANGE_600, controles)

    def _panel_compras(self, datos: dict):
        r = datos.get("resumen", {})
        otros = datos.get("otros_proveedores_registrados", [])
        if not r.get("lineas_de_compra") and not otros:
            return None
        controles = []
        if r.get("lineas_de_compra"):
            controles.append(ft.Row([
                self._cifra(_num(r.get("unidades")), "unidades compradas", ft.Colors.BLUE_700),
                self._cifra(_clp(r.get("monto_neto")), "monto neto", ft.Colors.GREEN_700),
                self._cifra(_num(r.get("lineas_de_compra")), "líneas de compra", ft.Colors.GREY_800),
            ], wrap=True, spacing=8))
        if datos.get("grupos"):
            grupos = datos["grupos"]
            clave = next(k for k in grupos[0] if k not in ("unidades", "monto_neto", "lineas"))
            maximo = max(g["unidades"] or 0 for g in grupos) or 1
            for i, g in enumerate(grupos):
                ancho = max(4, int(180 * (g["unidades"] or 0) / maximo))
                controles.append(ft.Row([
                    ft.Text(str(g[clave]), size=12, width=170, max_lines=2),
                    ft.Container(width=ancho, height=18, border_radius=4, bgcolor=PALETA_BARRAS[i % len(PALETA_BARRAS)]),
                    ft.Text(f"{_num(g['unidades'])} u · {_clp(g['monto_neto'])}", size=12, color=ft.Colors.GREY_800),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        for i, c in enumerate(datos.get("ultimas_compras", [])):
            controles.append(ft.Container(
                ft.Row([
                    self._boton_copiar(c.get("codigo", "")),
                    ft.Text(c["fecha"], size=12, width=80, weight=ft.FontWeight.BOLD),
                    ft.Text(c["proveedor"], size=12, width=150, max_lines=2, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLUE_800),
                    ft.Text(c["producto"], size=12, expand=True, max_lines=2),
                    ft.Text(f"{_num(c['cantidad'])} × {_clp(c['precio_unitario'])}", size=12, width=110),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=ft.Colors.BLUE_50 if i == 0 else ft.Colors.WHITE,   # la más reciente, destacada
                border_radius=8, padding=ft.Padding.symmetric(horizontal=6, vertical=2),
            ))
        if otros:
            controles.append(self._otros_proveedores(otros))
        return self._marco("Compras (Odoo en vivo)", ft.Icons.RECEIPT_LONG, ft.Colors.BLUE_600, controles)

    def _otros_proveedores(self, otros: list[dict]):
        """Proveedores registrados para el producto, pero sin compras confirmadas (en gris: no son compras)."""
        filas = [ft.Text("También registrados como proveedor (sin compras confirmadas)", size=12,
                         weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_700)]
        for o in otros:
            n = o.get("cotizaciones_sin_confirmar", 0)
            nota = (f"{n} cotización{'es' if n != 1 else ''} sin confirmar · última {o.get('ultima_cotizacion', '')}"
                    if n else "sin cotizaciones")
            filas.append(ft.Row([
                ft.Text(o["proveedor"], size=12, width=170, max_lines=2, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_800),
                ft.Text(nota, size=12, color=ft.Colors.GREY_600, expand=True),
            ], spacing=8))
            for p in o.get("productos", []):
                filas.append(ft.Row([
                    self._boton_copiar(p.get("codigo", "")),
                    ft.Text(p["producto"], size=12, expand=True, max_lines=2, color=ft.Colors.GREY_800),
                    ft.Text(_clp(p.get("precio_proveedor")), size=12, color=ft.Colors.GREY_600),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        return ft.Container(ft.Column(filas, spacing=4), bgcolor=ft.Colors.GREY_100, border_radius=8, padding=8)

    # ── Códigos para buscar en Odoo ────────────────────────────────────────────

    @staticmethod
    def _productos_mencionados(respuesta) -> list[dict]:
        """Productos que el asistente nombró en su respuesta, con su código REAL.

        Decisión de diseño: los códigos se toman de los resultados de las herramientas
        (datos de la base), no del texto del modelo, que puede traer errores de tipeo.
        El texto solo se usa para saber cuáles mencionó.
        """
        candidatos: dict[int, dict] = {}
        stock: dict[int, float] = {}
        for paso in respuesta.pasos:
            try:
                datos = json.loads(paso.resultado)
            except (json.JSONDecodeError, TypeError):
                continue  # resultado recortado o con error: se ignora
            if paso.nombre == "buscar_producto":
                for p in datos.get("productos", []):
                    candidatos.setdefault(p["id"], p)
            elif paso.nombre == "consultar_stock":
                for p in datos.get("productos", []):
                    stock[p["id"]] = p.get("stock")

        texto = (respuesta.texto or "").upper()
        mencionados = []
        for pid, p in candidatos.items():
            codigo = (p.get("codigo") or "").strip()
            nombre = (p.get("nombre") or "").strip()
            if (codigo and codigo.upper() in texto) or (nombre and nombre.upper() in texto):
                mencionados.append({
                    "id": pid,
                    "codigo": codigo,
                    "nombre": nombre,
                    "precio": p.get("precio_venta"),
                    "stock": stock.get(pid),
                })
        return mencionados[:15]

    def _tarjeta_codigos(self, productos: list[dict]):
        """Recuadro bajo la respuesta: un renglón por producto con botón para copiar el código."""
        filas = []
        for p in productos:
            detalle = []
            if p["precio"]:
                detalle.append(f"${p['precio']:,.0f}".replace(",", "."))
            if p["stock"] is not None:
                detalle.append(f"stock {p['stock']:g}")
            filas.append(
                ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.CONTENT_COPY,
                            icon_size=16,
                            tooltip="Copiar código",
                            disabled=not p["codigo"],
                            on_click=lambda e, c=p["codigo"]: self._copiar(c),
                        ),
                        ft.Text(p["codigo"] or "(sin código)", weight=ft.FontWeight.BOLD,
                                font_family="Consolas", selectable=True, width=125),
                        ft.Text(p["nombre"], expand=True, size=13),
                        ft.Text("  ·  ".join(detalle), size=12, color=ft.Colors.GREY_600),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        return ft.Container(
            ft.Column(
                [ft.Text("Códigos para buscar en Odoo", size=12, weight=ft.FontWeight.BOLD,
                         color=ft.Colors.AMBER_900)] + filas,
                spacing=0,
            ),
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            border_radius=8,
            bgcolor=ft.Colors.AMBER_50,
            border=ft.Border.all(1, ft.Colors.AMBER_200),
        )

    def _copiar(self, codigo: str):
        copiar(self.page, codigo, f"Código {codigo} copiado")

    def _nueva_conversacion(self, e):
        """Ya está hecha: borra el chat y el historial del agente."""
        if self.ocupado:
            return
        if self.agente:
            self.agente.reiniciar()
        self._chat.controls = [self._bienvenida()]
        self._estado.value = ""
        self.page.update()
