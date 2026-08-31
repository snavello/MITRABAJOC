# -*- coding: utf-8 -*-
"""Acomodar las ventanas del navegador cuando se corre con --headed (Windows).

Por qué existe: con --headed, Chromium abre su ventana DETRÁS de las demás y
`page.bring_to_front()` no alcanza — Windows impide que un proceso le robe el
primer plano a otro (ForegroundLockTimeout), así que el robot corría invisible.

La salida es no pelear por el foco: se marca la ventana como TOPMOST (siempre
encima, no requiere permisos de primer plano) y se la ubica en una posición
fija. Con dos actores, cada uno ocupa media pantalla y se ve el ida y vuelta
completo sin tocar nada.

Todo es best-effort: en Linux/Mac o si algo falla, no hace nada y el robot
sigue corriendo igual.
"""
import sys
import time

ES_WINDOWS = sys.platform == "win32"

if ES_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    HWND_TOPMOST = wintypes.HWND(-1)
    SWP_SHOWWINDOW = 0x0040
    SW_RESTORE = 9
    TITULO = "Chrome for Testing"


def _titulo(hwnd) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def ventanas_del_navegador() -> set:
    """Handles de las ventanas de Chromium lanzadas por Playwright."""
    if not ES_WINDOWS:
        return set()
    encontradas = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cada_ventana(hwnd, _):
        if user32.IsWindowVisible(hwnd) and TITULO in _titulo(hwnd):
            encontradas.add(hwnd)
        return True

    try:
        user32.EnumWindows(cada_ventana, 0)
    except Exception:
        pass
    return encontradas


def esperar_ventana_nueva(previas: set, timeout: float = 5.0):
    """El handle de la ventana que apareció después de `previas` (o None).
    La ventana tarda un instante en existir después de new_page()."""
    if not ES_WINDOWS:
        return None
    limite = time.time() + timeout
    while time.time() < limite:
        nuevas = ventanas_del_navegador() - previas
        if nuevas:
            return nuevas.pop()
        time.sleep(0.15)
    return None


def acomodar(hwnd, indice: int, total: int = 2) -> bool:
    """Coloca la ventana en su franja de pantalla y la deja SIEMPRE ENCIMA.
    `indice` es el orden del actor (0 = izquierda, 1 = derecha)."""
    if not ES_WINDOWS or not hwnd:
        return False
    try:
        ancho_pantalla = user32.GetSystemMetrics(0)
        alto_pantalla = user32.GetSystemMetrics(1)
        ancho = max(760, ancho_pantalla // max(1, total))
        alto = int(alto_pantalla * 0.92)
        x = min(indice * ancho, max(0, ancho_pantalla - ancho))
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, x, 0, ancho, alto, SWP_SHOWWINDOW)
        return True
    except Exception:
        return False
