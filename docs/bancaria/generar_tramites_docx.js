// Genera las dos versiones Word del catálogo de trámites de La Bancaria:
//   tramites-bancaria.docx          completo, una ficha por gestión con su
//                                   recuadro de observaciones (~90 páginas)
//   tramites-bancaria-resumen.docx  resumen de 6 páginas para leer primero
// Las dos con control de cambios activado. Los datos salen de
// tramites-bancaria.json (lo mismo que la página HTML); los textos fijos
// (criterio, hallazgos, cambios) repiten los de tramites-bancaria.plantilla.html:
// si cambian allá, cambiarlos acá.
// Uso (desde la raíz del repo, con docx de npm):
//   node docs/bancaria/generar_tramites_docx.js [logo.png] [carpeta_salida]
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, AlignmentType, HeadingLevel, LevelFormat,
  Footer, PageNumber, TabStopType, LineRuleType, PageBreak,
} = require('docx');

const [LOGO = 'static/marca/logo_plataforma_claro.png', CARPETA = 'docs/bancaria'] = process.argv.slice(2);
const D = JSON.parse(fs.readFileSync(path.join(__dirname, 'tramites-bancaria.json'), 'utf8'));
const logo = fs.readFileSync(LOGO);

const C = { tinta: '0A1421', miel: 'F0A01E', mielOsc: 'A8660A', rojo: 'A0030B', papel2: 'F4F6F9',
  mielSuave: 'FDF1DC', linea: 'DBE2EA', texto: '16243A', texto2: '4C5D75', nota: 'FFFBEF' };
const FUENTE = 'Arial';
const ANCHO = 9638; // A4 con márgenes de 2 cm, en DXA

const EJES = [
  ['afil', 'Afiliación, datos e identidad'], ['recibo', 'Recibo, salario y convenio'],
  ['trabajo', 'Licencias, condiciones de trabajo y reclamos'], ['social', 'Acción social, turismo y beneficios'],
  ['form', 'Formación y cultura'], ['prev', 'Previsión y jubilados'],
  ['inst', 'Vida institucional y comunicación'], ['emp', 'Bancos empleadores, endeudamiento y vivienda'],
];
const MODALIDAD = { online: 'Online', 'semi-online': 'Semi-online', presencial: 'Presencial',
  no_dice: 'Existe, sin canal publicado', no_existe: 'Sin canal' };
const ESTRATEGIA = { crear_de_cero: 'Nuevo en Colm3na', reemplazar: 'Reemplaza el canal actual',
  puerta_y_encadenado: 'Puerta del afiliado (convive con su sistema)', informar: 'Informar' };
const NIVEL = { listo: 'Listo hoy', ajuste: 'Ajuste menor', desarrollo: 'Desarrollo', fuera: 'Fuera de alcance' };
// Lo mismo que SIN_FORMULARIO y ORDEN_KIT de generar_tramites.py.
const SIN_FORMULARIO = ['T07', 'T21', 'T08', 'T16', 'T23', 'T68', 'T73', 'T34', 'T76', 'T54'];
const ORDEN_KIT = ['social', 'recibo', 'trabajo', 'prev', 'afil', 'inst', 'form', 'emp'];

const AF = D.filter(x => x.dirigido_al_afiliado);
const NO_AF = D.filter(x => !x.dirigido_al_afiliado);
const porId = Object.fromEntries(D.map(x => [x.id, x]));
const contar = (lista, f) => lista.reduce((a, x) => { const k = f(x); a[k] = (a[k] || 0) + 1; return a; }, {});
const cm = contar(AF, x => x.hoy.modalidad), ce = contar(AF, x => x.colm3na.estrategia), cn = contar(AF, x => x.colm3na.nivel);
const ordenados = [...D].sort((a, b) => ORDEN_KIT.indexOf(a.eje) - ORDEN_KIT.indexOf(b.eje));
const KIT = ordenados.filter(x => x.kit === 'kit').map(x => x.id);
const SEG = ordenados.filter(x => x.kit === 'segunda').map(x => x.id);
const sinCanal = (cm.no_existe || 0) + (cm.no_dice || 0);

// ---------- helpers ----------
const r = (text, o = {}) => new TextRun({ text, ...o });
const p = (children, o = {}) => new Paragraph({ children: Array.isArray(children) ? children : [r(children)], spacing: { after: 120 }, ...o });
const h1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [r(t)], pageBreakBefore: true });
const h2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [r(t)], keepNext: true });
const h3 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [r(t)], keepNext: true });
const vineta = (children) => new Paragraph({ children: Array.isArray(children) ? children : [r(children)], numbering: { reference: 'vinetas', level: 0 }, spacing: { after: 80 } });
const numerada = (children, ref) => new Paragraph({ children, numbering: { reference: ref, level: 0 }, spacing: { after: 100 } });
const etiq = (e, t, o = {}) => p([r(e + ': ', { bold: true, color: C.mielOsc }), r(t, o)], { spacing: { after: 100 } });
const gris = (t) => r(t, { color: C.texto2 });

