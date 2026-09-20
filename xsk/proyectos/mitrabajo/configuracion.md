---
proyecto: mitrabajo
nombre: Colm3na (MITRABAJOC)
repositorio: snavello/MITRABAJOC
entornos_dinamicos: pruebas, demo
entornos_destructivos: pruebas
actualizado: 2026-09-20
---

# Etapa 0 — Configuración

Qué necesita XSK para correr sobre Colm3na. **Este archivo nombra la variable
o el lugar; los valores viven en `.env` (local) o en Render.** Estado:
`tengo` (disponible hoy), `falta` (hay que conseguirlo), `confirmar` (existe
pero hay que verificar que sirva para esto).

## Entornos y acceso

| Dato | Para qué | Dónde vive | Estado |
|---|---|---|---|
| URL de Pruebas y Demo | tests dinámicos | `entorno.URLS` en el código | tengo |
| Entorno objetivo por defecto | a cuál pega Code si no se dice | `.env` → `XSK_ENTORNO_OBJETIVO` (`pruebas`) | tengo |
| Dominio propio | perímetro, cookies, HSTS, CSP | a definir con SDN | falta |
| Base de Pruebas (External URL) | verificar qué quedó escrito tras un test; limpiar | `.env` → `PRUEBAS_DATABASE_URL` | confirmar |
| Base de Demo (External URL) | ídem | `.env` → `DEMO_DATABASE_URL` | tengo |
| Poder recargar Pruebas/Demo | volver a un estado conocido tras un test destructivo | `cargar_demo.py` + lotes | tengo |

## Cuentas para atacar (una por rol)

Las de la demo (`CLAUDE.md`, "Accesos de la demo") sirven en Pruebas y Demo
porque los datos son los mismos. Faltan las que **no** existen a propósito:

| Cuenta | Rol | Estado |
|---|---|---|
| Plataforma (`PLATAFORMA_CUIT` + `PLATAFORMA_PASSWORD`) | admin de plataforma | tengo (`.env`) |
| Admin UOM, Admin Gastronómica, Admin Bancaria | Super Admin de tres sindicatos distintos (para aislamiento) | tengo |
| Admin de Seccional Rosario, Prensa Central, Prensa Córdoba | los tres roles del sindicato | tengo |
| Trabajador UOM, trabajador pluriempleo | afiliado | tengo |
| Empresa un sindicato, empresa multisindicato | empleador | tengo (registro en `/ingresar-empresa`) |
| Un usuario **desactivado** de cada rol | ¿sigue entrando? | falta: crearlos en Pruebas |
| Un trabajador de un sindicato **sin módulos** | ¿ve lo que no contrató? | falta: crearlo en Pruebas |

## Infraestructura

| Dato | Para qué | Dónde vive | Estado |
|---|---|---|---|
| API key de Render | leer configuración de servicios, variables, planes, health check | `.env` → `RENDER_API_KEY` (ya la usa el colector) | tengo |
| Token de Cloudflare | crear/verificar reglas del perímetro cuando exista | `.env` → `CLOUDFLARE_API_TOKEN` | falta: no hay cuenta todavía |
| `gh` autenticado | ramas, reglas de protección, secretos de Actions, colaboradores | `gh auth status` | tengo |
| Tokens de Grafana / Sentry | eje OBS: ¿se ve un ataque? | Render de Pruebas | tengo |
| Docker Desktop | herramientas que corren en contenedor (ZAP, si se usa) | a mano, avisar si no corre | tengo |
| Copia de la base en S3 | eje INF: ensayo de restauración, permisos del bucket | `.env` → `XSK_S3_BACKUP` (bucket/prefijo) + credenciales de solo lectura | falta: SDN dice que existe; hay que apuntarla |
| Proveedor de mail | R2 nivel 2 y R3 (confirmación de alta, recuperación de clave) | a elegir | falta: no existe |

## Herramientas de Code

Se instalan en la etapa 4, en `requirements-dev.txt` (jamás en
`requirements.txt`). Candidatas: `bandit`, `semgrep`, `pip-audit`,
`gitleaks` (binario), `sslyze`; `k6` ya está instalado; `httpx` ya es
dependencia de la app.

## Lo que XSK NO va a tocar sin preguntar

- Producción (no existe todavía; cuando exista, solo `configuracion`).
- Demo con tests `destructivo: si` (solo Pruebas, ver cabecera).
- Cuentas de personas reales, si alguna vez las hubiera en Pruebas.
