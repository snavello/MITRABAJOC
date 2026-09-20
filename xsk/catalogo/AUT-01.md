---
id: AUT-01
eje: AUT
titulo: La identidad del usuario no debe viajar en un dato que el cliente pueda cambiar
tipo: revision
herramienta: security-review + lectura dirigida (Code)
entorno: pruebas
destructivo: no
owasp: A01:2021
asvs: V4.1.1
cwe: CWE-639
activo: V6 (identidad), V1 (recibos), V7 (trámites)
---

## Objetivo

Que quién es el usuario se decida por un dato que el servidor firmó, no por
uno que el navegador manda en claro. Cubre O2: `cuil_trab` y `cuit_emp` son
cookies sin HMAC y ninguna ruta las cruza contra el `uid` de la sesión.

## Cómo se corre

1. Revisar `auth.py` (creación de cookies de identidad) y cada uso de
   `request.cookies.get("cuil_trab")` / `"cuit_emp"` en `main.py`.
2. Confirmar contra el mapa (`mapa.md` §1.2) las 8 rutas que se autentican
   solo con la cookie plana y las ~28 que validan sesión pero no cruzan `uid`.
3. Marcar por cada una si el dato de identidad se puede cambiar del lado del
   cliente sin invalidar la sesión.

## Resultado esperado

`paso` si la identidad sale siempre de la sesión firmada (o de un dato
firmado ligado a ella). Cualquier ruta que lea la identidad de una cookie
plana abre hallazgo. Se confirma dinámicamente con AUT-02.

## Notas

Es el hallazgo que el mapa marcó como más grave. La corrección
(firmar/ligar la identidad a la sesión) cambia cómo se corren AUT-02 y los
tests de IDS, por eso AUT va primero en la iteración.