const linea = { style: BorderStyle.SINGLE, size: 4, color: C.linea };
const bordes = { top: linea, bottom: linea, left: linea, right: linea };
function celda(parrafos, ancho, fill) {
  return new TableCell({ children: parrafos, width: { size: ancho, type: WidthType.DXA }, borders: bordes,
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    shading: fill ? { type: ShadingType.CLEAR, fill, color: 'auto' } : undefined });
}
function tabla(cab, filas, anchos) {
  const total = anchos.reduce((a, b) => a + b, 0);
  const fila = (cs, f) => new TableRow({ children: cs.map((t, i) => celda([p(Array.isArray(t) ? t : [r(t, f ? { bold: true, color: 'FFFFFF' } : {})], { spacing: { after: 0 } })], anchos[i], f ? C.tinta : undefined)), tableHeader: !!f });
  return new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: anchos, rows: [fila(cab, true), ...filas.map(f => fila(f))] });
}
// Recuadro para anotar: una celda con fondo cálido y renglones vacíos.
function observaciones(titulo = 'Mis observaciones', renglones = 3) {
  const vacios = Array.from({ length: renglones }, () => p([r('')], { spacing: { after: 160 } }));
  return [new Table({ width: { size: ANCHO, type: WidthType.DXA }, columnWidths: [ANCHO], rows: [new TableRow({ children: [
    new TableCell({ width: { size: ANCHO, type: WidthType.DXA },
      borders: { top: { style: BorderStyle.SINGLE, size: 4, color: C.miel }, bottom: { style: BorderStyle.SINGLE, size: 4, color: C.miel },
        left: { style: BorderStyle.SINGLE, size: 18, color: C.miel }, right: { style: BorderStyle.SINGLE, size: 4, color: C.miel } },
      shading: { type: ShadingType.CLEAR, fill: C.nota, color: 'auto' }, margins: { top: 80, bottom: 80, left: 160, right: 120 },
      children: [p([r(titulo, { bold: true, color: C.mielOsc, size: 20 })], { spacing: { after: 60 } }), ...vacios] })] })] }),
  p('', { spacing: { after: 200 } })];
}

// ---------- una gestión ----------
function gestion(x) {
  const h = x.hoy, c = x.colm3na;
  const marcas = [`Hoy: ${MODALIDAD[h.modalidad]}`, `Colm3na: ${ESTRATEGIA[c.estrategia]}`, NIVEL[c.nivel]];
  if (x.kit === 'kit') marcas.push('Kit de inicio');
  if (x.kit === 'segunda') marcas.push('Segunda tanda');
  if (h.confianza !== 'verificado') marcas.push('Deducido');
  const out = [
    h2(`${x.id} · ${x.nombre}`),
    p([r(marcas.join('  ·  '), { bold: true, color: C.rojo, size: 20 })], { spacing: { after: 60 }, keepNext: true }),
    p([gris(x.quien)], { spacing: { after: 100 }, keepNext: true }),
  ];
  if (x.incluye && x.incluye.length) out.push(p([r('Incluye: ' + x.incluye.join(' · '), { italics: true, color: C.texto2 })]));
  out.push(h3('Hoy'), p(h.circuito));
  if (h.requisitos) out.push(etiq('Requisitos', h.requisitos));
  if (h.sistema_interno) out.push(etiq('Sistema interno', h.sistema_interno));
  out.push(etiq('Fuentes', (h.fuentes && h.fuentes.length) ? h.fuentes.join('  ·  ') : 'sin fuente: no hay canal publicado', { color: C.texto2, size: 19 }));
  out.push(h3('En Colm3na'), p(c.propuesta));
  if (c.formulario) out.push(etiq('Formulario', c.formulario));
  if (c.encadenados) out.push(etiq('Formularios encadenados', c.encadenados));
  if (c.area) out.push(etiq('Área que lo atiende', c.area));
  if (c.falta) out.push(etiq('Qué falta', c.falta));
  if (x.kit_inicio && x.kit_inicio.por_que) out.push(etiq(x.kit_inicio.candidato ? 'Por qué al kit' : 'Para el kit', x.kit_inicio.por_que));
  if (x.validar_con_sindicato) out.push(etiq('Para validar con el sindicato', x.validar_con_sindicato));
  out.push(...observaciones());
  return out;
}
// Cada lista del kit numera desde 1: una referencia de numeración por lista.
const itemKit = (ref) => (id) => {
  const x = porId[id];
  return numerada([r(x.nombre, { bold: true }), r(`  (${x.id})`, { color: C.texto2 }), r(' — ' + x.kit_inicio.por_que)], ref);
};

