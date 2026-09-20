---
id: AUT-02
eje: AUT
titulo: Cambiar la cookie de identidad no debe dar acceso a los datos de otra persona (IDOR horizontal)
tipo: dinamico
herramienta: httpx desde Code
entorno: pruebas
destructivo: no
owasp: A01:2021
asvs: V4.2.1
cwe: CWE-639
activo: V1, V7, V6
---

## Objetivo

Probar de verdad lo que AUT-01 encuentra leyendo: con una sesión de
trabajador válida (o sin ninguna), cambiar `cuil_trab` por el CUIL de otro
afiliado del padrón sintético y ver si se accede a sus datos.

## Cómo se corre

1. Login como trabajador A (cuenta de la demo). Guardar sus cookies.
2. `GET /api/mis-recibos` con `cuil_trab` = CUIL de B. Ver si devuelve los
   recibos de B.
3. Repetir con `/api/mis-notificaciones`, `/perfil-foto/{cuil de B}`,
   `/api/tramites/mios`, un adjunto de trámite de B por id.
4. Mismo patrón con `cuit_emp` entre dos empleadores.
5. Sin ninguna sesión, solo con `cuil_trab` forjada, contra las 8 rutas de
   `mapa.md` §1.2.

## Resultado esperado

`paso` si toda respuesta con identidad ajena da 401/403 o solo datos
propios. Cualquier dato de B devuelto a A abre/confirma hallazgo (mismo que
AUT-01).

## Notas

No es destructivo: solo lecturas y un upload de prueba a `/api/leer` con
`MOCK_EXTRACTOR=1` para no gastar créditos. Datos sintéticos: se puede
repetir.
