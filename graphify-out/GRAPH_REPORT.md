# Graph Report - validador-demo  (2026-09-26)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 5700 nodes · 14206 edges · 264 communities (199 shown, 65 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 522 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `5cf1d03f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92
- Community 93
- Community 94
- Community 95
- Community 96
- Community 97
- Community 98
- Community 99
- Community 100
- Community 101
- Community 102
- Community 103
- Community 104
- Community 105
- Community 106
- Community 107
- Community 108
- Community 109
- Community 110
- Community 111
- Community 112
- Community 113
- Community 114
- Community 115
- Community 116
- Community 117
- Community 118
- Community 119
- Community 120
- Community 121
- Community 122
- Community 123
- Community 124
- Community 125
- Community 126
- Community 127
- Community 128
- Community 129
- Community 130
- Community 131
- Community 132
- Community 133
- Community 134
- Community 135
- Community 136
- Community 137
- Community 138
- Community 139
- Community 140
- Community 141
- Community 142
- Community 143
- Community 144
- Community 145
- Community 146
- Community 147
- Community 148
- Community 149
- Community 150
- Community 151
- Community 152
- Community 153
- Community 154
- Community 155
- Community 156
- Community 157
- Community 158
- Community 159
- Community 160
- Community 161
- Community 162
- Community 163
- Community 164
- Community 165
- Community 166
- Community 167
- Community 168
- Community 169
- Community 170
- Community 171
- Community 172
- Community 173
- Community 174
- Community 175
- Community 176
- Community 177
- Community 178
- Community 179
- Community 180
- Community 181
- Community 182
- Community 183
- Community 184
- Community 185
- Community 186
- Community 187
- Community 188
- Community 189
- Community 190
- Community 191
- Community 192
- Community 193
- Community 194
- Community 195
- Community 196
- Community 197
- Community 198
- Community 199
- Community 200
- Community 201
- Community 202
- Community 203
- Community 204
- Community 205
- Community 206
- Community 245
- Community 246
- Community 247
- Community 248
- Community 249
- Community 250
- Community 251
- Community 252
- Community 253
- Community 254
- Community 255
- Community 256
- Community 257
- Community 258
- Community 259
- Community 260
- Community 261

## God Nodes (most connected - your core abstractions)
1. `get_session()` - 250 edges
2. `Sindicato` - 133 edges
3. `_get()` - 127 edges
4. `_post()` - 121 edges
5. `UsuarioSindicato` - 113 edges
6. `Trabajador` - 106 edges
7. `exigir_sindicato()` - 84 edges
8. `Seccional` - 77 edges
9. `sesion_actual()` - 69 edges
10. `validar()` - 67 edges

## Surprising Connections (you probably didn't know these)
- `_uid()` --uses--> `UsuarioSindicato`  [INFERRED]
  test_areas_pase.py → db.py
- `test_editar_a_una_expresion_rota_tampoco_pasa()` --uses--> `Formula`  [INFERRED]
  test_formula_expresion_ruta.py → db.py
- `test_modulo_empleadores_habilitado()` --uses--> `Sindicato`  [INFERRED]
  test_cargar_demo_empleadores.py → db.py
- `test_alta_sin_marcar_ningun_modulo_queda_vacio()` --uses--> `Sindicato`  [INFERRED]
  test_modulos.py → db.py
- `test_alta_sindicato_con_catalogo_elegido()` --uses--> `Sindicato`  [INFERRED]
  test_modulos.py → db.py

## Import Cycles
- None detected.

## Communities (264 total, 65 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.01
Nodes (214): actualizar_perfil_empleador(), agregar_nota_tramite(), agregar_nota_tramite_empleador(), alcance_de_tramites(), alternar_plan_programado(), avanzar_georreferenciacion(), AvisoEnviado, _beneficio_a_dict() (+206 more)

