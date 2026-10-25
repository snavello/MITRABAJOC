# Colm3na: contexto para los revisores de XSD

Este texto se pega en la sección «Qué es la app» del encargo de cada revisor.
Se mantiene a mano, junto con la ficha.

## Qué es la app

Colm3na es una plataforma multi-sindicato argentina. Tiene cuatro apps:

- **El afiliado**, desde el teléfono. Verifica su recibo de sueldo y usa la credencial, las novedades, los trámites y las encuestas.
- **El panel del sindicato**, en escritorio. Lo usan los operadores para gestionar el padrón, los trámites, las noticias y lo demás. Incluye el Panel Sindical (`/admin/dashboard`).
- **La empresa.** El empleador recibe notificaciones y hace trámites.
- **Plataforma.** El equipo de Colm3na da de alta los sindicatos.

Las cuatro apps tienen **dos modelos de diseño**, y cada persona elige el suyo:

- **Laguna** (por defecto): claro, teñido y con degradé.
- **Noticiero**: papel, tinta índigo, un coral y titulares condensados en mayúsculas.

Los colores salen de la marca del sindicato o de los de Colm3na. Plataforma usa siempre los de Colm3na.

Modos de Impeccable:
- el panel y plataforma son **Operate**;
- la app del afiliado es **Operate** desde el teléfono;
- la portada del afiliado mezcla Operate con algo de **Read**.

## Lo que NO es diseño en las capturas

- El distintivo amarillo «PRUEBAS» abajo a la izquierda: indica el entorno.
- Los datos son sintéticos y locales. En la base de desarrollo, el sindicato 1 se llama «Unión Obrera Metalúrgica» y tiene el logo de La Bancaria: es un dato de prueba, no un error.
- Un riel o una pastilla fija puede verse cortada o a media página en la captura de página entera. Es la forma en que el capturador dibuja los elementos fijos.

## Decisiones que no se proponen deshacer

Todas las de «Decisiones tomadas» de `CLAUDE.md`. Las que más aparecen en una revisión:

- **Encabezado:** de una sola línea, con el logo del gremio a la izquierda y Colm3na a la derecha.
- **Panel:** riel lateral en escritorio.
- **Kicker:** el kicker y los números de sección se quedan (manda `diseno-mi-trabajo` sobre el `craft-floor` de Impeccable).
- **Colores de marca:** siempre los cuatro del sindicato.
- **Semáforo:** colores fijos de estado.
- **Opción elegida:** se pinta en el color del modelo, sin barra al costado.
- **Portada:** no hay portada clara; las portadas van oscuras.
- **Errores en los ingresos:** van en rojo fijo.
- **Títulos:** `titulo-pagina` en condensada, 31 px, mayúsculas.

## Corridas anteriores

Ver `historial.md` en esta carpeta.
