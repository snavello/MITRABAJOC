# Genera docs/bancaria/tramites-bancaria.html (el informe de trámites de La
# Bancaria) a partir de la lista de abajo y de tramites-bancaria.plantilla.html.
# Los totales por nivel y por eje salen de la misma lista: no hay números a mano.
# Para corregir una fila, se edita acá y se corre:
#   python docs/bancaria/generar_tramites.py
# Fuente: relevamiento de labancaria.org y de la Seccional Buenos Aires, 2026-10-13.
import collections
import html
from pathlib import Path

AQUI = Path(__file__).parent
SALIDA = AQUI / "tramites-bancaria.html"
PLANTILLA = AQUI / "tramites-bancaria.plantilla.html"

NIVELES = {
    "listo":      ("Listo hoy", "Se configura con lo que Colm3na ya tiene: un formulario de Trámites, una ficha de Beneficios, una notificación, una encuesta o una regla del recibo."),
    "ajuste":     ("Ajuste menor", "Necesita un cambio chico sobre un módulo existente: un campo más, un parámetro mensual, una entrada sin login."),
    "desarrollo": ("Desarrollo", "Necesita una pieza nueva (grupo familiar, cupos y pagos, comparar dos recibos). Está en las olas 2 y 3 del relevamiento."),
    "fuera":      ("Fuera de alcance", "Lo regula otra norma, es infraestructura física o vive en un sistema que no conviene reemplazar."),
}

EJES = [
    ("afil",   "Afiliación, datos e identidad"),
    ("recibo", "Recibo, salario y convenio"),
    ("trabajo","Licencias, condiciones de trabajo y reclamos"),
    ("social", "Acción social, turismo y beneficios"),
    ("form",   "Formación y cultura"),
    ("prev",   "Previsión y jubilados"),
    ("inst",   "Vida institucional y comunicación"),
    ("emp",    "Bancos empleadores y endeudamiento"),
]

# eje, nombre, quién, cómo se hace hoy, nivel, cómo lo resuelve Colm3na, origen (E explícito / I inferido), frecuencia, fuentes
T = []
def t(eje, nombre, quien, hoy, nivel, colm, origen, freq, *fuentes):
    T.append(dict(eje=eje, nombre=nombre, quien=quien, hoy=hoy, nivel=nivel, colm=colm, origen=origen, freq=freq, fuentes=fuentes))

# ---------------- Afiliación, datos e identidad
t("afil", "Solicitud de afiliación", "Bancario no afiliado",
  "Formulario web de labancaria.org (nombre, apellido, banco, provincia, ciudad, mail, teléfono) y Google Form de la Seccional Buenos Aires (DNI, banco, modalidad de trabajo). Después llama una persona y se firma en la seccional.",
  "ajuste", "Formulario de Trámites con los mismos campos más el recibo adjunto, que la IA lee para prellenar banco y categoría (P08). Falta una entrada sin login para quien no está en el padrón: hoy el registro exige estar en él.",
  "E", "Permanente; cada comunicado salarial cierra con «AFILIATE»",
  "https://labancaria.org/afiliate/", "https://www.bancariasba.com.ar/")
t("afil", "Actualización de datos personales («Tus Datos»)", "Afiliado",
  "Portal tusdatos.bancaria.org.ar con registro por mail. Pide documento, n.º de afiliado, CUIL, fecha de nacimiento, estado civil, nacionalidad, domicilio, celular, mail alternativo, banco, sucursal, domicilio de la sucursal, fecha de ingreso al banco y seccional. El sindicato tiene un listado filtrable por «actualizados / no actualizados».",
  "ajuste", "Perfil del afiliado (un solo dueño de los datos, por CUIL) y padrón del panel. Faltan en el perfil: fecha de ingreso al banco, sucursal, estado civil, nacionalidad, n.º de afiliado y un filtro «actualizó sus datos desde…» en Trabajadores.",
  "E", "Permanente", "https://tusdatos.bancaria.org.ar/")
t("afil", "Carnet de afiliado: emisión, reposición y uso", "Afiliado",
  "Carnet físico. Se exige para retirar el kit escolar, en Librería Hernández, Diarco, Megatlon, el viaje de bodas y para pedir el sepelio (n.º de afiliado). La web no dice cómo se pide ni cómo se repone.",
  "listo", "Credencial digital con QR verificable. La reposición deja de existir y el comercio verifica en el momento.",
  "I", "Cada vez que se usa un beneficio",
  "https://labancaria.org/beneficios/descuento-en-libreria-hernandez/", "https://www.bancariasba.com.ar/service/red-megatlon")
t("afil", "Reafiliación al jubilarse", "Recién jubilado",
  "Ficha «Cuando te jubiles REAFILIATE»: «No pierdas tu afiliación. Tu carnet vale». No dice canal ni requisitos.",
  "ajuste", "Trámite «Reafiliación» al área Previsión. Falta marcar en el padrón la condición (activo, jubilado) para que la credencial y los beneficios de jubilado (Megatlon sin cargo, 25% en Bahía Iguana) salgan solos (P03).",
  "E", "Una vez por persona", "https://labancaria.org/beneficios/cuando-te-jubiles-reafiliate/")
t("afil", "Reconocimiento de afiliado vitalicio (50 años)", "Sindicato (Previsión) y afiliado",
  "Acto anual con diploma y medalla entre septiembre y noviembre. No se publica cómo se arma la lista ni cómo se avisa.",
  "ajuste", "Con la fecha de afiliación en el padrón (un hecho, no un derivado), el panel lista a quienes cumplen y se les manda una notificación con la invitación.",
  "I", "Anual", "https://labancaria.org/emotivo-homenaje-a-las-y-los-afiliados-vitalicios/")
