---
id: AUT-03
eje: AUT
titulo: Un sindicato no debe poder leer ni tocar datos de otro (aislamiento multi-tenant)
tipo: dinamico
herramienta: httpx desde Code
entorno: pruebas
destructivo: no
owasp: A01:2021
asvs: V4.2.1
cwe: CWE-639
activo: V5, V3
---

## Objetivo

Que el `sindicato_id` salga siempre de la sesión y nunca de un parámetro, y
que ningún recurso identificado por id (noticia, beneficio, trámite,
adjunto, logo) cruce el límite del sindicato.

## Cómo se corre

1. Login como admin del sindicato X (UOM). Login como admin de Y (Gastronómica).
2. Con la sesión de X, pedir recursos por id que pertenezcan a Y:
   `/noticia-imagen/{id de Y}`, `/tramite-nota-adjunto/{id de Y}`, detalle
   de recibo/trámite de Y, exportaciones apuntando a Y.
3. Enumerar ids en las rutas públicas (`/noticia-imagen`, `/beneficio-imagen`)
   y ver si devuelven contenido de cualquier sindicato.
4. Como trabajador pluriempleo, `/app/elegir/{sindicato_id}` de un sindicato
   donde el CUIL no está empadronado.
5. Revisar en `dashboard.py` que cada agregado filtre por `sindicato_id` en
   el WHERE y no después.

## Resultado esperado

`paso` si todo cruce da 403/404 y los agregados filtran en la consulta.
Cualquier dato de Y visible desde X abre hallazgo.

## Notas

`/api/entornos/actividad` (público, agregados por sindicato) se prueba
aparte en DIS-04/AUT-04: acá el foco es la sesión de admin.
