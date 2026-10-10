// Genera las versiones Word (editables, con control de cambios activado) del
// plan de implementación y de la hoja guía de La Bancaria. El contenido es el
// mismo de los HTML de docs/bancaria/ (borrador v0.1).
// Uso (desde la raíz del repo, con docx de npm instalado):
//   node docs/bancaria/generar_docx.js [logo.png] [carpeta_salida]
// Por defecto toma el logo de Colm3na para fondo claro y escribe en docs/bancaria/.
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, AlignmentType, HeadingLevel, LevelFormat,
  Footer, PageNumber, TabStopType, VerticalAlign, LineRuleType,
} = require('docx');

const [LOGO = 'static/marca/logo_plataforma_claro.png', SALIDA = 'docs/bancaria'] = process.argv.slice(2);
const logo = fs.readFileSync(LOGO);

const C = { tinta: '0A1421', miel: 'F0A01E', mielOsc: 'B8720A', rojo: 'A0030B',
  papel2: 'F4F6F9', mielSuave: 'FDF1DC', linea: 'DBE2EA', texto: '16243A', texto2: '4C5D75' };
const FUENTE = 'Arial';
const ANCHO = 9638; // A4 con márgenes de 2 cm, en DXA

// ---------- helpers ----------
// "**negrita** resto" -> runs
function runs(txt, extra = {}) {
  return String(txt).split('**').map((t, i) => new TextRun({ text: t, bold: i % 2 === 1 || extra.bold, ...extra }))
    .filter((r, i, a) => true);
}
const p = (txt, o = {}) => new Paragraph({ children: runs(txt, o.run || {}), spacing: { after: 100, ...(o.spacing || {}) }, alignment: o.align, ...(o.par || {}) });
const vineta = (txt, nivel = 0) => new Paragraph({ children: runs(txt), numbering: { reference: 'vinetas', level: nivel }, spacing: { after: 50 } });
const casilla = (txt) => new Paragraph({ children: runs(txt), numbering: { reference: 'casillas', level: 0 }, spacing: { after: 60 } });
const h1 = (txt) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(txt)] });
const h2 = (txt) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(txt)] });
const h3 = (txt) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(txt)] });
const ceja = (txt) => new Paragraph({ children: [new TextRun({ text: txt.toUpperCase(), bold: true, color: C.rojo, size: 17, characterSpacing: 30 })], spacing: { after: 60 } });
const etiquetado = (etq, txt) => new Paragraph({ children: [new TextRun({ text: etq + ': ', bold: true, color: C.rojo }), ...runs(txt)], spacing: { after: 80 } });
// Recuadro destacado (fondo miel suave, filo izquierdo)
const destacado = (txt) => new Paragraph({
  children: runs(txt), spacing: { before: 120, after: 160 },
  shading: { type: ShadingType.CLEAR, fill: C.mielSuave, color: 'auto' },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: C.miel, space: 8 } },
  indent: { left: 160, right: 120 },
});
const instruccion = (txt) => new Paragraph({
  children: runs(txt, { color: C.texto2, size: 18 }), spacing: { before: 60, after: 200 },
  shading: { type: ShadingType.CLEAR, fill: C.papel2, color: 'auto' },
  // Solo arriba y abajo: docx-js escribe los cuatro lados de un párrafo en un
  // orden que el esquema de Word no acepta.
  border: { top: { style: BorderStyle.DASHED, size: 6, color: C.texto2, space: 6 }, bottom: { style: BorderStyle.DASHED, size: 6, color: C.texto2, space: 6 } },
  indent: { left: 140, right: 140 },
});