t("afil", "Carga del grupo familiar", "Afiliado",
  "Se repite en cada sistema: «Mis Familiares» del kit escolar (hijo o nieto, con DNI y partida), pasajeros con vínculo en reservas de turismo, actas de matrimonio y nacimiento para Megatlon familiar, cónyuge e hijos para el sepelio.",
  "desarrollo", "Grupo familiar en el padrón, con documentación y vencimientos (P05). Es la pieza que destraba kit escolar, turismo, Megatlon, sepelio y guardería sin volver a subir las partidas cada año.",
  "E", "Una vez, con actualizaciones", "https://kitescolar.bancaria.org.ar/", "https://reservasturismo.bancaria.org.ar/")

# ---------------- Recibo, salario y convenio
t("recibo", "Verificar el recibo contra el CCT 18/75", "Afiliado",
  "No existe. El afiliado compara a mano con las grillas, que se publican como adjunto (PDF o imagen) sin texto.",
  "listo", "Tu Recibo con los conceptos del CCT 18/75 ya modelados: coeficiente de antigüedad (art. 5), función y falla de caja como dos líneas (art. 22), título (art. 10), zona desfavorable (art. 25), computación (art. 14).",
  "I", "Mensual", "https://labancaria.org/grillas-actualizacion-salarial-11-09-26/")
t("recibo", "Controlar la actualización salarial del mes", "Afiliado",
  "Comunicado mensual entre el 11 y el 20 del mes siguiente, con un formato fijo: porcentaje del mes, acumulado, salario inicial, ROE y mínimo del Día del Bancario. El porcentaje rige «para todas las remuneraciones… incluyendo los adicionales». 2026: 2,9 · 2,9 · 3,4 · 2,6 · 2,1 · 1,9 · 2,1 · 1,7%.",
  "ajuste", "Un parámetro mensual del sindicato (inicial, ROE, porcentaje) que alimenta las reglas de control. Como el comunicado tiene siempre el mismo formato, se puede leer solo y el sindicato lo confirma.",
  "E", "Mensual", "https://labancaria.org/actualizacion-salarial-agosto-2026-17/")
t("recibo", "Salario inicial como piso de la escala", "Afiliado",
  "Se publica cada mes en la cabecera del comunicado (agosto 2026: $2.505.061,24).",
  "listo", "Regla de control: el básico no puede quedar debajo de inicial × coeficiente de la categoría del mes liquidado.",
  "E", "Mensual", "https://labancaria.org/actualizacion-salarial-julio-2026-21/")
t("recibo", "Participación en las ganancias (ROE)", "Afiliado",
  "Línea aparte del recibo, «según escala». Se paga solo si el sistema financiero supera 3,5 de rentabilidad (en septiembre de 2021 no se pagó).",
  "listo", "Regla de control: que la línea exista y coincida con el cuadro vigente. Los porcentajes sobre el inicial cambian (4,97% a fines de 2024, 2,89% desde julio de 2025), así que va como parámetro.",
  "E", "Mensual", "https://labancaria.org/para-tener-en-cuenta-consejo-directivo-plenario-de-secretarios-generales/")
t("recibo", "Cobro del retroactivo en el mes siguiente", "Afiliado",
  "«El retroactivo correspondiente se abonará junto con los salarios del mes de [N+1]».",
  "desarrollo", "Hay que comparar dos recibos seguidos de la misma persona: que en N+1 aparezca la diferencia del porcentaje sobre todos los conceptos de N. Es del motor de recibos v2.",
  "E", "Mensual", "https://labancaria.org/actualizacion-salarial-octubre-2025-23/")
t("recibo", "Compensación del Día del Bancario (6 de noviembre)", "Afiliado",
  "No remunerativa, pagada antes del 6/11, con un mínimo que cada comunicado actualiza (agosto 2026: $2.233.175,44, igual al 89,15% del inicial). La diferencia de octubre va con el sueldo de noviembre.",
  "ajuste", "Regla estacional en los recibos de octubre y noviembre: que figure como no remunerativa y supere mínimo × coeficiente. Más un aviso push a fines de octubre: «revisá que te la hayan pagado».",
  "E", "Anual", "https://labancaria.org/dia-del-bancario-a-no-laborable/", "https://labancaria.org/compensacion-dia-del-bancario-compensacion-minima-64-53040/")
t("recibo", "Gastos de conectividad por teletrabajo", "Teletrabajador",
  "No remunerativa y exenta de Ganancias, ajustada cada trimestre por el IPC de comunicaciones. Septiembre a noviembre de 2023: $389 por día, mínimo $3.501, mes completo $8.567.",
  "ajuste", "Regla: días remotos × monto, con mínimo y tope, en el rubro no remunerativo. El monto va como parámetro trimestral.",
  "E", "Mensual, ajuste trimestral", "https://labancaria.org/actualizacion-gastos-por-conectividad-2/")
t("recibo", "Pago de guardería (universal desde 2023)", "Madre o padre bancario",
  "Lo paga el banco; desde marzo de 2023 a madres y padres por igual. El trámite es ante el banco y la web no da requisitos.",
  "ajuste", "Consulta en el bot del convenio y regla de control del monto. Para saber a quién le corresponde hace falta el grupo familiar (P05).",
  "E", "Mensual mientras dure", "https://labancaria.org/acuerdo-salarial-2023/")
t("recibo", "Deducciones especiales de Ganancias", "Trabajador alcanzado",
  "Dictamen de 2023: ROE, falla de caja, viáticos y movilidad se deducen aparte, hasta el 40% del mínimo no imponible cada uno. Se cargan en ARCA (SIRADIG).",
  "desarrollo", "Hoy, una explicación en el bot del convenio. Controlar la retención del recibo es un cálculo impositivo completo que la app todavía no hace.",
  "E", "Anual con efecto mensual", "https://labancaria.org/impuesto-a-las-ganancias-historico-dictamen/")
