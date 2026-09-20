---
id: INF-05
eje: INF
titulo: Debe haber un perímetro delante del dominio (TLS, HSTS, WAF, anti-DDoS)
tipo: configuracion
herramienta: API de Cloudflare + sslyze/curl
entorno: demo
destructivo: no
owasp: A05:2021
asvs: V1.9.1
cwe: CWE-693
activo: V4, V1, V3
---

## Objetivo

Que el dominio propio tenga TLS al día, HSTS, y un perímetro (Cloudflare)
que aporte rate limiting y absorción de DDoS —lo que Code no puede probar y
por eso se delega y se verifica (regla 5 de METODO.md)—. Cubre la ausencia
de perímetro y de HSTS (O7).

## Cómo se corre

1. Cuando exista el dominio y Cloudflare: verificar por API que estén las
   reglas (rate limit, challenge, bloqueo geográfico si aplica) y que la IP
   de Render no sea alcanzable directo.
2. `curl -I` / sslyze contra el dominio: HSTS, versión de TLS, cabeceras.
3. Confirmar que `/healthz` sigue accesible para el health check de Render.

## Resultado esperado

`paso` si el perímetro está y las reglas disparan. Sin dominio/Cloudflare
todavía: `no_aplica` con la nota "pendiente de infra (configuracion.md)".

## Notas

No se prueba resistencia a un DDoS real: se verifica que la defensa exista.
