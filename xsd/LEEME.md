# XSD en Colm3na

XSD (XSANDERS Design Kit) es la auditoría de diseño con revisores en
paralelo, informe interactivo de decisiones, aplicación con agentes y
segunda vuelta. Se pide con **«revisá el diseño con XSD»** o con `/xsd`.

**El kit vive en su propio repositorio**, snavello/xsanders-design-kit, como
plugin de Claude Code. Su `README.md` explica cómo instalarlo en otro proyecto.
Acá quedan dos cosas:

```
.claude/skills/xsd/      copia textual de la skill del kit, fijada a un commit (ORIGEN.md)
                         METODO.md, plantillas/, herramientas/xsd.py, capturar.cjs, informe/
xsd/proyectos/mitrabajo/ lo de Colm3na: ficha, inventario (60 pantallas), sesiones.py,
                         contexto, historial y los consolidados de cada vuelta
xsd/proyectos/mitrabajo/catalogo/fuentes/
                         las 113 fichas de estilo extraídas del concurso de diseño y de otras
                         propuestas, de donde salieron los 60 del catálogo
```

El kit trae además el **catálogo de estilos**: los 60 estilos de interfaz aplicados a la portada de ACME,
una organización inventada. Se pide con «mostrame el catálogo XSD» o con `/xsd catalogo`. El detalle está en
`.claude/skills/xsd/catalogo/LEEME.md`.

La copia no se edita acá. Un cambio al método o a las herramientas se hace
en el repositorio del kit y se vuelve a copiar. `ORIGEN.md` explica cómo, y
`test_xsd.py` falla si la copia no es la del commit fijado.

La ventana de avance (plugin `avance-agentes`) es opcional y se instala
desde el mismo repositorio:
`/plugin marketplace add snavello/xsanders-design-kit` y después
`/plugin install avance-agentes@xsanders-design-kit`.
