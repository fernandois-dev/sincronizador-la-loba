"""
Generador del reporte de Bajo Stock semanal.

Consulta productos favoritos con riesgo CRITICO o SOLICITAR,
los agrupa por proveedor y produce el HTML del correo.
"""
from datetime import datetime


def _clp(valor) -> str:
    try:
        v = int(round(float(valor)))
    except (TypeError, ValueError):
        v = 0
    return "$" + f"{v:,}".replace(",", ".")


def obtener_datos_bajo_stock() -> dict[str, list]:
    """
    Retorna productos favoritos con riesgo CRITICO o SOLICITAR
    agrupados por nombre de proveedor.

    Estructura de cada producto:
        {id, producto, stock, stock_min, stock_max,
         cantidad_sugerida, precio_compra, subtotal,
         proveedor, riesgo}
    """
    from django.db import connection

    def _dictfetchall(cursor):
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                p.id,
                p.name                                      AS producto,
                p.qty_available                             AS stock,
                so.product_min_qty                          AS stock_min,
                so.product_max_qty                          AS stock_max,
                CASE WHEN so.product_max_qty > p.qty_available
                     THEN so.product_max_qty - p.qty_available
                     ELSE 0 END                             AS cantidad_sugerida,
                COALESCE(t.price, 0)                        AS precio_compra,
                (CASE WHEN so.product_max_qty > p.qty_available
                      THEN so.product_max_qty - p.qty_available
                      ELSE 0 END)
                    * COALESCE(t.price, 0)                  AS subtotal,
                COALESCE(t.partner, 'Sin Proveedor')        AS proveedor,
                CASE
                    WHEN p.qty_available < so.product_min_qty            THEN 'CRITICO'
                    WHEN p.qty_available <= so.product_min_qty * 1.2     THEN 'SOLICITAR'
                END AS riesgo
            FROM servidor_odooproducto p
            JOIN servidor_odooruta so
                ON so.product = CONCAT('[', p.default_code, '] ', p.name)
            LEFT JOIN servidor_odootarifa t
                ON t.product_tmpl_id = p.id
            WHERE p.favorito = 1
              AND p.activo   = 1
              AND (
                  p.qty_available < so.product_min_qty
                  OR p.qty_available <= so.product_min_qty * 1.2
              )
            ORDER BY
                COALESCE(t.partner, 'Sin Proveedor'),
                CASE WHEN p.qty_available < so.product_min_qty THEN 0 ELSE 1 END,
                p.qty_available
        """)
        rows = _dictfetchall(cursor)

    agrupado: dict[str, list] = {}
    for r in rows:
        prov = r["proveedor"] or "Sin Proveedor"
        agrupado.setdefault(prov, []).append(r)
    return agrupado


def _badge(riesgo: str) -> str:
    if riesgo == "CRITICO":
        return (
            '<span style="background:#dc2626;color:#fff;padding:2px 8px;'
            'border-radius:12px;font-size:11px;font-weight:700;">⚠ CRÍTICO</span>'
        )
    return (
        '<span style="background:#d97706;color:#fff;padding:2px 8px;'
        'border-radius:12px;font-size:11px;font-weight:700;">↑ SOLICITAR</span>'
    )


def generar_html(agrupado: dict[str, list]) -> str:
    """Genera el HTML completo del correo de bajo stock."""
    total_criticos  = 0
    total_solicitar = 0
    for productos in agrupado.values():
        for p in productos:
            if p["riesgo"] == "CRITICO":
                total_criticos += 1
            else:
                total_solicitar += 1

    fecha_str = datetime.now().strftime("%A %d de %B de %Y").capitalize()

    # ── Secciones por proveedor ────────────────────────────────────────────────
    secciones_html = ""
    for proveedor, productos in agrupado.items():
        subtotal_prov = sum(float(p.get("subtotal", 0) or 0) for p in productos)
        filas = ""
        for p in productos:
            fila_bg = "#fff1f1" if p["riesgo"] == "CRITICO" else "#fffbeb"
            filas += f"""
            <tr style="background:{fila_bg};">
                <td style="padding:10px 14px;border-bottom:1px solid #e5e7eb;font-size:13px;max-width:280px;">{p['producto']}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #e5e7eb;text-align:center;">{_badge(p['riesgo'])}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #e5e7eb;text-align:right;font-weight:700;color:#dc2626;">{int(p['stock'])}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #e5e7eb;text-align:right;color:#6b7280;">{int(p['stock_min'])} / {int(p['stock_max'])}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #e5e7eb;text-align:right;color:#1d4ed8;font-weight:600;">{int(p['cantidad_sugerida'])}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #e5e7eb;text-align:right;color:#374151;">{_clp(p['precio_compra'])}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #e5e7eb;text-align:right;font-weight:700;color:#059669;">{_clp(p['subtotal'])}</td>
            </tr>"""

        secciones_html += f"""
        <div style="margin-bottom:32px;">
            <div style="background:linear-gradient(90deg,#1e40af,#3b82f6);border-radius:8px 8px 0 0;
                        padding:12px 18px;display:flex;justify-content:space-between;align-items:center;">
                <span style="color:#fff;font-size:15px;font-weight:700;">🏪 {proveedor}</span>
                <span style="background:rgba(255,255,255,0.2);color:#fff;
                             padding:4px 12px;border-radius:20px;font-size:13px;">
                    Subtotal compra sugerida: <strong>{_clp(subtotal_prov)}</strong>
                </span>
            </div>
            <table style="width:100%;border-collapse:collapse;background:#fff;
                          border-radius:0 0 8px 8px;overflow:hidden;
                          box-shadow:0 2px 8px rgba(0,0,0,0.07);">
                <thead>
                    <tr style="background:#f0f9ff;">
                        <th style="padding:10px 14px;text-align:left;font-size:12px;color:#374151;border-bottom:2px solid #bfdbfe;">Producto</th>
                        <th style="padding:10px 14px;text-align:center;font-size:12px;color:#374151;border-bottom:2px solid #bfdbfe;">Estado</th>
                        <th style="padding:10px 14px;text-align:right;font-size:12px;color:#374151;border-bottom:2px solid #bfdbfe;">Stock actual</th>
                        <th style="padding:10px 14px;text-align:right;font-size:12px;color:#374151;border-bottom:2px solid #bfdbfe;">Mín / Máx</th>
                        <th style="padding:10px 14px;text-align:right;font-size:12px;color:#374151;border-bottom:2px solid #bfdbfe;">A comprar</th>
                        <th style="padding:10px 14px;text-align:right;font-size:12px;color:#374151;border-bottom:2px solid #bfdbfe;">P. compra</th>
                        <th style="padding:10px 14px;text-align:right;font-size:12px;color:#374151;border-bottom:2px solid #bfdbfe;">Subtotal</th>
                    </tr>
                </thead>
                <tbody>{filas}</tbody>
            </table>
        </div>"""

    if not secciones_html:
        secciones_html = """
        <div style="text-align:center;padding:48px;color:#6b7280;font-size:15px;">
            ✅ Todos los productos favoritos tienen stock suficiente esta semana.
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:'Segoe UI',Arial,sans-serif;">

