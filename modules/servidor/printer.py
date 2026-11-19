import sys
import platform

# Importar módulos específicos de plataforma
def _activar_pywin32() -> None:
    """Procesa pywin32.pth a mano (rutas win32/ y DLLs de pywin32_system32).

    En el programa compilado con flet build el Python incluido puede no leer
    los .pth de site-packages, y sin eso win32print no carga.
    """
    import os
    import site
    for base in list(sys.path):
        if os.path.isfile(os.path.join(base, "pywin32.pth")):
            site.addsitedir(base)
            dlls = os.path.join(base, "pywin32_system32")
            if os.path.isdir(dlls) and hasattr(os, "add_dll_directory"):
                os.add_dll_directory(dlls)
            return


if sys.platform == 'win32':
    try:
        try:
            from win32 import win32print
        except ImportError:
            _activar_pywin32()
            from win32 import win32print
        WINDOWS_PRINT_AVAILABLE = True
    except ImportError:
        WINDOWS_PRINT_AVAILABLE = False
        print("⚠️ win32print no disponible. Impresión en Windows deshabilitada.")
else:
    WINDOWS_PRINT_AVAILABLE = False

def get_impresoras_disponibles():
    """ Retorna la lista de nombres de impresoras instaladas en el sistema """
    sistema = platform.system()
    try:
        if sistema == 'Windows' and WINDOWS_PRINT_AVAILABLE:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            # Nivel 2: cada impresora es un diccionario con "pPrinterName" (el nivel 1 por defecto devuelve tuplas).
            return [printer["pPrinterName"] for printer in win32print.EnumPrinters(flags, None, 2)]
        elif sistema in ('Linux', 'Darwin'):
            import subprocess
            resultado = subprocess.run(['lpstat', '-p'], capture_output=True, text=True)
            return [linea.split()[1] for linea in resultado.stdout.splitlines() if linea.startswith('printer ')]
    except Exception as e:
        print(f"⚠️ No se pudo obtener la lista de impresoras: {e}")
    return []


