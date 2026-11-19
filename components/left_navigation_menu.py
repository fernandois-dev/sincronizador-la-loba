import flet as ft
from utilities import tema
from utilities.flet_compat import en_pagina
from utilities.servicios import guardar_preferencia


from utilities.flet_compat import PaginaFija
class PopupColorItem(PaginaFija, ft.PopupMenuItem):
    def __init__(self, color, name):
        super().__init__()
        self.content = ft.Row(
            controls=[
                ft.Icon(icon=ft.Icons.COLOR_LENS_OUTLINED, color=color),
                ft.Text(name),
            ],
        )
        self.on_click = self.seed_color_changed
        self.data = color

    def seed_color_changed(self, e):
        tema.aplicar(self.page, self.data)
        self.page.update()
        guardar_preferencia(self.page, "color", self.data)


class NavigationItem(PaginaFija, ft.Container):
    def __init__(self, destination, item_clicked, is_submenu=False, level=0):
        super().__init__()
        self.ink = True
        self.padding = 10
        self.border_radius = 5
        self.destination = destination
        self.is_submenu = is_submenu
        self.content = self.set_content(destination, level)
        self.on_click = item_clicked
        self.expand = True
        self.level = level

    def set_content(self, content, level):
        self.icon = content.icon
        self.text = content.label
        self.color = content.color
        indent = level * 16 # Adjust indentation amount here
        # Contador de pendientes (se oculta cuando es 0)
        self.contador_texto = ft.Text("", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_TERTIARY_CONTAINER)
        self.contador = ft.Container(
            content=self.contador_texto,
            visible=False,
            bgcolor=ft.Colors.TERTIARY_CONTAINER,
            border_radius=ft.BorderRadius.all(10),
            padding=ft.Padding.symmetric(horizontal=7, vertical=1),
        )
        return ft.Row(
            [
                ft.Container(width=indent), # Indentation container
                ft.Row(
                    [ft.Icon(self.icon, color=self.color), ft.Text(self.text)],
                    expand=True,
                    alignment=ft.MainAxisAlignment.START,
                ),
                self.contador,
            ],
            expand=True,
            alignment=ft.MainAxisAlignment.START,
        )

    def set_pendientes(self, cantidad: int):
        self.contador.visible = cantidad > 0
        self.contador_texto.value = "99+" if cantidad > 99 else str(cantidad)


class NavigationColumn(PaginaFija, ft.Column):
    def __init__(self, menudata, page):
        super().__init__()
        self.expand = True
        self.spacing = 0
        self.scroll = ft.ScrollMode.ALWAYS
        self.width = 200
        self.menudata = menudata
        self.selected_index = None # Tracks main menu selection
        self.selected_submenu_index = None # Tracks submenu selection
        self.page = page
        self.pendientes: dict = {}  # {ruta del menú: cantidad pendiente}
        self.navigation_items = self.get_navigation_items()
        self.controls = self.navigation_items
        self.actual_control_expanded = None


    def before_update(self):
        super().before_update()
        # self.update_selected_item() # Remove alt

    def get_navigation_items(self):
        navigation_items = []
        for destination in self.menudata.control_groups:
            if destination.children:
                navigation_items.append(
                    NavigationItem(
                        destination, item_clicked=lambda e: self.item_clicked_submenu(e)
                    )
                )
            else:
                navigation_items.append(
                    NavigationItem(destination, item_clicked=lambda e:self.item_clicked(e))
                )
        return navigation_items

    def contar_pendientes(self, destination) -> int:
        """Pendientes de una opción del menú; un grupo suma los de sus opciones."""
        return self.pendientes.get(destination.name, 0) + sum(self.contar_pendientes(h) for h in destination.children)

    def set_pendientes(self, pendientes: dict):
        """Muestra la cantidad de pendientes junto a cada opción del menú."""
        self.pendientes = dict(pendientes)
        for item in self.controls:
            if isinstance(item, NavigationItem):
                item.set_pendientes(self.contar_pendientes(item.destination))
        if en_pagina(self):
            self.update()

    def item_clicked(self, e):
        # self.selected_index = self.get_navigation_index(e.control.destination) #Fixed Main menu index
        self.selected_index = e.control.destination.name #Fixed Main menu index
        self.selected_submenu_index = None  # Reset submenu selection
        self.update_selected_item()
        self.page.custom_go(f"/{e.control.destination.name}")
        self.actual_control_expanded = None
        self.remove_submenus()
        self.update()

    def item_clicked_submenu(self, e):
        # self.selected_index = self.get_navigation_index(e.control.destination)#Fixed Main menu index
        self.selected_index = e.control.destination.name
        self.selected_submenu_index = None  # Reset submenu selection
        self.update_selected_item()


        if self.actual_control_expanded == e.control.destination:
            self.actual_control_expanded = None
            self.remove_submenus()
            self.update()
            return

        self.actual_control_expanded = e.control.destination
        self.remove_submenus()
        self.add_submenus(e.control.destination)
        self.update()

    def item_clicked_child(self, e):
        self.selected_index = e.control.destination.name
        # self.selected_submenu_index = self.controls.index(e.control) #Track submenu selection
        # e.control.update()
        self.page.custom_go(f"/{e.control.destination.name}")
        self.update_selected_item()


    def update_selected_item(self):
        troute = ft.TemplateRoute(self.page.route)
        
        url = f"/{self.selected_index}" if self.selected_index else troute.route
            
        for item in self.controls:
            item.bgcolor = None
            if url.startswith(f"/{item.destination.name}"):
                item.bgcolor = ft.Colors.SECONDARY_CONTAINER
                item.content.controls[0].name = item.destination.selected_icon
            else:
                item.content.controls[0].name = item.destination.icon
            
        paso = 1
        self.selected_index = None

    def add_submenus(self, destination):
        index = self.controls.index(
            next(
                (
                    item
                    for item in self.controls
                    if isinstance(item, NavigationItem) and item.destination == destination
                ),
                None,
            )
        )

        if index is not None:
            submenu_items = []
            for child in destination.children:
                item = NavigationItem(
                    child,
                    item_clicked=self.item_clicked_child,
                    is_submenu=True,
                    level=1,  # Submenu level is 1
                )
                item.set_pendientes(self.contar_pendientes(child))
                submenu_items.append(item)
            self.controls[index + 1 : index + 1] = submenu_items

    def remove_submenus(self):
        self.controls = [
            item
            for item in self.controls
            if not (isinstance(item, NavigationItem) and item.is_submenu)
        ]

    def get_navigation_index(self, destination):
        """
        Get the index of a control group in the navigation_items list.

        Args:
            destination: The ControlGroup instance to find.

        Returns:
            The index of the ControlGroup, or None if not found.
        """
        for i, nav_item in enumerate(self.navigation_items):
            if nav_item.destination == destination:
                return i
        return None
    
    def update_menu_from_route(self, route):
        """
        Updates the menu state based on the given route.

        Args:
            route (str): The current route (e.g., "/ventas/listado").
        """
        route_parts = route.strip("/").split("/")
        main_route = route_parts[0] if route_parts else None
        sub_route = route_parts[1] if len(route_parts) > 1 else None

        self.remove_submenus()
        self.selected_index = None
        self.selected_submenu_index = None
        self.actual_control_expanded = None

        for i, nav_item in enumerate(self.navigation_items):
            if nav_item.destination.name == main_route:
                self.selected_index = nav_item.destination.name
                if sub_route:
                    if nav_item.destination.children:
                        self.actual_control_expanded = nav_item.destination
                        self.add_submenus(nav_item.destination)

                        for j, item_child in enumerate(self.controls):
                            if isinstance(item_child, NavigationItem) and item_child.is_submenu:
                                if item_child.destination.name.split("/")[1] == sub_route:
                                    self.selected_index = item_child.destination.name
                                    self.selected_submenu_index = self.controls.index(item_child)
                                    try:
                                        item_child.update() # force update item
                                    except:
                                        pass
                                    break
                break

        #force update selected items
        # self.update_selected_item()
        # self.update()