<div style="max-width:860px;margin:32px auto;background:#f3f4f6;">

    <!-- HEADER -->
    <div style="background:linear-gradient(135deg,#dc2626 0%,#ea580c 50%,#f59e0b 100%);
                border-radius:12px 12px 0 0;padding:16px 24px;">
        <table style="width:100%;border-collapse:collapse;">
            <tr>
                <td style="vertical-align:middle;">
                    <span style="font-size:20px;">⭐</span>
                    <span style="color:#fff;font-size:18px;font-weight:800;margin-left:8px;vertical-align:middle;">
                        Reporte Semanal — Stock Bajo Favoritos
                    </span>
                    <span style="color:rgba(255,255,255,0.75);font-size:12px;margin-left:12px;vertical-align:middle;">
                        Gestor La Loba
                    </span>
                </td>
                <td style="text-align:right;vertical-align:middle;">
                    <span style="background:rgba(255,255,255,0.2);color:#fff;
                                 padding:4px 14px;border-radius:20px;font-size:12px;">
                        ⚠ <strong>{total_criticos}</strong> críticos &nbsp;·&nbsp;
                        ↑ <strong>{total_solicitar}</strong> por solicitar &nbsp;·&nbsp;
                        {fecha_str}
                    </span>
                </td>
            </tr>
        </table>
    </div>

    <!-- CONTENIDO -->
    <div style="padding:28px 0;">
        {secciones_html}
    </div>

    <!-- FOOTER -->
    <div style="background:#1f2937;border-radius:0 0 12px 12px;
                padding:20px 32px;text-align:center;">
        <p style="margin:0;color:#9ca3af;font-size:12px;">
            Generado automáticamente por <strong style="color:#fff;">Gestor La Loba</strong>
            &nbsp;·&nbsp; {datetime.now().strftime('%d/%m/%Y %H:%M')}
        </p>
        <p style="margin:6px 0 0;color:#6b7280;font-size:11px;">
            La cantidad sugerida = Stock Máximo − Stock Actual
        </p>
    </div>

</div>
</body>
</html>"""