const bordeCelda = { style: BorderStyle.SINGLE, size: 4, color: C.linea };
const bordes = { top: bordeCelda, bottom: bordeCelda, left: bordeCelda, right: bordeCelda };
function celda(txt, ancho, o = {}) {
  const parrafos = (Array.isArray(txt) ? txt : [txt]).map(t => new Paragraph({
    children: runs(t, o.run || {}), alignment: o.align, spacing: { after: 0 } }));
  return new TableCell({
    children: parrafos, width: { size: ancho, type: WidthType.DXA }, borders: bordes,
    margins: { top: 60, bottom: 60, left: 100, right: 100 }, verticalAlign: VerticalAlign.CENTER,
    shading: o.fill ? { type: ShadingType.CLEAR, fill: o.fill, color: 'auto' } : undefined,
    columnSpan: o.span,
  });
}
// tabla(encabezados, filas, anchos). Una fila que es {grupo:'...'} ocupa todo el ancho.
function tabla(encabezados, filas, anchos) {
  const total = anchos.reduce((a, b) => a + b, 0);
  const cab = new TableRow({ tableHeader: true, children: encabezados.map((t, i) =>
    celda(t, anchos[i], { fill: C.tinta, run: { bold: true, color: 'FFFFFF', size: 17 } })) });
  const cuerpo = filas.map(f => f.grupo
    ? new TableRow({ children: [celda(f.grupo, total, { span: anchos.length, fill: C.papel2, run: { bold: true, color: C.texto2, size: 17 } })] })
    : new TableRow({ children: f.map((t, i) => celda(t, anchos[i], f.opts && f.opts[i])) }));
  return new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: anchos, rows: [cab, ...cuerpo] });
}
const espacio = () => new Paragraph({ children: [], spacing: { after: 80 } });

function encabezado(kicker, titulo) {
  return [
    new Paragraph({ children: [new ImageRun({ type: 'png', data: logo, transformation: { width: 150, height: 43 },
      altText: { title: 'Colm3na', description: 'Logo de Colm3na', name: 'logo' } })], spacing: { after: 160 } }),
    new Paragraph({ children: [new TextRun({ text: kicker.toUpperCase(), bold: true, color: C.mielOsc, size: 17, characterSpacing: 30 })], spacing: { after: 60 } }),
    new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun(titulo)] }),
  ];
}
function pie(txt) {
  return new Footer({ children: [new Paragraph({
    tabStops: [{ type: TabStopType.RIGHT, position: ANCHO }],
    border: { top: { style: BorderStyle.SINGLE, size: 4, color: C.linea, space: 4 } },
    children: [new TextRun({ text: txt, size: 15, color: C.texto2 }), new TextRun({ text: '\tPágina ', size: 15, color: C.texto2 }),
      new TextRun({ children: [PageNumber.CURRENT], size: 15, color: C.texto2 }), new TextRun({ text: ' de ', size: 15, color: C.texto2 }),
      new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 15, color: C.texto2 })],
  })] });
}
function documento(children, textoPie, titulo) {
  return new Document({
    creator: 'Colm3na', title: titulo, description: 'Borrador v0.1 para revisión',
    features: { trackRevisions: true }, // las correcciones quedan marcadas
    styles: {
      default: { document: { run: { font: FUENTE, size: 20, color: C.texto }, paragraph: { spacing: { line: 276, lineRule: LineRuleType.AUTO } } } },
      paragraphStyles: [
        { id: 'Title', name: 'Title', basedOn: 'Normal', next: 'Normal', run: { font: FUENTE, size: 44, bold: true, color: C.tinta }, paragraph: { spacing: { after: 160 } } },
        { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FUENTE, size: 30, bold: true, color: C.tinta }, paragraph: { spacing: { before: 320, after: 120 }, outlineLevel: 0, border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: C.miel, space: 4 } } } },
        { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FUENTE, size: 25, bold: true, color: C.tinta }, paragraph: { spacing: { before: 260, after: 80 }, outlineLevel: 1 } },
        { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FUENTE, size: 20, bold: true, color: C.mielOsc, allCaps: true }, paragraph: { spacing: { before: 140, after: 60 }, outlineLevel: 2 } },
      ],
    },
    numbering: { config: [
      { reference: 'vinetas', levels: [
        { level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { run: { color: C.mielOsc }, paragraph: { indent: { left: 360, hanging: 240 } } } },
        { level: 1, format: LevelFormat.BULLET, text: '–', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 240 } } } } ] },
      { reference: 'casillas', levels: [
        { level: 0, format: LevelFormat.BULLET, text: '☐', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 400, hanging: 300 } } } } ] },
    ] },
    sections: [{
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } },
      footers: { default: pie(textoPie) },
      children,
    }],
  });
}

const INSTRUCCION = (hojas) => `**Cómo corregir este documento** (este recuadro no va en la versión final). El control de cambios está activado: escribí, borrá y reemplazá directamente sobre el texto y tus correcciones quedan marcadas. Para dudas o pedidos que no son texto (por ejemplo «sumar una fase» o «esto va antes»), usá comentarios. Lo que figura como [completar] es un dato que falta. No hace falta cuidar el formato ni la cantidad de páginas: al regenerar se vuelve a armar el diseño y se ajusta a ${hojas}.`;

