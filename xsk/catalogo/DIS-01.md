---
id: DIS-01
eje: DIS
titulo: Las rutas caras deben tener rate limit y tope de tamaño
tipo: dinamico
herramienta: httpx desde Code (MOCK_EXTRACTOR=1)
entorno: pruebas
destructivo: si
owasp: A04:2021
asvs: V12.1.1
cwe: CWE-770
activo: V4
---

## Objetivo

Que no se pueda gastar la IA ni tumbar el web con pocas requests. Cubre O11
(`/api/leer`, `/api/aportes` sin auth real, sin tope ni rate limit) y O12
(`_leer_logo` sin tope de tamaño).

## Cómo se corre

1. Con `MOCK_EXTRACTOR=1` en Pruebas, mandar muchas requests a `/api/leer`
   sin sesión real y ver si hay freno.
2. Subir un archivo muy grande a `/api/leer`, `/plataforma/marca`,
   `/recursos` y medir si se rechaza por tamaño antes de cargarlo entero en
   memoria.
3. Medir el efecto en CPU/memoria de Pruebas (mapa: medio núcleo, 512 MB).

## Resultado esperado

`paso` si hay rate limit y tope de tamaño temprano. Sin freno, hallazgo
(cruza con IA: gasto de créditos).

## Notas

`destructivo: si`: carga real. Solo Pruebas, con `MOCK_EXTRACTOR=1` para no
gastar créditos. Coordinar con la observabilidad para no disparar alertas.