// ---------- contenido ----------
const cuerpo = [];
// Portada
cuerpo.push(
  new Paragraph({ children: [new ImageRun({ type: 'png', data: logo, transformation: { width: 170, height: 46 } })], spacing: { after: 360 } }),
  p([r('ASOCIACIÓN BANCARIA · VERSIÓN 2, VERIFICADA FILA POR FILA · OCTUBRE 2026', { bold: true, color: C.mielOsc, size: 20, characterSpacing: 20 })]),
  new Paragraph({ heading: HeadingLevel.TITLE, children: [r('Trámites de La Bancaria en Colm3na')] }),
  p([r('Todo lo que un bancario, un jubilado o su familia le puede pedir al sindicato: cómo se hace hoy de verdad, y cómo lo reemplaza, lo complementa o lo crea Colm3na. Es la base para ofrecerle al sindicato un kit de inicio.', { size: 26 })], { spacing: { after: 240 } }),
  tabla(['Gestiones del afiliado', 'Online hoy', 'Sin canal publicado', 'Listas hoy en Colm3na'],
    [[String(AF.length), String(cm.online || 0), String(sinCanal), String(cn.listo || 0)]], [2410, 2409, 2410, 2409]),
  p('', { spacing: { after: 240 } }),
  h3('Cómo usar este documento'),
  vineta('Cada gestión termina con un recuadro «Mis observaciones»: escribí adentro lo que quieras.'),
  vineta('El control de cambios está activado: si corregís un texto, la corrección queda marcada. También podés usar comentarios de Word.'),
  vineta('Al final de cada sección hay un recuadro para ideas generales.'),
  vineta('La versión en línea, con filtros, es la página «Trámites de La Bancaria en Colm3na». Los datos de las dos salen del mismo archivo.'),
  h3('Contenido'),
  vineta('El criterio · Lo que hay que saber · Hoy y en Colm3na · Los sistemas de La Bancaria'),
  vineta('Propuesta de kit de inicio'),
  vineta(`Catálogo verificado: ${EJES.filter(([k]) => AF.some(x => x.eje === k)).map(([k, t]) => `${t} (${AF.filter(x => x.eje === k).length})`).join(', ')}`),
  vineta('Fuera del foco · Qué cambió respecto de la primera versión · Método y límites'),
  p([gris('Fuentes: labancaria.org entera (2.436 noticias, páginas, 46 fichas de beneficios, 13 publicaciones), el sitio de la Seccional Buenos Aires, los sistemas propios del sindicato leídos por dentro (sin usuario) y las grillas salariales firmadas. Uso interno.')], { spacing: { before: 240 } }),
);

// Criterio y hallazgos
cuerpo.push(h1('El criterio'), p([gris('Acordado antes de verificar. Ordena qué entra al informe y cómo se propone cada gestión.')]));
[['El foco es el afiliado', 'Servicios hacia el afiliado y pedidos del afiliado, de su familia y de los jubilados. Lo interno del sindicato queda aparte, al final.'],
 ['Los sistemas internos no se tocan', 'Si el sindicato ya usa un sistema propio, Colm3na pone la puerta del afiliado: el pedido, la respuesta y hasta los comprobantes de pago van por trámites encadenados, y el operador sigue cargando donde carga hoy.'],
 ['Online es online de verdad', 'Online solo si todo el circuito se resuelve por internet y la respuesta llega por el mismo medio. Si hay papel, pago en banco, paso por la sede o una respuesta por WhatsApp suelto, es semi-online.'],
 ['Verificado o deducido', 'Cada gestión dice de dónde sale. Lo que se deduce de la web y no está escrito como trámite lleva la marca «Deducido» y una pregunta para validar con el sindicato.'],
].forEach(([t, d]) => cuerpo.push(vineta([r(t + '. ', { bold: true }), r(d)])));
cuerpo.push(h2('Lo que hay que saber'));
[[`Online hay poco, y es casi todo para informarse`, `De ${AF.length} gestiones, ${cm.online || 0} son online: noticias, comunicados salariales, grillas, Dónde voto, la encuesta nacional, los cursos de Bancar. Lo único que el afiliado tramita online es actualizar sus datos en Tus Datos.`],
 [`Para ${sinCanal} no hay a quién pedir`, 'Reclamos por el sueldo o las condiciones de trabajo, denuncias, licencias, accidentes, consultas previsionales de jubilados: la web muestra la acción colectiva del sindicato, pero no un canal individual. La única guía de contacto («guardia gremial») es de marzo de 2020, armada para la cuarentena.'],
 ['Turismo: el sistema es de las seccionales', 'reservasturismo.bancaria.org.ar lo usan los operadores, no el afiliado. Colm3na no lo reemplaza: el afiliado pide la reserva en la app y recibe por el chat del expediente la boleta, sube el comprobante y sigue el estado. La seccional sigue cargando en su sistema.'],
 ['El recibo: lo que hay y lo que falta', 'Hoy Colm3na controla para La Bancaria los aportes de ley con sus topes, el tope del 2% de cargas sindicales y la cuota. Controlar el CCT 18/75 (básico por categoría, ROE, Día del Bancario) necesita la grilla del mes como parámetro y reglas por categoría: es desarrollo. Las grillas se publican escaneadas, sin texto.'],
 ['Lo sensible pide un ajuste antes', 'Una denuncia por violencia tiene que verla solo el área de Género. Hoy los administradores ven todos los trámites, así que hace falta un tipo de trámite confidencial y un aviso push con texto neutro.'],
 ['Mucho depende de la seccional', 'El kit recién nacido, los guardapolvos, Megatlon, la vacuna antigripal y los talleres de cultura solo aparecen en la Seccional Buenos Aires. Colm3na tiene formularios por seccional; hay que preguntar qué ofrece cada una de las otras.'],
].forEach(([t, d]) => cuerpo.push(h3(t), p(d)));
cuerpo.push(...observaciones('Mis ideas sobre el criterio y los hallazgos', 4));

