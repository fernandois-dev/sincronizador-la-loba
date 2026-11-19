


# Genera un reporte en formato PDF # con los datos de la tabla base filtrados por codigo de barras

#         ReportGenerator.download_pdf(report)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import cm
from barcode import Code128
from barcode.writer import ImageWriter
# from tkinter import Tk, filedialog
import os
import flet as ft




from utilities.flet_compat import abrir_dialogo, guardar_archivo
def generar_reporte_a4(page, nombre_hoja, products):
    def on_save_file_result(e: ft.FilePickerResultEvent):
        
        file_path = e.path
        if not file_path:
            abrir_dialogo(page, ft.SnackBar(ft.Text("Guardado cancelado")))
            return

        c = canvas.Canvas(file_path, pagesize=A4)
        width, height = A4

        x_offset = 50
        y_offset = height - 50
        col_width = (width - 2 * x_offset) / 3
        hoja_numero = 1
        
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(width / 2, height - 30, "{} - Página {}".format(nombre_hoja, hoja_numero))

        for i, item in enumerate(products):
            try:
                if i % 3 == 0 and i != 0:
                    y_offset -= 70
                    x_offset = 50
                    

                if y_offset < 100:
                    hoja_numero += 1
                    
                    c.showPage()
                    # Volver a dibujar el título en la nueva página
                    c.setFont("Helvetica-Bold", 11)
                    c.drawCentredString(width / 2, height - 30, "{} - Página {}".format(nombre_hoja, hoja_numero))
                    
                    y_offset = height - 50

                barcode = Code128(item.get("CODIGO BARRAS", ""), writer=ImageWriter())
                barcode_path = f"barcode_{i}"
                barcode.save(barcode_path)

                c.setFont("Helvetica-Bold", 9)
                c.drawString(x_offset, y_offset, item.get("PRODUCTO", "")[:28])
                c.drawImage(f"{barcode_path}.png", x_offset, y_offset - 51, width=120, height=50)

                os.remove(f"{barcode_path}.png")
                x_offset += col_width
            except Exception as e:
                print(f"Error al procesar el producto {item.get('PRODUCTO', '')}: {e}")
                continue
            
        try:
            c.save()
            return "PDF guardado correctamente en: {}".format(file_path)
        except Exception as e:
            return f"Error al guardar el PDF: {e}"
    
    guardar_archivo(page, on_save_file_result, file_name=f"{nombre_hoja}.pdf", file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"])


def generar_reporte_compras_pdf(page, products_selected):
    from datetime import datetime
    import os

    def on_save_file_result(e: ft.FilePickerResultEvent):
        file_path = e.path
        if not file_path:
            return

        try:
            # Agrupar por proveedor
            grupos = {}
            for p in products_selected:
                prov = p.get("proveedor", "Sin Proveedor")
                if prov not in grupos:
                    grupos[prov] = []
                grupos[prov].append(p)

            # Usar SimpleDocTemplate para un reporte profesional
            doc = SimpleDocTemplate(
                file_path, 
                pagesize=A4, 
                rightMargin=2*cm, 
                leftMargin=2*cm, 
                topMargin=2*cm, 
                bottomMargin=2*cm
            )
            elements = []
            styles = getSampleStyleSheet()
            
            # Título
            title_style = ParagraphStyle(
                'TitleStyle',
                parent=styles['Heading1'],
                fontSize=18,
                alignment=1, # Center
                spaceAfter=20
            )
            elements.append(Paragraph("Orden de Compra", title_style))
            elements.append(Paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
            elements.append(Spacer(1, 12))

            total_general = 0

            # Estilo de tabla
            table_style = TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('ALIGN', (0, 1), (0, -1), 'LEFT'), # Producto alineado a la izquierda
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ])

            for proveedor, productos in grupos.items():
                elements.append(Paragraph(f"Proveedor: {proveedor}", styles['Heading2']))
                
                # Datos de la tabla
                data = [["Producto", "Cant. Comprar", "Precio Compra", "Subtotal"]]
                subtotal_proveedor = 0
                
                for p in productos:
                    stock = float(p.get("stock", 0))
                    stock_max = float(p.get("stock_max", 0))
                    cant_comprar = max(0, stock_max - stock)
                    precio = float(p.get("precio_compra", 0))
                    subtotal = cant_comprar * precio
                    subtotal_proveedor += subtotal
                    
                    # Formato chileno: puntos para miles, sin decimales
                    precio_fmt = f"${precio:,.0f}".replace(",", ".")
                    subtotal_fmt = f"${subtotal:,.0f}".replace(",", ".")
                    
                    data.append([
                        p.get("producto", "")[:50],
                        f"{cant_comprar:.0f}",
                        precio_fmt,
                        subtotal_fmt
                    ])

                total_general += subtotal_proveedor
                
                # Crear tabla
                t = Table(data, colWidths=[8*cm, 3*cm, 3*cm, 3*cm])
                t.setStyle(table_style)
                elements.append(t)
                
                # Subtotal por proveedor
                subtotal_prov_fmt = f"${subtotal_proveedor:,.0f}".replace(",", ".")
                elements.append(Spacer(1, 6))
                elements.append(Paragraph(f"Subtotal {proveedor}: <b>{subtotal_prov_fmt}</b>", styles['Normal']))
                elements.append(Spacer(1, 12))

            # Total General
            total_gen_fmt = f"${total_general:,.0f}".replace(",", ".")
            elements.append(Spacer(1, 12))
            total_style = ParagraphStyle(
                'TotalStyle',
                parent=styles['Normal'],
                fontSize=14,
                alignment=2, # Right
                spaceBefore=20
            )
            elements.append(Paragraph(f"TOTAL GENERAL: <b>{total_gen_fmt}</b>", total_style))
            
            doc.build(elements)
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"PDF generado exitosamente"), bgcolor=ft.Colors.GREEN_700))
            
        except Exception as ex:
            print(f"Error generando PDF: {ex}")
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Error generando PDF: {str(ex)}"), bgcolor=ft.Colors.RED_700))

    guardar_archivo(page, on_save_file_result, 
        file_name=f"orden_compra_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf", 
        file_type=ft.FilePickerFileType.CUSTOM, 
        allowed_extensions=["pdf"]
    )