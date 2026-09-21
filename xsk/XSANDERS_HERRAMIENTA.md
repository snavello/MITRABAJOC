# XSANDERS Security Kit (XSK) — Método y herramientas

**Blueprint agnóstico para convertir XSK en una herramienta reutilizable.**
Documento vivo: se itera. Versión 0.1 — 2026-09-21.

> XSK nació adentro de un proyecto real (una plataforma FastAPI/Postgres) y
> ya completó **una iteración entera** sobre él: 18 hallazgos relevados,
> clasificados con la persona dueña del sistema, corregidos y verificados,
> más un CI que quedó cazando regresiones. Este documento **generaliza** ese
> método y esas herramientas —sacándoles lo específico del proyecto— para
> empezar a construir XSK como producto independiente, aplicable a cualquier
> sistema. El proyecto donde nació es el **caso 0**, y sus aprendizajes están
> al final, en carne viva.

Relación con los otros archivos de `xsk/`:
- `METODO.md` — el método operativo, ya genérico, que la herramienta ejecuta.
- `catalogo/` — el catálogo de tests (genérico).
- `motor/` — el motor puro que lee el registro y arma el ranking.
- `proyectos/<nombre>/` — el registro de UN sistema evaluado.
- **Este documento** — la visión de producto: qué es, qué principios lo
  sostienen, qué herramientas usa, qué aprendimos, y qué falta construir para
  que sea una herramienta que cualquiera pueda tomar.

---

## 1. Qué es

Un **método con sus herramientas** para llevar un sistema a un estado de
seguridad **verificado** antes de exponerlo a usuarios reales, y para
mantenerlo ahí a lo largo del tiempo.

Tres rasgos lo definen y lo diferencian de "pasar un scanner":

1. **Un agente de código es el ejecutor.** No es un informe que alguien lee y
   archiva: el agente revisa el código, corre el análisis estático, ataca el
   entorno de prueba con pedidos reales, configura el perímetro por API,
   **corrige** y deja tests de regresión. La persona dueña del sistema decide
   el alcance, acepta riesgos y pulsa el botón de los cambios irreversibles.
2. **El registro son archivos versionados, no un dashboard opaco.** Cada
   hallazgo y cada corrida es un archivo de texto en el repositorio,
   revisable en un PR, portable, con historia. El estado se calcula de esos
   archivos; no hay una base de datos que sea la única fuente de verdad.
3. **Todo se ata a un activo y a un estándar.** Un test que no protege nada
   que el sistema tenga en juego no existe; un hallazgo sin referencia a
   OWASP/ASVS/CWE está incompleto.

"Seguridad" acá es amplia a propósito: integridad, confidencialidad y
disponibilidad de la información; suplantación de identidad; inyección de
código; vulnerabilidades de infraestructura y de la cadena de suministro;
abuso y denegación de servicio; y **protección de datos personales** (marco
legal aplicable), porque para muchos sistemas el problema no es solo el
atacante.

---

## 2. Principios

Son las reglas que no se negocian. Las primeras siete venían del método;
las últimas cuatro las agregó la iteración 1 (ver §10).

1. **Todo test se conecta a un activo.** Se testea lo que el modelo de
   amenazas dice que está en juego, no una checklist genérica.
2. **Hechos, no derivados.** El registro guarda probabilidad, daño y
   complejidad; el riesgo y el ranking se calculan al mostrarlos. Cambiar la
   escala no reescribe la historia.
3. **Nada se borra.** Un hallazgo cambia de estado; nunca desaparece. Un
   riesgo aceptado se acepta con motivo, dueño y vencimiento.
4. **Cada corrección deja un test.** Si no hay test de regresión, la
   corrección no está cerrada.
5. **Lo que no se puede probar no se afirma.** Resistir un DDoS real no se
   prueba desde una máquina: se delega al perímetro y se verifica que el
   perímetro esté. El informe dice eso, no "resiste DDoS".
6. **El kit no es un arma cargada.** Credenciales y tokens en variables de
   entorno, nunca en el registro. Los hallazgos abiertos son un manual de
   ataque hasta que se corrigen: se tratan como confidenciales.
7. **Estándares desde el día uno.** OWASP Top 10, ASVS, CWE en cada test y
   hallazgo. Agregarlo después es el trabajo que nadie hace.
8. **El agente propone, la persona pulsa el botón de lo irreversible.** El
   agente corrige, pero un cambio que apaga un acceso, borra datos o sale al
   mundo lo confirma la persona. Y esos cambios se hacen **reversibles**
   cuando se puede (una bandera de entorno que los reactiva) mientras no
   exista una vía de recuperación.
