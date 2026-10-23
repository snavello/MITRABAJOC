# PLAN_TEMAS — dos modelos de diseño que se cambian a gusto

Acordado con SDN el 2026-10-23, al cerrar el concurso de diseño (rondas 1 a 10; la última en
https://claude.ai/artifact/3ERPpzHPvQXFjcaxRtu6ps). Este plan no se edita una vez acordado: el avance se lleva
en "Estado actual" de CLAUDE.md y en BITACORA.md.

## Decisiones

- **D1. Dos modelos.** `laguna` (el 162 · Eléctrico laguna) es el **por defecto**; `noticiero` (el 147 ·
  Noticiero índigo claro) es la alternativa. Cada uno se mantiene lo más fiel posible a su mockup: no se
  unifican entre sí.
- **D2. La elección de la persona se guarda en su CUENTA**, no en el navegador: `CuentaTrabajador.tema` para el
  afiliado y `CuentaPanel.tema` para el operador del panel. Vacío = no eligió y vale el del sindicato. Así se
  respeta en cualquier aparato.
- **D3. El sindicato elige el modelo por defecto** de sus afiliados (`Sindicato.tema_afiliados`) y de sus
  operadores (`Sindicato.tema_panel`), y **la paleta** (`Sindicato.paleta_tema`): `colm3na` (los colores del
  modelo, tal como se diseñó) o `sindicato` (sus cuatro colores de marca). La paleta NO la elige cada persona:
  es identidad del gremio.
- **D4. Paleta en variables.** Cada modelo declara sus colores por función (fondo, tinta, acento, superficie,
  degradé); con la paleta del sindicato esas funciones se derivan de `color_base/primario/acento/secundario`
  con `color-mix`, cuidando contraste ≥ 4,5:1. Los colores de estado (verde/ámbar/rojo) no cambian nunca.
- **D5. Fotos por modelo, cargadas por plataforma.** Toda foto se **normaliza al subirla** (escala de grises,
  niveles y contraste parejos, tamaño máximo, webp) y el color se lo pone el modelo al mostrarla: así cualquier
  foto conserva los efectos difusos y luminosos. Se guarda el punto de interés para el recorte. Bytes en la
  base, como todo (regla del proyecto). El sindicato elige su foto de portada de la biblioteca de su modelo.
- **D6. Selección sin "corchete" lateral** (SDN, ronda 10b): la opción elegida de un menú se pinta en el color
  del modelo (relleno o tinte, texto e ícono en contraste), nunca con una barra de color a un costado.
- **D7. Lo que no cambia.** Contenido, campos, rutas y lógica de cada pantalla: el rediseño no saca nada
  (inventarios en `docs/diseno/`). Pautas vigentes: listados largos nunca sobre fondo negro; Inicio fuera de la
  portada y Salir siempre flotando abajo junto a Inicio; importes en formato argentino; la portada del afiliado
  no muestra diferencias ni faltantes; accesos en el orden Credencial · Trámites · Notificaciones · Encuestas ·
  Mis aportes · Capacitación.

## Bloques

1. **Datos y preferencia** — `temas.py` (catálogo y resolución, puro), columnas en `CuentaTrabajador`,
   `CuentaPanel` y `Sindicato`, migración, `db.apariencia_*`, rutas para que la persona guarde su modelo, y las
   páginas del afiliado y del panel marcadas con `data-tema` y `data-paleta` (sin cambio visual todavía).
2. **Fotos por modelo** — normalización (`fotos_tema.py`, puro, con Pillow), tabla `FotoTema`, rutas de
   plataforma para subir/publicar/borrar y servir, y la foto de portada elegida por el sindicato.
3. **Pantallas de Apariencia** — en el perfil del afiliado (elige su modelo), en el panel (sección nueva
   "Apariencia", solo administradores: modelo por defecto, paleta con prueba de lectura, foto de portada) y en
   plataforma (biblioteca de fotos).
4. **El modelo Laguna en la app del afiliado** — portada y pestañas de `/app`, fiel al mockup.
5. **El modelo Noticiero en la app del afiliado.**
6. **Los dos modelos en el panel del sindicato** — portada, riel lateral con las 16 secciones y las pantallas.
7. **Paleta del sindicato** — las variables derivadas y el control de contraste en el alta del sindicato.

Cada bloque: rama propia, tests del área, versión de la app tocada, bitácora, PR y merge con el CI en verde.
