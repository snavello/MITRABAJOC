"""Extrae del código fuente lo que la documentación técnica necesita exacto:
modelos (tablas, columnas, FKs, índices, JSON, bytes), migraciones (id,
padre, fecha, título) y rutas (método, path, función, primera línea del
docstring). Deja todo en datos.json para que generar.py arme el HTML.
"""
import ast
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def _src(node, texto):
    return ast.get_source_segment(texto, node)


def modelos():
    texto = (RAIZ / "db.py").read_text(encoding="utf-8")
    arbol = ast.parse(texto)
    tablas = []
    for nodo in arbol.body:
        if not isinstance(nodo, ast.ClassDef):
            continue
        if not any(isinstance(k.value, ast.Constant) and k.arg == "table" and k.value.value for k in nodo.keywords):
            continue
        doc = ast.get_docstring(nodo) or ""
        cols = []
        for item in nodo.body:
            if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                continue
            nombre = item.target.id
            tipo = _src(item.annotation, texto)
            info = {"nombre": nombre, "tipo": tipo, "pk": False, "fk": None, "index": False,
                    "unique": False, "json": False, "bytes": "bytes" in tipo, "default": None,
                    "nullable": tipo.startswith("Optional["), "vector": False}
            v = item.value
            if isinstance(v, ast.Call) and getattr(v.func, "id", "") == "Field":
                for kw in v.keywords:
                    val = _src(kw.value, texto)
                    if kw.arg == "primary_key" and val == "True":
                        info["pk"] = True
                    elif kw.arg == "foreign_key":
                        info["fk"] = ast.literal_eval(kw.value)
                    elif kw.arg == "index" and val == "True":
                        info["index"] = True
                    elif kw.arg == "unique" and val == "True":
                        info["unique"] = True
                    elif kw.arg == "default":
                        info["default"] = val
                    elif kw.arg == "sa_column":
                        if "JSON" in val:
                            info["json"] = True
                        if "Vector" in val:
                            info["vector"] = True
                        if "index=True" in val:
                            info["index"] = True
                        if "unique=True" in val:
                            info["unique"] = True
                if v.args:
                    info["default"] = _src(v.args[0], texto)
            elif v is not None:
                info["default"] = _src(v, texto)
            cols.append(info)
        tablas.append({"clase": nodo.name, "tabla": nodo.name.lower(), "doc": doc, "linea": nodo.lineno,
                       "columnas": cols})
    return tablas


def migraciones():
    lista = []
    for f in sorted((RAIZ / "migrations/versions").glob("*.py")):
        s = f.read_text(encoding="utf-8")
        rev = re.search(r"^revision(?:: str)? = '([^']+)'", s, re.M).group(1)
        down = re.search(r"^down_revision[^=]*= (.+)$", s, re.M).group(1).strip()
        down = None if down == "None" else down.strip("'\"")
        fecha = re.search(r"Create Date: (\S+)", s)
        titulo = s.split('"""', 2)[1].strip().splitlines()[0].strip() if s.startswith('"""') else f.stem
        lista.append({"rev": rev, "down": down, "fecha": fecha.group(1) if fecha else "", "titulo": titulo,
                      "archivo": f.name, "crea_tabla": sorted(set(re.findall(r"op\.create_table\('([^']+)'", s)))})
    # Orden por cadena
    por_down = {m["down"]: m for m in lista}
    orden, actual = [], por_down.get(None)
    while actual:
        orden.append(actual)
        actual = por_down.get(actual["rev"])
    return orden


def rutas():
    texto = (RAIZ / "main.py").read_text(encoding="utf-8")
    arbol = ast.parse(texto)
    lista = []
    for nodo in arbol.body:
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in nodo.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and \
                    getattr(dec.func.value, "id", "") == "app" and dec.func.attr in ("get", "post", "put", "delete"):
                path = ast.literal_eval(dec.args[0])
                doc = (ast.get_docstring(nodo) or "").strip().split("\n\n")[0].replace("\n", " ")
                lista.append({"metodo": dec.func.attr.upper(), "path": path, "funcion": nodo.name,
                              "linea": nodo.lineno, "doc": doc})
    return lista


def main():
    datos = {"tablas": modelos(), "migraciones": migraciones(), "rutas": rutas()}
    salida = Path(__file__).with_name("datos.json")
    salida.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"tablas {len(datos['tablas'])}, columnas {sum(len(t['columnas']) for t in datos['tablas'])}, "
          f"migraciones {len(datos['migraciones'])}, rutas {len(datos['rutas'])}")
    for t in datos["tablas"]:
        fks = [c["fk"] for c in t["columnas"] if c["fk"]]
        print(f"  {t['tabla']:34} {len(t['columnas']):2} col  fk→{fks}")


if __name__ == "__main__":
    main()
