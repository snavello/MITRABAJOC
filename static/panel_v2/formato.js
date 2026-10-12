/* Panel Sindical v2: cómo se escriben los números y las fechas.

   Las mismas reglas que la v1 (static/dashboard.js): números en es-AR, "—"
   cuando no hay dato (nunca un 0 inventado), plata redondeada a pesos y
   fechas dd/mm/aaaa. Puro: Node lo prueba. */

export const fmtN = (n) => (n === null || n === undefined) ? "—" : Number(n).toLocaleString("es-AR");
export const fmtM = (n) => (n === null || n === undefined) ? "—" : "$ " + Math.round(n).toLocaleString("es-AR");

/* Un porcentaje como lo escribe la v1: el número que manda el servidor, con
   coma decimal ("20,8 %"; un 20 queda "20 %"). */
export const fmtPct = (n) => (n === null || n === undefined) ? "—" : String(n).replace(".", ",") + " %";

/* "AAAA-MM-DD[ HH:MM]" -> "dd/mm/aaaa". */
export function fFecha(s) {
  if (!s) return "—";
  const p = String(s).slice(0, 10).split("-");
  return p[2] + "/" + p[1] + "/" + p[0];
}

/* "AAAA-MM-DD" -> "lunes, 12 de octubre de 2026". */
export function fechaLarga(iso) {
  const [a, m, d] = String(iso).split("-").map(Number);
  if (!a || !m || !d) return String(iso || "");
  return new Date(a, m - 1, d).toLocaleDateString("es-AR",
    { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

/* La variación de "Recibos analizados" contra el período anterior de igual
   largo, con el mismo texto que la v1. */
export function deltaRecibos(actual, anterior) {
  if (!anterior) return { clase: "neu", texto: "s/d período anterior" };
  const pct = (actual - anterior) / anterior * 100;
  return { clase: pct >= 0 ? "up" : "down",
    texto: (pct >= 0 ? "▲ " : "▼ ") + Math.abs(pct).toFixed(0) + "% vs período anterior" };
}