t("recibo", "Consultar escalas, grillas y actas", "Afiliado, delegado, liquidador",
  "Posts «GRILLAS ACTUALIZACIÓN SALARIAL» con el contenido en un adjunto; actas desde 2016 por cámara (ABAPPRA, ADEBA, ABA, ABE) y acuerdos por banco.",
  "listo", "Se cargan en el bot del convenio (responde citando el acta) y cada actualización sale como noticia. Un simulador de sueldo por categoría es el paso siguiente (P14).",
  "E", "Mensual", "https://labancaria.org/categoria/actas/", "https://labancaria.org/categoria/otros-acuerdos/")
t("recibo", "Reclamo por liquidación incorrecta", "Afiliado",
  "No hay canal descripto: va por el delegado o la seccional. Hay conflictos registrados en Santander (2019 y 2026) y Supervielle (2021).",
  "listo", "Trámite «Reclamo de liquidación» con el recibo verificado adjunto. Iniciarlo con un clic desde la diferencia que marcó el recibo es un ajuste chico (P10).",
  "I", "Mensual o eventual", "https://labancaria.org/estado-de-alerta-banco-santander/")
t("recibo", "Reclamo de categoría", "Afiliado o comisión interna",
  "Por ejemplo, Santander tuvo que pasar a «2.º Jefe de Departamento de 2.ª» a los encargados de sucursales de 12 personas o menos, desde el 1/10/2025.",
  "listo", "Trámite con el recibo adjunto; el recibo ya muestra el básico contra el coeficiente de la antigüedad declarada.",
  "E", "A demanda", "https://labancaria.org/banco-santander-mesa-de-dialogo/")
t("recibo", "Encuadramiento en el CCT 18/75 (fintech, tercerizadas)", "Trabajador no encuadrado",
  "Reclamos colectivos: Nación Servicios (1.300 personas), Provincia Microempresas, Openbank, Mercado Pago, fintech del Banco del Chaco.",
  "ajuste", "Consulta para no afiliados con el recibo adjunto: muestra cuánto cobraría con el CCT 18/75. Usa la misma entrada sin login que la afiliación.",
  "E", "Eventual", "https://labancaria.org/provincia-microempresas-son-bancarios/")
t("recibo", "Traspaso por venta o fusión: que se respete la antigüedad", "Personal transferido",
  "Acuerdos por compra (Patagonia–Industrial y Columbia en 2026, Galicia–HSBC en 2024) que garantizan categoría, antigüedad y convenio.",
  "listo", "Notificación a los afiliados del banco vendido (se filtra por CUIT del empleador) y consulta por trámite. Verificar que el recibo nuevo conserve la antigüedad es comparar dos recibos: motor v2.",
  "E", "Eventual", "https://labancaria.org/acuerdo-asociacion-bancaria-banco-patagonia-por-la-compra-de-sucursales-del-bco-industrial/")
t("recibo", "Aportes de jubilación y obra social depositados", "Afiliado",
  "No existe.",
  "listo", "Mis aportes: el semáforo con el comprobante de ARCA. Ojo: los del Banco Provincia aportan a su propia caja (Ley 15.008), que ARCA no muestra.",
  "I", "Mensual", "https://labancaria.org/la-justicia-nos-dio-la-razon-ley-15008-cautelar-favorable/")
t("recibo", "Cuota sindical retenida contra la depositada", "Sindicato y afiliado",
  "No se publica nada. La cuota de afiliación es casi el 60% de los ingresos del gremio y la cuota solidaria el 26% (2022).",
  "desarrollo", "Cruzar la retención que aparece en cada recibo con lo que el banco depositó (P15).",
  "I", "Mensual", "https://labancaria.org/xlix-congreso-nacional-bancario-clausura/")

# ---------------- Licencias, condiciones de trabajo y reclamos
t("trabajo", "Consultas sobre licencias", "Afiliado",
  "El convenio y los acuerdos por banco las crean: estudio, licencias extendidas, violencia de género, y las ampliadas del Banco Nación en 2023 (familiar grave, congelamiento de óvulos, gestación por sustitución, regreso progresivo, trámites personales). La web no da días ni requisitos.",
  "listo", "Bot del convenio con el CCT y las actas cargadas, más un trámite de consulta al área Gremial.",
  "E", "A demanda", "https://labancaria.org/banco-nacion-ampliacion-de-licencias-y-beneficios-para-los-y-las-trabajadoras/")
t("trabajo", "Denuncia por violencia, acoso o discriminación", "Trabajador afectado o testigo",
  "Protocolo interno aprobado en 2023 y protocolos firmados banco por banco, extendidos a toda la actividad en 2021. La web no publica canal, plazos ni reglas de confidencialidad.",
  "listo", "Trámite que va solo al área de DDHH, Género e Igualdad (con Áreas V2 nadie más lo ve) y conversación con la afiliada en el hilo del expediente. Conviene revisar con la secretaría qué datos pide.",
  "E", "Permanente", "https://labancaria.org/libros/protocolo-interno-de-actuacion-para-situaciones-de-discriminacion-acoso-y-violencia-laboral-y-violencia-por-razones-de-genero-2/")
t("trabajo", "Consulta por consumo problemático (Banco Nación)", "Trabajador, compañero o delegado",
  "Convenio BNA–SEDRONAR–AB (2023) con mesa interdisciplinaria. El circuito no se publica.",
  "listo", "Trámite confidencial al área que el sindicato designe, solo para afiliados del BNA.",
  "I", "Permanente", "https://labancaria.org/convenio-consumo-problematico-en-el-ambito-laboral/")
t("trabajo", "Higiene y seguridad en el lugar de trabajo", "Trabajador o delegado",
  "Comisión de Higiene y Seguridad por entidad prevista en el convenio (acuerdo de 2013) y comités mixtos provinciales.",
  "listo", "Trámite con fotos adjuntas; la encuesta de condiciones por banco arma el mapa de riesgos (P30).",
  "E", "Permanente", "https://labancaria.org/obligatorio-cuidar-para-cuidar/")
