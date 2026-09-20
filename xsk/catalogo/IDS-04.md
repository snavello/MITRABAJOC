---
id: IDS-04
eje: IDS
titulo: El alta de cuenta debe acreditar identidad según el nivel de fiabilidad
tipo: revision
herramienta: security-review + lectura dirigida (Code)
entorno: pruebas
destructivo: no
owasp: A07:2021
asvs: V2.1.1
cwe: CWE-640
activo: V6, V1, V7
---

## Objetivo

Registrar el gap contra R2: hoy `/trabajador/registro` y `/empresa/registro`
crean la cuenta con solo el CUIL/CUIT (dato público) en el padrón (nivel 1).
Falta el modelo de niveles 1–4 y que lo que la app muestra dependa del nivel.

## Cómo se corre

1. Revisar ambas rutas de registro y qué exigen.
2. Confirmar que no hay confirmación por mail (R3) ni proveedor de mail.
3. Documentar qué datos ve una cuenta recién registrada nivel 1 (recibos
   propios no, pero sí notificaciones dirigidas, trámites, credencial).

## Resultado esperado

Estado actual = hallazgo (decisión R2). El test deja la nota: **el diseño de
niveles conviene antes del primer sindicato**, la implementación puede ir
después.

## Notas

Ligado a la recuperación de clave por mail (R3), que también falta.
