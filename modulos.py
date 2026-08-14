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
}

# Lo que existe HOY, para dar de alta un sindicato nuevo con todo tildado
# por default, y para el grandfathering de los sindicatos que ya existían
# antes de este sistema (ver migración b... tabla de módulos).
MODULOS_INICIALES = [
    "recibos", "aportes", "credencial", "capacitacion", "noticias", "beneficios",
]