9. **La clasificación es un juicio humano, no una fórmula.** La probabilidad
   y el daño se deciden con la persona dueña del sistema, de a un hallazgo:
   ella sabe cosas que el código no dice (qué dato es público, qué cuenta es
   compartida, qué tan probable es un actor).
10. **Un hallazgo puede ser un mini-proyecto.** Algunos hallazgos no se
    "arreglan": se rediseñan, con decisiones de producto propias. Se
    planifican pregunta por pregunta antes de tocar código, como un sprint.
11. **El registro tiene un estado llano.** Además de los estados internos,
    cada hallazgo muestra **Solucionado / Parcial / Pendiente / Aceptado**
    con una aclaración en una línea: es lo que se mira de un vistazo.

---

## 3. El ciclo: diez etapas

| Etapa | Nombre | Qué produce |
|---|---|---|
| 0 | Configuración | qué datos necesita el método y dónde viven (URLs de prueba, cuentas por rol, accesos a infra, todo con los valores en `.env`) |
| 1 | Relevamiento | objeto del sistema, organización, **activos** y **actores**, decisiones de la persona (preguntas de a una) |
| 2 | Mapeo + modelo de amenazas | superficie técnica **generada del código**; STRIDE por activo |
| 3 | Alcance | qué ejes entran en esta iteración y por qué (lo que bloquea salir primero) |
| 4 | Herramientas | con qué se corre cada test (revisión / estático / dinámico / configuración / manual) |
| 5 | Ejecución | la batería por eje, en pasos; cada corrida deja un archivo |
| 6 | Registro | un archivo por hallazgo |
| 7 | Clasificación | probabilidad × daño y complejidad, **con la persona, de a uno** |
| 8 | Corrección | una rama por hallazgo con su test de regresión; lo que no se corrige se acepta |
| 9 | Registro continuo | una página muestra avance, ranking y cómo seguir; al cerrar la iteración se propone la siguiente |

Es **iterativo**: la iteración 1 toma los ejes que bloquean salir; las
siguientes cubren el resto con el sistema ya en uso. Cada iteración deja un
estado "presentable" aunque se corte ahí.

---

## 4. Los nueve ejes

El alcance se organiza por ejes, no por tests sueltos. Cualquier sistema web
con usuarios y datos los tiene, aunque alguno quede vacío.

| Sigla | Eje | Cubre |
|---|---|---|
| IDS | Identidad y sesiones | logins, fuerza bruta, cookies, expiración, cambio y recuperación de clave, cuentas privilegiadas |
| AUT | Autorización y aislamiento | multi-tenant, roles, IDOR, gateo de rutas fail-closed |
| ENT | Entradas | inyección (SQL/plantilla/comando), XSS, CSRF, archivos subidos y cómo se sirven, redirección abierta, CORS |
| IA | Superficie de la IA | inyección de prompt vía documento del usuario, costo/abuso, qué datos viajan al proveedor, qué se hace con la salida |
| DAT | Datos y criptografía | secretos, hashing, backups, qué se loguea, cifrado en tránsito y reposo, retención |
| DIS | Disponibilidad y abuso | rate limiting, cupos, DoS por CPU, perímetro/anti-DDoS |
| INF | Infra y cadena de suministro | hosting, repositorio, dependencias, contenedores, CI, IaC |
| OBS | Detección y respuesta | qué se ve ante un ataque, registro de acciones, runbook de incidente |
| LEY | Protección de datos | marco legal aplicable: clasificación, consentimiento, derechos, responsable vs encargado, retención |

El eje **IA** es lo que separa a XSK de un checklist clásico: casi ningún
marco tradicional lo cubre, y hoy casi todo sistema nuevo tiene una
superficie de IA.

---

## 5. Modelo de riesgo y estados

**Riesgo = probabilidad × daño**, cada uno de 1 a 5 (simplificación del OWASP
Risk Rating). La escala de cada valor está en `METODO.md` (qué significa un
daño 3 vs un 5, una probabilidad 2 vs un 4).

| Riesgo | Nivel | Regla |
|---|---|---|
| 15–25 | Crítico | bloquea producción; se corrige antes que nada |
| 10–14 | Alto | bloquea producción |
| 5–9 | Medio | puede salir con dueño y fecha |
| 1–4 | Bajo | se registra; se corrige cuando conviene o se acepta |

