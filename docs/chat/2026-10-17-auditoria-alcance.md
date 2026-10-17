# Auditoría del alcance del Admin de Seccional (2026-10-17)

Medición con datos, antes y después de `PLAN_ALCANCE_SECCIONAL.md`, hecha
por Code con el lote sintético de La Bancaria (6 seccionales, 100
afiliados, 5.000 recibos, 2.000 trámites, 200 notificaciones, 30 noticias,
20 beneficios) sobre una base descartable: `cargar_demo.py` +
`cargar_bancaria.py`, un Admin de Seccional creado por la ruta real
(`POST /admin/usuario`, rol `seccional`) y comparado sección por sección
con el administrador general. Los scripts no se versionan; el método es el
que describe esta ficha y se repite en una hora.

## Lo que ve cada uno

| Sección | General | Local, antes | Local, después |
|---|---|---|---|
| Padrón (Trabajadores) | 100 | 100 | 20 (su seccional) |
| Trámites (bandeja) | 2.000 | 431 | 431 |
| Formularios de trámite | 5 | 5 | 5 (todos globales: los ve, no los toca) |
| Noticias | 30 | 30 | 22 (las globales y las suyas) |
| Beneficios | 20 | 20 | 20 (todos "a todas") |
| Notificaciones | 200 | 89 | 89 |
| Reportes | 1.597 | 389 | 389 |
| Panel Sindical, recibos | 5.000 | 5.000 | 1.180 |
| Panel Sindical, trámites | 2.000 | 2.000 | 431 |
| Panel, explorador de recibos | 370 | 370 | 97 |
| Panel, filtros de seccional | 6 | 6 | 1 |
| Panel, mapa | 6 burbujas | 6 | 1 |
| Pestaña Empleadores | sí | sí | no |
| Catálogo (Conceptos, Reglas, Aprendizaje, Convenio) | edita | edita | solo lectura |

## Lo que puede hacer el local sobre lo ajeno

| Acción | Antes | Después |
|---|---|---|
| Alta de afiliado en otra seccional | pasaba | bloqueado (vacía = la suya) |
| Carga masiva con otra seccional | pasaba | bloqueado y avisado |
| Editar o borrar noticia o beneficio ajeno o global | pasaba (y la redirigía a su seccional) | bloqueado |
| Crear formulario global | pasaba | queda de su seccional |
| Editar o borrar formulario global | pasaba | bloqueado |
| Alta en el catálogo | pasaba | bloqueado |
| Detalle de trámite ajeno | 403 | 403 |
| Detalle de recibo ajeno en el Panel | 200 | 404 |
| Rutas de Empleadores | pasaba | bloqueado |
| Editar, baja, credencial, confirmar o restablecer de afiliado ajeno | bloqueado | bloqueado |

El general no cambió en ningún número. Una seccional con `ve_todas` sigue
alcanzando todo (`test_alcance_seccional_panel.py`).

## Lo que quedó abierto

- En Pruebas, SDN vio al admin de Lomas de Zamora con todos los trámites;
  esa seccional tiene "ve solo la suya". En el código la bandeja recorta
  desde Áreas V2 y lo volvió a medir esta auditoría (431 de 2.000). Queda
  por mirar en Pruebas si ese usuario es administrador general o si lo que
  vio fue el Panel Sindical, que hasta hoy sí mostraba todo.
- Empleadores con seccional (opción b del plan): sprint propio si un
  sindicato con seccionales lo pide.
