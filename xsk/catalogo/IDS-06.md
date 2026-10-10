---
id: IDS-06
eje: IDS
titulo: ¿El CUIL/CUIT que nace en el sistema cumple el dígito verificador (módulo 11)?
tipo: revision
herramienta: lectura dirigida + suite (Code)
entorno: codigo
destructivo: no
owasp: A03:2021
asvs: V5.1.3
cwe: CWE-20
activo: V6, V1, V7
---

## Objetivo

El CUIL/CUIT es la identidad de la persona y de la empresa en todo el
sistema, y entre tablas se une por texto. Un número que no cumple el dígito
verificador no es de nadie: es un tipeo o un dato inventado. Si entra por un
alta, dos personas pueden terminar con el mismo número corregido (y
fusionadas), un afiliado se registra con un CUIL que no es el suyo, y el
sindicato pierde la única llave que tiene para cruzar padrón, recibos y
trámites.

## Cómo se corre

1. Inventariar las puertas por donde NACE un número (altas del panel, carga
   masiva, registro de afiliado y de empresa, alta de sindicato y de su
   primer admin, datos del usuario de plataforma) y las que solo lo
   REFERENCIAN (logins, filtros, criterios de notificación).
2. Verificar que cada puerta de alta rechaza un número con verificador
   inválido sin escribir nada, y acepta uno válido.
3. Verificar que hay una sola implementación del cálculo.
4. Contar en cada base cuántos números inválidos quedan y de qué origen.

## Resultado esperado

`paso`: toda puerta de alta exige el verificador, hay una sola
implementación, y en las bases no quedan números inválidos cargados a mano
(los sintéticos de los lotes pueden quedar, identificados por su regla).
Una puerta que acepta un inválido, o datos manuales inválidos en una base,
abren o mantienen un hallazgo.

## Notas

No prueba que el número sea DE esa persona (eso es IDS-04, niveles de
fiabilidad del registro): un CUIL válido ajeno pasa este test.