// Panorama
cuerpo.push(h2('Hoy y en Colm3na'));
cuerpo.push(tabla(['Cómo se hacen hoy', 'Gestiones'], Object.keys(MODALIDAD).filter(k => cm[k]).map(k => [MODALIDAD[k], String(cm[k])]), [6638, 3000]));
cuerpo.push(p('', { spacing: { after: 160 } }));
cuerpo.push(tabla(['Qué haría Colm3na', 'Gestiones'], Object.keys(ESTRATEGIA).filter(k => ce[k]).map(k => [ESTRATEGIA[k], String(ce[k])]), [6638, 3000]));
cuerpo.push(p('', { spacing: { after: 160 } }));
cuerpo.push(tabla(['Nivel en Colm3na', 'Gestiones'], Object.keys(NIVEL).filter(k => cn[k]).map(k => [NIVEL[k], String(cn[k])]), [6638, 3000]));

// Sistemas
cuerpo.push(h2('Los sistemas que La Bancaria ya tiene'), p([gris('Leídos por dentro: los textos y campos de sus pantallas, sus rutas y el manual del kit escolar. No se entró con usuario.')]));
cuerpo.push(tabla(['Sistema', 'Quién lo usa y cómo', '¿Online para el afiliado?', 'Relación con Colm3na'], [
  ['Tus Datos (tusdatos.bancaria.org.ar)', 'El afiliado: se registra con su DNI (se valida contra el padrón), mail, clave y captcha, y actualiza sus datos. Las seccionales ven lo que cambió, sin aprobar. La cuenta es la misma del kit escolar.', 'Sí, de punta a punta.', 'El perfil de Colm3na hace lo mismo con un solo dueño por CUIL; faltan algunos campos. Segunda tanda.'],
  ['Kit escolar (kitescolar.bancaria.org.ar)', 'El afiliado: datos, hijos o nietos con DNI y partida, una solicitud por chico con nivel, grado y certificado. Las seccionales revisan. Se retira en persona.', 'Semi-online.', 'Reemplazable, pero el portal guarda la familia de un año a otro y Colm3na todavía no tiene grupo familiar. Segunda tanda.'],
  ['Reservas de turismo (reservasturismo.bancaria.org.ar)', 'Solo las seccionales: eligen la seccional y ponen su clave, tipean el n.º de afiliado, cargan la solicitud, generan la boleta y suben el comprobante. Otra instancia autoriza.', 'No.', 'Se queda. Colm3na pone la puerta del afiliado con trámites encadenados.'],
  ['Dónde voto (dondevoto.bancaria.org.ar)', 'El afiliado: DNI o n.º de afiliado, sexo y captcha. Devuelve seccional, banco, sucursal, dirección, urna, mapa y constancia.', 'Sí.', 'Se enlaza desde la app con el aviso de la elección.'],
  ['Formularios de Google (Seccional Buenos Aires)', 'El afiliado: presolicitud de afiliación, vacuna antigripal, torneo de ajedrez, propuestas de cultura. Después lo llaman o le escriben.', 'Semi-online.', 'Se reemplazan por trámites con expediente.'],
  ['Fundación Bancar (bancar.org.ar)', 'El afiliado: campus de cursos y un Google Form para quien se anota por primera vez. Es una entidad aparte.', 'Sí.', 'Se informa: noticia y aviso con el enlace.'],
], [1900, 3538, 1500, 2700]));
cuerpo.push(p('', { spacing: { after: 160 } }), ...observaciones('Mis observaciones sobre los sistemas', 3));