t("trabajo", "Incidente de seguridad (asalto, balacera, falta de custodia)", "Personal de la sucursal",
  "La AB denuncia ante el BCRA y la Comisión Permanente de Seguridad Bancaria. Hubo un compañero asesinado en 2020.",
  "listo", "Trámite urgente con aviso al área. El botón SOS y la ficha de emergencias son la propuesta P29.",
  "I", "Eventual", "https://labancaria.org/seguridad-bancaria-nuestra-posicion/")
t("trabajo", "Accidente de trabajo o enfermedad profesional", "Trabajador o su familia",
  "La web no describe el trámite ante la ART; la ley de teletrabajo presume accidente el ocurrido trabajando en casa.",
  "listo", "Trámite de asesoramiento con la documentación adjunta.",
  "I", "Eventual", "https://labancaria.org/se-sanciono-la-ley-sobre-teletrabajo/")
t("trabajo", "Consulta antes de firmar un retiro voluntario o un despido", "Trabajador presionado",
  "Oleadas en 2024 a 2026 (plan prejubilatorio del BNA desde 58 años mujeres y 63 varones, Santander, Supervielle). «No vamos a tolerar que presionen a ningún trabajador».",
  "listo", "Trámite al área Gremial que, si la persona está cerca de jubilarse, se pasa a Previsión (pase entre áreas declarado en el formulario).",
  "I", "Oleadas", "https://labancaria.org/defender-al-nacion-es-defender-la-nacion-rechazamos-el-plan-de-ajuste-en-el-bna/")
t("trabajo", "Cierre de sucursal: reubicación y defensa del puesto", "Personal afectado",
  "Denuncias ante la Secretaría de Trabajo y el BCRA: Santander (más de 40 sucursales), BCRA (12 tesorerías), Hipotecario, Santa Cruz.",
  "listo", "Notificación a los afiliados de ese banco y encuesta nominal a los afectados (dónde trabajan, qué les ofrecieron).",
  "I", "Eventual", "https://labancaria.org/paro-nacional-en-el-bcra-y-banco-hipotecario/")
t("trabajo", "Teletrabajo: consentimiento, desconexión y cambios de contrato", "Teletrabajador",
  "Ley 27.555 y comisión paritaria específica. La AB denunció «contratos de novación» impuestos.",
  "listo", "Bot del convenio y trámite de consulta.",
  "E", "A demanda", "https://labancaria.org/comision-colectiva-ley-27555-teletrabajo/")
t("trabajo", "Jornada, horas extra, objetivos comerciales y presiones", "Trabajador, vía comisión interna",
  "Jornada de 7,5 h (Decreto 2289/76); pliegos colectivos por «objetivos inalcanzables».",
  "listo", "Trámite de reclamo y encuesta anónima por banco para medir cargas y presiones sin exponer a nadie.",
  "I", "Permanente", "https://labancaria.org/santander-en-alerta-cierres-y-precarizacion-retiros-y-presiones/")
t("trabajo", "Vacaciones negadas o forzadas", "Trabajador",
  "Presentaciones ante el Ministerio de Trabajo por maniobras patronales.",
  "listo", "Trámite de reclamo.",
  "E", "Temporada de vacaciones", "https://labancaria.org/vacaciones-pendientes/")
t("trabajo", "Medidas de fuerza: aviso, adhesión y días descontados", "Todos",
  "Comunicado en la web con la instrucción («sin concurrencia a los lugares de trabajo»). Cada seccional define la modalidad. Si el banco descuenta el día, la AB reclama.",
  "listo", "Notificación push segmentada por banco y seccional; confirmación de adhesión como encuesta nominal de una pregunta; trámite para reclamar el descuento.",
  "E", "Varias por año", "https://labancaria.org/estado-de-alerta-y-movilizacion-3/")
t("trabajo", "Persecución o amenazas a delegados", "Delegado o comisión interna",
  "Denuncia ante la Secretaría de Trabajo (Santander 2025–2026).",
  "listo", "Trámite al área Gremial.",
  "I", "Eventual", "https://labancaria.org/estado-de-alerta-banco-santander/")
t("trabajo", "«¿Cómo me afecta la reforma laboral?»", "Trabajador",
  "Guía explicativa en la web y cautelar contra el DNU 70/23 para los representados por la AB.",
  "listo", "Bot del convenio, más la guía como contenido de Capacitación.",
  "E", "A demanda", "https://labancaria.org/como-te-puede-afectar-la-reforma-laboral-de-milei/")
t("trabajo", "Contactar al delegado o a la seccional («guardia gremial»)", "Trabajador",
  "Escalamiento publicado: delegado (celular), mail del secretario general de la seccional, bancarios@bancaria.org.ar, teléfonos de la sede.",
  "listo", "Mi seccional con dirección, teléfono, horario y mapa ya existe. El directorio de delegados por banco y sucursal es la propuesta P11.",
  "E", "Permanente", "https://labancaria.org/guardia-gremial-contactos-actualizados/")
t("trabajo", "Cupo laboral travesti-trans (BNA y BCRA)", "Persona que busca empleo",
  "Acta AB–BNA de 2020 con cupo no menor al 1%; más de 50 ingresos. La vía de postulación no se publica.",
  "fuera", "La postulación es ante el banco. Colm3na puede difundirlo, no gestionarlo.",
  "E", "Abierto", "https://labancaria.org/trans-formando-el-mundo-del-trabajo/")

