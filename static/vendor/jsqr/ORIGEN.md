# jsQR vendoreado (Fiesta, app del sindicato)

Lo usa la puerta de `/fiesta/sindicato` (`PLAN_FIESTA.md`) para leer el QR de
la entrada con la cámara cuando el navegador no trae `BarcodeDetector`. Va
vendoreado como el resto: la CSP no deja cargar nada de un CDN.

| Paquete | Versión | Licencia | Origen |
|---|---|---|---|
| jsQR | 1.4.0 | Apache-2.0 (`LICENSE`; el paquete de npm la declara así) | https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js |

Bajado el 2026-11-12 sin tocar un byte (`LICENSE` desde
https://cdn.jsdelivr.net/npm/jsqr@1.4.0/LICENSE). Es un bundle UMD: cargado con
un `<script>` común deja `window.jsQR`. `test_fiesta_pantallas.py` compara
los SHA-256 de abajo contra la carpeta.

```
bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859  jsQR.js
c6596eb7be8581c18be736c846fb9173b69eccf6ef94c5135893ec56bd92ba08  LICENSE
```
