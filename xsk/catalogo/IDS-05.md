---
id: IDS-05
eje: IDS
titulo: El hash de claves debe estar al día (iteraciones, algoritmo)
tipo: revision
herramienta: security-review (Code)
entorno: pruebas
destructivo: no
owasp: A02:2021
asvs: V2.4.1
cwe: CWE-916
activo: V6
---

## Objetivo

Confirmar que `auth.hashear_clave` usa un algoritmo y un costo vigentes.
Hoy: PBKDF2-HMAC-SHA256, 100.000 iteraciones (O17); OWASP 2023 pide 600.000
para PBKDF2-SHA256.

## Cómo se corre

1. Leer `auth.hashear_clave` / `verificar_clave`.
2. Comparar iteraciones y algoritmo contra la guía OWASP vigente.
3. Ver si el formato guardado permite subir el costo sin romper las claves
   existentes (rehash al próximo login).

## Resultado esperado

`paso` si el costo está dentro de la guía vigente y hay camino de migración.
Costo bajo = hallazgo de complejidad baja (subir la constante + rehash
diferido).

## Notas

Bajo riesgo (requiere ya tener el hash robado), pero corrección barata.
