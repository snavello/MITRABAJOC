"""Los CUIL/CUIT de la demo, antes y después del módulo 11 (2026-10-10,
PLAN_CUIT_MOD11.md, etapa 3).

Hasta esa fecha NINGUNO de los números fijos de `cargar_demo.py` y
`cargar_bancaria.py` cumplía el dígito verificador, y desde que las altas y el
registro lo exigen el registro de las empresas de la demo dejaba de andar con
los viejos. Este mapa es la única fuente del cambio:

- `cargar_demo.py` y `cargar_bancaria.py` cargan los números NUEVOS
  (`test_identificadores_demo.py` verifica que todo número escrito en esos dos
  scripts sea un valor de este mapa);
- `regularizar_cuit.py` lo lee para clasificar un número viejo como "demo" y
  proponer exactamente el nuevo que está acá, así una base cargada antes
  (Pruebas, Demo) queda igual que una carga nueva.

Vive en un módulo propio y puro porque `cargar_demo.py` CARGA LA DEMO AL
IMPORTARSE (borra y recrea los sindicatos de demo): nadie puede importarlo
para leer una constante.

Los nuevos conservan los diez primeros dígitos con el verificador correcto
(`cuit.corregir`), salvo el admin de la UOM: corregido chocaba con Juan
Molina (20111111110 y 20111111119 dan los dos 20111111112), así que se le dio
el siguiente DNI libre (`cuit.siguiente_libre`). Es el caso que motivó la
regla de colisiones del plan (D4).
"""

REEMPLAZOS_MOD11 = {
    # UOM
    "30111111111": "30111111118",   # CUIT del sindicato (se guarda con guiones)
    "20111111110": "20111111120",   # Super Admin
    "20555555553": "20555555556",   # Admin de Seccional de Rosario
    "20666666665": "20666666667",
    "27131313136": "27131313131",
    "20101010109": "20101010105",
    "20121212127": "23121212129",   # r = 10: cambia el prefijo, como hace AFIP
    "27777777774": "27777777772",
    "20141414145": "20141414144",
    "20888888887": "20888888889",
    "20111111119": "20111111112",   # Juan Molina
    "27222222224": "27222222228",   # María Sánchez (pluriempleo, también en la Gastronómica)
    "20333333336": "20333333334",
    "30111222339": "30111222335",   # Constructora Ejemplo SA (multisindicato)
    "30999888776": "30999888778",   # Metalúrgica del Sur SRL
    # Federación Gastronómica
    "30222222222": "30222222229",   # CUIT del sindicato
    "20222222220": "20222222223",   # Super Admin
    "20999999991": "23999999999",   # r = 10
    "20444444440": "20444444445",
    # La Bancaria (cargar_bancaria.py)
    "20333444550": "20333444551",   # Super Admin
    "30525733859": "30525733854",   # CUIT del sindicato
}
