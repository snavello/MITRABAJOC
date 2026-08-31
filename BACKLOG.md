# BACKLOG.md — hallazgos y pedidos laterales

Anotaciones para no desviar el bloque de trabajo en curso (ver "Backlog
técnico" en la memoria del proyecto). Cada ítem se tacha o se borra cuando
se hace.

- [ ] **Colisión de números de expediente entre sindicatos** (hallazgo
  2026-08-31, armando el lote de AEFIP): `numero_expediente` es único en
  TODA la plataforma, pero su prefijo sale del código del TipoTramite y su
  correlativo se cuenta por tipo — si dos sindicatos crean un tipo con el
  mismo código (ej. "F01"), sus expedientes chocan y `db.crear_tramite`
  agota los 25 reintentos y revienta. Opciones: incluir el sindicato en el
  número, o hacer la unicidad por sindicato. Evaluar antes de que dos
  sindicatos reales elijan códigos iguales.
- [ ] **Selectores del dashboard: sacar Categoría + "TODOS" explícito**
  (pedido de Sd, 2026-08-31, para la próxima versión):
  1. Eliminar el selector "Categoría" de la zona de filtros.
  2. Agregar un chip "TODOS" al principio de Seccionales y de Empresas
     (seleccionado por defecto; elegir uno puntual lo desmarca y viceversa).
  3. Con eso, TODO filtro queda SIEMPRE con una opción marcada en color
     destacado, incluso en su estado default — hoy, por ejemplo, "Todos"
     en Formato de recibo queda neutro (blanco) y parece sin elegir.
     Ojo: esto relaja la regla §4.1 de DASHBOARD.md ("destacado =
     seleccionado activo"); pasa a ser "destacado = opción vigente".
     Decisión ya tomada por Sd, no re-preguntar.
- [ ] **Tarjeta "Panel Sindical" con estrella de "NEW"** (pedido de Sd,
  2026-08-29): en la portada del admin (`/admin/inicio`) y/o la pestaña de
  la tira, resaltar el módulo Dashboard recién estrenado con una estrellita
  o badge "Nuevo". Definir si expira sola (por fecha) o se saca a mano en
  un deploy posterior. Va en el próximo deploy.
