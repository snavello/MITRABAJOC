---
id: IDS-02
eje: IDS
titulo: Las cookies de sesión deben ser robustas (Secure, SameSite, firma, expiración)
tipo: revision
herramienta: security-review + httpx (inspección de cabeceras)
entorno: pruebas
destructivo: no
owasp: A05:2021
asvs: V3.4.1
cwe: CWE-614
activo: V6
---

## Objetivo

Que las cookies no se puedan robar en tránsito ni forjar: `Secure`,
`SameSite` explícito, `HttpOnly`, firma HMAC de largo completo y expiración
sensata. Cubre O8 (sin `Secure`), O17 (HMAC truncada a 128 bits) y O20
(sin revocación).

## Cómo se corre

1. Revisar las 20 llamadas a `set_cookie` (`mapa.md` §2): confirmar flags.
2. Pedir cada login por HTTPS en Pruebas y leer el `Set-Cookie` real.
3. Revisar `auth.py`: largo de la firma, algoritmo, expiración, y si existe
   forma de revocar una sesión (logout real, cambio de clave).

## Resultado esperado

`paso` si todas las cookies salen con `Secure`, `HttpOnly`, `SameSite`
explícito y firma de largo completo. Falta de `Secure` o de revocación abre
hallazgo.

## Notas

`Secure` solo se puede confirmar sobre HTTPS; en local (HTTP) se verifica
por código. Ligado a INF-05 (HSTS en el perímetro).
