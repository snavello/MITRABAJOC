---
id: IDS-03
eje: IDS
titulo: La cuenta de plataforma debe ser nominal, con clave hasheada y trazabilidad
tipo: revision
herramienta: security-review + lectura dirigida (Code)
entorno: pruebas
destructivo: no
owasp: A07:2021
asvs: V2.1.1
cwe: CWE-522
activo: V8, V6, V2
---

## Objetivo

Verificar el estado frente a la decisión R1: hoy `/plataforma` es una cuenta
compartida, con la clave comparada en claro contra `PLATAFORMA_PASSWORD`
(O3), sin registro de quién hizo qué. En producción tiene que ser usuarios
nominales con clave hasheada y bitácora.

## Cómo se corre

1. Revisar `auth.verificar_plataforma` y el login de plataforma.
2. Confirmar que no hay tabla de usuarios de plataforma ni registro de
   acciones (más allá de `AccesoLog` por rol).
3. Revisar `/plataforma/reset-clave` (O13): fija la clave de cualquiera sin
   la anterior; `debe_cambiar_clave` no se aplica.

## Resultado esperado

Estado actual = hallazgo (es funcionalidad nueva, R1). El test documenta el
gap contra R1 y sirve de criterio de verificación cuando se implemente.

## Notas

La implementación de R1 es de la iteración 2 o un sprint propio; el hallazgo
nace acá con dueño y con la nota de que bloquea producción real con
plataforma operada por más de una persona.
