"""
Ayudas para Flet 1.x.

Adaptaciones del Sincronizador a cambios de Flet 1.x:

1. ``Control.page`` es de solo lectura y lanza RuntimeError si el control
   todavía no está en la página. Muchas páginas y diálogos reciben la página
   en ``__init__`` y la usan antes de montarse. ``PaginaFija`` permite seguir
   asignando ``self.page = page``.

2. ``page.open()`` / ``page.close()`` ya no existen. Los diálogos, SnackBars
   y selectores de fecha se abren con ``page.show_dialog()``, que falla si el
   diálogo ya está abierto, y ``page.pop_dialog()`` cierra el que esté más
   arriba (que puede ser un SnackBar). ``abrir_dialogo`` y ``cerrar_dialogo``
   reproducen lo que hacían ``page.open`` y ``page.close`` en Flet 0.28:
   abrir o cerrar exactamente el diálogo indicado.

3. En 1.x los handlers síncronos corren en el loop principal y lo bloquean.
   Las tareas largas son ``async def`` con ``tarea_async`` y ejecutan lo que
   bloquea con ``await asyncio.to_thread(...)``: la pantalla solo se toca
   desde el loop, como espera Flet (no hace falta parchear Flet).

4. En 0.28 ``ft.Text(valor)`` convertía el valor a texto. En 1.x se envía tal
   cual: un número llega mal al cliente y un objeto (Decimal, una ForeignKey
   de Django) hace caer la app. ``instalar_texto_como_0_28()`` restaura la
   conversión.
"""

import asyncio
import functools
import itertools

import flet as ft

from logger_config import get_logger

logger = get_logger(__name__)


class PaginaFija:
    """Mixin que devuelve a ``Control.page`` el comportamiento de Flet 0.28.

    - Permite asignar ``self.page = page`` en ``__init__`` (en 1.x es de solo lectura).
    - Si no se asignó y el control todavía no está en la página, devuelve
      ``None`` en vez de lanzar RuntimeError, como en 0.28. Varias clases
      (por ejemplo las filas de NotDataTable) leen ``self.page`` antes de montarse.

    Debe ir antes de la clase de Flet: ``class MiPagina(PaginaFija, ft.Column)``.
    """

    @property
    def page(self):
        pagina = self.__dict__.get("_pagina_fija")
        if pagina is not None:
            return pagina
        try:
            return ft.BaseControl.page.fget(self)
        except RuntimeError:
            return None

    @page.setter
    def page(self, valor):
        self.__dict__["_pagina_fija"] = valor


def _pila(page: ft.Page):
    # Pila interna de diálogos de Flet 1.x (page._dialogs).
    return page._dialogs.controls


def abrir_dialogo(page: ft.Page, dialogo) -> None:
    """Abre un diálogo, SnackBar, DatePicker, etc. (equivale a page.open en 0.28).

    Si ya está abierto, lo vuelve a enviar con sus cambios (en 0.28,
    page.open() sobre un diálogo abierto también lo actualizaba). Si se cerró
    pero Flet todavía no lo sacó de la pila (animación de cierre), lo saca y
    lo vuelve a abrir.
    """
    if dialogo is None:
        return
    pila = _pila(page)
    if dialogo in pila:
        if getattr(dialogo, "open", False):
            dialogo.update()
            return
        pila.remove(dialogo)
        page._restore_dialog_on_dismiss(dialogo)
    page.show_dialog(dialogo)


def abrir_unico(page: ft.Page, dialogo) -> None:
    """Como ``abrir_dialogo``, pero antes cierra los abiertos de la misma clase.

    Reemplaza a ``page._open`` del Sincronizador en 0.28, que sacaba del
    overlay los componentes de la misma clase antes de abrir (por ejemplo,
    para que no se acumulen SnackBars o diálogos de carga).
    """
    if dialogo is None:
        return
    nombre = dialogo.__class__.__name__
    for otro in list(_pila(page)):
        if otro is not dialogo and otro.__class__.__name__ == nombre:
            cerrar_dialogo(page, otro)
    abrir_dialogo(page, dialogo)


def cerrar_dialogo(page: ft.Page, dialogo=None) -> None:
    """Cierra el diálogo indicado (equivale a page.close en 0.28).

    Sin diálogo, cierra el de más arriba (page.pop_dialog).
    """
    if dialogo is None:
        page.pop_dialog()
        return
    if getattr(dialogo, "open", False):
        dialogo.open = False
        if dialogo in _pila(page):
            dialogo.update()


