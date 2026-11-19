import flet as ft


from utilities.flet_compat import PaginaFija, abrir_unico, cerrar_dialogo
class StepStatus:
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    ERROR = "error"


class StepsModal(PaginaFija, ft.AlertDialog):
    """Modal que muestra el progreso de una operación paso a paso."""

    def __init__(self, page: ft.Page, title: str = "Procesando"):
        super().__init__()
        self.page = page
        self.modal = True
        self.title = ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_LARGE)
        self._steps: list[dict] = []
        self._step_containers: list[ft.Column] = []
        self._on_close_callback = None

        self._close_btn = ft.TextButton(
            "Cerrar",
            on_click=self._handle_close,
            visible=True,
            disabled=True,
        )

        self._steps_column = ft.Column(
            controls=[],
            width=380,
            spacing=12,
        )
        self.content = self._steps_column
        self.actions = [self._close_btn]
        self.actions_alignment = ft.MainAxisAlignment.END

    def add_step(self, name: str):
        """Agrega un paso al modal. Debe llamarse antes de show()."""
        index = len(self._steps)
        self._steps.append({"name": name, "status": StepStatus.PENDING, "error_msg": ""})

        icon_container = ft.Container(
            content=self._build_icon(StepStatus.PENDING),
            width=28,
            height=28,
            alignment=ft.Alignment.CENTER,
        )
        name_text = ft.Text(name, theme_style=ft.TextThemeStyle.BODY_LARGE)
        error_text = ft.Text("", color=ft.Colors.ERROR, size=12, visible=False)

        step_col = ft.Column(
            controls=[
                ft.Row(
                    controls=[icon_container, name_text],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=10,
                ),
                ft.Row(
                    controls=[ft.Container(width=38), error_text],
                    spacing=0,
                ),
            ],
            spacing=2,
            data=index,
        )
        self._step_containers.append(step_col)
        self._steps_column.controls.append(step_col)

    def _build_icon(self, status: str) -> ft.Control:
        if status == StepStatus.PENDING:
            return ft.Icon(ft.Icons.RADIO_BUTTON_UNCHECKED, color=ft.Colors.GREY_400, size=24)
        elif status == StepStatus.IN_PROGRESS:
            return ft.ProgressRing(width=20, height=20, stroke_width=2.5)
        elif status == StepStatus.SUCCESS:
            return ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=ft.Colors.GREEN_600, size=24)
        elif status == StepStatus.ERROR:
            return ft.Icon(ft.Icons.CANCEL_ROUNDED, color=ft.Colors.RED_600, size=24)

    def set_step_status(self, index: int, status: str, error_msg: str = ""):
        """Actualiza el estado visual de un paso."""
        self._steps[index]["status"] = status
        self._steps[index]["error_msg"] = error_msg

        step_col = self._step_containers[index]
        icon_container: ft.Container = step_col.controls[0].controls[0]
        icon_container.content = self._build_icon(status)

        error_text: ft.Text = step_col.controls[1].controls[1]
        if error_msg:
            error_text.value = error_msg
            error_text.visible = True
        else:
            error_text.visible = False

        self.page.update()

    def show(self, on_close=None):
        """Abre el modal."""
        self._on_close_callback = on_close
        abrir_unico(self.page, self)
        self.page.update()

    def set_step_name(self, index: int, name: str):
        """Actualiza el texto del nombre de un paso (útil para mostrar reintentos)."""
        step_col = self._step_containers[index]
        name_text: ft.Text = step_col.controls[0].controls[1]
        name_text.value = name
        self.page.update()

    def show_close_button(self, on_close=None):
        """Habilita el botón Cerrar. Si se pasa on_close, reemplaza el callback actual."""
        if on_close is not None:
            self._on_close_callback = on_close
        self._close_btn.disabled = False
        self.page.update()

    def _handle_close(self, e):
        cerrar_dialogo(self.page, self)
        self.page.update()
        if self._on_close_callback:
            self._on_close_callback()

    def hide(self):
        cerrar_dialogo(self.page, self)
        self.page.update()
