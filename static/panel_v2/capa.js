/* Panel Sindical v2: lo que se abre por encima de todo (el cajón de filtros,
   y después los modales) se pinta AFUERA de <main>, en #capas.

   Por qué: <main class="mesa-cont"> se levanta sobre el fondo de la mesa con
   `z-index: 1` (static/interior.css), y eso arma una capa propia: nada de
   adentro puede quedar por encima del encabezado, por más z-index que tenga.
   La v1 tiene su modal después de </main> por lo mismo.

   Es el "portal" de siempre, hecho con lo que trae Preact: los hijos se
   pintan en otra raíz cada vez que la capa se actualiza. */
import { render } from "preact";
import { useEffect, useRef } from "preact/hooks";

export function Capa({ children }) {
  const destino = useRef(null);
  if (!destino.current) destino.current = document.getElementById("capas");
  useEffect(() => { render(children, destino.current); });
  useEffect(() => () => render(null, destino.current), []);
  return null;
}