La **complejidad de corrección** (1 = un cambio de configuración; 5 =
rediseño) es el segundo criterio del ranking: a igual riesgo, primero lo más
fácil.

**Estados internos:** `abierto` → `en_correccion` → `corregido` →
`verificado`, o `abierto` → `aceptado`. Un `verificado` que vuelve a fallar
en una corrida vuelve a `abierto` (y lo anota).

**Estado llano (para la página):** Solucionado (corregido/verificado) ·
Parcial (en_correccion) · Pendiente (abierto) · Aceptado. Con una aclaración
de una línea por hallazgo. Esto fue un pedido explícito del caso 0 y resultó
clave: distingue "lo cerré del todo" de "lo mitigué pero falta" de "esto lo
asumo".

**Criterio de salida a producción:** ningún Crítico ni Alto abierto o en
corrección; todo Medio con dueño y fecha; todo aceptado con motivo, quién y
vencimiento; la última corrida de los ejes del alcance sin tests en `error`
(un test que no pudo correr no es un test que pasó); perímetro y
observabilidad verificados en el **mismo entorno** que sale a producción.

---

## 6. Las herramientas, por función

XSK es agnóstico de lenguaje: define **qué función** cumple cada herramienta,
no cuál. Estos son los cinco tipos de test y las herramientas de referencia,
con equivalentes por ecosistema.

| Tipo | Qué hace | Herramientas de referencia | Equivalentes |
|---|---|---|---|
| **revisión** | lectura del código con criterio de seguridad | skills de revisión del agente (p. ej. `security-review`, `code-review`) + lectura dirigida por el modelo de amenazas | cualquier LLM con acceso al repo |
| **estático** | análisis del código y las dependencias sin ejecutar | `bandit` (Python), `pip-audit` | `semgrep` (multi-lenguaje), `gitleaks` (secretos), `npm audit`/`osv-scanner`/`trivy`, `gosec`, `brakeman` (Ruby) |
| **dinámico** | pedidos reales contra el entorno | `httpx`/`requests` desde el agente, navegador real, `k6` (carga) | `curl`, Playwright/Puppeteer, OWASP ZAP, `nikto`, `sqlmap` (con cuidado) |
| **configuración** | consulta a la API del hosting / DNS / perímetro | API de Render, Cloudflare, GitHub | API de AWS/GCP/Azure, `sslyze`, `testssl.sh` |
| **manual** | lo que solo una persona puede verificar/decidir | la persona, con el agente guiando | — |

Notas de método sobre las herramientas:

- **La revisión y el estático van primero**: no tocan ningún entorno
  (`destructivo: no`), dan el primer lote de hallazgos sin riesgo, y el
  estático encuentra cosas que la lectura no (en el caso 0, un `eval` peligroso
  que el mapeo había pasado por alto).
- **Lo dinámico confirma desde afuera** lo que la revisión encontró, y prueba
  lo que solo se ve corriendo (fuerza bruta, IDOR, carga). Un test que
  **altera el entorno o gasta dinero** se marca `destructivo: si` y solo
  corre donde se autoriza; local (base recreable) suele ser más seguro que un
  entorno compartido para lo destructivo.
- **El perímetro y el DDoS se delegan y se verifican**, no se prueban
  (principio 5).
- **El CI es una herramienta de XSK, no solo del proyecto**: corre la suite y
  el estático en cada cambio; caza las regresiones que las corridas manuales
  no tocan. En el caso 0, el CI encontró dos defectos reales en su primer uso.

---

## 7. El registro como archivos

Todo el estado vive en archivos Markdown con una cabecera de líneas
`clave: valor` entre `---`. Sin YAML real (no hace falta una dependencia para
leer diez claves), sin tablas de base de datos. Ventajas: versionado,
revisable en un PR, portable a otro repositorio, y legible a ojo cuando la
herramienta no está.

```
xsk/
  catalogo/            un archivo por test: id, eje, tipo, herramienta,
                       entorno, destructivo, owasp/asvs/cwe, activo
  motor/               puro, sin dependencias: lee catálogo/hallazgos/corridas,
                       valida, calcula riesgo y arma el ranking
  proyectos/<nombre>/
    configuracion.md   qué datos hacen falta, qué se tiene, qué falta
    relevamiento.md    activos, actores, decisiones de la persona
    mapa.md            superficie técnica generada del código
    amenazas.md        STRIDE por activo
    alcance.md         qué ejes entran en cada iteración
    hallazgos/H-NNNN.md  uno por hallazgo (cabecera + cuerpo)
    corridas/*.md      una por corrida, con el resultado por test
    avance.md          iteración, etapa, estado de las diez etapas, cómo seguir
```

