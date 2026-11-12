# Capturas del documento integrador

Capturas REALES de la app corriendo con los datos de la demo. Cada una es
`capturas/<clave>.webp` y queda registrada en `capturas/manifest.json`. Los
capítulos las citan por clave (`data-captura="<clave>"`); `armar.py` las
incrusta. Si una captura falta, la figura se omite sin romper nada.

**Formato**
- `movil`: viewport 390x844, deviceScaleFactor 2, webp calidad 78. Solo la
  pantalla visible (no página entera) salvo que se indique `entera`.
- `escritorio`: viewport 1440x900, deviceScaleFactor 1, webp calidad 80.
  Pantalla visible; `entera` = página completa recortada a 2600 px de alto.
- Sin el distintivo de entorno (`#distintivo-entorno` oculto con CSS inyectado).
- Modelo de diseño por defecto (Laguna) salvo las marcadas `noticiero`.
- Datos sintéticos de la demo: ningún dato real de personas.

| clave | tipo | qué mostrar |
|---|---|---|
| t-ingreso | movil | `/ingresar`, ingreso del afiliado |
| t-portada | movil | `/app/inicio`, portada del afiliado (UOM, CUIL 20111111112) |
| t-portada-entera | movil entera | la misma portada completa (Tu día, noticias, beneficios) |
| t-portada-escritorio | escritorio | `/app/inicio` en escritorio |
| t-portada-noticiero | movil | la portada con el modelo Noticiero |
| t-recibo-subir | movil | `/app`, pestaña Tu Recibo, paso 1 (Subí) |
| t-recibo-espera | movil | la espera de la lectura (aro con reloj y fases) |
| t-recibo-revisar | movil entera | paso 2 Revisá, con lo leído (con MOCK_EXTRACTOR=1) |
| t-recibo-resultado | movil entera | paso 3 Resultado, con aportes OK / con diferencias |
| t-recibo-resultado-escritorio | escritorio entera | el resultado en escritorio |
| t-credencial | movil | pestaña Credencial (credencial digital con QR) |
| t-credencial-verificacion | movil | la verificación pública de la credencial (página del QR) |
| t-novedades | movil | pestaña Novedades (noticias + notificaciones) |
| t-noticia | movil | una noticia abierta |
| t-notificacion | movil | una notificación abierta (domicilio electrónico) |
| t-aportes | movil entera | Mis Aportes: semáforo ARCA |
| t-tramites | movil | Trámites: bandeja / "Necesita tu atención" |
| t-tramite-formulario | movil entera | un formulario de trámite con validaciones (carátula) |
| t-tramite-detalle | movil entera | un trámite con su chat estilo WhatsApp |
| t-encuesta | movil entera | una encuesta abierta para responder |
| t-tu-dia | movil | la hoja de un ítem de Tu día (artículo con fuente) |
| t-trivia | movil | la trivia diaria de Tu día |
| t-perfil | movil entera | Tu perfil (datos personales, domicilio, apariencia) |
| t-seccionales | movil | Seccionales cerca de mí (mapa/lista) |
| t-capacitacion | movil | Capacitación |
| t-registro | movil | `/ingresar` → registro (primer paso) |
| s-ingreso | escritorio | `/admin`, ingreso del panel del sindicato |
| s-portada | escritorio | `/admin/inicio`, portada del panel (Super Admin UOM 20111111120) |
| s-panel-sindical | escritorio entera | `/admin/dashboard`, Panel Sindical (KPIs y gráficos) |
| s-panel-mapa | escritorio | el mapa de seccionales del Panel Sindical |
| s-panel-explorador | escritorio | el explorador de datos del Panel |
| s-panel-ver | escritorio | el modal "Ver" del detalle de un recibo |
| s-panel-asistente | escritorio | el Asistente del Panel abierto (si se puede sin IA, con el mensaje de bienvenida) |
| s-reportes | escritorio | pestaña Reportes |
| s-reglas | escritorio | pestaña Reglas (fórmulas de control) |
| s-conceptos | escritorio | pestaña Conceptos |
| s-aprendizaje | escritorio | pestaña Aprendizaje |
| s-trabajadores | escritorio | pestaña Trabajadores (padrón, con nivel de fiabilidad) |
| s-tramites | escritorio | pestaña Trámites: bandeja con filtros |
| s-tramite-modal | escritorio | un trámite abierto: chat, cambio de estado, pase |
| s-constructor | escritorio entera | constructor de formularios (hoja de trabajo) |
| s-constructor-campo | escritorio | un campo abierto con Ingreso y Validación |
| s-notificaciones | escritorio | pestaña Notificaciones (alta, destinatarios) |
| s-noticias | escritorio | pestaña Noticias |
| s-beneficios | escritorio | pestaña Beneficios |
| s-encuestas | escritorio | pestaña Encuestas: constructor |
| s-encuesta-resultados | escritorio entera | resultados de una encuesta (demo de tres tomas) |
| s-seccionales | escritorio | pestaña Seccionales (con mapa) |
| s-areas-usuarios | escritorio | Áreas y Usuarios (áreas y permisos) |
| s-listas | escritorio | pestaña Listas |
| s-empleadores | escritorio | pestaña Empleadores |
| s-apariencia | escritorio entera | pestaña Apariencia (modelo, paleta, fotos, Tu día) |
| s-portada-noticiero | escritorio | portada del panel con el modelo Noticiero |
| s-acotado | escritorio | el panel visto por el Admin de Seccional de Rosario (20555555556) |
| p-ingreso | escritorio | `/plataforma`, ingreso de plataforma |
| p-inicio | escritorio | `/plataforma/inicio` |
| p-panel | escritorio | `/plataforma` panel: lista de sindicatos |
| p-sindicato-ficha | escritorio entera | ficha de un sindicato: marca, colores, módulos |
| p-uso-ia | escritorio | Uso de IA: consumo y costo |
| p-modelos | escritorio | Uso de IA → Modelos |
| p-fotos | escritorio | pestaña Fotos (biblioteca global) |
| p-usuarios | escritorio | usuarios de plataforma / usuarios de los paneles |
| e-ingreso | movil | `/ingresar-empresa` |
| e-portada | movil | `/empresa/inicio` (CUIT 30111222335) |
| e-portada-escritorio | escritorio | `/empresa/inicio` en escritorio |
| e-tramites | movil | trámites de la empresa |
| x-entornos | escritorio entera | `/entornos`, la landing con los accesos y Recursos |
| x-sala-de-mando | escritorio | `/entornos/esquema`, la Sala de mando |
| x-seguridad | escritorio entera | `/entornos/xsanders`, solapa Seguridad (XSK) |
| x-mapa-funcional | escritorio | `/entornos/mapa`, vista Grafo |
| x-herramientas | escritorio | pestaña Herramientas de `/entornos` |
| x-calculadora | escritorio entera | Calculadora bancaria v2 |
| x-asistente-tramites | escritorio entera | Asistente de trámites |
| x-laboratorio | escritorio | Laboratorio de modelos |
| x-identidad | movil | Verificación de identidad (paso selfie o datos) |
| x-planes | escritorio | pestaña Planes de Render |
| x-fiesta | movil | Fiesta SUPARA, app del afiliado (si se puede levantar) |
