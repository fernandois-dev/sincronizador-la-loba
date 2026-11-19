from datetime import date, datetime
from pathlib import Path
import flet as ft

from utilities.flet_compat import PaginaFija
# Ruta al archivo de log
from logger_config import LOG_FILE as _LOG_FILE  # carpeta de datos (ver utilities/carpeta_datos.py)

# Colores por nivel — mismos tokens de diseño que el resto de la app
_LEVEL_COLORS = {
    "DEBUG":    (ft.Colors.BLUE_50,    ft.Colors.BLUE_700),
    "INFO":     (ft.Colors.GREEN_50,   ft.Colors.GREEN_700),
    "WARNING":  (ft.Colors.ORANGE_50,  ft.Colors.ORANGE_700),
    "ERROR":    (ft.Colors.RED_50,     ft.Colors.RED_700),
    "CRITICAL": (ft.Colors.RED_100,    ft.Colors.RED_900),
}
_DEFAULT_COLORS = (ft.Colors.GREY_50, ft.Colors.GREY_600)

_PAGE_SIZE = 50


def _parse_line(raw: str) -> dict | None:
    """Parsea una línea del log. Retorna None si no tiene el formato esperado."""
    # Formato: "2026-04-08 15:22:01 | LEVEL    | module:line | mensaje"
    parts = raw.split(" | ", 3)
    if len(parts) < 4:
        return None
    try:
        ts = datetime.strptime(parts[0].strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return {
        "ts":      ts,
        "date":    ts.date(),
        "level":   parts[1].strip(),
        "module":  parts[2].strip(),
        "message": parts[3].strip(),
        "raw":     raw.rstrip(),
    }


def _load_log() -> list[dict]:
    """Lee el archivo de log y devuelve las entradas parseadas (más reciente primero)."""
    if not _LOG_FILE.exists():
        return []
    entries = []
    current = None
    with open(_LOG_FILE, encoding="utf-8", errors="replace") as f:
        for raw in f:
            parsed = _parse_line(raw)
            if parsed:
                if current:
                    entries.append(current)
                current = parsed
            elif current:
                # Línea de continuación (traceback)
                current["message"] += "\n" + raw.rstrip()
                current["raw"]     += "\n" + raw.rstrip()
    if current:
        entries.append(current)
    entries.reverse()
    return entries


class LogPage(PaginaFija, ft.Container):
    def __init__(self, page: ft.Page, params={}):
        super().__init__()
        self.page    = page
        self.expand  = True
        self.bgcolor = ft.Colors.GREY_100
        self.padding = ft.Padding.all(20)

        # Estado
        self._all_entries:      list[dict] = []
        self._filtered_entries: list[dict] = []
        self._current_page = 1

        # Filtros
        self._filter_text  = ""
        self._filter_level = "TODOS"
        self._filter_date  = None   # date | None

        self._build_ui()
        self._reload()

    # ── Construcción UI ────────────────────────────────────────────────────────

    def _build_ui(self):
        # Barra de filtros
        self._search_field = ft.TextField(
            hint_text="Buscar en mensaje o módulo…",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            height=40,
            text_size=13,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=0),
            on_change=self._on_search_change,
        )
        self._level_dropdown = ft.Dropdown(
            value="TODOS",
            width=140,
            content_padding=ft.Padding.symmetric(horizontal=8, vertical=0),
            text_size=13,
            options=[
                ft.DropdownOption("TODOS"),
                ft.DropdownOption("DEBUG"),
                ft.DropdownOption("INFO"),
                ft.DropdownOption("WARNING"),
                ft.DropdownOption("ERROR"),
                ft.DropdownOption("CRITICAL"),
            ],
            on_select=self._on_level_change,
        )
        self._date_field = ft.TextField(
            hint_text="Fecha  AAAA-MM-DD",
            width=160,
            height=40,
            text_size=13,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=0),
            on_submit=self._on_date_change,
            on_blur=self._on_date_change,
        )
        self._btn_clear_date = ft.IconButton(
            icon=ft.Icons.CLEAR,
            tooltip="Limpiar fecha",
            icon_size=18,
            on_click=self._clear_date,
        )
        self._btn_reload = ft.IconButton(
            icon=ft.Icons.REFRESH,
            tooltip="Recargar log",
            icon_size=18,
            on_click=lambda e: self._reload(),
        )
        self._count_label = ft.Text("", size=12, color=ft.Colors.GREY_600)

        filter_row = ft.Container(
            content=ft.Row(
                controls=[
                    self._search_field,
                    self._level_dropdown,
                    self._date_field,
                    self._btn_clear_date,
                    self._btn_reload,
                    self._count_label,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border_radius=ft.BorderRadius.all(12),
            padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            shadow=ft.BoxShadow(blur_radius=6, spread_radius=0,
                                color=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
                                offset=ft.Offset(0, 2)),
        )

        # Tabla
        self._table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Timestamp",  size=12, weight=ft.FontWeight.BOLD), numeric=False),
                ft.DataColumn(ft.Text("Nivel",      size=12, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Módulo",     size=12, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Mensaje",    size=12, weight=ft.FontWeight.BOLD)),
            ],
            rows=[],
            column_spacing=16,
            data_row_min_height=32,
            data_row_max_height=None,
            heading_row_height=36,
            border=ft.Border.all(1, ft.Colors.GREY_200),
            border_radius=ft.BorderRadius.all(8),
            heading_row_color=ft.Colors.GREY_100,
        )

        self._table_container = ft.Container(
            content=ft.Column(
                controls=[self._table],
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border_radius=ft.BorderRadius.all(12),
            shadow=ft.BoxShadow(blur_radius=6, spread_radius=0,
                                color=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
                                offset=ft.Offset(0, 2)),
            expand=True,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )

        # Paginador
        self._btn_prev = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT,
            on_click=lambda e: self._go_page(self._current_page - 1),
            icon_size=20,
        )
        self._btn_next = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT,
            on_click=lambda e: self._go_page(self._current_page + 1),
            icon_size=20,
        )
        self._page_label = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        paginator = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(expand=True),
                    self._btn_prev,
                    self._page_label,
                    self._btn_next,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border_radius=ft.BorderRadius.all(12),
            padding=ft.Padding.symmetric(horizontal=14, vertical=6),
            shadow=ft.BoxShadow(blur_radius=6, spread_radius=0,
                                color=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
                                offset=ft.Offset(0, 2)),
        )

        self.content = ft.Column(
            controls=[
                # Toolbar
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.ARTICLE_OUTLINED, size=20, color=ft.Colors.BLUE_700),
                            ft.Text("Log de la Aplicación", size=18,
                                    weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_700),
                        ],
                        spacing=8,
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=10),
                    border_radius=ft.BorderRadius.all(12),
                    shadow=ft.BoxShadow(blur_radius=6, spread_radius=0,
                                        color=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
                                        offset=ft.Offset(0, 2)),
                ),
                filter_row,
                self._table_container,
                paginator,
            ],
            spacing=12,
            expand=True,
        )

    # ── Carga y filtrado ───────────────────────────────────────────────────────

    def _reload(self):
        self._all_entries = _load_log()
        self._apply_filters()

    def _apply_filters(self):
        entries = self._all_entries

        if self._filter_level != "TODOS":
            entries = [e for e in entries if e["level"] == self._filter_level]

        if self._filter_date:
            entries = [e for e in entries if e["date"] == self._filter_date]

        if self._filter_text:
            q = self._filter_text.lower()
            entries = [e for e in entries
                       if q in e["message"].lower() or q in e["module"].lower()]

        self._filtered_entries = entries
        self._current_page = 1
        self._render_page()

    def _render_page(self):
        total   = len(self._filtered_entries)
        n_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self._current_page = max(1, min(self._current_page, n_pages))

        start = (self._current_page - 1) * _PAGE_SIZE
        page_entries = self._filtered_entries[start: start + _PAGE_SIZE]

        self._table.rows = [self._build_row(e) for e in page_entries]
        self._page_label.value = f"Pág. {self._current_page} / {n_pages}"
        self._count_label.value = f"{total} registros"
        self._btn_prev.disabled = self._current_page <= 1
        self._btn_next.disabled = self._current_page >= n_pages

        try:
            self._table.update()
            self._page_label.update()
            self._count_label.update()
            self._btn_prev.update()
            self._btn_next.update()
        except Exception:
            pass

    def _build_row(self, entry: dict) -> ft.DataRow:
        bg, fg = _LEVEL_COLORS.get(entry["level"], _DEFAULT_COLORS)

        # Badge de nivel
        level_badge = ft.Container(
            content=ft.Text(entry["level"], size=10, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
            bgcolor=fg,
            border_radius=ft.BorderRadius.all(4),
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
        )

        # Mensaje — si tiene saltos de línea (traceback) se muestra en fuente mono pequeña
        msg_text = ft.Text(
            entry["message"],
            size=11,
            font_family="Roboto Mono" if "\n" in entry["message"] else None,
            selectable=True,
            max_lines=6,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        return ft.DataRow(
            color=bg,
            cells=[
                ft.DataCell(ft.Text(entry["ts"].strftime("%Y-%m-%d %H:%M:%S"),
                                    size=11, color=ft.Colors.ON_SURFACE_VARIANT)),
                ft.DataCell(level_badge),
                ft.DataCell(ft.Text(entry["module"], size=11, color=ft.Colors.ON_SURFACE_VARIANT,
                                    selectable=True)),
                ft.DataCell(msg_text),
            ],
        )

    # ── Eventos ────────────────────────────────────────────────────────────────

    def _on_search_change(self, e):
        self._filter_text = e.control.value or ""
        self._apply_filters()

    def _on_level_change(self, e):
        self._filter_level = e.control.value or "TODOS"
        self._apply_filters()

    def _on_date_change(self, e):
        raw = (e.control.value or "").strip()
        try:
            self._filter_date = datetime.strptime(raw, "%Y-%m-%d").date() if raw else None
            e.control.error_text = None
        except ValueError:
            self._filter_date = None
            e.control.error_text = "Formato inválido"
        e.control.update()
        self._apply_filters()

    def _clear_date(self, e):
        self._filter_date = None
        self._date_field.value = ""
        self._date_field.error_text = None
        self._date_field.update()
        self._apply_filters()

    def _go_page(self, n: int):
        self._current_page = n
        self._render_page()