El **motor** (`motor/registro.py` en el caso 0) es puro: valida cada archivo
—y falla nombrando la clave que falta—, calcula riesgo/nivel, arma el ranking
(riesgo desc, complejidad asc) y el resumen. Es lo que hace que el registro
sea confiable: un archivo mal formado no pasa silenciosamente.

---

## 8. El tablero

Una página muestra, leída de esos archivos: en qué etapa va el método, un
banner de "¿puede salir a producción?", el **ranking de expuestos no
corregidos** por riesgo y complejidad, el **estado de resolución**
(Solucionado/Parcial/Pendiente/Aceptado con aclaración), la cobertura por eje
y el historial de corridas. Es **solo lectura**: no corre nada, no guarda
nada. En el caso 0 vive detrás de una autenticación interna y no se expone a
terceros, porque los hallazgos abiertos son un manual de ataque.

Para el producto standalone, esta página es candidata a ser un componente
reutilizable (ver §11).

---

## 9. Cómo se corre una iteración (resumen operativo)

1. **Etapa 0–1:** configurar y relevar con la persona (preguntas de a una).
   Salen los activos en su orden de prioridad y las decisiones (quién es el
   responsable legal, cómo se recupera una clave, qué se puede tocar de la
   infra).
2. **Etapa 2:** el agente **genera el mapa del código** (rutas, guardianes,
   uploads, secretos, llamadas externas, cabeceras, superficie de IA) y de ahí
   el modelo de amenazas por activo. El mapa deja "observaciones" que son
   hipótesis, no hallazgos.
3. **Etapa 3–4:** se elige el alcance (los ejes que bloquean salir) y el
   catálogo de tests con su herramienta.
4. **Etapa 5–6:** se corre la batería por eje. Primero revisión + estático
   (sin tocar nada), después lo dinámico. Cada `fallo` abre un hallazgo.
5. **Etapa 7:** se clasifica con la persona, de a uno.
6. **Etapa 8:** se corrige por el ranking, una rama por hallazgo, cada una con
   su test de regresión; lo que no se corrige se acepta con firma.
7. **Etapa 9:** el tablero refleja todo; se propone la iteración siguiente.

---

## 10. Aprendizajes de la iteración 1 (el caso 0)

Esto es lo más valioso para construir el producto: qué pasó de verdad.

- **El mapeo generado del código encontró lo más grave.** La revisión dirigida
  destapó que la identidad de un usuario viajaba en una cookie sin firmar
  (suplantación entre usuarios) — algo que ningún scanner genérico habría
  marcado, porque hay que entender la app.
- **El estático encontró lo que la lectura pasó por alto.** `bandit` marcó un
  `eval` con sandbox evadible en un motor de fórmulas: ejecución de código
  por un usuario semi-confiable. No estaba en las observaciones del mapa.
- **La clasificación con la persona movió la mitad de los puntajes.** Varios
  hallazgos bajaron o subieron porque la persona sabía algo que el código no
  decía: "ese dato ya es público", "en el alta todavía no hay nada cargado",
  "esta pantalla ahora guarda material sensible". **No se puede automatizar.**
- **Corregir tiene efectos de segundo orden.** Firmar la identidad rompió ~30
  tests que la construían del modo viejo; meter un campo nuevo en el token
  cambió su longitud y activó un comportamiento de comillas en las cookies que
  solo se veía en el harness de tests; un limitador de intentos global se
  contaminaba entre tests. Ninguno era el arreglo en sí: eran el radio de
  impacto. **El agente tiene que buscar el radio de impacto, no solo el punto.**
- **La reversibilidad importa cuando no hay recuperación.** Retirar un acceso
  viejo (una cuenta compartida, un PIN) se hizo con banderas de entorno que lo
  reactivan en una emergencia, porque todavía no había recuperación de clave.
  Apagado por defecto = efectivamente retirado; reversible = seguro.
- **La pasada dinámica confirma lo que la revisión afirma.** Con pedidos HTTP
  reales se probó que la cookie forjada ya no daba acceso y que la fuerza
  bruta se frenaba. Eso convierte "corregido" en "verificado".
- **El CI paga en el primer uso.** Apenas se encendió, cazó una regresión real
  (un cambio que rompía fórmulas con espacios) y un test intermitente que
  fallaba al cruzar un minuto. Las corridas manuales no los habían tocado.
