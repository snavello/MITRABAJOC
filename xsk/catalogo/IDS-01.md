---
id: IDS-01
eje: IDS
titulo: Los cuatro logins deben resistir la fuerza bruta y el credential stuffing
tipo: dinamico
herramienta: httpx desde Code
entorno: pruebas
destructivo: si
owasp: A07:2021
asvs: V2.2.1
cwe: CWE-307
activo: V6, V3
---

## Objetivo

Que probar miles de claves contra `/admin/login`, `/plataforma/login`,
`/trabajador/login` y `/empresa/login` se frene (O9: hoy no hay límite de
intentos en ninguno).

## Cómo se corre

1. Contra Pruebas, lanzar N intentos fallidos seguidos contra cada login
   desde la misma IP y medir si en algún punto se frena (429, espera,
   captcha).
2. Probar el bloqueo por cuenta vs. por IP (una cuenta atacada desde muchas
   IPs; muchas cuentas desde una IP).
3. Verificar que un bloqueo no permita negarle el acceso a un usuario
   legítimo (no bloquear la cuenta, sí ralentizar el origen).

## Resultado esperado

`paso` si hay un freno efectivo (rate limit por IP + backoff) que no se
pueda saltar rotando el `X-Forwarded-For`. Sin freno, hallazgo.

## Notas

`destructivo: si`: genera muchos intentos y puede dejar registros. Solo
Pruebas. Ojo con el freno por `X-Forwarded-For` (el del PIN se saltea
rotando esa cabecera; ver O9 y el rate limit del PIN en `mapa.md` §2).
