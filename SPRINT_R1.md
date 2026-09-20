# SPRINT_R1.md — Usuarios de plataforma nominales

Acordado con SDN el 2026-09-20 (sub-sprint del XSANDERS Security Kit). Cierra
tres hallazgos: **H-0002** (clave de plataforma con default y sin hash),
**H-0003** (PIN compartido de la landing) y **H-0016** (cuenta de plataforma
compartida sin trazabilidad). Como los demás `PLAN_*/SPRINT_*`, documenta lo
acordado y no se edita después; el avance va en `CLAUDE.md` y en el registro
de XSK.

## El esquema (decisión de SDN)

Usuarios de plataforma **nominales** en una tabla. La misma credencial
(**usuario + clave**) entra a **`/plataforma` y a `/entornos`** — la landing
deja de usar el PIN.

- **Login por nombre de usuario** (`snavello`), no por CUIT. El CUIL pasa a
  ser un dato del perfil (obligatorio, pero no la llave).
- **Dos roles**: `superadmin` (gestiona usuarios, con registro en log) y
  `admin` (usa plataforma y entornos, no crea usuarios). Total 4–5.
- El genérico **20000000000 sigue vivo** (login de transición) **hasta que
  los nominales funcionen**; después se elimina en un paso aparte. El PIN de
  `/entornos` **desaparece** cuando los nominales funcionan.

## Alta y primer ingreso

- Se siembran **dos superadmin**: `snavello` (Sandro Navello) y
  `arsantagati` (Alejandro Santagati), con clave inicial de **un solo uso**
  (`snaSandro` / `arsAlejandro`). Estas dos semillas **no vencen**: valen
  hasta que la persona entre la primera vez.
- Los usuarios que crean los superadmin llevan una **clave transitoria de
  máximo 7 días**. Si no entran en 7 días, la clave vence y no pueden
  loguear hasta que un superadmin la reemita.
- **Primer ingreso** (clave transitoria o datos incompletos): la persona
  **solo ve la pantalla de "cambiá tu clave y completá tus datos"**, no entra
  a `/plataforma` ni a `/entornos` hasta completarla. Debe:
  - cambiar la clave (mínimo **10 caracteres**, distinta de la transitoria),
  - cargar **CUIL, DNI, mail, dirección y teléfono** (todos obligatorios).
- **Validaciones**: CUIL 11 dígitos; mail con formato válido y **único**
  entre usuarios de plataforma (sirve a futuro para recuperación).

## Reglas

- **Guarda del último superadmin**: no se puede desactivar ni eliminar al
  último superadmin activo.
- **Log** (`LogPlataforma`): alta / edición / desactivación de usuario,
  reseteo de clave, y **login** (quién, cuándo, IP). Es el "quién tocó qué"
  que hoy no existe.
- La clave se guarda hasheada (PBKDF2 600k, `auth.hashear_clave`), nunca en
  claro (a diferencia del genérico).

## Etapas de construcción

0. Modelo (`UsuarioPlataforma`, `LogPlataforma`) + migración + siembra de los
   dos superadmin + funciones de `auth` + tests. **(esta etapa)**
1. Login de `/plataforma` por usuario nominal (con fallback al genérico
   durante la transición) + pantalla de cambio forzado y carga de datos +
   sesión que lleva el rol + log de login.
2. `/entornos` con el mismo login (el PIN queda como fallback hasta cerrar
   la transición).
3. Gestión de usuarios en `/plataforma` (solo superadmin): alta con clave
   transitoria, edición, activar/desactivar, resetear clave; con el log.
4. Cierre de la transición (paso aparte, cuando SDN confirme que los
   nominales andan): sacar el genérico 20000000000 y el PIN de la landing.
   Eso recién ahí marca H-0002/H-0003/H-0016 como Solucionados.

## Estado de los hallazgos durante el sprint

Hasta la etapa 4, H-0002/H-0003 quedan **Parcial** (existe el camino
nominal, pero el genérico y el PIN siguen vivos por transición). H-0016 pasa
a **Parcial** al haber usuarios nominales con log, y a **Solucionado** cuando
el genérico se elimine.
