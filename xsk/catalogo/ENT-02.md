---
id: ENT-02
eje: ENT
titulo: Un archivo subido no debe ejecutarse como HTML/script al servirse
tipo: dinamico
herramienta: httpx desde Code
entorno: pruebas
destructivo: no
owasp: A03:2021
asvs: V12.5.1
cwe: CWE-79
activo: V5, V6, V1
---

## Objetivo

Que un SVG o HTML subido no ejecute script en el origen de la app. Cubre O5
(SVG en logos/noticias/beneficios servido inline, público, sin CSP) y O6
(`/recursos` sirve HTML como `text/html` inline tras el PIN).

## Cómo se corre

1. Como admin de sindicato, subir un SVG con `<script>` como logo; abrir
   `/logo/{id}` y ver si ejecuta.
2. Subir HTML a `/recursos` y abrirlo.
3. Verificar el efecto de ENT-01 (CSP + nosniff + Content-Disposition) sobre
   estos casos.

## Resultado esperado

`paso` si el archivo no ejecuta (allow-list de tipo, `nosniff`,
Content-Disposition, CSP). Ejecución = hallazgo (XSS almacenado, cruza tenants).

## Notas

Iteración 2. ENT-01 (cabeceras) es la contención de fondo; la corrección
completa es allow-list + servir como adjunto.