class PrinterZebra():
    def __init__(self, printer_name):
        self.barcodes_to_impresion = []
        self.printer_name = printer_name
        self.platform = platform.system()
  
    def print_zpl(self):
        
        consolidado = "\n".join(self.barcodes_to_impresion)
        self.barcodes_to_impresion = []
        
        zpl_data = f"""
^XA
^CF0,18  ; Fuente más pequeña para el texto descriptivo

{consolidado}

^XZ
"""
        
        try:
            if self.platform == 'Windows' and WINDOWS_PRINT_AVAILABLE:
                self._print_windows(zpl_data)
            elif self.platform == 'Linux':
                self._print_linux(zpl_data)
            elif self.platform == 'Darwin':  # macOS
                self._print_macos(zpl_data)
            else:
                raise NotImplementedError(f"Impresión no implementada para {self.platform}")
        except Exception as e:
            print(f"❌ Error al imprimir: {e}")
            raise
    
    def _print_windows(self, zpl_data):
        """ Enviar código ZPL a la impresora Zebra en Windows """
        printer_handle = win32print.OpenPrinter(self.printer_name)
        try:
            printer_info = win32print.GetPrinter(printer_handle, 2)
            printer_job = win32print.StartDocPrinter(printer_handle, 1, ("Impresión ZPL", None, "RAW"))
            win32print.StartPagePrinter(printer_handle)
            win32print.WritePrinter(printer_handle, zpl_data.encode("utf-8"))
            win32print.EndPagePrinter(printer_handle)
            win32print.EndDocPrinter(printer_handle)
            print("✅ Código de barras enviado a la impresora (Windows).")
        finally:
            win32print.ClosePrinter(printer_handle)
    
    def _print_linux(self, zpl_data):
        """ Enviar código ZPL a la impresora Zebra en Linux """
        # En Linux, las impresoras Zebra suelen estar en /dev/usb/lpX o se acceden por CUPS
        # Opción 1: Usar lpr con CUPS
        import subprocess
        try:
            # Intentar imprimir usando lpr (CUPS)
            process = subprocess.Popen(
                ['lpr', '-P', self.printer_name, '-o', 'raw'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate(input=zpl_data.encode('utf-8'))
            
            if process.returncode == 0:
                print("✅ Código de barras enviado a la impresora (Linux/CUPS).")
            else:
                raise Exception(f"Error lpr: {stderr.decode('utf-8')}")
                
        except FileNotFoundError:
            # Si lpr no está disponible, intentar escribir directamente al dispositivo
            print("⚠️ lpr no encontrado, intentando acceso directo al dispositivo...")
            self._print_linux_direct(zpl_data)
    
    def _print_linux_direct(self, zpl_data):
        """ Enviar directamente al dispositivo USB en Linux """
        # Buscar dispositivos USB de impresora
        import os
        usb_devices = [f'/dev/usb/lp{i}' for i in range(4)] + [f'/dev/lp{i}' for i in range(4)]
        
        for device in usb_devices:
            if os.path.exists(device):
                try:
                    with open(device, 'wb') as printer:
                        printer.write(zpl_data.encode('utf-8'))
                    print(f"✅ Código de barras enviado a {device}.")
                    return
                except PermissionError:
                    print(f"⚠️ Sin permisos para escribir en {device}. Ejecute: sudo chmod 666 {device}")
                except Exception as e:
                    print(f"⚠️ Error al escribir en {device}: {e}")
        
        raise Exception("No se encontró ningún dispositivo de impresora USB disponible")
    
    def _print_macos(self, zpl_data):
        """ Enviar código ZPL a la impresora Zebra en macOS """
        import subprocess
        try:
            # En macOS también se usa CUPS con lpr
            process = subprocess.Popen(
                ['lpr', '-P', self.printer_name, '-o', 'raw'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate(input=zpl_data.encode('utf-8'))
            
            if process.returncode == 0:
                print("✅ Código de barras enviado a la impresora (macOS).")
            else:
                raise Exception(f"Error lpr: {stderr.decode('utf-8')}")
        except Exception as e:
            raise Exception(f"Error al imprimir en macOS: {e}")
        
    def agregar_barcode(self, producto:str, barcode:str):
        
        if len(self.barcodes_to_impresion) == 0:
            self.get_barcode_izquierda(producto, barcode)
        elif len(self.barcodes_to_impresion) == 1:
            self.get_barcode_centro(producto, barcode)
        else:
            self.get_barcode_derecha(producto, barcode)
 
    def create_data(self, zpl_data):
        
        for producto in zpl_data:
            for num in range(producto["cantidad"]):
                self.agregar_barcode(producto["producto"][:28], producto["codigo"])
                if len(self.barcodes_to_impresion) == 3:
                    self.print_zpl()
        if len(self.barcodes_to_impresion) > 0:
            self.print_zpl()
   

    @staticmethod
    def _digito_verificador_ean(digitos: str) -> int:
        """ Calcula el dígito verificador EAN/UPC para los dígitos sin el verificador """
        suma = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digitos)))
        return (10 - suma % 10) % 10

    @classmethod
    def _zpl_barcode(cls, barcode: str) -> str:
        """ Retorna el ZPL del código de barras eligiendo el formato que entra en la etiqueta.
            - LL...: Code 128 como siempre (formato propio de La Loba)
            - EAN-13 / UPC-A válidos: formato nativo, más angosto que Code 128
            - Otros: Code 128 automático; si es muy largo baja el grosor de barra a 1
        """
        barcode = str(barcode).strip()
        if barcode.startswith("LL"):
            return f"^BY2^BCN,50,Y,N,N^FD{barcode}^FS"

        if barcode.isdigit():
            if len(barcode) == 13 and cls._digito_verificador_ean(barcode[:12]) == int(barcode[12]):
                return f"^BY2^BEN,50,Y,N^FD{barcode[:12]}^FS"
            if len(barcode) == 12 and cls._digito_verificador_ean(barcode[:11]) == int(barcode[11]):
                return f"^BY2^BUN,50,Y,N,Y^FD{barcode[:11]}^FS"

        # Estimación conservadora del ancho en Code 128 (subset B: 11 módulos por carácter
        # + inicio, verificador y fin). Ancho útil de la etiqueta ~240 puntos.
        modulos = 35 + 11 * len(barcode)
        grosor = 2 if modulos * 2 <= 240 else 1
        return f"^BY{grosor}^BCN,50,Y,N,N,A^FD{barcode}^FS"

    def get_barcode_izquierda(self, producto: str, barcode: str):
        self.barcodes_to_impresion.append(f"""
                ^FO30,10{self._zpl_barcode(barcode)}
                ^FO40,85^A0N,14,14^FD{producto}^FS""")

    def get_barcode_centro(self, producto: str, barcode: str):
        self.barcodes_to_impresion.append(f"""
                ^FO295,10{self._zpl_barcode(barcode)}
                ^FO305,85^A0N,14,14^FD{producto}^FS""")

    def get_barcode_derecha(self, producto: str, barcode: str):
        self.barcodes_to_impresion.append(f"""
                ^FO560,10{self._zpl_barcode(barcode)}
                ^FO570,85^A0N,14,14^FD{producto}^FS""")