// =====================================================================
// PLAN DE IMPLEMENTACIÓN
// =====================================================================
function fase(num, nombre, semanas, objetivo, hace, aporta, cierra, responsables, tituloHace = 'Qué se hace') {
  const out = [h2(`Fase ${num} · ${nombre} (${semanas})`), etiquetado('Objetivo', objetivo), h3(tituloHace), ...hace.map(t => vineta(t)),
    h3('Qué aporta el sindicato'), ...aporta.map(t => vineta(t)), etiquetado('Cierra cuando', cierra)];
  if (responsables) out.push(etiquetado('Responsables', responsables));
  return out;
}

const plan = [
  ...encabezado('Propuesta para consensuar · Borrador v0.1 · octubre 2026', 'Plan de implementación en La Bancaria'),
  instruccion(INSTRUCCION('4 hojas A4')),
  p('Cómo pasamos de la primera reunión a toda la Asociación Bancaria usando Colm3na: seis fases, quién hace qué, qué datos hacen falta y cómo se mide cada paso. Un borrador para acordar en grande con las autoridades y ajustar con el equipo del sindicato.', { run: { size: 22 } }),
  tabla(['6 fases', 'Semana 4', '50 a 500', '≈ 20 semanas'],
    [['de la preparación a la implementación total', 'entorno de prueba con los datos de La Bancaria', 'afiliados reales en la prueba piloto', 'hasta el padrón completo (orientativo)']],
    [2409, 2410, 2409, 2410]),

  h1('Cómo trabajamos'),
  vineta('**Es un producto que ya funciona.** No hay desarrollo a medida: se releva, se configura, se prueba con afiliados reales y se acompaña.'),
  vineta('**El sindicato es dueño de las reglas y los datos.** Conceptos, escalas, trámites y mensajes los define o valida su gente.'),
  vineta('**Avance gradual.** Cada funcionalidad avanza a su ritmo y cada fase cierra con un criterio que se puede verificar.'),
  vineta('**Datos protegidos desde el primer día.** El padrón real llega con el acuerdo de datos firmado y por un canal seguro.'),

  h1('Calendario: seis fases, con el entorno de prueba en la semana 4'),
  p('El diagrama de barras de la versión final se arma a partir de esta tabla.', { run: { color: C.texto2, size: 18, italics: true } }),
  tabla(['Fase', 'Semanas', 'Hitos con el sindicato'], [
    ['0 · Preparación', 'Semana 0', '—'],
    ['1 · Definición del plan', 'Semana 1', 'Lanzamiento (semana 1)'],
    ['2 · Relevamiento detallado', 'Semanas 2 y 3', 'Datos completos (semana 3)'],
    ['3 · Configuración e implementación', 'Semanas 3 a 6', 'Entorno de prueba disponible (semana 4), si los datos llegaron en la semana 3. Aceptación de la configuración (semana 6)'],
    ['4 · Prueba piloto', 'Semanas 7 a 12: unos 50 afiliados en las semanas 7 y 8; hasta 500 en las semanas 9 a 12', 'Resultados del piloto (semana 12)'],
    ['5 · Implementación total', 'Semanas 13 a 20: oleada 1 en 13–15, oleada 2 en 16–17, oleada 3 en 18–20', 'Padrón completo y cierre (semana 20)'],
  ], [2700, 3600, 3338]),

  h1('Hitos y presentaciones'),
  tabla(['Sem.', 'Hito o presentación', 'Con quién'], [
    ['1', 'Lanzamiento: presentación de la plataforma y del plan', 'Secretarías, sistemas, prensa y seccionales'],
    ['2–3', 'Talleres de relevamiento, cada uno con su demostración', 'Referentes de cada tema'],
    ['3', 'Datos completos: padrón, convenio y escalas, bancos y documentos', 'Referentes técnico y de liquidación'],
    ['4', 'El sindicato recorre el entorno de prueba con sus propios datos', 'Referentes y operadores del panel'],
    ['6', 'Aceptación de la configuración y fecha de inicio del piloto', 'Referente operativo y autoridad responsable'],
    ['7', 'Presentación del piloto y capacitación', 'Seccionales del piloto y delegados'],
    ['12', 'Resultados del piloto y decisión de seguir', 'Autoridades'],
    ['13–20', 'Lanzamiento por oleadas de seccionales y cierre', 'Todo el padrón · Autoridades'],
  ], [900, 5138, 3600]),
  p('Durante todo el proyecto: reunión semanal de seguimiento (45 minutos) y demostración quincenal de lo avanzado.', { spacing: { before: 80 } }),

  h1('Qué se implementa'),
  p('Propuesta inicial: la prioridad de cada funcionalidad la define el sindicato en la fase 1.', { run: { color: C.texto2 } }),
  tabla(['Funcionalidad', 'Propuesta'], [
    { grupo: 'Para el afiliado, en su teléfono' },
    ['Verificación del recibo de sueldo contra el convenio', 'Piloto'],
    ['Mis aportes: semáforo de aportes con ARCA', 'Piloto'],
    ['Credencial digital con código QR', 'Piloto'],
    ['Novedades y notificaciones del sindicato', 'Piloto'],
    ['Trámites con expediente y conversación', 'Piloto'],
    ['Beneficios, encuestas y capacitación', 'Después'],
    ['Consultas sobre el convenio', 'Después'],
    { grupo: 'Para el sindicato, en su panel' },
    ['Padrón, seccionales y mapa de afiliados', 'Piloto'],
    ['Usuarios y áreas con permisos por seccional', 'Piloto'],
    ['Conceptos y reglas de control del CCT 18/75', 'Piloto'],
    ['Notificaciones por seccional, banco o provincia', 'Piloto'],
    ['Panel Sindical y reportes de recibos verificados', 'Piloto'],
    ['Avisos y trámites con los bancos empleadores', 'Después'],
    ['Resultados de encuestas', 'Después'],
  ], [7638, 2000]),

  h1('Fases 0 a 2: preparar, acordar y relevar'),
  p('Las tres primeras fases dejan todo listo para que el entorno de prueba esté disponible en la semana 4.', { run: { color: C.texto2 } }),
  ...fase(0, 'Preparación', 'Semana 0', 'Llegar al lanzamiento con todo listo, para no hacerle perder tiempo al sindicato.', [
    'Ajustar este plan con lo acordado en la reunión con las autoridades.',
    'Crear el espacio de La Bancaria en el entorno de prueba, con su nombre, sus colores y recibos de ejemplo armados según el CCT 18/75.',
    'Preparar el kit de relevamiento: formularios por tema, lista de documentos y modelo de planilla del padrón.',
    'Redactar el borrador del acuerdo de tratamiento de datos personales.',
    'Preparar la presentación de lanzamiento.',
  ], [
    'Una autoridad responsable del proyecto y un referente operativo para el día a día.',
    'Fecha del lanzamiento y lista de convocados.',
    'Logo y colores institucionales.',
  ], 'El kit, la demostración y el borrador del acuerdo están enviados y el lanzamiento tiene fecha.', 'Dirección del proyecto (Colm3na) y referente operativo.'),
  ...fase(1, 'Definición del plan', 'Semana 1', 'Acordar alcance, prioridades, piloto y calendario, y que cada referente sepa qué se le va a pedir.', [
    'Lanzamiento con secretarías, sistemas, prensa y seccionales: presentación de la plataforma y de este plan.',
    'Nombrar a los referentes del sindicato y fijar el día de la reunión semanal.',
    'Priorizar funcionalidades: cuáles entran en el piloto y cuáles después.',
    'Definir el piloto: seccionales, bancos, cantidad y perfil de afiliados (entre 50 y 500).',
    'Acordar el canal seguro para el padrón y la fecha de entrega de cada dato.',
    'Acordar cómo se verifica la identidad del afiliado cuando se registra.',
  ], [
    'Referentes con tiempo asignado al proyecto.',
    'Las prioridades del gremio y las seccionales candidatas al piloto.',
    'Revisión del acuerdo de datos por su asesoría legal.',
  ], 'El sindicato aprueba la versión 1 de este plan, con nombres, prioridades y fechas.', 'Dirección del proyecto y autoridad responsable del sindicato.'),
  ...fase(2, 'Relevamiento detallado', 'Semanas 2 y 3', 'Conocer el sindicato lo suficiente para configurarlo sin suposiciones.', [
    '**Estructura:** seccionales con su domicilio, áreas internas y quiénes operan el panel, con qué permisos.',
    '**Padrón y alta de afiliados:** dónde está, qué campos tiene, su calidad y cómo se actualiza (ver «Datos para el alta de afiliados»).',
    '**Convenio y liquidación:** conceptos del CCT 18/75, escalas y acuerdos vigentes, cuota sindical y recibos de muestra de cada banco.',
    '**Empleadores:** bancos y entidades donde trabajan los afiliados, con su CUIT.',
    '**Trámites y comunicación:** qué gestiones hace hoy el afiliado, quién las atiende y cómo se comunica el gremio.',
    '**Tecnología:** sistemas actuales, correo institucional y canal de transferencia de datos.',
  ], [
    'Estatuto, CCT, actas paritarias, escalas vigentes y formularios de trámites actuales.',
    'El padrón, por el canal acordado.',
    'De 30 a 60 recibos reales de distintos bancos, con consentimiento o anonimizados.',
    'La firma del Secretario General para la credencial y la lista de operadores del panel.',
  ], 'Están respondidos los formularios, recibidos los documentos y el padrón, y firmado el acuerdo de datos.', 'Implementación funcional (Colm3na) y referentes del sindicato.', 'Qué se hace: talleres de dos horas por tema'),
  destacado('**La semana 4 depende de la semana 3.** Si al cierre del relevamiento falta algún dato, el entorno de prueba se arma igual con lo que haya y lo pendiente se suma cuando llega. Lo que no se puede reemplazar es el padrón y el convenio: sin ellos no hay prueba con datos propios.'),

  h1('Fases 3 a 5: configurar, probar con afiliados y llegar a todos'),
  p('Desde la fase 4 la plataforma la usan afiliados reales. Cada paso se amplía solo cuando el anterior funciona.', { run: { color: C.texto2 } }),
  ...fase(3, 'Configuración e implementación', 'Semanas 3 a 6', 'Que un afiliado del padrón pueda entrar, subir un recibo real y recibir una verificación correcta según su convenio.', [
    'Cargar marca, seccionales, áreas y usuarios con sus permisos; cargar padrón y bancos y conciliar los totales con el sindicato.',
    'Cargar conceptos, reglas de control y escalas, cada una con su fuente (artículo del convenio o acta paritaria).',
    '**Semana 4:** el equipo del sindicato recorre el entorno de prueba con sus propios datos.',
    'Probar con los recibos de muestra hasta que el resultado sea correcto revisado a mano. La plataforma propone los conceptos nuevos que encuentra y el sindicato los aprueba.',
    'Configurar lo priorizado: credencial, novedades, notificaciones y los primeros dos o tres tipos de trámite.',
    'Capacitar a operadores del panel y referentes de seccional, con guías breves para el administrador y el afiliado.',
  ], [
    'Aprobación del catálogo de conceptos y de las reglas de control.',
    'Textos iniciales: bienvenida, novedades, beneficios.',
    'Tiempo de los operadores para la capacitación.',
  ], 'Al menos 20 recibos reales de 4 bancos dan resultado correcto, el padrón está conciliado y los operadores capacitados. El referente operativo firma la aceptación.', 'Implementación funcional y desarrollo (Colm3na); referentes de convenio y sistemas.'),
  ...fase(4, 'Prueba piloto con afiliados reales', 'Semanas 7 a 12', 'Validar con uso real que la configuración es correcta, que la app se entiende y que el sindicato puede operarla.', [
    'Pasar la configuración aceptada al entorno definitivo y habilitar al grupo piloto.',
    'Arranque escalonado: unos 50 afiliados de una o dos seccionales, y ampliación hasta 500 cuando el primer grupo funciona.',
    'La verificación del recibo se habilita por grupos, a medida que la calidad medida de la lectura lo permite.',
    'Mesa de ayuda del piloto y revisión semanal de recibos dudosos, conceptos nuevos y trámites.',
    'Abarcar al menos dos cierres de mes, para ver dos recibos de cada afiliado.',
  ], [
    'Elegir e invitar a los afiliados del piloto, con variedad de bancos.',
    'Delegados que acompañan el primer ingreso.',
    'Operadores que atienden trámites y responden cada semana sobre conceptos y diferencias.',
  ], 'Se cumplen los indicadores del piloto o se decide en forma explícita cómo seguir. Las autoridades reciben el informe de resultados.', 'Dirección del proyecto e implementación funcional; referentes de las seccionales piloto.'),
  ...fase(5, 'Implementación total', 'desde la semana 13', 'Llegar a todo el padrón, con el sindicato operando en forma autónoma y Colm3na como soporte.', [
    'Despliegue por oleadas de seccionales, con capacitación antes de cada una.',
    'Campaña a los afiliados: la app se instala en el teléfono desde un enlace, sin pasar por una tienda.',
    'Sumar las funcionalidades que quedaron para después, según la prioridad acordada.',
    'Mesa de ayuda en dos niveles: el sindicato atiende al afiliado y Colm3na al sindicato, con tiempos de respuesta por gravedad.',
  ], [
    'El orden de las oleadas y la comunicación institucional.',
    'Mantener escalas y conceptos al día en cada paritaria.',
  ], 'Todo el padrón fue invitado y la mesa de ayuda funciona. Se firman el acta de cierre y el acuerdo de soporte y evolución.', null),
  destacado('**Nota de calendario.** Si la fase 1 arranca en la segunda quincena de octubre, el piloto cae sobre los recibos de noviembre (Día del Bancario) y de diciembre (aguinaldo): esos conceptos se cargan en la fase 3. La fase 5 cruza el receso de enero, por eso el orden y las fechas de las oleadas se fijan con el sindicato.'),

  h1('Responsables'),
  p('Los nombres se completan en la fase 1. Una misma persona puede cubrir más de un rol.', { run: { color: C.texto2 } }),
  tabla(['Rol', 'Qué hace', 'Nombre'], [
    { grupo: 'Por La Bancaria' },
    ['**Autoridad responsable del proyecto**', 'Aprueba alcance y prioridades, destraba decisiones y recibe los informes de cada fase.', '[completar]'],
    ['**Referente operativo**', 'Secretaría gremial o administración. Contraparte diaria: coordina talleres y valida la configuración.', '[completar]'],
    ['**Referente técnico**', 'Entrega el padrón y los datos, y acuerda el canal seguro.', '[completar]'],
    ['**Referente de convenio y liquidación**', 'Conceptos, escalas y recibos de muestra; actualiza las escalas en cada paritaria.', '[completar]'],
    ['**Comunicación y prensa**', 'Marca, novedades y lanzamiento a los afiliados.', '[completar]'],
    ['**Asesoría legal**', 'Acuerdo de tratamiento de datos y textos legales de la app.', '[completar]'],
    ['**Referentes de seccional y delegados**', 'Acompañan a los afiliados del piloto y de cada oleada.', '[completar]'],
    { grupo: 'Por Colm3na' },
    ['**Dirección del proyecto**', 'Conduce el plan, presenta en cada hito y lleva el registro de decisiones.', '[completar]'],
    ['**Implementación funcional**', 'Talleres, configuración junto al sindicato, capacitación, guías y mesa de ayuda.', '[completar]'],
    ['**Desarrollo y datos**', 'Carga del padrón, entornos, seguridad, ajustes y soporte técnico.', '[completar]'],
    ['**Coordinación institucional y administración**', 'Relación con las autoridades, acuerdos y contrato.', '[completar]'],
  ], [3000, 4638, 2000]),
  destacado('**Privacidad del afiliado.** La afiliación sindical es un dato sensible (Ley 25.326). El sindicato es el responsable de la base y Colm3na la gestiona como encargado del tratamiento. El sindicato ve con nombre solo los recibos que el afiliado decide enviarle; el resto suma a los indicadores sin identificar a nadie.'),

  h1('Datos para el alta de afiliados'),
  tabla(['Dato', 'Para qué sirve', 'Necesidad'], [
    ['CUIL', 'Identifica al afiliado en toda la plataforma; con él se registra', 'Imprescindible'],
    ['Apellido y nombre', 'Credencial, padrón y comunicaciones', 'Imprescindible'],
    ['Provincia y localidad', 'Agrupar y dirigir comunicaciones por zona', 'Imprescindible'],
    ['Seccional', 'Quién lo atiende y qué operadores pueden verlo', 'Muy recomendable'],
    ['Banco empleador (CUIT)', 'Comparar por empleador y enviar avisos por banco', 'Muy recomendable'],
    ['Correo electrónico', 'Invitación, recuperación de clave y confirmación de identidad', 'Muy recomendable'],
    ['Celular', 'Invitación y contacto', 'Recomendable'],
    ['Domicilio completo', 'Ubicarlo en el mapa y sugerirle la seccional más cercana', 'Opcional'],
    ['Fecha de afiliación, n.º de afiliado', 'Antigüedad gremial y datos de la credencial', 'A definir'],
  ], [2900, 4738, 2000]),
  p('Formato: una planilla con una fila por afiliado y CUIL válidos sin repetir, más un criterio para informar altas y bajas cada mes. Para los operadores del panel: nombre, CUIL, correo, seccional y área de cada uno.', { spacing: { before: 80 }, run: { color: C.texto2 } }),

  h1('Indicadores del piloto'),
  tabla(['Indicador', 'Meta propuesta'], [
    ['Afiliados del piloto que ingresaron', '70 % o más'],
    ['Verificaron al menos un recibo', '50 % o más'],
    ['Recibos leídos bien (muestra revisada)', '90 % o más'],
    ['Trámites respondidos en 3 días hábiles', '80 % o más'],
    ['Notificaciones leídas en 7 días', '50 % o más'],
    ['Incidencias críticas abiertas al cierre', 'Ninguna'],
  ], [7138, 2500]),

  h1('Riesgos y cómo se contienen'),
  tabla(['Riesgo', 'Cómo se contiene'], [
    ['Datos que llegan tarde', 'Lista mínima para arrancar y carga por partes'],
    ['Cada banco arma su recibo distinto', 'Recibos de muestra de todos los bancos del piloto'],
    ['Nueva escala por paritaria', 'Un responsable la carga con su vigencia'],
    ['Referentes sin tiempo', 'Tiempo asignado y reunión semanal fija'],
    ['Baja adopción', 'Delegados, ayuda en el primer ingreso y mensajes claros sobre privacidad'],
  ], [3800, 5838]),

  destacado('**Cómo sigue este documento.** Esta versión 0.1 es la base para la reunión con las autoridades. Con lo que se acuerde ahí se arma la versión 1, que el sindicato aprueba al cierre de la fase 1 con nombres, prioridades y fechas. Desde entonces, toda decisión que cambie alcance, plazos o datos personales queda registrada con fecha y con quién la tomó.'),
];