// Kit
cuerpo.push(h1('Propuesta de kit de inicio'), p([gris('Para conversar con el sindicato, no para imponer. Gestiones listas hoy, que hoy se hacen con papel, WhatsApp, un Google Form o sin canal, y que tocan a mucha gente o se repiten todo el año. Entre paréntesis, el código de su ficha en el catálogo.')]));
cuerpo.push(h2(`${KIT.length} formularios listos para el primer día`), ...KIT.map(itemKit('kit1')), ...observaciones('¿Qué sacaría, qué agregaría?', 3));
cuerpo.push(h2('Lo que el afiliado usa sin formulario nuevo'), ...SIN_FORMULARIO.map(itemKit('kit2')), ...observaciones('Mis observaciones', 2));
cuerpo.push(h2(`Segunda tanda: ${SEG.length} gestiones que piden un ajuste o conviven con lo que ya funciona`), ...SEG.map(itemKit('kit3')), ...observaciones('Mis observaciones', 2));

// Catálogo
EJES.forEach(([k, t], i) => {
  const items = AF.filter(x => x.eje === k);
  if (!items.length) return;
  const n = contar(items, x => x.colm3na.nivel);
  cuerpo.push(h1(i === 0 ? `Catálogo verificado · ${t}` : t),
    p([gris(`${items.length} gestiones · ` + Object.keys(NIVEL).filter(z => n[z]).map(z => `${n[z]} ${NIVEL[z].toLowerCase()}`).join(' · '))]));
  items.forEach(x => cuerpo.push(...gestion(x)));
});

// Cierre
cuerpo.push(h1('Fuera del foco'), p([gris('Aparecen en la web pero no son gestiones del afiliado.')]));
NO_AF.forEach(x => cuerpo.push(vineta([r(x.nombre + ': ', { bold: true }), r(x.colm3na.propuesta)])));
cuerpo.push(h2('Qué cambió respecto de la primera versión'));
[['Turismo', 'La primera versión decía que había «un sistema completo de reservas». Es un sistema interno de las seccionales; para el afiliado la reserva sigue siendo semi-online.'],
 ['Tus Datos', 'Es online de punta a punta y no tiene paso de aprobación del sindicato. Comparte la cuenta con el kit escolar.'],
 ['El recibo', 'El control del CCT 18/75 no está listo, es desarrollo. El «salario inicial» de los comunicados es el conformado, no el básico (agosto 2026: básico $1.642.764,63, conformado $2.505.061,24). Los adicionales hoy son montos fijos y el ROE sale de una tabla por tramos. La demo de La Bancaria tenía ese error y se corrigió el mismo día con la grilla firmada (grilla_bancaria.py).'],
 ['Denuncias por violencia', 'Pasan de «listo» a «ajuste»: hoy los administradores ven todos los trámites. El protocolo interno de 2023 es para la gente del sindicato; la violencia en el banco va por los protocolos de cada banco.'],
 ['Guardia gremial', 'Era el canal de emergencia de la cuarentena de 2020, no un servicio vigente.'],
 ['Previsión', 'La «clave de la seguridad social» es lo que pide ANSES para su web, no lo que pide el sindicato. Ningún formulario de Colm3na pide claves.'],
 ['Altas, fusiones y bajas', 'Se agregaron 17 gestiones que faltaban y se fusionaron o sacaron 11 que estaban repetidas o no correspondían.'],
].forEach(([t, d]) => cuerpo.push(vineta([r(t + '. ', { bold: true }), r(d)])));
cuerpo.push(h2('Método y límites'),
  p('Primera pasada: toda labancaria.org por su API pública, el sitio de la Seccional Buenos Aires y los sistemas propios del sindicato. Verificación: cinco revisiones independientes, una por tema, volvieron sobre cada gestión, releyeron las fuentes, abrieron las páginas en vivo y leyeron el código de las pantallas de los sistemas, el manual del kit escolar, los formularios de Google, el formulario en papel del kit recién nacido y las grillas salariales firmadas.'),
  p('No se pudo ver: el interior de los sistemas con usuario, quién autoriza las reservas de turismo, y si los cambios de Tus Datos pasan solos al padrón del sindicato. Antes de usarlo afuera, validar con Acción Social, Previsión, Acción Gremial y DDHH qué gestiones existen hoy, en qué seccionales y por qué canal entran.'),
  ...observaciones('Ideas generales', 6));