# ---------------- Acción social, turismo y beneficios
t("social", "Reserva de hotel o paquete turístico", "Afiliado (con tarifas para jubilados)",
  "Más de 30 alojamientos propios o en convenio. Se reserva por la seccional, saccionsocial@bancaria.org.ar o WhatsApp 11 2638 1654. Existe además reservasturismo.bancaria.org.ar con solicitud, pasajeros con vínculo, temporada, régimen, tarifario, boleta de pago, comprobante, cuotas y estados.",
  "listo", "La solicitud, como trámite encadenado hasta la confirmación. El cupo por hotel y el pago son de la propuesta P20; con un sistema de reservas ya funcionando, conviene que Colm3na tome el pedido y se lo pase, no reemplazarlo.",
  "E", "Todo el año; picos en invierno, fines de semana largos y noviembre", "https://labancaria.org/project-type/turismo/", "https://reservasturismo.bancaria.org.ar/")
t("social", "Viaje de bodas sin cargo (Mirador del Tafí)", "Afiliado que se casa",
  "Hasta 7 días. Se presenta la solicitud de Acción Social, el turno del Registro Civil o el certificado de matrimonio y la licencia del banco.",
  "listo", "Trámite con esos tres adjuntos y la confirmación de fechas en el hilo.",
  "E", "Por evento", "https://www.bancariasba.com.ar/service/viaje-de-bodas-sin-cargo/")
t("social", "Kit escolar", "Afiliado con hijos o nietos en edad escolar",
  "Portal kitescolar.bancaria.org.ar con manual de 20 páginas: registro con mail y captcha, datos en cuatro pasos, familiares con DNI y partida, una solicitud por chico con nivel, grado y certificado de escolaridad, estados, modificar y eliminar. Se retira con el carnet.",
  "listo", "Trámite por hijo con los mismos campos y adjuntos, más las validaciones del constructor (nivel coherente con el grado). Con el grupo familiar (P05) las partidas no se vuelven a subir cada año.",
  "E", "Anual (febrero y marzo)", "https://www.bancariasba.com.ar/service/kit-escolar-2026", "https://kitescolar.bancaria.org.ar/")
t("social", "Kit recién nacido", "Afiliado que tuvo un hijo",
  "Formulario en papel con acta de nacimiento, carnet y DNI, que se entrega a la comisión gremial interna.",
  "listo", "Trámite con el acta adjunta. Es el caso típico del motor de subsidios por evento vital (P01).",
  "E", "Por evento", "https://www.bancariasba.com.ar/service/kit-recien-nacido/")
t("social", "Guardapolvos a precio subsidiado", "Afiliado con hijos",
  "Talles 6 a 18, en Sarmiento 342. Consultas a saccionsocialba@bancaria.org.ar.",
  "listo", "Beneficio con su ficha, o trámite de pedido con talle y cantidad.",
  "E", "Anual", "https://www.bancariasba.com.ar/service/guardapolvos-con-descuento/")
t("social", "Servicio de sepelio", "Familiar del afiliado",
  "El Surco cubre traslado, sala velatoria y féretro del titular, el cónyuge, los hijos hasta 21 años y los hijos con discapacidad. Se llama al 0810-999-3441 (CABA) o 0800-666-1575 (resto) con el n.º de afiliado.",
  "listo", "Ficha de Beneficios con los teléfonos y el n.º de afiliado a mano en la credencial. La ficha de emergencias es la propuesta P29.",
  "E", "Por evento", "https://www.bancariasba.com.ar/service/servicio-por-fallecimiento/")
t("social", "Alta en Megatlon por convenio", "Afiliado, grupo familiar o jubilado",
  "Presencial en Sarmiento 341 PB con DNI y carnet; el plan familiar pide además actas de matrimonio o convivencia y de nacimiento. Individual $46.660, familiar $93.320, jubilados sin cargo.",
  "listo", "Trámite con los adjuntos, sin ir a la sede.",
  "E", "A demanda", "https://www.bancariasba.com.ar/service/red-megatlon")
t("social", "Descuentos en comercios y servicios", "Afiliado",
  "Diarco (10%, tope $25.000 por mes), Hertz (25%, código LABANCARIA), Avis (12%), Librería Hernández (15%), Carpincho, Rutaatlántica (30%), CFMOTO, Aerolíneas (10%). Se accede mostrando el carnet.",
  "listo", "Beneficios en la portada y en el carrusel, con la credencial digital como comprobante.",
  "E", "Permanente", "https://labancaria.org/beneficios/", "https://www.bancariasba.com.ar/service/supermercado-diarco-2/")
t("social", "Vacante en el jardín maternopaternal", "Madre o padre afiliado",
  "«Consultá vacantes para tu hijo/a». Hay jardines en Río Cuarto y Santa Fe. No dice el canal.",
  "listo", "Trámite de pedido de vacante dirigido a la seccional que tiene el jardín.",
  "E", "Anual", "https://labancaria.org/beneficios/jardin-maternopaternal/")
t("social", "Vacunación antigripal", "Afiliados, bancarios no afiliados y su familia",
  "Inscripción por Google Form de la Seccional Buenos Aires; 9.000 vacunados en 2022, en las delegaciones.",
  "ajuste", "Inscripción como trámite o encuesta nominal. Los no afiliados necesitan la entrada sin login; los turnos por delegación son la propuesta P12.",
  "E", "Anual (otoño)", "https://labancaria.org/cierre-de-campana-vacunacion-2022/")
t("social", "Torneos, olimpíadas, maratones y encuentros", "Afiliado y familia",
  "Ajedrez virtual por Google Form; Olimpíadas bianuales con unas 20 disciplinas; maratón de Tafí con 2.500 inscriptos.",
  "listo", "Trámite de inscripción con fecha de cierre. Las campañas con ventana y cupo son la propuesta P04.",
  "E", "Varias por año", "https://labancaria.org/torneo-virtual-de-ajedrez/", "https://labancaria.org/olimpiadas-bancarias-2019/")