### Community 1 - "Community 1"
Cohesion: 0.04
Nodes (133): _post(), crear_documento_convenio(), DocumentoConvenio, El PDF del convenio o de un acta, con lo que el admin declara sobre él. LA…, Guarda el documento en estado "pendiente". NO indexa: eso tarda ~9 minutos y…, La seccional con la que nace lo que crea este usuario. None cuando alcanza…, seccional_de_usuario(), abm_concepto() (+125 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (88): categoria_de(), coeficiente_antiguedad(), _completar_catalogo(), componer_recibo_bancario(), crear_sindicato(), _linea(), quitar_duplicados_legacy(), Las líneas de ingreso de un recibo bancario, según el CCT 18/75. Los rasgos del… (+80 more)

### Community 3 - "Community 3"
Cohesion: 0.03
Nodes (109): contextlib, cuits_conocidos(), modelo_ia(), El modelo vigente de UN uso. Se lee en cada llamada a propósito: cambiarlo…, Los CUITs de empleador que la app ya conoce, para el enmascarado: con `cuil`,…, La razón social con que el sindicato tiene cargado a ese empleador, para…, razon_social_de_cuit(), fastapi_responses (+101 more)

### Community 4 - "Community 4"
Cohesion: 0.03
Nodes (107): contar_notificaciones_no_leidas(), contar_tramites_con_novedades(), contar_tramites_empleador_nuevos(), contar_tramites_nuevos(), convenios_del_sindicato(), es_super_admin(), foto_empleador(), foto_trabajador() (+99 more)

### Community 5 - "Community 5"
Cohesion: 0.05
Nodes (81): _armar_recibo(), _autocorregir(), _cerrar_totales(), contexto_lote(), _envoltorio_recibo(), _fecha_ar(), _inyectar_error(), limpiar() (+73 more)

### Community 6 - "Community 6"
Cohesion: 0.04
Nodes (90): _get(), destinatarios_notificacion(), detalle_consulta(), detalle_notificaciones_grupo(), detalle_tramite(), limites_bruto(), El trámite con formulario respondido, hilo de conversación e historial (reusa…, Las notificaciones individuales que componen una fila agregada del explorador… (+82 more)

### Community 7 - "Community 7"
Cohesion: 0.06
Nodes (81): abrirModal(), alternarSeccional(), aplicarEstado(), asistAbrir(), asistAjustar(), asistBurbuja(), asistCandidatos(), asistChipAplicado() (+73 more)

### Community 8 - "Community 8"
Cohesion: 0.05
Nodes (73): _alnum(), analizar(), con_certeza(), marcar(), Caja, _casi_el_cuil(), _casi_igual(), color_tapon() (+65 more)

### Community 9 - "Community 9"
Cohesion: 0.06
Nodes (69): _hallazgo(), parametrize, Motor de XSK (`xsk/motor/registro.py`): lectura del registro, riesgo y ranking.…, Las plantillas tienen valores válidos a propósito: si el formato del motor…, test_aceptado_exige_motivo_y_firma(), test_el_registro_real_de_mitrabajo_se_lee_entero(), test_leer_cabecera_acepta_crlf(), test_leer_cabecera_falla_con_mensaje() (+61 more)

### Community 10 - "Community 10"
Cohesion: 0.05
Nodes (49): Textos de la documentación que no salen solos del código: qué es cada tabla,…, asistente_panel(), caja(), codo(), der(), _enlace(), entornos_deploy(), flecha() (+41 more)

### Community 11 - "Community 11"
Cohesion: 0.07
Nodes (65): crear_sesion(), Crea un token de sesión firmado con los datos del usuario. `ident` es la…, _admin_de_seccional(), _mapa(), _padron(), _por_nombre(), _publicar(), Una anónima que no guarda seccional no tiene ese dato en la urna ni razón para… (+57 more)

### Community 12 - "Community 12"
Cohesion: 0.05
Nodes (63): Conocidos, Lo que la app ya sabe antes de leer. Todo opcional: en el aprendizaje del admin…, _cargar(), _es_importe_o_concepto(), P(), parametrize, Tests de enmascarado.py (PLAN_ENMASCARADO.md, bloque 1). Dos partes: - Casos…, A CUENTA FUTUROS AUMENTOS' adentro de la tabla no es una cuenta bancaria, y su… (+55 more)

### Community 13 - "Community 13"
Cohesion: 0.05
Nodes (63): verificar_clave(), Deja un evento en la bitácora de plataforma (XSK H-0016)., Cuántos superadmin activos hay (para la guarda del último)., Sindicatos donde este CUIT está dado de alta como Empleador activo -- mismo…, El camino INVERSO: se acaba de tocar una fila del padrón, hay que ver si ese…, registrar_acceso(), registrar_log_plataforma(), sincronizar_por_cuil() (+55 more)

### Community 14 - "Community 14"
Cohesion: 0.10
Nodes (62): encuestas_del_sindicato(), Las encuestas del sindicato, más nuevas primero. `alcance` es el de seccional…, hoy(), date, El día de hoy en Buenos Aires. Reemplaza a date.today()., _alta(), _csv(), _padron_grande() (+54 more)

### Community 15 - "Community 15"
Cohesion: 0.05
Nodes (59): alcance_seccional(), permisos_efectivos(), PermisoUsuario, Secciones del panel que este usuario puede tocar, ahora mismo. Se calcula…, Sobre qué seccionales trabaja este usuario. - `None` = todas (Super Admin, o…, Ajuste individual sobre lo que hereda del área. `tipo` es "agregar" o…, Reemplaza los ajustes individuales del usuario. Si una sección viene en las dos…, set_permisos_usuario() (+51 more)

### Community 16 - "Community 16"
Cohesion: 0.05
Nodes (47): con_ocr, Palabra, Un trozo de texto con su caja en la imagen de la página. Puede ser una palabra…, _crear_motor(), imagenes_pdf(), LecturaFoto, leer_foto(), ocr_disponible() (+39 more)

### Community 17 - "Community 17"
Cohesion: 0.06
Nodes (55): ImagenEnmascarado, Una fila por documento que pasó por el enmascarado en modo sombra o activo…, DIAGNÓSTICO TRANSITORIO, solo Pruebas (pedido de SDN, 2026-09-24): la imagen…, Guarda el registro de `preparacion.preparar` y devuelve su id. NUNCA levanta:…, Los últimos registros del enmascarado, más reciente primero, para la sub-…, registrar_enmascarado(), RegistroEnmascarado, registros_enmascarado() (+47 more)

### Community 18 - "Community 18"
Cohesion: 0.04
Nodes (59): BinResponse, delete, Compara solo los dígitos de lo tecleado (un espacio o un guion no lo invalidan)…, verificar_pin(), _analisis_resumen(), api_entornos_esquema(), api_entornos_planes(), api_entornos_test_detalle() (+51 more)

### Community 19 - "Community 19"
Cohesion: 0.06
Nodes (53): a_milisegundos(), convertir(), ejecutar(), ErrorRender, escritura_aceptable(), main(), pedir_render(), datetime (+45 more)

### Community 20 - "Community 20"
Cohesion: 0.06
Nodes (51): True solo si ESTE proceso ganó el derecho a mandar el aviso `clave` del día…, reclamar_aviso_diario(), armar_texto(), arrancar(), _bucle(), debe_correr(), enviar_ahora(), intentar() (+43 more)

### Community 21 - "Community 21"
Cohesion: 0.08
Nodes (43): hashear_clave(), Devuelve 'sha256$<iter>$sal$hash' usando PBKDF2-HMAC-SHA256., completar_usuario_plataforma(), hay_usuarios_plataforma(), LogPlataforma, La fila del usuario de plataforma por su nombre de login, o None. No filtra por…, ¿Ya existe al menos un usuario de plataforma nominal? Sirve para saber si la…, Primer ingreso: fija la clave definitiva, marca la cuenta como completa y… (+35 more)

### Community 22 - "Community 22"
Cohesion: 0.05
Nodes (34): anthropic, argparse, muestra(), Muestrea cada 30s, durante un test de carga, CPU/RAM del servicio web y…, Pide el último punto de una métrica (endpoint: cpu, memory, active-connections)…, _ultimo_valor(), payload_de(), Publica en /entornos#tests-pruebas los 4 experimentos de… (+26 more)

### Community 23 - "Community 23"
Cohesion: 0.15
Nodes (46): Inyecta el cliente de Anthropic: el real (main.py al arrancar no hace falta, se…, usar_cliente(), consultas_asistente_hoy(), Para el tope diario del Asistente. `creado` es string ordenable, así que "hoy"…, ClienteFalso, _dia(), _filtros(), _guion() (+38 more)

### Community 24 - "Community 24"
Cohesion: 0.09
Nodes (49): abrirCruce(), alternar(), alturaDe(), CAL, cambiarVista(), cargar(), cargarEvolucion(), cerrarCruce() (+41 more)

### Community 25 - "Community 25"
Cohesion: 0.07
Nodes (47): Delegación/seccional de un sindicato (ej. por zona geográfica). El admin las da…, Seccional, Limpia los contadores. Solo para los tests., reiniciar_topes(), _alta(), _postear(), Georreferenciación de seccionales: alta, edición, precisiones y aislamiento. Lo…, `aproximada` es el centro de la localidad, no la puerta. Es el caso que más… (+39 more)

### Community 26 - "Community 26"
Cohesion: 0.06
Nodes (36): AccesoLog, actividad_resumen(), guardar_imagenes_enmascarado(), guardar_recurso(), date, Documentación del proyecto subida desde la landing /entornos (ver recursos.py,…, El recurso entero, bytes incluidos: solo para servirlo., Un login exitoso de cualquiera de los 4 roles -- para el dashboard de Actividad… (+28 more)

### Community 27 - "Community 27"
Cohesion: 0.08
Nodes (42): Token opaco para el QR (/v/{token}). Se genera y se guarda la primera vez que…, token_credencial(), _qr_credencial(), (svg, segundos_de_vida) del QR efímero de una credencial ya emitida. Un solo…, codigo_efimero(), _firma(), qr_svg(), QR de verificación de la credencial sindical. Solo `segno` (Python puro, sin… (+34 more)

### Community 28 - "Community 28"
Cohesion: 0.08
Nodes (39): main(), payload_regla(), Alertas sobre las métricas de Render (los eventos 3 y 4 del plan) y sobre el…, uid_de_regla(), validar_alertas(), ejecuciones_por_mes(), main(), payload_check() (+31 more)

### Community 29 - "Community 29"
Cohesion: 0.10
Nodes (43): _agregados(), Solo números y nombres de seccional/empresa. Nada de personas., clausula_aceptada(), consultas_por_tema(), explorador_consultas(), explorador_notificaciones(), _explorador_notificaciones_de_afiliado(), explorador_recibos() (+35 more)

### Community 30 - "Community 30"
Cohesion: 0.09
Nodes (35): avisos_de_encuesta(), notificacion_destinatarios(), Detalle fila por fila (CUIL + si leyó y cuándo) de una notificación. Con…, Los avisos de esta encuesta con su lectura: enviados y leídos. Es el "2 envíos…, _cuils(), _encuesta_publicada(), _padron(), Encuestas, Fase 0 de SPRINT_ENCUESTAS.md: catálogo, permisos y modelo. Los… (+27 more)

### Community 31 - "Community 31"
Cohesion: 0.07
Nodes (39): hash_desactualizado(), Autenticación propia de la plataforma multi-sindicato (sin terceros). Cuatro…, Una variable de entorno que NO puede faltar ni caer a un default: si no está,…, True si el hash usa un formato o costo viejo y conviene re-hashearlo (al…, _requerido(), verificar_plataforma(), hashlib, hmac (+31 more)

### Community 32 - "Community 32"
Cohesion: 0.08
Nodes (36): Beneficio, beneficio_vigente(), beneficios_vigentes(), Noticia, Lista vacía = todas las seccionales (incluye trabajadores sin seccional…, Mismo criterio que noticia_vigente: hoy en AAAA-MM-DD, vigente = fecha_desde <=…, Beneficios vigentes HOY de un sindicato, dirigidos a la seccional del…, Novedad del sindicato para sus trabajadores (portada + pestaña Novedades).… (+28 more)

### Community 33 - "Community 33"
Cohesion: 0.09
Nodes (38): _esquema_datos(), Todo lo que la Sala de mando muestra vivo, en un dict serializable.…, cargar_config(), Path, estado(), _estado_de(), _grafico(), _instantaneo() (+30 more)

### Community 34 - "Community 34"
Cohesion: 0.09
Nodes (37): armar_conclusion(), carga_legible(), construir(), delta(), etiqueta_workers(), _fase(), _fila(), filas_csv() (+29 more)

### Community 35 - "Community 35"
Cohesion: 0.06
Nodes (39): _avance_de_ventana(), _dias_hasta(), encuestas_de_trabajador(), Las encuestas de este sindicato a las que ESTE CUIL fue invitado. Solo las…, Cuántos días faltan para el cierre. 0 = cierra HOY (el último día se puede…, Qué porcentaje del período ya pasó, 0..100. Es la barra de avance de N19 -- la…, ayuda_de(), cortes_saneados() (+31 more)

### Community 36 - "Community 36"
Cohesion: 0.07
Nodes (37): PermisoArea, Una sección del panel habilitada para un área -- una fila por sección (ver…, _cliente(), Gateo por permisos de las rutas del panel -- Fase 2 de SPRINT_AREAS.md. Dos…, Una ruta renombrada deja su entrada vieja apuntando a la nada, y la ruta nueva…, Que la lista de exentas no crezca por descuido: cada agregado ahí es una ruta…, La pantalla del Panel Sindical no lleva datos: los pide el JS a los endpoints…, Aunque arme el POST a mano: esconder la pestaña no es el control. (+29 more)

### Community 37 - "Community 37"
Cohesion: 0.09
Nodes (35): CampoTramiteEmpleador, crear_tipo_tramite_empleador(), editar_tipo_tramite_empleador(), Mirror de TipoTramite, para formularios "externos" que el sindicato pone a…, Mirror de CampoTramite., Mirror de Tramite, con `cuit` en vez de `cuil`. Numeración de expediente…, Mirror de editar_tipo_tramite: sincroniza por id en vez de borrar y recrear…, TipoTramiteEmpleador (+27 more)

### Community 38 - "Community 38"
Cohesion: 0.08
Nodes (33): Guarda los modelos elegidos. Un id que no está en el catálogo se IGNORA y el…, Guarda una fila de consumo de la API por cada llamada real -- se llama en el…, registrar_uso_ia(), set_modelos_ia(), _fila_con(), _mock_msg(), Costo en dólares de cada llamada a la IA, y el modelo elegido por uso. Lo que…, Todo lo registrado antes de que existieran las columnas. Se muestra con los… (+25 more)

### Community 39 - "Community 39"
Cohesion: 0.08
Nodes (37): _contenido(), _dato(), ErrorLectura, extraer(), extraer_aportes(), _imagen_desde_pdf(), lineas_comparables(), _mock_activo() (+29 more)

### Community 40 - "Community 40"
Cohesion: 0.08
Nodes (35): borrar_fragmentos_de_documento(), buscar_fragmentos(), documento_para_indexar(), Actualiza el progreso de la indexación. La llama el hilo de fondo., Los k fragmentos más parecidos a la pregunta, con su similitud. El filtro por…, Lo que el hilo de fondo necesita, en un dict: no se puede pasar un objeto de…, set_estado_documento(), io (+27 more)

### Community 41 - "Community 41"
Cohesion: 0.07
Nodes (32): BASE_URL, errores, options, usuarios, BASE_URL, errores, erroresRecibo, imagenesBin (+24 more)

### Community 42 - "Community 42"
Cohesion: 0.08
Nodes (35): concurrent_futures, dataclasses, Analisis, abrir_imagen(), imagen_pdf(), Una sola página como imagen PIL (la IA hoy recibe solo la primera)., La foto como imagen PIL, DERECHA: un teléfono guarda la rotación en el EXIF, y…, _digitos() (+27 more)

### Community 43 - "Community 43"
Cohesion: 0.13
Nodes (32): geocache_guardar(), Guarda o refresca la respuesta de esa consulta. Es un upsert a mano porque la…, clave_cache(), normalizar_direccion(), La clave con la que una dirección se guarda y se busca en GeoCache. Normaliza…, Resuelve una dirección argentina a una lista de candidatos ubicables. El camino…, _con_red(), El servicio de geocodificación (geo.py), SIN salir a la red. Todo pedido de… (+24 more)

### Community 44 - "Community 44"
Cohesion: 0.10
Nodes (35): Una fila del listado, con el costo YA calculado. Si la fila congeló su precio,…, _uso_ia_fila(), kpis(), Los indicadores de negocio del entorno, con la sesión que se recibe., plataforma_probar_modelos(), Banco de pruebas: lee el MISMO archivo con dos o más modelos y devuelve, lado a…, catalogo(), catalogo_pantalla() (+27 more)

### Community 45 - "Community 45"
Cohesion: 0.09
Nodes (31): CuentaEmpleador, La identidad única del empleador en toda la plataforma: CUIT + clave. Mismo…, Test liviano de la carga de datos de prueba de empleadores agregada a…, El autorregistro es el flujo real -- el script no debe crear CuentaEmpleador…, test_cuit_compartido_resuelve_dos_sindicatos(), test_cuit_no_compartido_resuelve_un_solo_sindicato(), test_modulo_empleadores_habilitado(), test_no_precrea_cuenta_empleador() (+23 more)

### Community 46 - "Community 46"
Cohesion: 0.07
Nodes (27): fijar_job_test_carga(), test_carga_por_id(), tests_carga_recientes(), _parsear_escalones(), _experimento_de_prueba(), _MP, Pestaña "Tests" de /entornos: dispara el test de estrés (carga/) como un Job de…, Correr.sh no tiene cookie de sesión -- se autentica con el PIN en el header, no… (+19 more)

### Community 47 - "Community 47"
Cohesion: 0.09
Nodes (35): administra_areas_y_usuarios(), contar_super_admins(), Quién puede entrar a la pantalla de Áreas y Usuarios. Los dos roles de…, Super Admins activos del sindicato, sin contar a `excluyendo`. Existe para el…, Rearma el vínculo usuario <-> padrón y deja la marca al día. Se llama después…, sincronizar_empleado(), abm_seccional(), admin_area_abm() (+27 more)

### Community 48 - "Community 48"
Cohesion: 0.11
Nodes (34): permisos_individuales(), {"agregar": [...], "bloquear": [...]} del usuario, para pintar la pantalla en…, Usuarios del panel con su rol, área, seccional y ajustes individuales -- todo…, usuarios_del_sindicato(), _crear_area(), _panel_de(), CRUD de Áreas y Usuarios y armado del panel -- Fase 3 de SPRINT_AREAS.md. El…, Defensivo, mismo criterio que set_modulos_sindicato: no se persiste basura que… (+26 more)

### Community 49 - "Community 49"
Cohesion: 0.11
Nodes (32): aplicar_config(), aplicar_politica(), asegurar_carpeta(), asegurar_contact_point(), _asegurar_punto(), _contexto_tls(), estado_alertas(), Grafana (+24 more)

### Community 50 - "Community 50"
Cohesion: 0.09
Nodes (32): _cuil(), limpiar(), obtener_o_crear_sindicato(), Siembra el sindicato y los 1.000 trabajadores sintéticos para el test de carga…, sembrar_trabajadores(), sembrar_base(), Seccionales, empresas, trabajadores y cuentas. Devuelve los catálogos., sembrar_base() (+24 more)

### Community 51 - "Community 51"
Cohesion: 0.11
Nodes (33): area_destino_para(), A qué área cae un trámite de ESE formulario presentado por alguien de ESA…, Listado filtrable para el panel de admin, más recientes primero. Con…, tramites_del_sindicato(), _admin(), _crear_tipo(), _panel(), _presentar() (+25 more)

### Community 52 - "Community 52"
Cohesion: 0.11
Nodes (34): encuesta_por_id(), Una encuesta con sus preguntas. `sindicato_id` acota: una encuesta de otro…, _admin_de_seccional(), _encuesta_con_datos(), Un Admin de Seccional: las MISMAS secciones que el Super Admin, lo que lo…, Una encuesta publicada con gente repartida en dos seccionales y dos…, Una encuesta de varias preguntas deja varias filas por persona: la pastilla…, Asociativo (como Qlik): elegir un empleador que deja 10 casos y que las… (+26 more)

### Community 53 - "Community 53"
Cohesion: 0.11
Nodes (31): _a_params(), catalogo(), cliente(), describir_filtros(), disponible(), _entero_o_nulo(), _enteros(), ErrorModelo (+23 more)

### Community 54 - "Community 54"
Cohesion: 0.06
Nodes (3): las ultimas siete columnas json a jsonb Revision ID: d2c8f04a6b31 Revises:…, encuestas: modelo base (Fase 0) Revision ID: d9e4b71c8a52 Revises: b5c8e30a91f6…, sqlalchemy_dialects

### Community 55 - "Community 55"
Cohesion: 0.10
Nodes (31): areas_del_sindicato(), Áreas del sindicato con su seccional y sus permisos, para el CRUD y los…, _cliente(), _marta(), Admin de Seccional -- Fase 1 de SPRINT_AREAS_V2.md. El rol intermedio: "el…, No es un descuido: lo que lo achica es el alcance, no el catálogo. Tener dos…, Con esto se fabricaría un usuario sin techo y el alcance local dejaría de…, Sería darse alcance sobre todo el sindicato de un clic. (+23 more)

### Community 56 - "Community 56"
Cohesion: 0.09
Nodes (31): _a_cache(), _buscar_calle(), _de_cache(), _es_puerta(), _esperar_turno(), expandir_abreviaturas(), _georef(), _localidad_canonica() (+23 more)

### Community 58 - "Community 58"
Cohesion: 0.09
Nodes (27): credencial_de(), generar_codigo_credencial(), Código y vigencia REALES (persistidos) de la credencial de un empadronamiento.…, Genera y persiste un código de credencial nuevo para ese empadronamiento (lo…, fastembed, _coprimo_de(), filigrana_svg(), _guilloche() (+19 more)

### Community 59 - "Community 59"
Cohesion: 0.10
Nodes (29): (cuil, domicilio) de los afiliados activos sin coordenadas y CON localidad. Sin…, trabajadores_sin_geo(), _persona(), Provincia y localidad son obligatorias en el domicilio del afiliado. Decisión…, Las cuatro rutas preguntan lo mismo a la misma función. Si cada una decidiera…, Lo que hace que la decisión sea la decisión: el domicilio fino NO es…, El borde que se olvida: la obligatoriedad también tiene que valer en la…, Sin localidad, "Georreferenciar pendientes" no puede hacer nada: exigir… (+21 more)

### Community 60 - "Community 60"
Cohesion: 0.09
Nodes (29): difflib, operator, Detección de conceptos con código provisorio y sugerencia de similar. Usa el…, El corazón del asunto: estos pares se parecen MÁS que el duplicado real (hasta…, Deja constancia de por qué se filtra por código provisorio: un par legítimo…, Un código provisorio es frágil aunque no sea duplicado: nunca matchea por…, test_catalogo_sin_provisorios_no_marca_nada(), test_la_similitud_sola_no_alcanza() (+21 more)

### Community 61 - "Community 61"
Cohesion: 0.11
Nodes (25): limpiar_evento(), Reconstruye el evento con lo mínimo. Devuelve None (no se manda) si se pasó el…, sentry_sdk_transport, _admin(), _evento_sucio(), Sentry (sentry_config.py): errores no previstos, con contexto y SIN datos…, Es una respuesta de defensa de la app, no un defecto: llenaría la cuota con…, Un evento como lo armaría el SDK, con todo lo que NO tiene que salir. (+17 more)

### Community 62 - "Community 62"
Cohesion: 0.07
Nodes (8): copy, Disparador del colector (observabilidad/aplicar_disparador.py): un check de…, Las tres escriben lo mismo: el cron de GitHub, el hilo de la app y este…, test_el_disparador_es_una_tercera_via_que_no_reemplaza_a_las_otras(), test_valores_invalidos_se_rechazan(), _con(), Monitor de uptime de Pruebas (observabilidad/aplicar_uptime.py). Plan en…, test_valores_invalidos_se_rechazan()

### Community 63 - "Community 63"
Cohesion: 0.09
Nodes (29): Area, areas_de_pase_de_tipo(), Área organizativa DE UNA SECCIONAL (Secretaría Legal de Rosario, Tesorería de…, Los ids de área a los que ESTE formulario habilita derivar., La estructura de Áreas V2 que carga cargar_demo.py, verificada corriendo el…, Si todas las áreas heredan lo mismo, la pantalla de permisos parece decorativa.…, Un área destino de trámite (o de pase) sin nadie adentro es, en la demo, un…, Trabajar en el gremio sin estar afiliado a él es un caso real: el usuario… (+21 more)

### Community 64 - "Community 64"
Cohesion: 0.17
Nodes (29): areas_a_las_que_puede_pasar(), [{id, nombre, seccional}] de los destinos VÁLIDOS ahora mismo. Se saca el área…, _admin(), _area_de(), _cli(), _crear_tipo(), _presentar(), Pase de trámites entre áreas -- Fase 4 de SPRINT_AREAS_V2.md (N8). El área que… (+21 more)

### Community 65 - "Community 65"
Cohesion: 0.10
Nodes (23): borrar_suscripcion_push(), suscripciones_push_de(), api_push_clave_publica(), Clave pública VAPID para suscribirse. Vacía = push apagado (sin claves…, _enviar_a_suscripciones(), habilitado(), notificar_tramite(), Notificaciones Web Push a la PWA del trabajador (2026-09-02). Canal para las… (+15 more)

### Community 66 - "Community 66"
Cohesion: 0.10
Nodes (27): borrar_tope(), crear_tope(), editar_tope(), Para la pantalla de /plataforma: todos los topes por vigencia descendente (el…, El tope con vigencia_desde más reciente ANTERIOR al dado (para la validación de…, False si ya existe un tope con esa vigencia (para cambiar un período existente…, Si la tabla de topes está vacía, la carga desde data/topes_ss.csv (mismo…, Tope máximo y piso mínimo de la base imponible de la seguridad social, por… (+19 more)

### Community 67 - "Community 67"
Cohesion: 0.09
Nodes (27): ConfiguracionPlataforma, marca_plataforma(), Marca de 'Mi Trabajo' para las pantallas sin sindicato (logins, panel de…, Parámetros globales de plataforma (no por sindicato). Fila única, id=1., set_tope_sindical(), _es_superadmin_plataforma(), home(), ingresar() (+19 more)

### Community 68 - "Community 68"
Cohesion: 0.09
Nodes (17): estado(), El reporte completo para la pestaña. Nunca lanza: cada falla queda en `errores`., Todos los errores del entorno, sin resolver, de las últimas dos semanas (no el…, _url_todos(), Reporte de errores de Sentry en la pestaña Observabilidad…, test_cada_error_dice_cuando_donde_quien_y_con_que_referencia(), test_el_boton_de_sentry_del_panel_general_lleva_a_los_errores_reales(), test_el_enlace_lleva_a_los_errores_reales_del_entorno_y_no_al_evento_de_prueba() (+9 more)

### Community 69 - "Community 69"
Cohesion: 0.11
Nodes (28): test_detectar_nuevos_propaga_categoria_universal(), test_matchear_lineas_sin_categoria_universal_no_matchea(), test_matchear_lineas_usa_categoria_universal_como_red_de_seguridad(), Conceptos específicos de un empleador (cuit_empleador) con fallback a los…, _recibo(), test_cae_al_generico_si_el_cuit_no_tiene_ese_concepto(), test_codigo_efectivo_resuelve_al_generico(), test_detectar_nuevos_no_reproponer_lo_ya_cargado_para_ese_cuit() (+20 more)

### Community 70 - "Community 70"
Cohesion: 0.09
Nodes (14): ok(), _ejecutar_falso(), ejecutar(), parametrize, Pestaña "Observabilidad" de /entornos (docs/chat/2026-09-19-plan-…, test_el_boton_avisa_si_alguna_metrica_de_render_fallo(), test_el_boton_corre_el_colector_ahora_y_dice_cuanto_dejo(), test_el_boton_dice_que_falta_en_vez_de_romperse() (+6 more)

### Community 71 - "Community 71"
Cohesion: 0.12
Nodes (27): _cantidad(), _cfg(), descripcion_del_codigo(), detalle(), _discover(), ErrorSentry, _evento(), gravedad() (+19 more)

### Community 72 - "Community 72"
Cohesion: 0.08
Nodes (11): _evento_sentry(), grafana(), PrometheusDeMentira, fixture, parametrize, Gráficos de Grafana dentro de la pestaña Observabilidad…, sentry(), test_el_detalle_muestra_los_pasos_de_la_app_del_mas_reciente_al_mas_viejo() (+3 more)

### Community 73 - "Community 73"
Cohesion: 0.10
Nodes (21): ast, main(), migraciones(), modelos(), Extrae del código fuente lo que la documentación técnica necesita exacto:…, rutas(), _src(), _arrastrar() (+13 more)

### Community 74 - "Community 74"
Cohesion: 0.08
Nodes (5): _alerta(), Métricas de Render en Grafana: colector, remote write, tablero y alertas…, test_el_5xx_exige_un_minimo_de_pedidos_para_no_gritar_por_uno_de_diez(), test_las_alertas_de_metricas_no_gritan_por_falta_de_datos_pero_la_del_colector_si(), test_los_eventos_3_y_4_estan_con_los_umbrales_acordados()

### Community 75 - "Community 75"
Cohesion: 0.19
Nodes (25): _celda(), comparativa(), construir(), _delta(), _fase(), _fila(), _fmt_ms(), _fmt_pct() (+17 more)

### Community 76 - "Community 76"
Cohesion: 0.10
Nodes (25): collections, activo(), capturar(), iniciar(), iniciar_desde_el_entorno(), limpiar_miga(), limpiar_texto(), limpiar_valor() (+17 more)

### Community 77 - "Community 77"
Cohesion: 0.10
Nodes (25): datos_personales(), _dict_personales(), padron_del_sindicato(), perfil_trabajador(), El padrón completo de un sindicato, con los datos personales de cada afiliado…, El bloque personal de un CUIL, o None si ese CUIL no existe en la plataforma.…, Datos propios del trabajador para mostrarle su perfil. Devuelve None si ese…, inspect (+17 more)

### Community 78 - "Community 78"
Cohesion: 0.16
Nodes (24): _api_key(), aplicar_plan_db(), aplicar_plan_web(), _poner_workers(), configurado(), crear_job(), _db_id(), estado_job() (+16 more)

### Community 79 - "Community 79"
Cohesion: 0.12
Nodes (23): _dia(), main(), _multiple(), pesos(), date, Marcas de una pregunta múltiple, con Pareto y una opción excluyente. Si hay una…, Un día dentro de lo que YA CORRIÓ de la ventana, con más peso los primeros: es…, Llena una encuesta YA PUBLICADA con respuestas sintéticas verosímiles. No crea… (+15 more)

### Community 80 - "Community 80"
Cohesion: 0.12
Nodes (21): _campo_tramite_a_dict(), editar_tipo_tramite(), CUILs de trabajadores ACTIVOS de este sindicato que matchean el criterio --…, Actualiza título/código/activo y SINCRONIZA los campos por id: el constructor…, resolver_destinatarios(), tipo_tramite_por_id(), test_formulario_para_iniciar_en_noticia(), Notificaciones (Fase 2 de Módulos + Notificaciones + Trámites): cada criterio… (+13 more)

### Community 81 - "Community 81"
Cohesion: 0.18
Nodes (23): _alta_usuario(), _marta(), Identidad del empleado del sindicato -- Fase 2 de SPRINT_AREAS_V2.md. El…, Trabajar en el gremio sin estar afiliado a él es un caso real, no un error: el…, El camino inverso: alguien tiene usuario del panel y RECIÉN DESPUÉS lo cargan…, El mismo CUIL puede estar empadronado en varios sindicatos. Ser empleado de uno…, El caso que un apagado ingenuo rompe: dos altas para la misma persona (pasa con…, Se indexa por ID y no por CUIL a propósito: el test de más arriba deja DOS… (+15 more)

### Community 82 - "Community 82"
Cohesion: 0.17
Nodes (22): _dia(), _pedir(), _por_nombre(), Mapa de seccionales del Panel Sindical (GET /admin/dashboard/seccionales-geo).…, El mapa son seis números por seccional. Si alguna vez alguien le suma "y de…, Dos de los seis indicadores son una foto del padrón (misma decisión que el KPI…, El mapa ES el selector: si respetara el filtro, tocar un marcador dejaría el…, Con ceros y no ausente: "no hay recibos en Salta" es información. (+14 more)

### Community 83 - "Community 83"
Cohesion: 0.20
Nodes (22): _admin(), _clausula(), _form_edicion(), _id_de(), _lista(), _plataforma(), Reportes unificados (2026-09-24): la pestaña Reportes del panel del sindicato…, Ningún dato que identifique al trabajador o a la empresa de un recibo no… (+14 more)

### Community 84 - "Community 84"
Cohesion: 0.10
Nodes (17): _leer(), main(), Path, Siembra la marca de la plataforma (Colm3na) en la base del entorno. Por qué…, Devuelve (bytes, mime, nombre) del archivo, o (None, "", "") si falta., set_marca_plataforma(), _insertar(), _lotes() (+9 more)

### Community 85 - "Community 85"
Cohesion: 0.14
Nodes (22): notificaciones_del_sindicato(), Notificaciones enviadas por este sindicato, con el resumen leídos/total, más…, _central(), _cli(), _cordoba(), Una sola regla de alcance, para escribir Y para ver -- Fase 6 (N10). Hasta acá…, Pidiendo por CUIL se llegaría igual a gente de afuera, así que el recorte no…, La razón por la que el recorte vive en resolver_destinatarios y no en la ruta:… (+14 more)

### Community 86 - "Community 86"
Cohesion: 0.17
Nodes (22): Los trámites que presentó ESTE trabajador en ESTE sindicato, más recientes…, tramites_de_trabajador(), _campo_id(), Trámites (Fase 3 de Módulos + Notificaciones + Trámites): alta de tipo con…, GET /admin/tramites-nuevos-cantidad -- el globo de "Ver trámites" en admin.html…, Aísla la verificación de PERTENENCIA del trámite del gate de módulo (ya probado…, _sesion_trabajador(), test_aislamiento_entre_sindicatos() (+14 more)

### Community 87 - "Community 87"
Cohesion: 0.10
Nodes (23): hoy_texto(), Hoy como "AAAA-MM-DD" -- el formato de <input type=date> y el que se compara…, _celda(), csv_de_encuesta(), _dia_pedido(), evolucion(), filtros_saneados(), linaje() (+15 more)

### Community 88 - "Community 88"
Cohesion: 0.14
Nodes (20): crear_notificacion_empleador(), NotificacionEmpleador, NotificacionEmpleadorDestinatario, CUITs de empleadores ACTIVOS de este sindicato que matchean el criterio.…, Resuelve los destinatarios y los FIJA en el momento de enviar (snapshot, mismo…, Mensaje dirigido del sindicato a un grupo de empleadores -- mismo patrón que…, Una fila por CUIT que recibió una NotificacionEmpleador puntual -- separado de…, resolver_destinatarios_empleador() (+12 more)

### Community 89 - "Community 89"
Cohesion: 0.14
Nodes (20): Lo que la portada del afiliado dice de SUS propios recibos: cuántos verificó en…, resumen_recibos_trabajador(), Portada del trabajador (/app/inicio): pantalla de bienvenida nueva, no…, La portada es una ruta nueva -- /app (Tu Recibo) no debe haber cambiado., La tarjeta grande dice cuántos recibos verificó ESTE AÑO y cómo salió el…, Cero recibos no es lo mismo que un recibo en cero: sin ninguno, la tarjeta no…, La miniatura de la noticia es lo que la hace leerse como una novedad y no como…, El carrusel se rehízo, no se sacó: con más de un beneficio tiene que salir con… (+12 more)

### Community 90 - "Community 90"
Cohesion: 0.19
Nodes (21): Con `usuario_id`, el detalle informa además si ESE usuario puede responder y a…, tramite_detalle(), _admin(), Responder y cambiar estado, un solo acto -- Fase 5 (decisión N9). El problema…, El corazón de la fase. Antes: dos eventos (nota_admin + cambio_estado) por una…, Contestar sin cambiar de estado es un caso normal, no un borde., Si el <select> viene con el estado actual (que es lo que hace la pantalla), no…, Escribir es lo que el admin quiso hacer: perderle el mensaje por un valor mal… (+13 more)

### Community 91 - "Community 91"
Cohesion: 0.16
Nodes (20): aplicar(), asegurar_fuente_render(), construir_tablero(), _consulta_vivo(), en_vivo(), estado(), fila(), main() (+12 more)

### Community 92 - "Community 92"
Cohesion: 0.15
Nodes (21): analizar(), _hora_ba(), _hora_entera_ba(), leer(), lineas_del_dia(), _num(), _pct(), _pct_contra_limite() (+13 more)

### Community 93 - "Community 93"
Cohesion: 0.14
Nodes (18): Si esta regla corresponde ahora, devuelve la marca de su horario programado…, toca(), Solapa "Planes" de /entornos: subir y bajar el plan del servicio web y de…, Se edita el comando real, no se reescribe entero: si alguien agregó una bandera…, Durante un cambio de plan Postgres pasa por "updating_instance" y la app entera…, Si a las 08:00 el proceso estaba levantando (justo lo que pasa cuando la regla…, 23:55 del domingo con gracia: a las 00:02 del lunes todavía le toca, y la marca…, _regla() (+10 more)

### Community 94 - "Community 94"
Cohesion: 0.13
Nodes (20): _con_etiquetas(), _csv_agregado(), _describir_grupo(), _mediana(), _numero_ar(), Los agregados del dashboard de una encuesta (SPRINT_ENCUESTAS.md, Fase 4). Es a…, Una línea por opción (o una sola, en la escala), con un valor por toma. None…, El valor que parte la muestra al medio. Se calcula del conteo por valor y no… (+12 more)

### Community 95 - "Community 95"
Cohesion: 0.14
Nodes (18): advertencia_ultimo_deposito(), calcular_semaforo(), _parsear_fecha_ar(), Lógica del semáforo de aportes. Recibe el estado mensual (extraído por IA del…, Devuelve el color global y el detalle para pintar el semáforo. Reglas del color…, DD/MM/AAAA (o D/M/AAAA) impreso en el recibo -> (año, mes), o None si no…, Señal temprana y COMPLEMENTARIA a ARCA (Dto-Ley 17.250/67): si el último…, Verificación del Punto 3 del Sprint A (alerta temprana de último depósito). Sin… (+10 more)

### Community 96 - "Community 96"
Cohesion: 0.14
Nodes (20): actualizar_cambio_plan(), Cierra una entrada de bitácora abierta. El planificador anota el cambio ANTES…, entornos_planes_aplicar(), El botón "Aplicar ahora". `destino` es "web" o "db"., buscar(), catalogo(), _decorar(), _num() (+12 more)

### Community 97 - "Community 97"
Cohesion: 0.13
Nodes (21): contar_notificaciones_no_leidas_empleador(), contar_tramites_empleador_con_novedades(), notificaciones_de_empleador(), perfil_empleador(), Datos propios de la empresa para mostrarle su perfil -- mismo criterio que…, Mirror de contar_tramites_con_novedades., tipo_tramite_empleador_por_id(), api_actualizar_perfil_empleador() (+13 more)

### Community 98 - "Community 98"
Cohesion: 0.10
Nodes (21): api_entornos_observabilidad(), api_entornos_observabilidad_metricas(), api_entornos_observabilidad_sentry(), api_entornos_observabilidad_sentry_evento(), entornos_observabilidad_actualizar(), entornos_observabilidad_config(), entornos_observabilidad_probar_mail(), entornos_observabilidad_probar_telegram() (+13 more)

### Community 99 - "Community 99"
Cohesion: 0.14
Nodes (20): Vigencia por fecha de las fórmulas: un recibo se valida con la fórmula que…, _recibo(), test_formula_con_limite_sin_periodo_no_vigente(), test_formula_con_rango_respeta_limites(), test_formula_hasta_null_es_vigente_hoy_y_a_futuro(), test_formula_sin_fechas_siempre_vigente(), test_rango_abierto_se_superpone_con_cualquiera(), test_rangos_contiguos_no_se_superponen() (+12 more)

### Community 100 - "Community 100"
Cohesion: 0.11
Nodes (15): leer_sesion(), Valida la firma del token y devuelve el payload, o None si es inválido., Sesión por inactividad (15 min, sliding window): cada request autenticado…, Sesión VÁLIDA pero acción no permitida: el redirect de sesión vencida no puede…, Entrada 2 del BACKLOG, cerrada por la Fase 6 de SPRINT_AREAS_V2.md. Un POST de…, Loguearse como plataforma y DESPUÉS como sindicato, en el mismo cliente (mismo…, Regresión del bug real reportado: admin de sindicato logueado en una pestaña,…, Mismo caso reportado, con plataforma en vez de sindicato. (+7 more)

### Community 101 - "Community 101"
Cohesion: 0.13
Nodes (20): cuerpo(), El JSON que recibe el frontend: mensaje + código, siempre igual., exception_handler, _capturar_en_sentry(), error_de_base(), error_no_manejado(), _panel_de(), pool_agotado() (+12 more)

### Community 103 - "Community 103"
Cohesion: 0.16
Nodes (20): _booleano(), _columna_urna(), _con_filtros_urna(), _conteo_opciones(), _conteo_simple(), _cruce_por_corte(), _cuantos_respondieron(), _escala() (+12 more)

### Community 104 - "Community 104"
Cohesion: 0.22
Nodes (18): _aportes(), _contar(), _leer(), _leer_aportes(), _mockear(), /api/leer corta ANTES de devolver nada cuando el recibo no es del CUIL…, Reemplaza la lectura por IA: los tests no gastan créditos., _recibo() (+10 more)

### Community 105 - "Community 105"
Cohesion: 0.17
Nodes (19): Verificación del Punto 5B del Sprint B (retención de cuota para el envío al…, test_retencion_sindical_cero_si_no_hay_conceptos_sindicales(), test_retencion_sindical_suma_convenio_y_afiliacion(), _recibo(), test_caso_real_julio_2025_recibo_que_no_aplico_el_tope(), test_caso_real_mayo_2015_remuneracion_sobre_el_tope_sin_discrepancia(), test_concepto_faltante_sujeto_a_tope_agrega_alerta(), test_discrepancia_con_piso_aplicado_menciona_jornada_parcial() (+11 more)

### Community 106 - "Community 106"
Cohesion: 0.15
Nodes (18): El bloque "Mi seccional" del perfil del afiliado, y su domicilio. Los tres…, No hay forma de que el afiliado se cambie de seccional ni la pida: la decisión…, Ni armando el POST a mano: /api/perfil no toca seccional_id., El domicilio lo edita el propio afiliado, así que este endpoint queda expuesto…, Vendoreado como Chart.js, nunca CDN, y con el sello ?v= obligatorio de /static…, Es obligatoria por la licencia de OSM: no se saca ni se achica., Sesión de trabajador armada como en el resto de la suite: la cookie firmada…, _sesion() (+10 more)

### Community 107 - "Community 107"
Cohesion: 0.14
Nodes (19): El motor de validación no puede explotar por lo que devuelva la IA ni por una…, _recibo(), test_a_numero_convierte_lo_convertible(), test_a_numero_devuelve_none_ante_la_duda(), test_error_de_expresion_acepta_las_validas(), test_error_de_expresion_rechaza_las_rotas(), test_formula_rota_no_tumba_el_recibo(), test_importe_como_texto_se_usa_igual() (+11 more)

### Community 110 - "Community 110"
Cohesion: 0.14
Nodes (16): psycopg, _columnas(), esquema_alembic(), esquema_modelos(), _psycopg(), fixture, El esquema de las migraciones tiene que ser el de los modelos. `conftest.py`…, El que encontró las quince columnas `json` contra `jsonb`. (+8 more)

### Community 111 - "Community 111"
Cohesion: 0.13
Nodes (15): Los avisos del panel: que cada rechazo del servidor tenga su cartel, y que el…, El "falla cerrado" de PERMISOS_RUTAS. Estaba roto: `_sin_permiso` se usaba una…, El caso exacto del reporte: era el único que fallaba de verdad, y era el único…, Estaban en el de áreas: el cartel aparecía arriba del formulario equivocado. Un…, Antes lo que cambiaba era el título del PANEL, y este seguía diciendo "Dar de…, Áreas y Seccionales ya lo hacían; Usuarios era el que faltaba., _super(), test_al_super_admin_si_le_llega_abierta() (+7 more)

### Community 112 - "Community 112"
Cohesion: 0.19
Nodes (17): base64, _campo_bytes(), codificar_etiqueta(), codificar_muestra(), codificar_serie(), codificar_write_request(), _contexto_tls(), escribir() (+9 more)

### Community 113 - "Community 113"
Cohesion: 0.17
Nodes (15): borrar_recurso(), listar_recursos(), Metadatos de los recursos subidos, SIN los bytes: un video pesa decenas de MB y…, normalizar_fragmento(), estrategia" o "#estrategia" -> "#estrategia"; vacío queda vacío., _cliente_con_pase(), Recursos de la landing /entornos (recursos.py + rutas /recursos/* de main.py):…, Fail-closed sobre SEMILLA. Agregar un documento son tres cosas --el archivo, la… (+7 more)

### Community 114 - "Community 114"
Cohesion: 0.16
Nodes (17): planes_programados(), registrar_cambio_plan(), ahora_ba(), aplicar(), arrancar(), _bucle(), datetime, Lanza el hilo. No hace nada si no hay credenciales de Render (no habría cómo… (+9 more)

### Community 115 - "Community 115"
Cohesion: 0.26
Nodes (16): initBannerInstalar(), initPushTramites(), _pushB64aBytes(), _pushSuscribir(), _pwaAccionLinkFijo(), _pwaCrearLinkFijo(), _pwaDescartar(), _pwaEsIOS() (+8 more)

### Community 116 - "Community 116"
Cohesion: 0.15
Nodes (14): engine_para_migraciones(), _opciones_postgres(), El string `options` de libpq: `-c parametro=valor` por cada uno., Engine de Alembic (migrations/env.py): una sola conexión, sin pool. Las…, sqlalchemy_exc, _cliente(), Los techos del engine (C2 del cuelgue de Pruebas del 2026-09-18,…, Solo la consulta cortada por tiempo es un 503. Un error operacional cualquiera… (+6 more)

### Community 117 - "Community 117"
Cohesion: 0.18
Nodes (16): _avisar(), _correr_al_pasado(), _dia_de_respuesta(), _nominal(), _padron(), Las encuestas de la demo: un padrón de verdad y tres tomas en el tiempo. Lo…, Carga el padrón sintético y las encuestas. Devuelve un resumen., Afiliados sintéticos repartidos entre las seccionales y los empleadores. Sin… (+8 more)

### Community 118 - "Community 118"
Cohesion: 0.18
Nodes (16): _abrir_seccionales(), _login_admin(), _login_trabajador(), Robot E2E de georreferenciación: mapas de verdad, en un navegador de verdad. Es…, Editar una seccional YA ubicada abre en el paso 2 con el globo puesto: corregir…, El mismo mapa, otra pregunta: cuánta gente de cada seccional respondió una…, Con el permiso dado y la posición simulada en Rosario., Negar el permiso NO puede dejar la pantalla inservible: se mide desde el… (+8 more)

### Community 119 - "Community 119"
Cohesion: 0.19
Nodes (16): _admin_client(), Sistema de módulos habilitables por sindicato (Fase 1 del plan de Módulos +…, _sesion_trabajador(), test_admin_completo_con_catalogo_completo(), test_admin_oculta_pestanas_sin_modulo(), test_alta_sin_marcar_ningun_modulo_queda_vacio(), test_alta_sindicato_con_catalogo_elegido(), test_edicion_cambia_modulos() (+8 more)

### Community 120 - "Community 120"
Cohesion: 0.15
Nodes (13): _bloque_test(), browser_type_launch_args(), entorno_aefip(), nuevo_actor(), fixture, pytest_runtest_makereport(), pytest_sessionfinish(), Fixtures del entorno E2E. OJO con el orden de los conftest: el de la RAÍZ… (+5 more)

### Community 121 - "Community 121"
Cohesion: 0.13
Nodes (8): _dias(), Vencimientos de tokens (observabilidad/aplicar_vencimientos.py y la pestaña…, Vence al terminar el 18, hora de Buenos Aires: 2026-10-19 00:00 (-03:00) =…, test_el_estado_de_la_pestana_incluye_los_vencimientos(), test_el_mas_urgente_va_primero(), test_el_token_sirve_todo_el_dia_de_su_fecha(), test_la_pestana_dice_cuantos_dias_faltan_y_en_que_estado_esta(), test_valores_invalidos_se_rechazan()

### Community 122 - "Community 122"
Cohesion: 0.19
Nodes (15): afiliado_por_id(), buscar_afiliados(), catalogo_empresas(), _destino_legible(), diferencias_empresa(), _etiquetas_empresas(), _etiquetas_seccionales(), El destino de una Notificacion en palabras: a quién se dirigió el envío,… (+7 more)

### Community 123 - "Community 123"
Cohesion: 0.25
Nodes (14): Usuario del panel de un sindicato. Tres clases: - Super Admin…, UsuarioSindicato, _admin_client(), Autogestión de administradores por el propio sindicato (antes solo plataforma…, test_alta_de_un_segundo_admin_queda_en_el_sindicato_de_la_sesion(), test_alta_duplicada_en_el_mismo_sindicato_rechaza(), test_baja_y_reactivar(), test_editar_solo_cambia_nombre() (+6 more)

### Community 124 - "Community 124"
Cohesion: 0.20
Nodes (14): test_limite_dinamico_hoy(), test_saneo_de_validaciones(), _a_comparable(), _compara(), evaluar_envio(), _limite_comparable(), Validaciones de los formularios de Trámites (capa acordada 2026-09-01). Cada…, El límite como lo lee una persona en un mensaje ('180', '31/12/2026', 'el día… (+6 more)

### Community 125 - "Community 125"
Cohesion: 0.27
Nodes (13): filas_test1(), filas_test2(), leer_puntos(), obj_metrica(), percentil(), Path, Máximo de cada métrica del servidor dentro de [desde_rel, hasta_rel) segundos…, Arma carga/log/<carpeta>/resumen.csv a partir de la salida cruda de k6 (--out… (+5 more)

### Community 126 - "Community 126"
Cohesion: 0.16
Nodes (14): eventos_de_encuesta(), El historial de la encuesta, más nuevo primero, con el NOMBRE de quien hizo…, El texto sugerido de la notificación que anuncia una encuesta. Es un BORRADOR…, El borrador de la noticia que anuncia una encuesta (título y bajada)., texto_aviso(), texto_noticia(), dia_legible(), 2026-10-12" -> "12/10/2026", para los textos que lee una persona. Una fecha ISO… (+6 more)

### Community 127 - "Community 127"
Cohesion: 0.15
Nodes (14): formulario_activo_de(), Devuelve el formulario_id solo si sigue siendo un tipo ACTIVO del sindicato (de…, _antiguedad(), api_beneficio(), api_noticia(), _fmt_fecha_hora_corta(), _parsear_creada(), Detalle completo de una noticia (texto completo + flags de imagen) para el… (+6 more)

### Community 128 - "Community 128"
Cohesion: 0.21
Nodes (12): Tipos de trámite del sindicato con sus campos, para el constructor de admin y…, tipos_tramite_del_sindicato(), test_formulario_adjunto_en_chat(), _ids(), Capa de validaciones de Trámites (Fase 1: fija + consistencia). Cubre: el motor…, _sesion_trabajador(), test_alta_tipo_con_validaciones_y_reglas(), test_envio_bloqueado_con_errores_campos() (+4 more)

### Community 129 - "Community 129"
Cohesion: 0.16
Nodes (14): cambio_estructural(), opciones_de(), a, b, c" -> ["a", "b", "c"], sin vacías ni repetidas. Mismo formato que…, Si entre dos versiones de las preguntas cambió algo MÁS que el texto. Es lo que…, _condicion_de_opcion(), cruce(), _cruce_por_pregunta(), _cuenta_pregunta() (+6 more)

### Community 130 - "Community 130"
Cohesion: 0.14
Nodes (13): comparar_lineas(), [(modelo, datos)] -> la tabla línea por línea. El emparejado va en DOS pasadas:…, El caso que apareció probando cuatro modelos: mismos totales, mismas 17 líneas,…, Si un modelo se saltea una línea, emparejar por posición dejaría todo lo que…, Caso real (2026-09-13, recibo de verdad): Haiku leyó el código "128-001" donde…, La descripción es la segunda pasada, no la primera: dos líneas con la misma…, Un modelo transcribe el descuento como figura en la columna Deducciones…, test_comparar_lineas_empareja_por_codigo_y_no_por_posicion() (+5 more)

### Community 131 - "Community 131"
Cohesion: 0.19
Nodes (11): Aportes de ley (jubilación, PAMI, obra social) identificados por la IA vía…, Un sindicato que cargó los 3 genéricos de descuento pero NINGÚN concepto de…, Un empleador SIN NINGÚN concepto propio cargado: los códigos/nombres de sus…, _recibo_empleador_nuevo(), _recibo_sin_ningun_ingreso_cargado(), test_base_remunerativa_aproximada_detecta_discrepancia_real(), test_base_remunerativa_no_se_aproxima_si_matchea_algun_ingreso(), test_base_remunerativa_usa_total_impreso_si_no_matchea_ningun_ingreso() (+3 more)

### Community 132 - "Community 132"
Cohesion: 0.18
Nodes (12): _con_modales(), Los modales se pueden mover, y en TODAS las pantallas que tienen modales.…, `.modal-recibo-card` es una tarjeta ADENTRO del modal de trámite. Si entrara en…, Las plantillas que tienen al menos una caja de modal., Baranda del propio test: si el regex dejara de encontrar cajas, los dos tests…, Regla del proyecto, sin excepciones: todo lo que sale de /static/ va con `?v=`.…, En un teléfono el modal es una hoja pegada al borde inferior: moverla no tiene…, test_el_script_va_con_sello_de_version() (+4 more)

### Community 133 - "Community 133"
Cohesion: 0.19
Nodes (8): _con(), Configuración de la observabilidad (observabilidad/config.json y…, test_cambiar_el_mail_o_el_intervalo_es_editar_una_linea(), test_el_config_no_lleva_ningun_token(), claves(), test_el_punto_de_contacto_es_un_solo_mail_con_aviso_al_resolverse(), test_los_intervalos_admiten_segundos_minutos_y_horas(), test_un_mail_o_un_intervalo_mal_escritos_se_rechazan_antes_de_tocar_grafana()

### Community 134 - "Community 134"
Cohesion: 0.24
Nodes (12): _celdas(), _conexiones(), construir(), descargar(), parsear(), _precio(), _ram_mb(), Baja el catálogo de planes de Render desde su propia página de precios y lo… (+4 more)

### Community 135 - "Community 135"
Cohesion: 0.23
Nodes (12): asyncio, cargar_usuarios(), correr_escalon(), journey_lectura(), journey_recibo(), main(), _paso(), percentil() (+4 more)

### Community 136 - "Community 136"
Cohesion: 0.27
Nodes (12): abortar(), cliente_para(), herramienta(), main(), _nombre_base(), Copia TODOS los datos de la demo al entorno de Pruebas (pg_dump + pg_restore).…, Último tramo de la URL, sin query: sirve para reconocer la base., Las tres guardas. Ninguna es opcional. (+4 more)

### Community 137 - "Community 137"
Cohesion: 0.17
Nodes (13): borrar_plan_programado(), cambios_de_plan(), crear_plan_programado(), PlanProgramado, Una regla semanal: "los días D, a las HH:MM de Buenos Aires, poné el servicio X…, Intenta quedarse con el derecho a aplicar esta regla en esta marca de tiempo.…, reclamar_plan_programado(), Render no guarda historial de planes de las bases: si esto no queda anotado… (+5 more)

### Community 138 - "Community 138"
Cohesion: 0.19
Nodes (10): guardar_semaforo(), Último semáforo calculado para ese empadronamiento, o None si todavía no subió…, Persiste el resultado de calcular_semaforo() para no perderlo al navegar o…, semaforo_guardado(), _MP, El semáforo de aportes se guarda al calcularse (POST /api/aportes) y sobrevive…, test_api_aportes_persiste_al_calcular(), test_app_pinta_el_semaforo_guardado_sin_volver_a_subir_nada() (+2 more)

### Community 139 - "Community 139"
Cohesion: 0.23
Nodes (11): Todo el consumo de IA de TODOS los sindicatos, más reciente primero, con el…, uso_ia_listado(), Pruebas quedó con MOCK_EXTRACTOR=1 de los tests de carga (carga/README.md):…, test_una_lectura_de_mock_no_aporta_ni_costo_ni_tiempo(), _mock_msg(), Consumo de la API de IA: se registra en cada llamada real (recibo, aportes de…, El costo ya se generó aunque la lectura no sirva -- no hay que perderlo solo…, test_admin_aprender_registra_tipo_aprendizaje() (+3 more)

### Community 140 - "Community 140"
Cohesion: 0.23
Nodes (12): fastapi_routing, _pedir(), _problema(), parametrize, Ninguna ruta de la app entrega nada a quien no inició sesión. Recorre TODAS las…, Pide la ruta con parámetros bien formados, para que el rechazo lo dé el control…, None si la respuesta es un rechazo aceptable; si no, qué está mal., _rutas() (+4 more)

### Community 141 - "Community 141"
Cohesion: 0.15
Nodes (13): coordenadas_validas(), distancia_km(), normalizar_precision(), Cualquier cosa que no sea una de las cuatro precisiones es `sin_geo`. Fail-…, True solo si las dos son números dentro del rango del planeta. Se chequea antes…, ¿Este punto sirve para que una persona camine hasta ahí? Es la regla que separa…, Haversine. Devuelve None si falta o no sirve alguna coordenada. El cliente…, ubicacion_precisa() (+5 more)

### Community 142 - "Community 142"
Cohesion: 0.15
Nodes (10): subprocess, Los 4 experimentos publicados en /entornos#tests-pruebas tienen que coincidir…, Si alguien toca carga/log/ o consolidar.py y se olvida de regenerar, el JSON…, Las corridas fueron de noche en UTC y de tarde en Buenos Aires: si alguna fecha…, Los NDJSON que escribe k6 pesan ~1 GB entre todas las corridas y no se…, resumen.csv y servidor.log son la fuente que audita verificar.py. Si quedaran…, test_el_json_consolidado_esta_al_dia_con_los_datos_crudos(), test_las_fechas_estan_en_hora_de_buenos_aires() (+2 more)

### Community 143 - "Community 143"
Cohesion: 0.18
Nodes (12): contar_encuestas_pendientes(), notificaciones_de_trabajador(), Notificaciones que le llegaron a este CUIL en este sindicato, más nuevas…, Encuestas ABIERTAS a las que este CUIL fue invitado y no respondió. Es el…, acepta_respuestas(), estado(), El estado de una encuesta, derivado -- nunca guardado (N6). `hoy` entra por…, Si la encuesta está tomando respuestas en este momento. Existe como función… (+4 more)

### Community 144 - "Community 144"
Cohesion: 0.23
Nodes (9): Recibo que la IA marcó con alto grado de certeza de datos posiblemente…, ReciboSospechoso, _mockear_extraer(), fake(), Alerta de posible adulteración al leer un recibo: si la IA marca…, test_con_alerta_no_bloquea_y_guarda_el_archivo(), test_sin_alerta_no_guarda_nada(), fake() (+1 more)

### Community 145 - "Community 145"
Cohesion: 0.21
Nodes (8): muestra_distintivo(), normalizar(), En qué entorno corre la app (local / pruebas / demo / prod). Se lee de la…, Devuelve el entorno en minúsculas, o "" si no está definido o no es uno de los…, pytest, Distintivo de entorno (entorno.py + templates/_entorno.html): se muestra en…, test_acerca_de_muestra_entorno_y_version(), test_normalizacion_y_regla_de_distintivo()

### Community 146 - "Community 146"
Cohesion: 0.18
Nodes (6): codigo_de_ruta(), Códigos de error propios de Mi Trabajo. Por qué existe este archivo…, fastapi, Cada error que ve una persona viaja con su código propio, y el mensaje de…, test_error_app_toma_status_y_mensaje_del_catalogo(), test_error_inesperado_en_otra_ruta_cae_en_e_interno()

### Community 147 - "Community 147"
Cohesion: 0.26
Nodes (11): cliente_para(), ErrorPg, _mayor(), _psql(), Exception, Elegir un pg_dump/pg_restore que pueda hablar con el servidor de Render. Por…, Algo que hay que contarle a la persona, no un traceback., Primer número de una cadena de versión ('16.15 (Debian...)' -> 16). (+3 more)

### Community 148 - "Community 148"
Cohesion: 0.36
Nodes (11): abortar(), backup_demo(), exigir_arbol_limpio(), git(), main(), podar_backups(), Promueve lo que hay en `main` a la DEMO (rama `demo`, que Render sigue). Es EL…, Deja solo los DUMPS_A_CONSERVAR dumps más nuevos y borra los demás. Cada… (+3 more)

### Community 149 - "Community 149"
Cohesion: 0.29
Nodes (9): archivos(), Path, Reparte los archivos test_*.py entre los trabajos paralelos del CI. El CI…, reparto(), _partes_del_workflow(), El reparto de la suite entre los trabajos paralelos del CI (ci_reparto.py +…, test_el_reparto_es_determinista_y_valida_el_rango(), test_el_workflow_declara_las_mismas_partes_que_usa() (+1 more)

### Community 150 - "Community 150"
Cohesion: 0.22
Nodes (10): ctypes, acomodar(), esperar_ventana_nueva(), Acomodar las ventanas del navegador cuando se corre con --headed (Windows). Por…, Handles de las ventanas de Chromium lanzadas por Playwright., El handle de la ventana que apareció después de `previas` (o None). La ventana…, Coloca la ventana en su franja de pantalla y la deja SIEMPRE ENCIMA. `indice`…, _titulo() (+2 more)

### Community 151 - "Community 151"
Cohesion: 0.31
Nodes (9): _a_json(), dibujar_pdf(), _fmt(), main(), _ocr_pdf(), Path, Arma los datos de prueba del enmascarado (PLAN_ENMASCARADO.md, bloque 1). Uso…, Palabras de un PDF-imagen con el mismo lector de fotos que usa la app… (+1 more)

### Community 152 - "Community 152"
Cohesion: 0.18
Nodes (11): campos_para_guardar(), _georreferenciar_padron(), georreferenciar_padron_en_segundo_plano(), Ubica en el mapa a los afiliados cargados sin coordenadas. Va en un hilo por lo…, El hilo. Cada fila se guarda apenas se resuelve, no todas juntas al final: si…, El bloque de domicilio listo para escribir en Seccional o Trabajador. Un solo…, test_campos_para_guardar_recorta_y_limpia(), test_coordenadas_sin_precision_quedan_manual() (+3 more)

### Community 153 - "Community 153"
Cohesion: 0.33
Nodes (10): _es_oscuro(), La portada del trabajador pinta texto claro sobre --marca-base: si el sindicato…, _id_de(), _payload(), 4to color de marca (color_base): fondo oscuro de la portada del trabajador y de…, test_alta_sindicato_guarda_color_base_oscuro(), test_alta_sindicato_rechaza_color_base_claro(), test_editar_sindicato_guarda_color_base_oscuro_nuevo() (+2 more)

### Community 154 - "Community 154"
Cohesion: 0.18
Nodes (10): background_color, description, display, icons, lang, name, scope, short_name (+2 more)

### Community 155 - "Community 155"
Cohesion: 0.20
Nodes (11): _campos(), _decodificar_write_request(), _desde_snappy(), _leer_varint(), Prometheus rechaza una serie con etiquetas desordenadas o muestras fuera de…, Recorre un mensaje protobuf: devuelve [(numero, tipo_de_cable, valor)]., Descomprime un bloque snappy (literales y copias) — el formato completo, no…, test_caracteres_no_ascii_en_etiquetas_sobreviven() (+3 more)

### Community 156 - "Community 156"
Cohesion: 0.18
Nodes (11): _cli(), _local(), Navegando (no por fetch), el rechazo tiene que volver al panel con un aviso.…, El arreglo no puede convertir toda respuesta de API en un redirect., Lo de arriba es cosmética; esto es la regla. Que el cartel sea lindo no puede…, El recorte lo hace el servidor: si viviera en el JS, la fila de la otra…, test_al_admin_local_no_le_llega_el_alta_de_seccional_abierta(), test_el_403_del_admin_local_no_deja_json_crudo() (+3 more)

### Community 157 - "Community 157"
Cohesion: 0.18
Nodes (7): envio(), _fila(), fixture, Transport, sentry(), SentryDeMentira, TransporteFalso

### Community 158 - "Community 158"
Cohesion: 0.40
Nodes (9): armar_estado(), comparar(), correr(), _id_afiliado(), _ids(), main(), periodo_esperado(), Set de aceptación del prompt del Asistente del Panel (docs/ASISTENTE_PANEL.md… (+1 more)

### Community 159 - "Community 159"
Cohesion: 0.24
Nodes (10): _columna_trabajador(), _cuils_alcanzados(), _join_padron(), _mapa_seccionales(), Los CUIL del padrón que caen dentro del filtro, o None si no hay filtro (y…, Participación por seccional, con coordenadas, para el mapa de burbujas.…, La columna del PADRÓN que corresponde a un corte. Sale de dos tablas distintas…, Cruza una consulta sobre `EncuestaParticipante` con las DOS tablas del padrón,… (+2 more)

### Community 160 - "Community 160"
Cohesion: 0.20
Nodes (10): El dashboard entero de una encuesta, ya recortado y con el umbral aplicado.…, resultados(), Sin esa diferencia el filtro por seccional muestra tres curvas iguales y no se…, Con tres afiliados el umbral esconde hasta el total general, y las dos…, Participación y lectura solo sirven juntos. Con "0 leídos" el dashboard no…, La toma en curso tiene que llevar días corridos: con todas las respuestas en el…, test_hay_padron_suficiente_para_que_el_umbral_no_esconda_todo(), test_la_curva_de_ritmo_no_es_un_punto_solo() (+2 more)

### Community 161 - "Community 161"
Cohesion: 0.20
Nodes (5): shutil, tempfile, skipif, Escenario "filtro frenético" del harness de carga (C7 del cuelgue de Pruebas…, test_el_script_de_k6_es_javascript_valido()

### Community 163 - "Community 163"
Cohesion: 0.22
Nodes (9): _falso_render(), _orden(), Los cambios que se mandaron, en orden, resumidos., El estado intermedio "muchos workers sobre poca CPU" es la peor combinación…, Al revés: primero la CPU, después los workers que la van a usar., Simula la API de Render y devuelve la lista de llamadas en orden., test_al_bajar_de_plan_los_workers_bajan_primero(), test_al_subir_de_plan_los_workers_suben_despues() (+1 more)

### Community 164 - "Community 164"
Cohesion: 0.31
Nodes (7): main(), numeros_del_texto(), Auditoría de carga/experimentos.json contra los datos crudos. Existe por un…, Las cifras que aparecen en una frase, normalizadas. Antes de extraerlas se…, Todas las cifras que este test PUEDE citar: las de sus propias tablas y cargas,…, revisar(), vocabulario_de()

### Community 165 - "Community 165"
Cohesion: 0.25
Nodes (9): modulo_habilitado(), modulos_habilitados(), Módulos que tiene disponibles este sindicato (ver modulos.py). Lista vacía si…, Reemplaza los permisos del área. Descarta cualquier sección que no exista en el…, set_permisos_area(), Simula una fila ya migrada (grandfathered): todo lo que existía antes del…, test_grandfathering_helpers(), Ver el mapa (sección "dashboard") y cargar una dirección (sección… (+1 more)

### Community 166 - "Community 166"
Cohesion: 0.42
Nodes (8): _login_admin(), _login_trabajador(), Smoke test E2E con Playwright: el robot entra por las pantallas REALES. A…, Entra con el primer CUIL del lote que exista. Devuelve cuál fue.…, test_admin_dashboard_carga_con_datos(), test_admin_dashboard_modal_ver(), test_trabajador_entra_a_su_app(), Page

### Community 167 - "Community 167"
Cohesion: 0.36
Nodes (8): _funcion(), skipif, Front del Panel Sindical: menos presión sobre el servidor (C4 del cuelgue de…, test_debounce_de_400_ms_y_abortador_vigente(), test_el_refresco_usa_la_cola_y_no_una_rafaga(), test_la_cola_nunca_pasa_de_cuatro_en_vuelo_y_termina_todo(), test_los_contadores_de_pestanas_inactivas_van_despues_de_los_paneles(), test_un_503_se_reintenta_y_solo_el_503()

### Community 168 - "Community 168"
Cohesion: 0.44
Nodes (8): _cuantas(), _guardar(), La ruta /admin/formula prueba la expresión ANTES de guardarla. Antes no se…, test_coma_decimal_se_rechaza(), test_editar_a_una_expresion_rota_tampoco_pasa(), test_expresion_valida_se_guarda(), test_signo_porcentaje_se_rechaza(), test_variable_inexistente_se_rechaza()

### Community 169 - "Community 169"
Cohesion: 0.25
Nodes (9): _errores_emitidos(), _errores_renderizados(), Los `err=` que manda main.py, en sus dos formas de escritura., El agujero de fondo. Un `err=` sin cartel es una pantalla que vuelve al panel…, El otro lado: un cartel que nadie dispara es código que miente sobre lo que la…, Regresión puntual del que faltaba, por si el test general se afloja., test_no_hay_carteles_muertos(), test_sinarea_tiene_cartel() (+1 more)

### Community 170 - "Community 170"
Cohesion: 0.25
Nodes (5): parsear_filtros(), date, Por empresa del tenant: MAX(fecha_ultimo_deposito) sobre sus recibos, días…, Valida y normaliza los query params comunes del dashboard. `params` es un…, semaforo()

### Community 171 - "Community 171"
Cohesion: 0.29
Nodes (8): areas_que_vieron(), puede_responder_tramite(), puede_ver_tramite(), Las áreas que tuvieron el trámite alguna vez: la que lo tiene ahora más todas…, Ver y RESPONDER son cosas distintas desde que existe el pase. El área que…, Si ESTE usuario alcanza ESE trámite, por los dos ejes. No alcanza con filtrar…, El caso real: 'esto no era para nosotros'., test_la_cadena_funciona_y_se_puede_devolver()

### Community 172 - "Community 172"
Cohesion: 0.25
Nodes (7): ErrorApp, HTTPException, Un error con código propio. El status y el mensaje salen de MENSAJES, así que…, api_enviar_sindicato(), api_reportar(), payload = {"recibo": {...}, "resultado": {...}} — se guarda el recibo completo,…, Envío voluntario y explícito del trabajador: comparte los datos de su recibo…

### Community 173 - "Community 173"
Cohesion: 0.36
Nodes (6): _a_numero(), _fecha_iso_de_ar(), _procesado_en_de(), columnas analiticas de reciboverificado (Panel Sindical) Los agregados del…, dd/mm/AAAA HH:MM" (como guardaba main.py) -> "AAAA-MM-DD HH:MM"., upgrade()

### Community 174 - "Community 174"
Cohesion: 0.25
Nodes (8): _avisos(), _indicadores(), _participacion(), Participación, avisos leídos, ritmo y estado. Los dos primeros solo sirven…, (padrón, respondieron) del grupo. Del padrón, que sabe quién participó pero…, Enviados y leídos de TODOS los avisos de la encuesta, y el desglose por envío:…, Respuestas por día, de la URNA. Sale del `dia` que guarda la urna y no del…, _ritmo()

### Community 175 - "Community 175"
Cohesion: 0.25
Nodes (8): _id_trabajador(), La regla de privacidad también vale para los totales: con afiliado elegido…, Las consultas al bot son anónimas: con afiliado, nada (y el KPI es None, no 0…, test_afiliado_ajeno_o_inexistente_no_matchea_nada(), test_afiliado_no_aplica_a_consultas(), test_afiliado_recibos_solo_los_enviados(), test_afiliado_tramites_y_notificaciones(), test_buscar_afiliados()

### Community 176 - "Community 176"
Cohesion: 0.29
Nodes (5): Red de seguridad: cualquier excepción no prevista tiene que devolver JSON (no…, test_500_en_llamada_fetch_sigue_devolviendo_json(), test_500_en_post_de_pagina_completa_redirige_con_aviso(), _get_session_roto(), test_excepcion_no_prevista_devuelve_json_no_texto_plano()

### Community 178 - "Community 178"
Cohesion: 0.39
Nodes (7): Verificación de: (1) Total neto = ingresos - descuentos, (2) el CUIL del recibo…, _recibo(), test_cuil_coincide_no_genera_discrepancia(), test_cuil_no_coincide_bloquea_y_no_chequea_nada(), test_cuil_no_coincide_helper(), test_sin_cuil_sesion_no_rompe(), test_total_neto_es_ingresos_menos_descuentos()

### Community 179 - "Community 179"
Cohesion: 0.33
Nodes (5): PersonaAmbigua, PersonaNoEncontrada, Exception, El admin nombró a alguien que no está en el padrón. Se le avisa al modelo (como…, Varios afiliados coinciden. Se resuelve en el cajón, con un clic del admin, SIN…

### Community 180 - "Community 180"
Cohesion: 0.29
Nodes (7): init_db(), Marca como error los documentos que quedaron en "procesando". La indexación…, Inicialización en el arranque. NO crea tablas: el esquema lo administra Alembic…, rescatar_indexaciones_colgadas(), _startup(), on_event, test_seed_aefip_ya_no_se_siembra_solo()

### Community 181 - "Community 181"
Cohesion: 0.38
Nodes (7): modelos_ia(), {uso: modelo_id} para los tres usos de precios_ia.USOS, ya resuelto: lo que…, default_de(), Fail-closed: el panel muestra "el de origen" al lado de uno de estos ids. Si…, test_guardar_los_modelos_desde_el_panel(), test_los_defaults_son_las_constantes_de_los_modulos(), test_sin_configuracion_corre_el_default_del_modulo()

### Community 182 - "Community 182"
Cohesion: 0.29
Nodes (6): logging_config, Entorno de Alembic para Mi Trabajo. Usa el MISMO engine y modelos que la…, Modo offline: emite SQL sin conectarse (genera scripts)., Modo online: la misma base y los mismos modelos que la app, pero con el engine…, run_migrations_offline(), run_migrations_online()

### Community 183 - "Community 183"
Cohesion: 0.29
Nodes (6): _csv_nominal(), Una fila por persona del padrón, con sus respuestas. Va todo el padrón y no…, {cuil: {pregunta_id: [filas de la urna]}}, vía RespuestaNominal., Lo que esa persona contestó a esa pregunta, en una celda., _respuestas_por_cuil(), _texto_de_respuesta()

### Community 184 - "Community 184"
Cohesion: 0.48
Nodes (6): acotar(), mover(), resetear(), soltar(), trasladar(), vigilarCierre()

### Community 185 - "Community 185"
Cohesion: 0.29
Nodes (4): grafana(), GrafanaDeMentira, fixture, Reemplaza a Grafana.pedir: responde lo que Grafana respondería y anota cada…

### Community 186 - "Community 186"
Cohesion: 0.43
Nodes (6): _mock_response(), Verificación del Punto 1 del Sprint A (extractor bi-formato). No llama a la API…, _run_extraer_con_mock(), test_clasico(), test_nuevo(), types

### Community 187 - "Community 187"
Cohesion: 0.33
Nodes (6): anonimizar_detalle(), detalle_recibo(), detalle_reporte(), Borra EN EL LUGAR los datos identificatorios del trabajador y de la empresa de…, El recibo para el modal "Ver" de Reportes: el mismo del Panel (anonimizado y…, El recibo completo tal como quedó verificado (conceptos, totales,…

### Community 188 - "Community 188"
Cohesion: 0.33
Nodes (6): actualizar_test_carga(), Lo llama el Job (proceso aparte, misma base) para dejar avance, resumen final,…, La lista de /entornos ya no embebe la tabla de resultados -- linkea a…, La página de detalle (/entornos/tests/{id}): config real con la que corrió, la…, test_entornos_renderiza_la_pestana_tests_con_el_link_al_detalle(), test_pagina_detalle_de_test_muestra_config_resultados_y_analisis()

### Community 189 - "Community 189"
Cohesion: 0.33
Nodes (6): Editable SOLO desde el panel de plataforma (mismo criterio que el tope…, set_config_dashboard(), test_consultas_prendido(), test_detalle_consulta_flag(), test_pagina_dashboard_flag_prendido(), test_plataforma_edita_color_destacado_y_umbrales()

### Community 190 - "Community 190"
Cohesion: 0.33
Nodes (3): _Informe, Un hito del guion, con el segundo en que ocurrió., Un dato verificable que el robot dejó en la app (ej. el número de expediente),…

### Community 191 - "Community 191"
Cohesion: 0.33
Nodes (6): armar_direccion_texto(), La dirección como se muestra, armada de los campos estructurados. La arma el…, En CABA la localidad y la provincia son la misma cosa, y la primera versión…, test_armar_direccion_texto_completa(), test_armar_direccion_texto_tolera_huecos(), test_caba_no_se_escribe_dos_veces()

### Community 192 - "Community 192"
Cohesion: 0.60
Nodes (5): _agregar_bloque(), downgrade(), _quitar_bloque(), los datos personales del afiliado pasan a la persona Revision ID: a7e3f90b5c21…, upgrade()

### Community 193 - "Community 193"
Cohesion: 0.33
Nodes (6): _serie_render(), test_convertir_renombra_etiquetas_y_descarta_las_redundantes(), test_los_pedidos_http_traen_codigo_de_estado_y_host(), test_un_valor_nulo_no_se_manda_como_cero(), test_una_metrica_que_falla_no_tira_las_demas(), falso()

### Community 194 - "Community 194"
Cohesion: 0.33
Nodes (4): fixture, Transport, sentry(), TransporteFalso

### Community 195 - "Community 195"
Cohesion: 0.53
Nodes (5): Verificación del Punto 2 del Sprint A (tope sindical 2%, Ley 27.802 art. 133).…, _recibo(), test_afiliacion_no_cuenta_para_el_tope(), test_no_supera_el_tope(), test_supera_el_tope()

### Community 197 - "Community 197"
Cohesion: 0.50
Nodes (3): _agregar_domicilio(), georreferenciacion de seccionales y domicilios Revision ID: e3b7a91c5d64…, upgrade()

### Community 198 - "Community 198"
Cohesion: 0.40
Nodes (5): _dia(), La red de seguridad del bug de arriba: si el servidor rechaza los filtros, el…, test_rangos_invalidos_422(), test_serie_recibos_rellena_dias_vacios(), test_un_rango_rechazado_dice_por_que_y_la_pantalla_tiene_donde_decirlo()

### Community 199 - "Community 199"
Cohesion: 0.40
Nodes (5): _ids_recibos(), El detalle guardado TIENE nombre/CUIL/legajo adentro del JSON: el servidor los…, test_detalle_aislamiento_de_tenant(), test_detalle_recibo_enviado_identificado(), test_detalle_recibo_no_enviado_anonimizado()

### Community 200 - "Community 200"
Cohesion: 0.40
Nodes (5): Durante un deploy Render devuelve dos instancias; la vieja queda sin datos…, test_cada_grafico_en_vivo_muestra_el_uso_junto_a_su_limite(), test_la_fila_en_vivo_consulta_a_render_directo_y_siempre_trae_ahora(), test_la_fila_en_vivo_elige_la_instancia_mas_reciente_durante_un_deploy(), _vivos()

### Community 202 - "Community 202"
Cohesion: 0.67
Nodes (3): construir_md(), Regenera carga/INFORME.md desde carga/experimentos.json, con el mismo contenido…, tabla()

### Community 203 - "Community 203"
Cohesion: 0.50
Nodes (4): _cuiles_por_nombre(), _normalizar(), CUILes del padrón cuyo nombre contiene todas las palabras buscadas, sin…, minúsculas, sin tildes, sin puntuación, espacios simples.

### Community 204 - "Community 204"
Cohesion: 0.50
Nodes (4): PaseTipoTramite, Un área a la que ESTE formulario se puede derivar. La lista es CERRADA y se…, Reemplaza la lista cerrada de destinos de pase del formulario. Descarta áreas…, set_areas_de_pase()

### Community 205 - "Community 205"
Cohesion: 0.50
Nodes (4): El JS sin sus comentarios, para poder buscar código y no prosa., El bug que esto impide: el panel armaba su rango con `new Date()` del NAVEGADOR…, _sin_comentarios(), test_la_pagina_le_da_al_navegador_la_fecha_del_servidor()

### Community 206 - "Community 206"
Cohesion: 0.50
Nodes (4): Un usuario de área con EXACTAMENTE esas secciones. Es como se prueba que las…, Dos pastillas y no una pantalla sola: el constructor es largo y dejaba la lista…, test_el_panel_arranca_en_la_lista_salvo_que_no_haya_ninguna(), _usuario_de_area()

## Knowledge Gaps
- **38 isolated node(s):** `background_color`, `description`, `display`, `icons`, `lang` (+33 more)
  These have ≤1 connection - possible missing edges. (Counts symbols only; 2194 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **65 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_session()` connect `Community 6` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 11`, `Community 13`, `Community 14`, `Community 15`, `Community 143`, `Community 17`, `Community 20`, `Community 21`, `Community 23`, `Community 153`, `Community 26`, `Community 25`, `Community 29`, `Community 30`, `Community 32`, `Community 33`, `Community 36`, `Community 165`, `Community 170`, `Community 43`, `Community 172`, `Community 45`, `Community 44`, `Community 47`, `Community 48`, `Community 175`, `Community 50`, `Community 51`, `Community 52`, `Community 180`, `Community 187`, `Community 59`, `Community 189`, `Community 63`, `Community 67`, `Community 203`, `Community 77`, `Community 206`, `Community 79`, `Community 80`, `Community 81`, `Community 82`, `Community 83`, `Community 89`, `Community 106`, `Community 117`, `Community 122`, `Community 123`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Why does `UsuarioSindicato` connect `Community 123` to `Community 0`, `Community 128`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 11`, `Community 139`, `Community 13`, `Community 14`, `Community 15`, `Community 21`, `Community 23`, `Community 25`, `Community 27`, `Community 30`, `Community 32`, `Community 36`, `Community 37`, `Community 165`, `Community 168`, `Community 45`, `Community 47`, `Community 48`, `Community 176`, `Community 51`, `Community 52`, `Community 55`, `Community 57`, `Community 59`, `Community 61`, `Community 63`, `Community 64`, `Community 65`, `Community 66`, `Community 77`, `Community 206`, `Community 80`, `Community 81`, `Community 82`, `Community 83`, `Community 85`, `Community 86`, `Community 88`, `Community 90`, `Community 100`, `Community 111`, `Community 116`, `Community 119`, `Community 120`?**
  _High betweenness centrality (0.015) - this node is a cross-community bridge._
- **Why does `validar()` connect `Community 105` to `Community 3`, `Community 131`, `Community 69`, `Community 5`, `Community 99`, `Community 195`, `Community 122`, `Community 107`, `Community 178`, `Community 22`, `Community 186`, `Community 60`?**
  _High betweenness centrality (0.014) - this node is a cross-community bridge._
- **Are the 37 inferred relationships involving `Sindicato` (e.g. with `main()` and `buscar_sindicato()`) actually correct?**
  _`Sindicato` has 37 INFERRED edges - model-reasoned connections that need verification._
- **What connects `background_color`, `description`, `display` to the rest of the system?**
  _38 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.013528939246607195 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.03680843900796768 - nodes in this community are weakly interconnected._