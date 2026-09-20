# XSK — proyecto `mitrabajo` (Colm3na)

Lo **específico** de aplicar XSK a Colm3na. Nada de acá se extrae con el
método; es el registro de este sistema.

| Archivo | Etapa | Qué es |
|---|---|---|
| `configuracion.md` | 0 | qué datos necesita el método, qué se tiene y qué falta (valores en `.env`, nunca acá) |
| `relevamiento.md` | 1 | objeto del sistema, activos, actores |
| `mapa.md` | 2 | superficie técnica generada del código |
| `amenazas.md` | 2 | modelo de amenazas por activo |
| `alcance.md` | 3 | qué ejes entran en cada iteración |
| `hallazgos/` | 6–8 | un archivo por hallazgo, `H-NNNN.md` |
| `corridas/` | 5 | un archivo por corrida, `AAAA-MM-DD-HHMM-EJE.md` |
| `avance.md` | 9 | iteración y etapa actual, estado de las diez etapas, cómo seguir |

La página `/entornos/xsanders` lee esta carpeta con `xsk.motor.registro`.

**Confidencialidad.** Los hallazgos abiertos describen cómo atacar el
sistema. El repositorio es privado y la página va detrás del PIN de
Entornos; aun así, un hallazgo no se pega en un chat, un mail ni una
presentación hasta que esté `verificado`.
