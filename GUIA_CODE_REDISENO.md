# Rediseño de Mi Trabajo con Claude Code — guía práctica

Cómo llevar el diseño nuevo (portada oscura + interiores claros, con la marca
de cada sindicato) desde las maquetas hasta producción.

**La idea de esta guía:** vos no escribís comandos. Le pedís las cosas a Code
en lenguaje natural y él las ejecuta. Lo único que hacés a mano son dos cosas
que están fuera de su alcance: la consola de Render y el panel de plataforma.

Cada bloque de texto en recuadro es un pedido para copiar y pegar tal cual.

---

## ANTES DE EMPEZAR

### Lo que ya tenés resuelto

El skill de diseño ya está instalado. Bien: eso era lo único que necesitaba
gestión aparte.

### Lo único que hacés a mano ahora

Descomprimí el ZIP de diseño dentro de la carpeta del proyecto, en una
subcarpeta llamada `_entrega`. Que quede así:

```
validador-demo/
└── _entrega/
    ├── diseno-mi-trabajo/SKILL.md
    ├── marca.css
    ├── landing.html
    └── oscuras.html
```

No te preocupes por ubicarlos bien: Code los va a acomodar en el primer pedido.

### Los colores que vas a usar

Tenelos a mano. Los necesitás dos veces: cuando Code pruebe el diseño, y
cuando los cargues de verdad al final.

| Sindicato | base | primario | acento | apoyo |
|---|---|---|---|---|
| Unión Obrera Metalúrgica | `#0f1b2d` | `#1a3d6b` | `#e8a33d` | `#2fa88f` |
| Federación Gastronómica | `#0d2027` | `#14484f` | `#5fd6b4` | `#a8d5cb` |

El color **base** siempre tiene que ser oscuro. Si no, el texto blanco del
encabezado desaparece sobre el fondo.

---

## PEDIDO 1 — Que prepare el terreno

Lo primero es que arme una rama de trabajo separada y ubique los archivos
nuevos. La rama importa: si el rediseño no te convence, la descartás y el
proyecto queda intacto.

> Vamos a arrancar un rediseño de interfaz. Antes que nada, prepará el terreno:
>
> Traé lo último que haya en GitHub y creá una rama nueva llamada
> `rediseno-ui`. De acá en adelante trabajamos ahí, no toques `main`.
>
> En la carpeta `_entrega` dejé archivos nuevos. Ubicalos donde corresponde:
> el `SKILL.md` de diseño va a `.claude/skills/diseno-mi-trabajo/`, el archivo
> `marca.css` va a la carpeta `static`, y los dos HTML de maquetas van a una
> carpeta nueva `disenos` en la raíz. Las maquetas son solo referencia visual,
> no forman parte de la app: agregá esa carpeta al `.gitignore`. Cuando
> termines, borrá la carpeta `_entrega`.
>
> Hacé un commit con todo eso y confirmame en qué rama quedamos parados.
> No modifiques nada de la aplicación todavía.

**Qué verificar antes de seguir:** que te confirme que está en `rediseno-ui`.
Si sigue en `main`, frenalo y pedile que cree la rama.

---

## PEDIDO 2 — Que arme el plan, sin escribir código

Este paso parece un rodeo pero es el que más tiempo ahorra. Un plan se corrige
en dos minutos de conversación; el código ya escrito, no.

> Ahora quiero el plan del rediseño, todavía sin escribir código.
>
> Leé el skill de diseño que está en `.claude/skills/diseno-mi-trabajo/`, el
> archivo `static/marca.css`, y la maqueta aprobada en `disenos/landing.html`
> (me interesan las columnas 1A y 1B: portada oscura con acento ámbar e
> interior claro). Mirá también las plantillas actuales, `db.py`, `main.py` y
> el `CLAUDE.md`.
>
> Devolveme un plan que cubra:
> qué archivos vas a crear y cuáles modificar, con una línea por cada uno;
> cómo estructurás la portada nueva del trabajador y en qué ruta va a vivir;
> qué cambios hacen falta en la base de datos para el cuarto color de marca;
> qué pantallas quedan oscuras y cuáles claras;
> y qué riesgos ves, o qué se puede romper.
>
> No escribas código todavía, quiero revisar el plan primero.

**Qué revisar en la respuesta:**

La portada tiene que ser una **ruta nueva**, no reemplazar la pantalla de subir
el recibo. Si propone reemplazarla, corregilo.

Tiene que contemplar el **cuarto color** en la base de datos, con su columna
nueva.

No debería proponer **frameworks nuevos** (Tailwind, Bootstrap, React). El
sistema es CSS propio y así funciona bien con Jinja2.

Si algo no cierra, decíselo por chat y que rehaga el plan. Recién cuando te
convenza, seguí.

---

## PEDIDO 3 — Que construya solo la portada y te la muestre

Acá viene la parte importante: **no le pidas todas las pantallas juntas**.
Que haga una sola, la vean, y ahí corregís lo que no te guste. Después el
resto sale derecho.

> Bien, adelante con el plan, pero por ahora construí **solo la portada del
> trabajador**.
>
> Cuando la tengas, levantá la aplicación y sacame capturas de cómo se ve en
> pantalla de celular, de 390 píxeles de ancho. Probala con dos paletas
> distintas, para confirmar que la marca por sindicato funciona de verdad:
>
> Metalúrgica: base #0f1b2d, primario #1a3d6b, acento #e8a33d, apoyo #2fa88f
> Gastronómica: base #0d2027, primario #14484f, acento #5fd6b4, apoyo #a8d5cb
>
> Mostrame las dos capturas antes de seguir con el resto. Todavía no hagas
> commit.

**Qué mirar en las capturas:**

