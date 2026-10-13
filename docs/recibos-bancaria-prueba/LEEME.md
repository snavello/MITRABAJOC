# Recibos bancarios simulados para pruebas

Diez recibos de sueldo de La Bancaria (CCT 18/75), **simulados**, para subir a
la app (o imprimir y escanear) y ver cómo los lee y valida. Bancos y persona
son ficticios, y cada hoja lo dice al pie.

- **CUIL 27999999994** (el usuario de prueba de Pruebas, clave 27999): la app
  solo acepta recibos del CUIL con el que se inició sesión (E-RECIBO-04).
- **Período agosto 2026**, con los montos de la grilla firmada el 11/09/2026
  (`grilla_bancaria.py`, `docs/cct-1875-bancarios.md`). Rama administrativa.
- Aportes de ley 11% / 3% / 3% sobre el remunerativo, con el tope de agosto
  2026 ($ 4.594.798,23); cuota sindical 2% del bruto.
- El conformado figura como **"Complemento salario conformado"** (conformado
  menos básico). Es un nombre provisorio: la grilla no dice cómo lo imprime un
  banco.

| Archivo | Caso | Resultado esperado |
|---|---|---|
| 01-inicial-conformado | Ingresante: básico + complemento hasta el conformado, ROE $ 72.413,50 (el del comunicado) | OK |
| 02-cajero-titulo-secundario | 7 años, cajero (función y falla en dos líneas), título secundario | OK |
| 03-titulo-universitario-anexo-iii | 12 años, título universitario, **formato nuevo** (costo total empleador, Anexo III) | OK |
| 04-jefe-de-seccion-cajero | 20 años: el básico supera al conformado, sin complemento | OK |
| 05-zona-patagonica-sin-roe | 10 años, zona patagónica (Chubut), banco en el tramo de ROE que no paga | OK |
| 06-jefe-principal-tope | Jefe Ppal. de Dpto., **formato nuevo**: el bruto supera el tope, aportes sobre el tope | OK |
| 07-reintegro-ganancias | 15 años, título terciario, **devolución de Ganancias impresa entre los descuentos** | OK, con alerta de reintegro |
| 08-ERROR-jubilacion-10 | Jubilación al 10% en vez del 11% | Diferencia en Jubilación |
| 09-ERROR-sin-obra-social | No descuenta obra social | Falta Obra Social |
| 10-ERROR-neto-mal-sumado | El neto impreso tiene $ 10.000 menos de lo que da la cuenta | Total inconsistente (neto) |

Los resultados esperados los verifica `test_grilla_bancaria.py` con el
validador real, armando cada recibo igual que el PDF y pasándolo por el mismo
camino que `/api/leer` + `/api/validar`. Lo que el test NO cubre es la lectura
de la IA: si un PDF da otro resultado en la app, lo primero es mirar qué leyó.

**Regenerar** (después de una grilla nueva): reportlab no es dependencia del
proyecto, así que en un entorno aparte:

```
pip install reportlab
python docs/recibos-bancaria-prueba/generar.py
```

**Borrar lo que se cargó con ellos** (en Pruebas, como Job de Render):
`python cargar_bancaria.py --borrar-recibos-de 27999999994` para ver cuántas
filas hay, y con `--si` para borrarlas.