- **Un hallazgo puede ser un sprint.** "Usar cuentas nominales en vez de una
  compartida" no era un fix: era un mini-proyecto con decisiones de producto
  (cómo se crea el primer usuario, qué datos se piden, cómo se cierra la
  transición). Se planificó pregunta por pregunta y se construyó en etapas,
  cada una verificada.
- **La disciplina del registro sostiene todo.** Poder decir en cualquier
  momento "9 solucionados, 3 parciales, 4 pendientes, bloquea 1, y este es el
  que bloquea y por qué" es lo que hace que el proceso no se pierda entre
  decenas de correcciones.

---

## 11. De método a producto: qué falta construir

Hoy XSK es un método + un registro + un motor que viven dentro de un
proyecto. Para que sea una **herramienta que cualquiera tome y aplique**,
esto es lo que hay que construir. Es la agenda para iterar este documento.

### 11.1 Empaquetado
- Sacar `motor/` + `catalogo/` a un **paquete instalable** (o CLI): `xsk init`,
  `xsk estado`, `xsk correr <eje>`, `xsk clasificar`, `xsk ranking`.
- La **skill** del agente (la que guía las etapas) como artefacto portable,
  independiente del proyecto.
- El registro por proyecto (`proyectos/<nombre>/`) como una carpeta que se
  crea en el repo del sistema evaluado, o en un repo aparte.

### 11.2 Catálogo multi-stack
- El catálogo de referencia está sesgado a **Python/FastAPI/Postgres**. Hay
  que abstraer los tests a "qué se verifica" y dar recetas por stack
  (Node/Express, Django, Rails, Go, PHP, un SPA + API, etc.).
- Los adaptadores de **herramientas por ecosistema** (§6): que `xsk` sepa
  llamar al estático correcto según el lenguaje detectado.

### 11.3 El tablero como producto
- La página lectora del registro, hoy embebida en la app del caso 0, como
  **componente reutilizable** o app standalone que apunta a cualquier
  `proyectos/<nombre>/`.
- **Dos vistas**: la interna (técnica, cruda, con los hallazgos abiertos) y
  una **presentable** (metodología, alcance, hallazgos cerrados, riesgos
  residuales aceptados) sin exponer detalles explotables — para mostrarle a un
  cliente o un auditor. Cada hallazgo referencia su estándar, lista para eso.

### 11.4 Multi-proyecto y continuidad
- Un `xsk` que maneje **varios sistemas** (la estructura `proyectos/<nombre>/`
  ya lo permite) con un índice general.
- **Re-ejecución**: volver a correr un eje y detectar reabiertos; el CI del
  sistema evaluado como disparador.
- Métricas de programa: cuántos hallazgos por eje, tiempo a cierre, deuda
  aceptada que vence.

### 11.5 Integraciones
- Perímetro (Cloudflare/WAF), hosting (Render/AWS/…), repositorio (GitHub) por
  API, como adaptadores enchufables.
- Import/export a formatos estándar (SARIF, CycloneDX para dependencias) para
  que XSK converse con otras herramientas.

---

## 12. Preguntas abiertas (para iterar)

Lo que todavía no está decidido y conviene resolver antes de invertir en el
producto:

1. **Forma de distribución.** ¿CLI + paquete? ¿Una app con su propio backend?
   ¿Una GitHub App que corre el CI de seguridad? ¿Las tres capas?
2. **El agente.** ¿XSK asume un agente de código concreto, o define un
   contrato ("estas etapas, estos artefactos") que cualquier agente cumple?
3. **El registro: repo del cliente o repo de XSK.** ¿Los hallazgos viven en el
   repositorio del sistema evaluado (versionados con él) o en un repo de XSK
   por cliente? Afecta confidencialidad y acceso.
4. **Modelo de negocio y confidencialidad.** Si XSK es un servicio, los
   hallazgos abiertos son material sensible del cliente: ¿cómo se guardan,
   quién los ve, cómo se entregan?
5. **Alcance del catálogo inicial.** ¿Se ancla a un stack (el mejor cubierto)
   para el primer release, o se arranca multi-stack más flojo?
6. **La vista presentable.** ¿Qué necesita exactamente un cliente/inversor/
   auditor para confiar en un informe XSK? Esto define la vista (c) del §11.3.

---

*Este documento se itera. Al cerrar cada iteración de XSK sobre un sistema
real, se vuelve acá y se suma lo aprendido (§10) y lo que eso implica para el
producto (§11–12).*
