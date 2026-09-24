# Medición del enmascarado — 2026-09-24 18:10

Modelo: `claude-sonnet-4-6`. Cada recibo se leyó tres veces: **original**, **tapado** (con la identidad conocida, como el afiliado) y **tapado sin conocidos** (como el aprendizaje del admin). Criterio del plan: cero diferencias en importes y en la clasificación de cada línea.

| Recibo | Camino | Zonas | Fugas | Totales iguales | Líneas (orig/tap/sin) | Líneas distintas | Período y categoría | Identidad rearmada (CUIL/CUIT/nombre) | Alerta adulteración |
|---|---|---|---|---|---|---|---|---|---|
| recibo_2014_12.pdf | pdf_imagen | 17 | 0 | sí | 17/17/17 | 0 de 17 | sí | sí/sí/sí | False/False/False |
| recibo_2015_01.pdf | pdf_imagen | 17 | 0 | sí | 17/17/17 | 0 de 17 | sí | sí/sí/sí | False/False/False |
| recibo_2015_02.pdf | pdf_imagen | 17 | 0 | sí | 16/16/16 | 1 de 16 | sí | sí/sí/sí | False/False/False |
| recibo_2015_03.pdf | pdf_imagen | 17 | 0 | sí | 17/17/17 | 0 de 17 | sí | sí/sí/sí | False/False/False |
| recibo_2015_04.pdf | pdf_imagen | 17 | 0 | sí | 17/17/17 | 0 de 17 | sí | sí/sí/sí | False/False/False |
| recibo_2015_06.pdf | pdf_imagen | 17 | 0 | sí | 17/17/17 | 1 de 17 | sí | sí/sí/sí | False/False/False |
| recibo_2015_07.pdf | pdf_imagen | 17 | 0 | sí | 17/17/17 | 0 de 17 | sí | sí/sí/sí | False/False/False |
| recibo_2015_08.pdf | pdf_imagen | 17 | 0 | sí | 17/17/17 | 0 de 17 | sí | sí/sí/sí | False/False/False |
| recibo_2015_09.pdf | pdf_imagen | 17 | 0 | sí | 16/16/16 | 0 de 16 | sí | sí/sí/sí | False/False/False |
| recibo_2015_10.pdf | pdf_imagen | 17 | 0 | sí | 17/17/17 | 1 de 17 | sí | sí/sí/sí | False/False/False |
| recibo_digital_ficticio.pdf | pdf_texto | 17 | 0 | sí | 8/8/8 | 0 de 8 | sí | sí/sí/sí | False/False/False |

## Líneas que difieren

- **recibo_2015_02.pdf** `44-001` SEGURO OBLIGATORIO - DGI (-380,00): original: otro · tapado: aporte_trabajador · sin conocidos: aporte_trabajador
- **recibo_2015_06.pdf** `44-001` SEGURO OBLIGATORIO - DGI (-380,00): original: aporte_trabajador · tapado: aporte_trabajador · sin conocidos: otro
- **recibo_2015_10.pdf** `44-001` SEGURO OBLIGATORIO - DGI (-380,00): original: otro · tapado: aporte_trabajador · sin conocidos: aporte_trabajador

## Identidad leída y rearmada

- **recibo_2014_12.pdf**: cuil: 27999999999 / 27999999999 / 27999999999; cuit: 30444640975 / 30444640975 / 30444640975; nombre: NIEVES, JULIA / NIEVES, JULIA / NIEVES, JULIA; legajo: 045213/07 / 045213/07 / 045213/07; empleador: TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA
- **recibo_2015_01.pdf**: cuil: 27999999999 / 27999999999 / 27999999999; cuit: 30444640975 / 30444640975 / 30444640975; nombre: NIEVES, JULIA / NIEVES, JULIA / NIEVES, JULIA; legajo: 045213/07 / 045213/07 / 045213/07; empleador: TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA
- **recibo_2015_02.pdf**: cuil: 27999999999 / 27999999999 / 27999999999; cuit: 30444640975 / 30444640975 / 30444640975; nombre: NIEVES, JULIA / NIEVES, JULIA / NIEVES, JULIA; legajo: 045213/07 / 045213/07 / 045213/07; empleador: TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA
- **recibo_2015_03.pdf**: cuil: 27999999999 / 27999999999 / 27999999999; cuit: 30444640975 / 30444640975 / 30444640975; nombre: NIEVES, JULIA / NIEVES, JULIA / NIEVES, JULIA; legajo: 045213/07 / 045213/07 / 045213/07; empleador: TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA. / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA.
- **recibo_2015_04.pdf**: cuil: 27999999999 / 27999999999 / 27999999999; cuit: 30444640975 / 30444640975 / 30444640975; nombre: NIEVES, JULIA / NIEVES, JULIA / NIEVES, JULIA; legajo: 045213/07 / 045213/07 / 045213/07; empleador: TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA. / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA.
- **recibo_2015_06.pdf**: cuil: 27999999999 / 27999999999 / 27999999999; cuit: 30444640975 / 30444640975 / 30444640975; nombre: NIEVES, JULIA / NIEVES, JULIA / NIEVES, JULIA; legajo: 045213/07 / 045213/07 / 045213/07; empleador: TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA
- **recibo_2015_07.pdf**: cuil: 27999999999 / 27999999999 / 27999999999; cuit: 30444640975 / 30444640975 / 30444640975; nombre: NIEVES, JULIA / NIEVES, JULIA / NIEVES, JULIA; legajo: 045213/07 / 045213/07 / 045213/07; empleador: TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA. / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA.
- **recibo_2015_08.pdf**: cuil: 27999999999 / 27999999999 / 27999999999; cuit: 30444640975 / 30444640975 / 30444640975; nombre: NIEVES, JULIA / NIEVES, JULIA / NIEVES, JULIA; legajo: 045213/07 / 045213/07 / 045213/07; empleador: TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA. / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA.
- **recibo_2015_09.pdf**: cuil: 27999999999 / 27999999999 / 27999999999; cuit: 30444640975 / 30444640975 / 30444640975; nombre: NIEVES, JULIA / NIEVES, JULIA / NIEVES, JULIA; legajo: 045213/07 / 045213/07 / 045213/07; empleador: TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA
- **recibo_2015_10.pdf**: cuil: 27999999999 / 27999999999 / 27999999999; cuit: 30444640975 / 30444640975 / 30444640975; nombre: NIEVES, JULIA / NIEVES, JULIA / NIEVES, JULIA; legajo: 045213/07 / 045213/07 / 045213/07; empleador: TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA / TALLERES METALURGICOS DEL SUR SOCIEDAD ANONIMA
- **recibo_digital_ficticio.pdf**: cuil: 27287654311 / 27287654311 / 27287654311; cuit: 30712345671 / 30712345671 / 30712345671; nombre: GONZÁLEZ PEÑA, MARÍA JOSÉ / GONZÁLEZ PEÑA, MARÍA JOSÉ / GONZÁLEZ PEÑA, MARÍA JOSÉ; legajo: 1187 / 1187 / 1187; empleador: DISTRIBUIDORA LOS ANDES S.R.L. / DISTRIBUIDORA LOS ANDES S.R.L. / DISTRIBUIDORA LOS ANDES S.R.L.