// =====================================================================
// RESUMEN (6 páginas): lo mismo, en tablas; el detalle queda en el completo
// =====================================================================
const T = 20; // letra de las tablas del resumen: 10 pt
const rt = (text, o = {}) => r(text, { size: T, ...o });
// Tabla compacta: celdas con texto o con [runs]; filas {grupo} ocupan todo el ancho.
function tablaR(cab, filas, anchos) {
  const total = anchos.reduce((a, b) => a + b, 0);
  const cel = (contenido, ancho, o = {}) => new TableCell({
    width: { size: ancho, type: WidthType.DXA }, borders: bordes, columnSpan: o.span,
    margins: { top: 25, bottom: 25, left: 90, right: 90 },
    shading: o.fill ? { type: ShadingType.CLEAR, fill: o.fill, color: 'auto' } : undefined,
    children: [new Paragraph({ spacing: { after: 0, line: 252, lineRule: LineRuleType.AUTO },
      children: Array.isArray(contenido) ? contenido : [rt(String(contenido), o.run || {})] })] });
  const filaCab = new TableRow({ tableHeader: true, children: cab.map((t, i) => cel(t, anchos[i], { fill: C.tinta, run: { bold: true, color: 'FFFFFF' } })) });
  const cuerpoT = filas.map(f => f.grupo
    ? new TableRow({ cantSplit: true, children: [cel(f.grupo, total, { span: anchos.length, fill: C.papel2, run: { bold: true, color: C.texto } })] })
    : new TableRow({ cantSplit: true, children: f.map((t, i) => cel(t, anchos[i])) }));
  return new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: anchos, rows: [filaCab, ...cuerpoT] });
}
const espacio = (n = 120) => p('', { spacing: { after: n } });
const corto = (t) => String(t).split(/\s*[(;]/)[0].trim();
// Corta en el último espacio antes del límite, con puntos suspensivos.
const recorte = (t, n) => t.length <= n ? t : t.slice(0, t.lastIndexOf(' ', n)).replace(/[,:.]$/, '') + '…';
const h2r = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [r(t)], keepNext: true, spacing: { before: 200, after: 80 } });
const NIVEL_CORTO = { listo: 'Listo', ajuste: 'Ajuste', desarrollo: 'Desarrollo', fuera: 'Fuera' };
const HOY_CORTO = { online: 'Online', 'semi-online': 'Semi-online', presencial: 'Presencial', no_dice: 'Existe, sin canal', no_existe: 'Sin canal' };
const ESTR_CORTA = { crear_de_cero: 'Nuevo', reemplazar: 'Reemplaza', puerta_y_encadenado: 'Puerta', informar: 'Informar' };

const resumen = [];
resumen.push(
  new Paragraph({ children: [new ImageRun({ type: 'png', data: logo, transformation: { width: 130, height: 35 } })], spacing: { after: 160 } }),
  p([r('ASOCIACIÓN BANCARIA · RESUMEN DEL CATÁLOGO VERIFICADO · OCTUBRE 2026', { bold: true, color: C.mielOsc, size: 18, characterSpacing: 20 })], { spacing: { after: 60 } }),
  new Paragraph({ heading: HeadingLevel.TITLE, children: [r('Trámites de La Bancaria en Colm3na')], spacing: { after: 100 } }),
  p([r('Resumen para leer primero. Cada gestión lleva su código (T01, T39…): el detalle, las fuentes y el recuadro para anotar están en el Word completo.', { color: C.texto2 })]),
  tablaR(['Gestiones del afiliado', 'Online hoy', 'Sin canal publicado', 'Listas hoy en Colm3na'],
    [[String(AF.length), String(cm.online || 0), String(sinCanal), String(cn.listo || 0)]], [2410, 2409, 2410, 2409]),
  h2r('Lo que hay que saber'),
);
[[`Online hay poco. `, `${cm.online || 0} de ${AF.length} gestiones son online, y casi todas son para informarse. Lo único que el afiliado tramita online es Tus Datos.`],
 [`Para ${sinCanal} no hay a quién pedir. `, 'Reclamos, denuncias, licencias, accidentes, consultas de jubilados: la web muestra acción colectiva, no un canal individual. Es el campo más grande.'],
 ['Turismo es interno. ', 'El sistema de reservas lo usan las seccionales. Colm3na pone la puerta del afiliado: pedido, boleta y comprobante por trámites encadenados.'],
 ['El recibo. ', 'Hoy se controlan los aportes de ley, el tope del 2% y la cuota. Controlar el CCT 18/75 necesita la grilla del mes como parámetro: es desarrollo.'],
 ['Lo sensible pide un ajuste. ', 'Hoy los administradores ven todos los trámites; una denuncia por violencia necesita un trámite confidencial y un aviso con texto neutro.'],
 ['Mucho depende de la seccional. ', 'Kit recién nacido, guardapolvos, Megatlon, vacuna y cultura solo aparecen en la Seccional Buenos Aires.'],
].forEach(([t, d]) => resumen.push(vineta([r(t, { bold: true }), r(d)])));
resumen.push(h2r('El criterio'), p([r('Foco en el afiliado, su familia y los jubilados. Los sistemas internos del sindicato no se tocan: Colm3na pone la puerta. Online solo si lo es de punta a punta. Cada gestión dice si está verificada o deducida.')]));

