# Prompt reutilizable — Mapa funcional de un proyecto

Fecha: 2026-09-30 · Origen: sesión de Claude Code en `snavello/MITRABAJOC`
(ver `docs/chat/2026-09-26-graphify-orientacion.md` y
`docs/chat/2026-09-30-mapa-funcional.md`) · Quién: SDN

**Para qué sirve.** Pegar el bloque de abajo en Claude Code dentro de OTRO
proyecto para construir su mapa funcional: una página que muestra la
aplicación como la piensa una persona (app → funcionalidad → de qué está
hecha) y qué se afecta si se toca una pieza. Resume lo que se aprendió acá,
incluidos los caminos que NO funcionaron, para no repetirlos.

**Implementación de referencia** (Python + FastAPI + SQLModel):
[`mapa_funcional.py`](https://github.com/snavello/MITRABAJOC/blob/main/mapa_funcional.py)
en `snavello/MITRABAJOC`. Para otro stack se adapta la lectura (tabla al
final); la idea, la página y las reglas son las mismas.

**Dónde verlo funcionando**: en Colm3na, `/entornos` → pestaña **Mapa
funcional** (Pruebas y local), que lo genera desde el código desplegado y
tiene el botón "Actualizar desde el código". Este prompt se publica también
como Recurso de esa landing (`python mapa_funcional.py --publicar-prompt`).

---

## El prompt (copiar desde acá)

```text
Quiero un MAPA FUNCIONAL de este proyecto: una ayuda de orientación, no una
fuente de verdad. Todo lo que ya tenemos (CLAUDE.md, historial, bitácora,
fichas) se sigue respetando y manda sobre el mapa; el código manda sobre
todo. No quiero automatismos (hooks, reglas que empujen a consultarlo) ni
sugerencias mandatarias. Antes de ejecutar nada, analizá el código, mostrame
el plan y esperá mi OK. Preguntá ante cualquier ambigüedad, de a UNA
pregunta por vez.

QUÉ ES EL MAPA
- Nivel 1: la APP o el rol (ej.: afiliado, empresa, backoffice, plataforma,
  herramientas internas; más "Común" para login, salud, archivos).
- Nivel 2: la FUNCIONALIDAD, con el nombre que ve una persona (la pestaña o
  pantalla: "Tu Recibo", "Trámites", "Panel"), no el nombre de un archivo.
- Nivel 3, para cada funcionalidad, cinco columnas: Pantalla (plantilla/
  componente + JS) → Rutas → Código (módulos con nombre en castellano que
  diga qué hacen: "Georreferenciación de domicilios", nunca "geo") → Datos
  (tablas) → Servicios externos (APIs, OCR, colas, correo...). Si existen,
  también el permiso o el módulo contratado que la habilita.

CÓMO SE ARMA (reglas)
1. Todo se LEE DEL CÓDIGO con análisis estático (ast o el parser del
   lenguaje), sin IA y sin red: rutas de sus declaraciones; qué código corre
   cada ruta siguiendo las llamadas entre funciones del propio proyecto;
   qué tablas toca por el uso de los modelos Y por su nombre dentro del SQL
   escrito a mano; qué servicios por la librería importada, las URLs y las
   variables de entorno de claves (ANTHROPIC_, GRAFANA_...). Cuidado con
   dos casos que se escapan fácil: el cliente creado a nivel de módulo
   (`client = Anthropic()`) y el importado dentro de una función
   (`from extractor import client`).
2. Lo único escrito a mano: una tabla corta "prefijo de ruta →
   (app, funcionalidad)" y los nombres legibles de módulos y servicios.
   Gana la primera regla que encaje.
3. FAIL-VISIBLE: una ruta que no encaja en ninguna regla aparece en
   "Sin clasificar", a la vista. Nunca se descarta en silencio.
4. Filtros de ruido: NO recorrer los guardianes de sesión/permiso (todas las
   rutas los usan y repetirían lo mismo en cada funcionalidad) y no mostrar
   utilidades transversales (fechas, errores, versión).
5. Límite dicho en la página: las llamadas dinámicas (getattr, callbacks por
   texto, inyección) no se ven, y una función con ramas por parámetro trae
   lo de todas sus ramas.
5b. LAS CUATRO DISTORSIONES que aparecieron al revisar el mapa de origen,
   pieza por pieza (buscalas desde el principio):
   a. PÁGINAS COMPLETAS: la ruta que arma la página entera de una app
      (ej. /app con sus seis pestañas) le carga a UNA funcionalidad todo lo
      que las demás necesitan (el QR y la filigrana de la credencial
      aparecían en "Tu Recibo"). Van en su propia funcionalidad
      "Página de la app (carga inicial)", una por app.
   b. CONSULTAS DE "¿ESTÁ CONFIGURADO?": mostrar si un servicio tiene clave
      (configurado(), habilitado(), *_disponible()) no es llamarlo. El
      módulo queda a la vista, pero no se entra ni suma el servicio.
   c. GUARDIANES que no están en la lista (un control de pase propio de una
      sección) meten su módulo en todas las rutas que protegen.
   d. UTILIDADES chicas dentro de módulos grandes: llamar a una función
      privada que solo limpia un CUIL no es "usar el motor de validación".
      Una función privada de otro módulo sin llamadas, tablas ni servicios
      es una utilidad y no cuenta.
   Y dos cuidados del detector: las docstrings NO son código (un
   comentario que dice "...del JOIN" y nombra "empleador" sumaba esa
   tabla), y del SQL escrito a mano solo vale el nombre que sigue a
   FROM/JOIN/UPDATE/INTO.
   PANTALLAS: no las asignes a mano. Una plantilla es pantalla de una
   funcionalidad si LLAMA a sus rutas (fetch o action de formulario, en la
   plantilla o en el JS que carga con <script src>). No cuentan: enlaces de
   navegación, imágenes (el logo está en todas), el login que una ruta
   muestra cuando no hay sesión, parciales citados por nombre en el código,
   ni un .js nombrado en un comentario. A mano solo lo que el detector no
   puede ver (URLs armadas con variables).
   Para encontrar el resto: una auditoría que liste, por funcionalidad,
   cada pieza con cuántas de sus rutas la traen y el camino de llamadas más
   corto. Lo que no se explica en una frase es sospechoso.
6. VERIFICAR antes de mostrarme: contrastá el resultado con lo que ya dicen
   CLAUDE.md y la documentación (qué funcionalidad usa qué servicio o
   tabla). Cada diferencia es un hueco del detector o un hallazgo: decime
   cuál es cuál.

LA PÁGINA (un solo HTML autocontenido, generado; NO se versiona)
- Barra izquierda: apps y funcionalidades, con cantidad de rutas.
- Vista LISTA: la funcionalidad elegida en las cinco columnas unidas por
  líneas; tocar una caja resalta sus conexiones y muestra al costado sus
  funciones y "También lo usan: ..." (en qué otras funcionalidades aparece:
  para saber qué se afecta si se cambia). Arriba, una vista general con
  todas las apps.
- Vista GRAFO (misma página, botón Lista | Grafo):
  - Al inicio: el ISOTIPO del proyecto (sin la palabra, fondo transparente,
    embebido en base64) al centro, unido a las apps, y cada app a sus
    funcionalidades. Tamaño del logo: 5 veces el ícono de una
    funcionalidad, para que se vea sin molestar.
  - Clic en una funcionalidad (en el grafo o en la barra): DESPLIEGA
    alrededor su pantalla, código, tablas y servicios, cada tipo con su
    forma y color (triángulo, círculo, cuadrado, hexágono) y leyenda.
  - Clic en otra: SE SUMA sin perder la anterior. Lo ya dibujado se congela
    (no se mueve); lo nuevo se ubica en anillo alrededor de su
    funcionalidad y la física solo lo acomoda un poco. Lo compartido queda
    como UN nodo unido a ambas, y al costado "En común entre las
    desplegadas".
  - Otro clic la repliega y saca solo lo que ninguna otra desplegada usa
    (contar referencias por nodo y por arista). Botones Limpiar, Enfocar
    desplegadas y Ver todo.
  - Una vez acomodado, la física se apaga: nada queda calculando.
- Nombres legibles en todos lados; nada de siglas ni nombres de archivo
  sueltos.

LO QUE YA SABEMOS QUE NO SIRVE (no repetirlo)
- Un grafo por FUNCIÓN: miles de nodos (5.700 en el caso de origen) y el
  visor del navegador se traba ("nube densa que desaparece").
- Un grafo por ARCHIVO: no dice nada, porque un archivo no es una
  funcionalidad (un main con todas las rutas, un db con todas las tablas) y
  los nombres de archivo no explican qué hacen.
- Herramientas de grafo genéricas que infieren relaciones: se probó una
  (graphify) y asociaba decoradores de rutas a funciones homónimas de otra
  carpeta, marcándolas como EXTRACTED con confianza 1.0. La etiqueta de
  confianza de una herramienta no garantiza nada: se verifica en el código.
- Instalar hooks que obliguen a consultar el grafo antes de leer archivos.

ENTREGABLES Y CIERRE
- Un script generador versionado en la raíz (ej. `mapa_funcional.py`) que
  escriba y abra `mapa-funcional/mapa.html`, con esa carpeta en .gitignore.
- Una entrada corta en CLAUDE.md: qué es, que ORIENTA pero manda el código,
  cómo se regenera y qué hacer con "Sin clasificar".
- Cierre de bloque según las reglas del proyecto (bitácora, documento del
  bloque, commit en rama propia). Si el proyecto no tiene esas reglas,
  preguntame antes de inventarlas.
- Probalo en un navegador real antes de dármelo (desplegar, sumar,
  replegar, limpiar; sin errores de consola) y mostrame el resultado.
```

---

## Cómo adaptar la lectura a otros stacks

| Qué hay que leer | Python (FastAPI/Flask) | Django | Node (Express/Nest) | Next.js | Rails | Java (Spring) |
|---|---|---|---|---|---|---|
| Rutas | decoradores `@app.get(...)` / `@bp.route` | `urls.py` (`path(...)`) | `app.get/router.get`, `@Get()` | carpetas `app/` o `pages/`, `route.ts` | `config/routes.rb` | `@GetMapping`, `@RequestMapping` |
| Pantalla | `TemplateResponse("x.html")` / `render_template` | `render(request, "x.html")` | `res.render`, componentes | el `page.tsx` de la ruta | vista por convención | `return "vista"` / Thymeleaf |
| Llamadas | `ast` (Name/Attribute + imports) | `ast` | TypeScript Compiler API / ts-morph | ts-morph | Ripper / Prism | JavaParser |
| Tablas | clases `table=True` (SQLModel), `Base` (SQLAlchemy) + SQL crudo | `models.Model` + SQL crudo | Prisma `schema.prisma`, TypeORM `@Entity` | Prisma / Drizzle | `ApplicationRecord` + `schema.rb` | `@Entity` / `@Table` |
| Servicios | imports (`anthropic`, `boto3`...), URLs, `os.environ["X_"]` | idem | imports, `process.env.X_` | idem | gems, `ENV["X_"]` | dependencias, `@Value("${x}")` |

En todos los casos: si una parte no se puede leer con seguridad, se dice
en la página en vez de adivinarla.

## Resultado de referencia (Colm3na, 2026-09-30)

6 apps, 49 funcionalidades, 245 rutas (ninguna sin clasificar), 64 tablas.
Verificado contra CLAUDE.md: la lectura de recibos usa la API de Anthropic,
el OCR y el enmascarado; el convenio usa Anthropic y embeddings locales;
seccionales y padrón usan Georef y Nominatim; observabilidad usa Sentry,
Grafana y Telegram. En la verificación aparecieron y se corrigieron tres
huecos del detector: el cliente de la IA creado a nivel de módulo, el
importado dentro de una función y las tablas nombradas en SQL escrito a mano.
La revisión pieza por pieza (2026-09-30) encontró las cuatro distorsiones del
punto 5b y la de las docstrings; tras corregirlas quedaron 55 funcionalidades
(cinco de ellas "carga inicial"), 248 rutas y ninguna relación sin explicar.