t("social", "Día del Niño, fiestas y regalos", "Afiliado con hijos",
  "Los organiza cada seccional. La web no explica la inscripción.",
  "listo", "Notificación por seccional e inscripción de los chicos por trámite.",
  "I", "Anual", "https://labancaria.org/intereses-colectivos-programa-n-128/")
t("social", "Actividades y viajes para jubilados", "Jubilado afiliado",
  "Viajes subsidiados, cine debate, juegos de mesa y cumpleaños del mes en la Seccional Buenos Aires y el Centro de Pasivos (Gaona 1645).",
  "listo", "Notificación a los jubilados e inscripción por trámite. Requiere la condición de jubilado en el padrón.",
  "E", "Mensual", "https://labancaria.org/intereses-colectivos-programa-vigesimo-octavo/")
t("social", "Colectas y donación de sangre", "Afiliado",
  "Colectas por inundaciones (Bahía Blanca, Corrientes) y la Colecta Nacional de Sangre de julio de 2026.",
  "listo", "Notificación más inscripción del donante por trámite. Un relevamiento de afectados va como encuesta nominal.",
  "E", "Por campaña", "https://labancaria.org/la-solidaridad-se-lleva-en-la-sangre/")
t("social", "Hoteles e infraestructura propia", "—",
  "Hoteles, colonia de Tanti, futuro club en Ezeiza.",
  "fuera", "Es infraestructura física. Colm3na solo toma la reserva.",
  "E", "—", "https://labancaria.org/terreno-en-ezeiza-futuro-club-de-las-y-los-trabajadores-bancarios/")

# ---------------- Formación y cultura
t("form", "Cursos y diplomaturas de Bancar", "Afiliado y grupo familiar",
  "Sistema propio (inscripciones.bancar.org.ar). 1.401 inscriptos a cursos y 1.487 a diplomaturas en 2022-23; 34 cursos express en el verano de 2026.",
  "listo", "Noticia con el enlace hoy. El catálogo con inscripción y certificado con QR es la propuesta P22.",
  "E", "Casi mensual", "https://labancaria.org/bancar-verano-2026-cursos-express/")
t("form", "Curso «Activos y conectados» para adultos mayores", "Jubilado",
  "Inscripción por WhatsApp 11 7820-8368; 8 encuentros virtuales.",
  "listo", "Trámite de inscripción para jubilados.",
  "E", "Cada dos meses", "https://labancaria.org/activos-y-conectados-nuevo-curso-para-adultos-mayores/")
t("form", "Capacitación de delegados", "Delegado",
  "Jornadas de la Seccional Buenos Aires con material descargable (CCT 18/75, rol del delegado, liquidaciones salariales, salud ocupacional, violencias).",
  "desarrollo", "Capacitación por sindicato: hoy el módulo solo tiene el contenido fijo de plataforma (pendiente 1 del proyecto).",
  "E", "Anual", "https://www.bancariasba.com.ar/seminare/jornadas-de-capacitacion-gremial/")
t("form", "Diplomaturas con universidades", "Afiliado o delegado",
  "Seguridad Bancaria (UNLZ), Derecho Laboral (UNPAZ), Escuela Sindical de Género (ESiGen).",
  "listo", "Noticia con el enlace de inscripción de la universidad.",
  "E", "Anual", "https://labancaria.org/diplomatura-en-seguridad-bancaria/")
t("form", "Entradas a la Feria del Libro y presentación de libros", "Afiliado",
  "Entradas gratis de la Seccional Buenos Aires (registro por enlace, una por mail); escritores bancarios presentan su libro.",
  "listo", "Trámite de pedido de entradas y de postulación de un libro.",
  "E", "Anual (abril y mayo)", "https://labancaria.org/feria-del-libro-2023/")
t("form", "Propuesta de un proyecto cultural", "Afiliado",
  "culturabancaria.com: «Si sos afiliado/a y tenés un proyecto: hablemos».",
  "listo", "Trámite al área Cultura.",
  "E", "Permanente", "https://www.culturabancaria.com/")
t("form", "Biblioteca Norberto Galasso", "Afiliado o investigador",
  "Catálogo Koha propio con usuario y clave.",
  "fuera", "Es un catálogo que ya funciona; Colm3na solo enlaza.",
  "E", "Permanente", "https://labancaria.koha.theke.io/cgi-bin/koha/opac-main.pl")

# ---------------- Previsión y jubilados
t("prev", "Asesoramiento para jubilarse", "Afiliado cerca de la edad",
  "Secretaría de Previsión: historial laboral, requisitos y regularización. Teléfono 4131-4252, WhatsApp 11 3832-7679, sprevision@bancaria.org.ar, Sarmiento 337 piso 11.",
  "listo", "Trámite al área Previsión con turno y adjuntos. La ruta jubilatoria con aviso proactivo por edad es la propuesta P13.",
  "E", "Continua", "https://labancaria.org/beneficios/tenes-pensando-jubilarte-te-asesoramos/")
t("prev", "Gestiones ante ANSES", "Afiliado, jubilado o familiar",
  "La secretaría hace de nexo: jubilación, pensión por fallecimiento, haber no cobrado, apoderado, documentación física. Piden CUIL, clave de la seguridad social y DNI.",
  "listo", "Trámite con el DNI adjunto. La clave de la seguridad social no se pide nunca por la app.",
  "E", "Continua", "https://labancaria.org/prevision-tramites-anses/")
t("prev", "Moratoria previsional", "Afiliado con aportes faltantes",
  "Asesoramiento presencial o por teléfono. Venció el 23/3/2025 y el gremio pide la prórroga. «De 400 jubilaciones del año, el 80% fueron por moratoria».",
  "listo", "Trámite de consulta y respuestas en el bot.",
  "E", "Picos por vencimientos", "https://labancaria.org/prevision-asignaciones-familiares-moratoria/")