// Hoy y en Colm3na: una tabla de dos columnas pares
const hoyFilas = Object.keys(MODALIDAD).filter(k => cm[k]).map(k => [MODALIDAD[k], String(cm[k])]);
const colFilas = Object.keys(ESTRATEGIA).filter(k => ce[k]).map(k => [ESTRATEGIA[k], String(ce[k])]);
const nFilas = Math.max(hoyFilas.length, colFilas.length);
resumen.push(h2r('Hoy y en Colm3na'), tablaR(['Cómo se hacen hoy', 'N.º', 'Qué haría Colm3na', 'N.º'],
  Array.from({ length: nFilas }, (_, i) => [...(hoyFilas[i] || ['', '']), ...(colFilas[i] || ['', ''])]), [3200, 900, 4638, 900]),
  p([rt(`En Colm3na: ${cn.listo || 0} listas hoy, ${cn.ajuste || 0} con un ajuste menor y ${cn.desarrollo || 0} que necesitan desarrollo.`, { color: C.texto2 })], { spacing: { before: 80, after: 80 } }));

resumen.push(h2r('Los sistemas que La Bancaria ya tiene'), tablaR(['Sistema', 'Quién lo usa', 'Relación con Colm3na'], [
  ['Tus Datos', 'El afiliado, online de punta a punta. Las seccionales ven los cambios, sin aprobar.', 'Perfil de Colm3na; faltan campos. Segunda tanda.'],
  ['Kit escolar', 'El afiliado lo pide online; se retira en persona.', 'Reemplazable cuando haya grupo familiar. Segunda tanda.'],
  ['Reservas de turismo', 'Solo las seccionales. El afiliado entra por seccional, mail o WhatsApp y paga en el banco.', 'Se queda. Colm3na pone la puerta con encadenados.'],
  ['Dónde voto', 'El afiliado, online.', 'Se enlaza desde la app con el aviso de la elección.'],
  ['Formularios de Google', 'El afiliado (afiliación, vacuna, torneos, cultura); la respuesta llega por fuera.', 'Se reemplazan por trámites con expediente.'],
  ['Fundación Bancar', 'El afiliado, online. Entidad aparte.', 'Se informa con noticia y aviso.'],
], [2000, 4038, 3600]));

// Kit
const filaKit = (id, i) => { const x = porId[id]; return [String(i + 1), [rt(x.nombre, { bold: true }), rt(`  ${x.id}`, { color: C.texto2 })], corto(x.colm3na.area) || '—', MODALIDAD[x.hoy.modalidad]]; };
resumen.push(h2r(`Kit de inicio: ${KIT.length} formularios listos para el primer día`),
  tablaR(['#', 'Gestión', 'Área que lo atiende', 'Hoy'], KIT.map(filaKit), [500, 4438, 2900, 1800]));
resumen.push(h2r('Lo que el afiliado usa sin formulario nuevo'),
  tablaR(['#', 'Gestión', 'Cómo', 'Hoy'], SIN_FORMULARIO.map((id, i) => { const x = porId[id]; return [String(i + 1), [rt(x.nombre, { bold: true }), rt(`  ${x.id}`, { color: C.texto2 })], ESTRATEGIA[x.colm3na.estrategia], MODALIDAD[x.hoy.modalidad]]; }), [500, 4438, 2900, 1800]));
resumen.push(h2r(`Segunda tanda: ${SEG.length} gestiones con un ajuste o que ya funcionan online`),
  tablaR(['#', 'Gestión', 'Qué falta', 'Nivel'], SEG.map((id, i) => { const x = porId[id]; return [String(i + 1), [rt(x.nombre, { bold: true }), rt(`  ${x.id}`, { color: C.texto2 })], recorte(corto(x.colm3na.falta || x.colm3na.propuesta), 70), NIVEL_CORTO[x.colm3na.nivel]]; }), [500, 4338, 3800, 1000]));

