# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
- **Afiliado (trabajador sindicalizado argentino), en el teléfono.** Es la
  audiencia que manda (SDN, 2026-10-20). Abre la app desde el celular —en el
  colectivo, en el descanso, en la fábrica— para saber si su recibo de sueldo
  está bien liquidado, ver las novedades y beneficios de su gremio, mostrar su
  credencial y hacer trámites. No es experto en liquidaciones: necesita un
  veredicto claro y en su idioma.
- **Usuario de sindicato**, en escritorio: Super Admin, Admin de Seccional y
  usuarios de área. Carga noticias, beneficios, notificaciones, trámites y
  conceptos; lee reportes y el Panel Sindical. Usa la herramienta todos los días.
- **Empresa (empleador)**: notificaciones y trámites con el gremio.
- **Plataforma (Colm3na)**: da de alta sindicatos, controla el uso de IA.

## Product Purpose
Que cada trabajador sindicalizado pueda verificar, con una foto o un PDF de su
recibo, si los aportes (jubilación, obra social, cuota sindical, etc.) están
bien calculados según el convenio de su gremio, y que el sindicato tenga en un
solo lugar la relación digital con sus afiliados. Éxito: el afiliado entiende
su recibo y confía en el gremio; el sindicato ve dónde se liquida mal.

## Positioning
Plataforma multi-sindicato: una misma app sirve a varios gremios, cada uno con
su marca (cuatro colores y logo) y en aislamiento total. Lo que nadie más
tiene: la lectura del recibo por IA validada contra las fórmulas del convenio
de ese gremio, y el semáforo de aportes contra ARCA.

## Operating Context
Recibos de sueldo argentinos (formato clásico y Anexo III del Dto 407/2026),
convenios colectivos (CCT), ARCA, padrón de afiliados, seccionales,
credencial gremial. Cuatro apps: trabajador (`/app`), sindicato (`/admin`),
empresa (`/empresa`), plataforma (`/plataforma`). Demo comercial ante
sindicatos y un inversor.

## Capabilities and Constraints
- FastAPI + Jinja2, CSS propio con variables; sin frameworks de CSS, sin paso
  de compilación, sin CDN (la CSP no lo permite): todo vendoreado y servido
  desde `/static/` con sello `?v=`.
- La marca de cada sindicato son cuatro colores (`--marca-base` oscuro
  validado, `--marca-primario`, `--marca-acento`, `--marca-apoyo`) inyectados
  desde la base. Cualquier diseño tiene que funcionar con CUALQUIER paleta.
- Los colores de estado (verde pagado/OK, ámbar parcial, rojo impago/diferencia)
  nunca toman la marca.
- Encabezado común de una línea: logo del sindicato a la izquierda, Colm3na
  firma a la derecha.
- Voz rioplatense en segunda persona ("Subí tu recibo").

## Brand Commitments
- La plataforma se llama **Colm3na**; el gremio manda en cada pantalla y
  Colm3na firma.
- Barlow Condensed (licencia SIL OFL, vendoreada) como voz de títulos;
  cifras con números tabulares.
- Íconos SVG de línea, nunca emojis.

## Evidence on Hand
Sindicatos de demo con datos sintéticos: Unión Obrera Metalúrgica, Federación
Gastronómica y La Bancaria (CCT 18/75, lote de 5.000 recibos). Diez recibos
PDF simulados en `docs/recibos-bancaria-prueba/`. No hay testimonios, clientes
reales ni métricas de uso publicables: no inventarlos.

## Product Principles
- El afiliado primero: el veredicto del recibo se entiende en segundos.
- Un sistema, no un rejunte: las cuatro apps se reconocen como la misma
  familia aunque cambie la marca del gremio.
- Ni trámite estatal gris, ni panfleto militante, ni ERP del montón: los
  gremios son de distintos signos y la app no toma partido.
- Hechos, no adornos: cada número que se muestra es real o está marcado.

## Accessibility & Inclusion
Uso mayoritario en teléfonos de gama media y con conexiones lentas; texto con
contraste suficiente sobre el `--marca-base` de cualquier gremio.