class LeftNavigationMenu(PaginaFija, ft.Column):
    def __init__(self, menudata, page):
        super().__init__()
        self.menudata = menudata
        self.page = page

        self.rail = NavigationColumn(menudata=menudata, page=self.page)

        self.dark_light_text = ft.Text("Tema claro")
        self.dark_light_icon = ft.IconButton(
            icon=ft.Icons.BRIGHTNESS_2_OUTLINED,
            tooltip="Cambiar entre claro y oscuro",
            on_click=self.theme_changed,
        )

        self.color_picker = ft.PopupMenuButton(
            icon=ft.Icons.COLOR_LENS_OUTLINED,
            tooltip="Color de la app",
            items=[PopupColorItem(color=valor, name=nombre) for valor, nombre in tema.COLORES],
        )


        # Fixed height for theme and color controls
        self.fixed_height_controls = ft.Container(
            height=100,  # Adjust height as needed
            padding=ft.Padding.all(10),
            content=ft.Column(
                controls=[
                    ft.Column(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Row(
                                controls=[
                                    self.dark_light_icon,
                                    self.dark_light_text,
                                ]
                            ),
                            ft.Row(
                                controls=[
                                    self.color_picker,
                                    ft.Text("Color"),
                                ]
                            ),
                        ]
                    )
                ]
            )
        )

        self.controls = [self.rail, self.fixed_height_controls]
        
    def set_pendientes(self, pendientes: dict):
        self.rail.set_pendientes(pendientes)

    def update_selected_index(self, route):
       self.rail.update_menu_from_route(route)
       
       
    def update_selected_item(self):
        self.rail.update_selected_item()
    

    def theme_changed(self, e):
        oscuro = self.page.theme_mode == ft.ThemeMode.LIGHT
        self.aplicar_tema(oscuro)
        guardar_preferencia(self.page, "tema", "oscuro" if oscuro else "claro")

    def aplicar_tema(self, oscuro: bool):
        """Pone el tema claro u oscuro y ajusta el botón del menú."""
        if oscuro:
            self.page.theme_mode = ft.ThemeMode.DARK
            self.dark_light_text.value = "Tema oscuro"
            self.dark_light_icon.icon = ft.Icons.BRIGHTNESS_HIGH
        else:
            self.page.theme_mode = ft.ThemeMode.LIGHT
            self.dark_light_text.value = "Tema claro"
            self.dark_light_icon.icon = ft.Icons.BRIGHTNESS_2
        self.page.update()
