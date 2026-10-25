# De dónde sale esta skill

Esta carpeta es copia **textual** de la skill `xsd` del plugin XSD (XSANDERS
Design Kit), que vive en su propio repositorio. No se edita acá: un cambio
al método, a las herramientas o al informe se hace allá y se vuelve a copiar.
Lo que es de Colm3na (ficha, inventario, sesiones, contexto e historial) sí
vive acá, en `xsd/proyectos/mitrabajo/`.

- Repositorio: https://github.com/snavello/xsanders-design-kit
- Carpeta copiada: `plugins/xsd/skills/xsd/`
- Commit: `ce7e570479c81edc16e4ba37c2dd62a1f6d36eff` (2026-10-25)
- Versión del plugin: 1.0.0

Se copia en vez de instalar el plugin para que `/xsd` ande en cualquier
sesión de este repositorio, también en la nube, sin depender de llegar a
otro repo. La ventana de avance (plugin `avance-agentes`) no se copia: es
opcional y se instala desde el mismo repositorio.

## Para actualizarla

1. En el repo del kit, `git pull` y anotar el commit.
2. Borrar esta carpeta menos este archivo y copiar `plugins/xsd/skills/xsd/`.
3. Cambiar el commit de arriba y recalcular los SHA-256 de abajo
   (`test_xsd.py` falla si no coinciden).

## SHA-256 de la copia

  - `METODO.md`: `7a3069d002889bc6ddfdf3fb6899170496c25a5278b2d27b0c1a44f74598c7ea`
  - `SKILL.md`: `7e4ab8bbcf656d586e21ef2a62bebdeb8927523f0b59b7771fe1128fabf78a2e`
  - `herramientas/capturar.cjs`: `a7ae0905e43798436baba3214a861ec66597285c49c8a46c28ffd539fd0698fb`
  - `herramientas/xsd.py`: `76dfa291d0049de28f6138d05c931d432a931653f48fc5e7af53cd5d219aca1a`
  - `informe/index.html`: `b2b017acdb11e4302a9de610f0de5e73193344c206e075fede88d075380c388b`
  - `plantillas/brief_equipo.md`: `4847cb4beccce47db0c2fd8ba405e35f7011fda96bbae39de519c46c6ad3af05`
  - `plantillas/brief_revisor.md`: `a9379c09bf5f3e0da55162e98e962d6538a959ff1f01ae02340b37d9000624ca`
  - `plantillas/brief_segunda_vuelta.md`: `e1b144aae579c67e7ffccf99b533f43bea3ea858961f4104e56f798cb7a81c6f`
  - `plantillas/ficha.json`: `ec50834ee554251cabe1c143f4be4e392461434da1a0c77d17a1675096428e75`
