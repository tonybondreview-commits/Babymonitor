"""Generazione del QR code (per aprire l'app su un altro dispositivo).

Genera l'SVG del QR (per la webapp) e una versione ASCII (per il terminale).
La libreria `qrcode` e' facoltativa: se manca, HAS_QR e' False e l'app mostra
solo l'indirizzo in chiaro.
"""

from __future__ import annotations

try:
    import qrcode
    HAS_QR = True
except ImportError:  # pragma: no cover
    HAS_QR = False


def _matrix(data: str):
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.get_matrix()


def svg(data: str, scale: int = 8) -> str:
    """Ritorna il QR come SVG (sfondo bianco, moduli neri)."""
    m = _matrix(data)
    n = len(m)
    size = n * scale
    rects = []
    for y, row in enumerate(m):
        for x, cell in enumerate(row):
            if cell:
                rects.append(f'<rect x="{x * scale}" y="{y * scale}" width="{scale}" height="{scale}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<g fill="#000000">{"".join(rects)}</g></svg>'
    )


def ascii_qr(data: str) -> str:
    """Ritorna il QR come testo (per stamparlo nel terminale di Termux)."""
    m = _matrix(data)
    lines = []
    for row in m:
        lines.append("".join("██" if cell else "  " for cell in row))
    return "\n".join(lines)
