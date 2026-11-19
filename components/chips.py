import flet as ft



from utilities.flet_compat import PaginaFija
class ChipComponent(PaginaFija, ft.Row):
    def __init__(self, page, chip_delete_all_callback=None):
        super().__init__()
        self.scroll=ft.ScrollMode.AUTO
        self.visible=False
        self.height=40
        self.page = page
        self.chips = []
        self.chip_delete_all_callback = chip_delete_all_callback
        self.is_filtered = False
        self.controls = []
        self.alignment=ft.MainAxisAlignment.START
        self.vertical_alignment=ft.CrossAxisAlignment.CENTER
        self.chip_delete_all = self.build_chip_delete_all()
        
    def build_chip_delete_all(self):
        def on_delete(e):
            self.remove_all_chips()
            if self.chip_delete_all_callback:
                self.chip_delete_all_callback()
        """
        Crea un chip que permite eliminar todos los chips de la lista.
        """
        return ft.Chip(
            label=ft.Text("TODOS", size=12),
            color=ft.Colors.TERTIARY_CONTAINER,
            label_text_style=ft.TextStyle(color=ft.Colors.ON_PRIMARY_CONTAINER, size=12),
            on_delete=on_delete,
        )


    def add_chip(self, label, color=None, on_delete=None):
        # verifica que label no exista en los chips
        if any(chip.label == label for chip in self.chips):
            return
        chip = ft.Chip(
            label=ft.Text(label, size=12),
            label_text_style=ft.TextStyle(color=ft.Colors.ON_PRIMARY_CONTAINER, size=12),
            on_delete=on_delete
        )
        self.chips.append(chip)
        self.controls = self.chips + [self.chip_delete_all] if self.chip_delete_all_callback else self.chips
        self.visible = True
        

    def remove_chip(self, label):
        chip_to_remove = next((chip for chip in self.chips if chip.label.value == label), None)
        if chip_to_remove:
            self.chips.remove(chip_to_remove)
            self.controls.remove(chip_to_remove)
        if not self.chips:
            self.controls = []
            self.visible = False

    def remove_all_chips(self):
        self.controls.clear()
        self.chips.clear()
        self.visible = False
        # self.update()