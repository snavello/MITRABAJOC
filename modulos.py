"""Catálogo de módulos habilitables por sindicato.

El admin de plataforma elige, por sindicato, qué módulos tiene disponibles
(pensado para distintos modelos comerciales -- no todos los sindicatos
adoptan todo). Eso controla qué tarjetas ve el trabajador y qué pestañas ve
el admin del sindicato. Ver Sindicato.modulos_habilitados en db.py.
"""

MODULOS = {
    "recibos": "Tu recibo",
    "aportes": "Mis aportes",
    "credencial": "Credencial",
    "capacitacion": "Capacitación",
    "noticias": "Noticias",
    "beneficios": "Beneficios",
    "notificaciones": "Notificaciones",
    "tramites": "Trámites",
    # Un solo módulo gatea todo lo relacionado a empleadores: el CRUD de
    # empresas, las notificaciones sindicato→empresa y los formularios de
    # trámites externos -- no hay sub-toggles.
    "empleadores": "Empleadores",
    # Piloto de RAG (ver PLAN_RAG_CONVENIO.md). Opt-in, fuera de
    # MODULOS_INICIALES: ningún sindicato lo estrena sin pedirlo.
    "convenio": "Consultas sobre el convenio",
    # Panel Sindical (docs/DASHBOARD.md). Opt-in, fuera de MODULOS_INICIALES.
    # A futuro se diferenciará STD (KPIs + gráficos) de PRO (además, el
    # explorador de datos), excluyentes entre sí -- por eso el gate del
    # explorador en main.py pasa por su propio helper
    # (_exigir_dashboard_detalle) y no por _exigir_modulo directo: cuando
    # existan los dos módulos, se cambia solo ese helper.
    "dashboard": "Panel Sindical",
}

# Lo que existe HOY, para dar de alta un sindicato nuevo con todo tildado
# por default, y para el grandfathering de los sindicatos que ya existían
# antes de este sistema (ver migración b... tabla de módulos).
MODULOS_INICIALES = [
    "recibos", "aportes", "credencial", "capacitacion", "noticias", "beneficios",
]
