export function money(v) {
  if (v == null || (typeof v === "number" && isNaN(v))) return "-";
  const n = Number(v);
  const decimals = Number.isInteger(n) ? 0 : 2;
  return n.toLocaleString("fr-FR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// Largeur d'une barre : 0 quand la valeur est nulle, sinon au moins 3px pour
// qu'une petite valeur non nulle reste visible et ne se confonde pas avec
// le fond gris de la piste (repris tel quel de web/js/app.js).
export function barWidth(value, max) {
  if (!(value > 0)) return "0";
  return `max(3px, ${((value / max) * 100).toFixed(1)}%)`;
}