t("prev", "Haber, movilidad y juicios de reajuste", "Jubilado",
  "No hay canal específico; la web habla de juicios por reajuste.",
  "listo", "Trámite al área Previsión o Legal.",
  "I", "Mensual o trimestral", "https://labancaria.org/prevision-no-pueden-seguir-perdiendo/")
t("prev", "Cajas provinciales: Banco Provincia y Córdoba", "Activos y jubilados de esas bancas",
  "Ley 15.008 del Bapro (cautelar de 2023, reforma de 2024 que vuelve al 82%) y Ley 10.694 de Córdoba. Más de 15.000 jubilados y 10.000 activos del Bapro.",
  "listo", "Notificación filtrada por el CUIT del Banco Provincia y trámite de consulta.",
  "E", "Eventual", "https://labancaria.org/banco-provincia-recuperamos-los-derechos-de-sus-jubilados-y-jubiladas/")
t("prev", "Inscripción a medicamentos gratuitos de PAMI", "Jubilado o familiar",
  "Desde diciembre de 2024 hay que inscribirse. La web no dice cómo.",
  "listo", "Trámite de orientación al área Previsión.",
  "I", "Eventual", "https://labancaria.org/recorte-en-los-medicamentos-otra-vez-con-los-jubilados-as/")
t("prev", "Firmas y movilizaciones de jubilados", "Jubilado, afiliado o delegado",
  "Planillas en papel («envianos las planillas firmadas») y marchas de los miércoles.",
  "ajuste", "Adhesión digital como encuesta nominal. Una firma con validez legal sigue necesitando el papel o una firma verificada.",
  "E", "Semanal y por campaña", "https://labancaria.org/jubilazo-federal/")

# ---------------- Vida institucional y comunicación
t("inst", "«Dónde voto» en las elecciones", "Afiliado",
  "dondevoto.bancaria.org.ar consulta el padrón por persona. Regla: los activos votan en su lugar de trabajo, los teletrabajadores en la sucursal cercana o una delegación, los jubilados en Sarmiento 337 o Gaona 1645.",
  "ajuste", "Mesa asignada en el padrón y una tarjeta en la app con lugar, horario y mapa (P33). Hay elecciones de seccionales anunciadas para noviembre de 2026.",
  "E", "Cada 4 años (seccionales: nov 2026)", "https://dondevoto.bancaria.org.ar/", "https://labancaria.org/eleccion-diciembre-14-donde-se-vota/")
t("inst", "Saber si estoy habilitado para votar", "Afiliado",
  "Hacen falta 6 meses de afiliación a la fecha del comicio. 70.164 habilitados en 2021.",
  "ajuste", "Con la fecha de afiliación en el padrón, la app lo dice sola.",
  "E", "Cada elección", "https://labancaria.org/convocatoria-electoral-resoluciones-del-consejo-directivo-y-la-junta-electoral/")
t("inst", "Convocatoria a elecciones, congresos y plenarios", "Sindicato",
  "Comunicados en la web, Diario Popular y Boletín Oficial.",
  "listo", "Notificaciones push por seccional y noticia. Para convocar solo a delegados falta marcarlos en el padrón.",
  "E", "Varias por año", "https://labancaria.org/liii-congreso-nacional-bancario/")
t("inst", "Presentación de listas y avales", "Agrupaciones",
  "Ante la Junta Electoral, con escribano y veedores (Decreto 467/88). La Lista 1 presentó 26.165 avales en 2021.",
  "fuera", "Lo regula la ley de asociaciones sindicales.",
  "E", "Cada elección", "https://labancaria.org/elecciones-bancarias-lista-1-celeste-y-blanca/")
t("inst", "Elección de delegados y comisiones internas", "Trabajadores de cada banco",
  "2.974 delegados electos tras la pandemia. El procedimiento no se publica.",
  "desarrollo", "Padrón por banco y sucursal, convocatoria y resultado (P11 y P33).",
  "I", "Periódica por banco", "https://labancaria.org/xlix-congreso-nacional-bancario-apertura/")
t("inst", "Encuesta Nacional Bancaria", "Sindicato; responde el trabajador",
  "Bianual (2022 por bit.ly, 2024 sobre consumo). Los informes se publican como libros. La web no dice cuántos respondieron.",
  "listo", "Encuestas anónimas con cortes por seccional y banco, umbral de anonimato, recordatorio a los que faltan y evolución entre tomas. La de 2026 sería la primera en la app.",
  "E", "Bianual", "https://labancaria.org/encuesta-nacional-bancaria-2022/")
t("inst", "Relevamiento de afectados por una emergencia", "Seccional",
  "Bahía Blanca relevó a mano a los bancarios afectados por la inundación.",
  "listo", "Encuesta nominal a los afiliados de la provincia o seccional afectada.",
  "I", "Por evento", "https://labancaria.org/colecta-por-damnificados-as-de-bahia-blanca-2/")
t("inst", "Enterarse de la actualización salarial del mes", "Todos",
  "Hay que entrar a la web; un comunicado por mes.",
  "listo", "Notificación push el día que se firma, con el porcentaje y un enlace para verificar el recibo de ese mes.",
  "E", "Mensual", "https://labancaria.org/categoria/noticias/acuerdos-salariales/")
t("inst", "Noticias, radio y síntesis de prensa", "Afiliado",
  "Unos 2.400 posts desde 2020; el programa «Intereses Colectivos» todos los martes; síntesis de prensa diaria.",
  "listo", "Novedades con vigencia y dirigidas por seccional.",
  "E", "Diaria", "https://labancaria.org/sintesis-de-prensa/")
t("inst", "Oficios judiciales", "Juzgados",
  "Se reciben en sadministracion@bancaria.org.ar.",
  "fuera", "Es correspondencia judicial, no un trámite del afiliado.",
  "E", "Eventual", "https://labancaria.org/convenio-colectivo-18-75/")