// Las 81 de un vistazo
const vistazo = [];
EJES.forEach(([k, t]) => {
  const items = AF.filter(x => x.eje === k);
  if (!items.length) return;
  vistazo.push({ grupo: `${t} (${items.length})` });
  items.forEach(x => vistazo.push([x.id, x.nombre + (x.kit === 'kit' ? '  ★' : ''), HOY_CORTO[x.hoy.modalidad], ESTR_CORTA[x.colm3na.estrategia], NIVEL_CORTO[x.colm3na.nivel]]));
});
resumen.push(h2r(`Las ${AF.length} gestiones de un vistazo`),
  p([rt('★ = en el kit de inicio. Colm3na: Nuevo (hoy no hay canal), Reemplaza (papel, Google Form o WhatsApp), Puerta (convive con su sistema interno), Informar (aviso, noticia o enlace).', { color: C.texto2 })], { spacing: { after: 80 } }),
  tablaR(['Código', 'Gestión', 'Hoy', 'Colm3na', 'Nivel'], vistazo, [1100, 4250, 1800, 1300, 1188]));

resumen.push(h2r('Qué validar primero con el sindicato'));
['¿Qué servicios ofrece cada seccional? Varios solo aparecen en la Seccional Buenos Aires.',
 '¿Quién autoriza las reservas de turismo, y aceptan recibir el pedido y el comprobante por Colm3na?',
 '¿Cómo reciben hoy una denuncia de violencia, y aceptan que solo la vea el área de Género?',
 '¿Los cambios de Tus Datos pasan solos al padrón (SAF) o alguien los copia a mano?',
 '¿Nos pueden pasar las grillas salariales en planilla, en vez del escaneo firmado?',
].forEach(t => resumen.push(vineta(t)));
resumen.push(...observaciones('Mis observaciones', 2));

// ---------- documentos ----------
function pie(texto) {
  return new Footer({ children: [new Paragraph({
    tabStops: [{ type: TabStopType.RIGHT, position: ANCHO }],
    border: { top: { style: BorderStyle.SINGLE, size: 4, color: C.linea, space: 4 } },
    children: [r(texto, { size: 17, color: C.texto2 }), r('\tPágina ', { size: 17, color: C.texto2 }),
      new TextRun({ children: [PageNumber.CURRENT], size: 17, color: C.texto2 }), r(' de ', { size: 17, color: C.texto2 }),
      new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 17, color: C.texto2 })] })] });
}
function documento(children, { titulo, textoPie, letra }) {
  const numeracionKit = ['kit1', 'kit2', 'kit3'].map(reference => ({ reference, levels: [
    { level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { run: { bold: true, color: C.mielOsc }, paragraph: { indent: { left: 480, hanging: 360 } } } }] }));
  return new Document({
    creator: 'Colm3na', title: titulo, description: 'Versión 2, verificada',
    features: { trackRevisions: true },
    styles: {
      default: { document: { run: { font: FUENTE, size: letra, color: C.texto }, paragraph: { spacing: { line: 288, lineRule: LineRuleType.AUTO } } } },
      paragraphStyles: [
        { id: 'Title', name: 'Title', basedOn: 'Normal', next: 'Normal', run: { font: FUENTE, size: 48, bold: true, color: C.tinta }, paragraph: { spacing: { after: 200 } } },
        { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FUENTE, size: 36, bold: true, color: C.tinta }, paragraph: { spacing: { before: 120, after: 160 }, outlineLevel: 0, border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: C.miel, space: 4 } } } },
        { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FUENTE, size: 28, bold: true, color: C.tinta }, paragraph: { spacing: { before: 320, after: 80 }, outlineLevel: 1 } },
        { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FUENTE, size: 22, bold: true, color: C.mielOsc, allCaps: true }, paragraph: { spacing: { before: 160, after: 60 }, outlineLevel: 2 } },
      ],
    },
    numbering: { config: [
      { reference: 'vinetas', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { run: { color: C.mielOsc }, paragraph: { indent: { left: 400, hanging: 260 } } } }] },
      ...numeracionKit,
    ] },
    sections: [{
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } },
      footers: { default: pie(textoPie) },
      children,
    }],
  });
}
const salidas = [
  ['tramites-bancaria.docx', documento(cuerpo, { titulo: 'Trámites de La Bancaria en Colm3na', textoPie: 'Colm3na · Trámites de La Bancaria · versión 2 · uso interno', letra: 24 })],
  ['tramites-bancaria-resumen.docx', documento(resumen, { titulo: 'Trámites de La Bancaria en Colm3na (resumen)', textoPie: 'Colm3na · Trámites de La Bancaria · resumen · uso interno', letra: 22 })],
];
salidas.forEach(([nombre, d]) => Packer.toBuffer(d).then(b => {
  fs.writeFileSync(path.join(CARPETA, nombre), b);
  console.log(`${nombre}: ${AF.length} gestiones, kit ${KIT.length} + ${SEG.length}`);
}));