def campo_flet(clase_flet, nombre):
    """Descriptor de un campo de Flet (por ejemplo ``TextField.value``).

    En 0.28 los campos eran ``property`` y las subclases que los redefinen
    usaban ``super(...).value.fset(self, v)``. En 1.x son descriptores ``Prop``:
    se escribe con ``campo_flet(ft.TextField, "value").__set__(self, v)`` y se
    lee con ``.__get__(self, type(self))``.
    """
    for clase in clase_flet.__mro__:
        if nombre in clase.__dict__:
            return clase.__dict__[nombre]
    raise AttributeError(f"{clase_flet.__name__} no tiene el campo {nombre}")


def instalar_texto_como_0_28() -> None:
    """``ft.Text.value`` y ``ft.TextField.value`` convierten a ``str`` lo que no
    sea texto (ver punto 4). Por ejemplo, un campo de búsqueda que recibe un
    producto de Django muestra su nombre en vez de hacer caer la app.
    """
    from flet.controls.value_types import Prop

    class _PropTexto(Prop):
        __slots__ = ()
        _como_0_28 = True

        def __set__(self, obj, value):
            if value is not None and not isinstance(value, str):
                value = str(value)
            super().__set__(obj, value)

    for clase in (ft.Text, ft.TextField):
        actual = clase.__dict__.get("value")
        if isinstance(actual, Prop) and not getattr(actual, "_como_0_28", False):
            setattr(clase, "value", _PropTexto(actual.name, actual.default))


def en_pagina(control) -> bool:
    """True si el control ya está en la página.

    En 0.28 ``control.page`` era None antes de montarse; en 1.x lanza
    RuntimeError en los controles de Flet.
    """
    try:
        return control.page is not None
    except RuntimeError:
        return False


_montajes = itertools.count(1)


def montar_componente(page, componente, *args, **kwargs):
    """Incrusta un ``@ft.component`` dentro de la app imperativa.

    ``page.render()`` reemplazaría la vista entera; aquí solo se crea el
    control del componente (para ponerlo como ``content`` de un Container) y
    se arranca el planificador de la sesión, que es quien vuelve a dibujar el
    componente cuando cambia su estado. No se activa el "modo componentes",
    para no apagar la actualización automática del resto de la app.

    Cada montaje lleva una ``key`` nueva: así Flet no reutiliza el estado del
    componente anterior que ocupaba el mismo lugar, y montar de nuevo equivale
    a empezar de cero (con sus efectos de montaje).
    """
    from flet.components.component import Renderer

    async def _arrancar():
        page.session.start_updates_scheduler()

    try:
        asyncio.get_running_loop()
        page.session.start_updates_scheduler()
    except RuntimeError:
        page.run_task(_arrancar)
    kwargs.setdefault("key", f"montaje-{next(_montajes)}")
    return Renderer().render(componente, *args, **kwargs)



def tarea_async(fn):
    """Decorador para ``async def`` que se lanzan desde la interfaz (clics, lambdas).

    Llamar a la función sin ``await`` la programa con ``page.run_task`` y
    devuelve el futuro, así que los ``on_click=lambda e: self.cargar()``
    siguen funcionando. La página se toma de ``self.page`` (métodos de
    controles), del argumento ``page`` o del primer ``ft.Page`` recibido.

    Dentro de la función, lo que bloquea se ejecuta con
    ``await asyncio.to_thread(...)``; los cambios de pantalla quedan en el loop
    principal, que es lo que Flet 1.x espera.

    Para esperar el resultado desde otra corrutina: ``await fn.ahora(...)``.
    """

    def _pagina(args, kwargs):
        if args and isinstance(getattr(args[0], "page", None), ft.Page):
            return args[0].page
        page = kwargs.get("page")
        if isinstance(page, ft.Page):
            return page
        return next((a for a in args if isinstance(a, ft.Page)), None)

    async def _con_registro(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception:
            logger.error("Error en tarea %s.", getattr(fn, "__qualname__", fn), exc_info=True)
            raise

    @functools.wraps(fn)
    def envoltura(*args, **kwargs):
        page = _pagina(args, kwargs)
        if page is None:
            raise RuntimeError(f"{fn.__qualname__}: no se encontró la página para programar la tarea")
        return page.run_task(_con_registro, *args, **kwargs)

    envoltura.ahora = fn
    return envoltura


def guardar_archivo(page: ft.Page, al_elegir, **opciones) -> None:
    """Abre el diálogo "Guardar como" y llama a ``al_elegir(resultado)``.

    En Flet 1.x ``FilePicker`` es un servicio: ``save_file`` es async y devuelve
    la ruta (ya no hay overlay ni ``on_result``). ``resultado.path`` es la ruta
    elegida o None si se canceló, igual que el evento de 0.28.
    """
    from types import SimpleNamespace

    async def _abrir():
        selector = ft.FilePicker()
        ruta = await selector.save_file(**opciones)
        al_elegir(SimpleNamespace(path=ruta))

    page.run_task(_abrir)