# ---------------- Bancos empleadores y endeudamiento
t("emp", "Avisos y actas a los bancos empleadores", "Sindicato",
  "Actas con las cámaras ABAPPRA, ADEBA, ABA y ABE, y acuerdos por banco.",
  "listo", "Módulo Empleadores: notificaciones y trámites con cada banco por CUIT. El plan lo deja para después del piloto.",
  "E", "Mensual", "https://labancaria.org/categoria/otros-acuerdos/")
t("emp", "Endeudamiento de los trabajadores", "Afiliado",
  "Movilización contra el sobreendeudamiento (agosto 2026), Foro «La deuda no puede mandar», tablero de deudores con datos del BCRA de toda la población (abierto desde agosto de 2026). No hay asesoramiento individual.",
  "desarrollo", "Los descuentos por préstamos y embargos ya se leen en el recibo: agregados anónimos en el Panel (P25) y avisos al afiliado cuando la cuota pesa demasiado (P32). Una encuesta anónima mide el problema hoy mismo.",
  "I", "Mensual", "https://labancaria.org/marchamos-contra-el-sobrendeeudamiento-familiar/", "https://labancaria.org/deudores/")
t("emp", "Vivienda", "Afiliado",
  "Existe una Secretaría de Vivienda (sviviendas@bancaria.org.ar) y un plan de la Seccional Jujuy con el instituto provincial.",
  "listo", "Trámite de inscripción a un plan, cuando lo haya.",
  "I", "Por plan", "https://labancaria.org/autoridades/")

# ------------------------------------------------------------------ HTML
e = html.escape
cnt = collections.Counter(x["nivel"] for x in T)
porje = {k: collections.Counter(x["nivel"] for x in T if x["eje"] == k) for k, _ in EJES}
total = len(T)
inferidos = sum(1 for x in T if x["origen"] == "I")
NOMBRE_EJE = dict(EJES)

def fuente_corta(u):
    s = u.replace("https://", "").replace("http://", "").rstrip("/")
    return s if len(s) <= 46 else s[:44] + "…"

filas = []
for k, titulo in EJES:
    items = [x for x in T if x["eje"] == k]
    c = porje[k]
    resumen = " · ".join(f"{c[n]} {NIVELES[n][0].lower()}" for n in NIVELES if c[n])
    filas.append(f'<section class="eje" data-eje="{k}"><header class="eje-cab"><h3>{e(titulo)}</h3><p class="eje-res">{len(items)} gestiones · {resumen}</p></header><div class="tabla-cont"><table><thead><tr><th class="c-n">Trámite o gestión</th><th class="c-h">Cómo se hace hoy</th><th class="c-c">En Colm3na</th></tr></thead><tbody>')
    for x in items:
        fuentes = "".join(f'<a href="{e(u)}" target="_blank" rel="noopener">{e(fuente_corta(u))}</a>' for u in x["fuentes"])
        org = '<span class="org inf" title="Se deduce de la web, no está escrito como trámite">inferido</span>' if x["origen"] == "I" else '<span class="org">en la web</span>'
        filas.append(
            f'<tr data-nivel="{x["nivel"]}"><td class="c-n"><b>{e(x["nombre"])}</b><span class="quien">{e(x["quien"])}</span>'
            f'<span class="meta">{org}<span class="freq">{e(x["freq"])}</span></span></td>'
            f'<td class="c-h">{e(x["hoy"])}<span class="fuentes">{fuentes}</span></td>'
            f'<td class="c-c"><span class="niv n-{x["nivel"]}">{NIVELES[x["nivel"]][0]}</span>{e(x["colm"])}</td></tr>')
    filas.append("</tbody></table></div></section>")
CATALOGO = "\n".join(filas)

barras = []
for k, titulo in EJES:
    c = porje[k]; n = sum(c.values())
    segs = "".join(f'<span class="seg n-{lv}" style="flex:{c[lv]}" title="{NIVELES[lv][0]}: {c[lv]}"></span>' for lv in NIVELES if c[lv])
    barras.append(f'<div class="barra-fila"><span class="barra-et">{e(titulo)}</span><span class="barra">{segs}</span><span class="barra-n">{n}</span></div>')
BARRAS = "\n".join(barras)

LEYENDA = "".join(f'<div class="ley"><span class="niv n-{k}">{v[0]}</span><b class="ley-n">{cnt[k]}</b><p>{e(v[1])}</p></div>' for k, v in NIVELES.items())
CHIPS = '<button type="button" class="chip activo" data-f="todos">Todos ({})</button>'.format(total) + "".join(
    f'<button type="button" class="chip" data-f="{k}">{v[0]} ({cnt[k]})</button>' for k, v in NIVELES.items())

listos_ajuste = cnt["listo"] + cnt["ajuste"]
pct = round(100 * listos_ajuste / total)

plantilla = PLANTILLA.read_text(encoding="utf-8")
salida = (plantilla.replace("{{CATALOGO}}", CATALOGO).replace("{{BARRAS}}", BARRAS).replace("{{LEYENDA}}", LEYENDA)
          .replace("{{CHIPS}}", CHIPS).replace("{{TOTAL}}", str(total)).replace("{{LISTO}}", str(cnt["listo"]))
          .replace("{{AJUSTE}}", str(cnt["ajuste"])).replace("{{DESARROLLO}}", str(cnt["desarrollo"]))
          .replace("{{FUERA}}", str(cnt["fuera"])).replace("{{PCT}}", str(pct)).replace("{{INFERIDOS}}", str(inferidos)))
assert "{{" not in salida
SALIDA.write_text(salida, encoding="utf-8")
print(total, dict(cnt), "inferidos", inferidos, "pct", pct)
