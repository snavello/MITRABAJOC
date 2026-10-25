/* Panel Sindical v2: cómo se escriben los números y las fechas.

   Las mismas reglas que la v1 (static/dashboard.js, retirada el 2026-10-25): números en es-AR, "—"
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

/* "AAAA-MM-DD" -> "dd/mm", para los ejes de los gráficos (`fCorta` de la v1). */
export function fCorta(iso) {
  const p = String(iso).split("-");
  return p[2] + "/" + p[1];
}

/* Los números de los ejes, los montos cortos y el CUIL (R4-02) salen de
   static/numeros_ar.js, el espejo en el navegador de formato_ar.py: la
   página lo carga como script común (window.NumAR) antes que los módulos.
   Así el eje de un gráfico, la tarjeta de arriba y el filtro `cuil` de
   Jinja escriben igual. Sin NumAR (Node, en los tests) los números caen a
   es-AR pelado, que da lo mismo, y el CUIL queda como vino. */
const AR = () => (typeof globalThis !== "undefined" && globalThis.NumAR) || null;
const miles = (n, d) => (AR() ? AR().miles(n, d)
  : Number(n).toLocaleString("es-AR", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }));

/* Un número de eje: "1.000", nunca "1,000". */
export const fmtEje = (v) => (v === null || v === undefined || v === "" ? "" : miles(Number(v), 0));

/* Un monto de eje, corto: "$ 0", "$ 500 mil", "$ 1,5 M". El ",0" no se
   escribe: "$ 2 M". */
export function fmtMEje(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  const signo = n < 0 ? "-" : "";
  const a = Math.abs(n);
  if (a >= 1e6) return signo + "$ " + miles(a / 1e6, 1).replace(/,0$/, "") + " M";
  if (a >= 1000) return signo + "$ " + miles(Math.round(a / 1000), 0) + " mil";
  return signo + "$ " + miles(Math.round(a), 0);
}

/* El CUIL con guiones (20-66000004-8): la regla del filtro `cuil` de Jinja,
   vía NumAR. Sin dato, "—". */
export function fCuil(v) {
  if (v === null || v === undefined || v === "") return "—";
  return AR() ? AR().cuil(v) : String(v);
}