Que el **logo del sindicato tenga protagonismo** arriba de todo. Que las
tarjetas se lean cómodas en el ancho de un celular, sin apretarse. Que el
texto contraste bien sobre el fondo oscuro.

Y lo más importante: que al cambiar de paleta **cambie de verdad**. Si las dos
capturas se ven casi iguales, significa que hay colores escritos a mano en el
código en vez de tomarlos de la marca. Eso hay que corregirlo ahí mismo, o
después se arrastra a todas las pantallas.

Iterá lo que haga falta. Como es una sola pantalla, cada corrección es rápida.

---

## PEDIDO 4 — Que haga el resto y lo suba

Con la portada aprobada, el resto es aplicar el mismo criterio.

> La portada quedó bien. Seguí con el resto del plan:
>
> Aplicá el sistema a las pantallas interiores del trabajador, las del recibo
> y las de aportes, con el encabezado oscuro y el cuerpo claro. Aplicalo
> también al panel del sindicato y al de plataforma.
>
> Agregá el cuarto color al modelo de sindicato y a los formularios de alta y
> edición, con una validación que impida cargar un color base que no sea
> oscuro.
>
> Las secciones que todavía no existen, Credencial y Beneficios, van como
> tarjetas con un "próximamente".
>
> Actualizá el `ESTADO_DEL_PROYECTO.md` y el `CLAUDE.md` con lo que cambió.
>
> Importante: no toques la lógica de validación de recibos ni el semáforo de
> aportes. Esto es solo presentación.
>
> Al terminar, sacá capturas de cada pantalla, hacé el commit en la rama
> `rediseno-ui` y subila a GitHub. No la fusiones a `main` todavía, quiero
> probarla antes.

**Por qué esos dos límites del final.** El primero ("no toques la lógica")
evita que, de paso, modifique algo que ya funciona bien. El segundo ("no
fusiones a main") es clave: un cambio en `main` dispara el despliegue en
Render automáticamente, así que querés decidir vos cuándo sale a producción.

---

## PEDIDO 5 — Probarlo en tu computadora

> Levantá la aplicación en local para que la pruebe. Tené en cuenta que el
> cuarto color cambió la estructura de la tabla de sindicatos, así que rehacé
> la base de datos local y volvé a cargar los datos de demo antes de
> levantarla. Avisame en qué dirección la abro.

Recorré los tres accesos con los datos de demo y mirá que todo se vea como
esperabas. Si algo falta o quedó raro, pedíselo ahora, antes de fusionar.

---

## PEDIDO 6 — Que lo fusione y lo publique

Cuando estés conforme:

> Ya lo probé y está bien. Fusioná la rama `rediseno-ui` a `main` y subila.

Render detecta el cambio y redespliega solo.

---

## LO QUE HACÉS VOS DESPUÉS

Estos dos pasos son tuyos porque Code no tiene acceso ni a la consola de
Render ni al panel de administración de la plataforma.

### Reiniciar la base de datos en Render

El cuarto color agregó una columna, así que hace falta el reinicio de base que
ya conocés. Es el único lugar donde escribís comandos.

En Render, entrá a tu servicio y abrí la pestaña **Shell**. Escribí:

```
rm -f /var/data/validador.db
```

Después andá a **Manual Deploy → Restart service**. Ese reinicio es el que hace
que la aplicación cree las tablas nuevas con la columna del cuarto color.

Cuando el servicio vuelva a estar en verde, volvé a la Shell y escribí:

```
python cargar_demo.py
```

Tenés que ver los dos tildes de los sindicatos de demostración.

### Cargar los colores y el logo de cada sindicato

Este es el paso que le da sentido a todo el rediseño. Entrá a `/plataforma`
con tu CUIT y tu clave, y por cada sindicato:

Tocá **Editar** en la lista de sindicatos. Cargá los cuatro colores de la tabla
del principio. Subí el **logo en PNG**: conviene que sea cuadrado, con fondo
transparente y de al menos 200 por 200 píxeles, porque en la portada nueva se
ve grande y un logo chico o pixelado se nota bastante. Guardá.

Después entrá como trabajador de ese sindicato y mirá cómo quedó. Repetí con el
segundo y compará los dos: tienen que verse claramente distintos, con la misma
estructura. Si algún color quedó flojo de contraste, lo ajustás desde el mismo
panel, sin tocar código.

---

## DOS REGLAS QUE CONVIENE DEJAR ESCRITAS

Ahora que Code maneja tu GitHub y la app está en producción, vale la pena
fijarle dos límites permanentes. Pedíselo una vez:

> Agregá al `CLAUDE.md` dos reglas de trabajo que quiero que valgan siempre:
> primero, nunca fusionar a `main` ni subir cambios a esa rama sin que yo te lo
> pida explícitamente, porque eso dispara el despliegue en producción; segundo,
> nunca usar `--force` en git ni reescribir el historial.

Al quedar en el `CLAUDE.md`, valen para todas las sesiones y no las repetís en
cada pedido.

---

## RESUMEN

| Paso | Quién | Qué pasa |
|---|---|---|
| Preparación | Vos | Descomprimir el ZIP en `_entrega`, tener los colores a mano |
| Pedido 1 | Code | Rama nueva, ubicar archivos, commit |
| Pedido 2 | Code | El plan, sin código. Lo revisás y corregís por chat |
| Pedido 3 | Code | Solo la portada, con capturas de dos paletas. Iterás |
| Pedido 4 | Code | El resto de las pantallas y el cuarto color. Sube la rama |
| Pedido 5 | Code | Levanta la app local para que la pruebes |
| Pedido 6 | Code | Fusiona a `main` cuando vos lo aprobás |
| Cierre A | Vos | Reinicio de base en la consola de Render |
| Cierre B | Vos | Cargar colores y logos de cada sindicato en `/plataforma` |