// =====================================================================
// HOJA GUÍA DE LA REUNIÓN
// =====================================================================
const guia = [
  ...encabezado('Hoja guía · Reunión con autoridades · octubre 2026', 'Reunión con las autoridades de La Bancaria'),
  instruccion(INSTRUCCION('1 hoja A4')),
  etiquetado('Objetivo', 'acordar en grande cómo se implementa Colm3na en la Asociación Bancaria, quién lo conduce del lado del sindicato y qué necesita cada parte para que el sindicato pruebe la plataforma con sus propios datos en la semana 4.'),
  tabla(['Duración sugerida', 'Participan', 'Fecha', 'Lugar'],
    [['90 minutos', 'Secretaría General o Comisión Directiva, secretarías involucradas y Colm3na', '[completar]', '[completar]']],
    [1900, 4338, 1700, 1700]),

  h1('Orden del día'),
  tabla(['N.º', 'Tema', 'Minutos'], [
    ['1', 'Apertura y objetivo de la reunión', '5'],
    ['2', 'Demostración con un recibo bancario', '15'],
    ['3', 'El plan en seis fases y su calendario', '15'],
    ['4', 'Funcionalidades prioritarias', '15'],
    ['5', 'Datos disponibles para el alta de afiliados', '10'],
    ['6', 'Privacidad y protección de datos personales', '10'],
    ['7', 'Responsables y forma de trabajo', '10'],
    ['8', 'Acuerdos y próximos pasos', '10'],
    ['', '**Total**', '**90**'],
  ], [900, 7238, 1500]),

  h2('Mensajes clave'),
  vineta('**Producto que ya funciona:** se configura con el CCT 18/75.'),
  vineta('**El afiliado decide** qué recibos comparte con el sindicato.'),
  vineta('**Semana 4:** el sindicato prueba con sus propios datos.'),

  h1('Lo que buscamos acordar'),
  casilla('Aval al enfoque por fases y fecha tentativa del lanzamiento.'),
  casilla('Autoridad responsable del proyecto y referente operativo para el día a día.'),
  casilla('Referentes técnico, de convenio y liquidación, de comunicación y legal.'),
  casilla('Funcionalidades para el piloto y para después.'),
  casilla('Alcance del piloto: seccionales, bancos y cantidad de afiliados, entre 50 y 500.'),
  casilla('Qué datos del padrón hay, en qué formato y para cuándo.'),
  casilla('Cómo se verifica la identidad del afiliado cuando se registra.'),
  casilla('Quién revisa y firma el acuerdo de tratamiento de datos personales.'),
  casilla('Quién comunica a los afiliados y por qué canales: delegados, prensa, redes.'),
  destacado('**Verificación de identidad, de menor a mayor exigencia:** CUIL en el padrón · correo confirmado · recibo propio verificado por la plataforma · presencial en la seccional.'),

  h1('Funcionalidades prioritarias'),
  p('En la hoja impresa cada fila lleva casilleros Piloto / Después / No, con la propuesta de Colm3na marcada en color.', { run: { color: C.texto2, size: 18, italics: true } }),
  tabla(['Funcionalidad', 'Propuesta de Colm3na'], [
    { grupo: 'Para el afiliado' },
    ['Verificación del recibo de sueldo', 'Piloto'],
    ['Mis aportes (semáforo con ARCA)', 'Piloto'],
    ['Credencial digital', 'Piloto'],
    ['Novedades y notificaciones', 'Piloto'],
    ['Trámites con expediente', 'Piloto'],
    ['Beneficios', 'Después'],
    ['Encuestas', 'Después'],
    ['Consultas sobre el convenio', 'Después'],
    { grupo: 'Para el sindicato' },
    ['Panel Sindical y reportes', 'Piloto'],
    ['Avisos y trámites con los bancos', 'Después'],
  ], [6638, 3000]),

  h1('Datos disponibles para el alta de afiliados'),
  p('En la hoja impresa cada dato lleva casilleros Sí / Parcial / No, y debajo dos renglones: «Dónde está y en qué formato» y «Quién lo administra y cada cuánto se actualiza».', { run: { color: C.texto2, size: 18, italics: true } }),
  tabla(['Dato', 'Necesidad'], [
    ['CUIL', 'Imprescindible'],
    ['Apellido y nombre', 'Imprescindible'],
    ['Provincia y localidad', 'Imprescindible'],
    ['Seccional', 'Muy recomendable'],
    ['Banco empleador (CUIT)', 'Muy recomendable'],
    ['Correo electrónico', 'Muy recomendable'],
    ['Celular', 'Recomendable'],
    ['Domicilio completo', 'Opcional'],
    ['Fecha de afiliación, n.º de afiliado', 'A definir'],
  ], [6638, 3000]),

  h1('Próximos pasos'),
  h3('Después de la reunión, Colm3na'),
  vineta('Envía la versión 1 del plan con lo acordado.'),
  vineta('Envía el kit de relevamiento y el modelo de planilla del padrón.'),
  vineta('Envía el borrador del acuerdo de tratamiento de datos.'),
  vineta('Arma el espacio de La Bancaria en el entorno de prueba, con su marca.'),
  h3('Después de la reunión, La Bancaria'),
  vineta('Comunica los nombres de la autoridad responsable y de los referentes.'),
  vineta('Fija fecha y convocados para el lanzamiento.'),
  vineta('Envía logo, colores, CCT, escalas vigentes y estatuto.'),
  vineta('Pasa el borrador del acuerdo de datos a su asesoría legal.'),

  h1('Acuerdos y notas'),
  p('En la hoja impresa: renglones en blanco para completar durante la reunión.', { run: { color: C.texto2, size: 18, italics: true } }),
];

(async () => {
  const salidas = [
    [plan, 'Colm3na · Plan de implementación en La Bancaria · Borrador v0.1', 'Plan de implementación en La Bancaria', 'plan-implementacion-bancaria.docx'],
    [guia, 'Colm3na · Hoja guía para la reunión con las autoridades de La Bancaria · Borrador v0.1', 'Reunión con las autoridades de La Bancaria', 'guia-reunion-autoridades-bancaria.docx'],
  ];
  for (const [hijos, textoPie, titulo, archivo] of salidas) {
    const buf = await Packer.toBuffer(documento(hijos, textoPie, titulo));
    fs.writeFileSync(path.join(SALIDA, archivo), buf);
    console.log(archivo, buf.length, 'bytes');
  }
})();
