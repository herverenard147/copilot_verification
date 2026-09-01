import { money } from "./utils.js";
import { Icon } from "./Icons.jsx";

// Fidèlement porté de web/js/app.js (chip 3 états, contrôles, diagramme,
// badges) — logique et libellés identiques ; seule la présentation change
// (icônes SVG plutôt qu'emoji, voir DECISIONS.md de la maquette).

const CHIP_META = {
  true: ["chip--ok", "check", "Contrôle conforme"],
  false: ["chip--bad", "warn", "Anomalie détectée sur ce contrôle"],
  null: ["chip--neutral", "minus", "Non vérifiable, information absente sur ce reçu"],
};

export function Chip({ label, value }) {
  const key = value === true ? "true" : value === false ? "false" : "null";
  const [cls, icon, tip] = CHIP_META[key];
  return <span className={`chip ${cls}`} title={tip}><Icon name={icon} className="icon" style={{ width: 13, height: 13 }} />{label}</span>;
}

function pct(rate) {
  return rate.toLocaleString("fr-FR", { maximumFractionDigits: 2 }) + " %";
}

function Control({ title, value, msgs }) {
  const key = value === true ? "ok" : value === false ? "bad" : "none";
  const meta = { ok: ["chip--ok", "check"], bad: ["chip--bad", "warn"], none: ["chip--neutral", "minus"] }[key];
  const detailCls = key === "bad" ? "control-detail control-detail--bad" : "control-detail";
  return (
    <div className="control-row">
      <div className="control-head">
        <span className={`chip ${meta[0]}`}><Icon name={meta[1]} className="icon" style={{ width: 13, height: 13 }} /></span>
        <span className="control-title">{title}</span>
      </div>
      <div className={detailCls}>{msgs[key]}</div>
    </div>
  );
}

export function ControlsPanel({ audit, balanced, receipt, journal, country }) {
  const a = audit || {};
  const sub = receipt.subtotal, tax = receipt.tax, total = receipt.total;
  const itemsSum = (receipt.items || []).reduce((s, it) => s + (Number(it.line_price) || 0), 0);
  const td = (journal || []).reduce((s, l) => s + (l.debit || 0), 0);
  const tc = (journal || []).reduce((s, l) => s + (l.credit || 0), 0);
  const isID = country !== "CI";
  const ctyLabel = isID ? "indonésien" : "ivoirien";
  const expRate = isID ? 11 : 18;
  const rate = tax && sub ? (tax / sub) * 100 : null;
  const attendu = (sub || 0) + (tax || 0), diff = (total || 0) - attendu;

  return (
    <>
      <Control title="Somme des articles" value={a.line_sum_ok} msgs={{
        ok: `La somme des articles (${money(itemsSum)}) correspond au sous-total (${money(sub)})`,
        bad: `La somme des articles (${money(itemsSum)}) ne correspond pas au sous-total annoncé (${money(sub)}), écart de ${money(Math.abs(itemsSum - (sub || 0)))}. Vérifiez qu'aucun article ne manque.`,
        none: "Le sous-total n'est pas indiqué sur ce reçu, vérification impossible",
      }} />
      <Control title="Calcul du total" value={a.total_ok} msgs={{
        ok: `Sous-total (${money(sub)}) + taxe (${money(tax || 0)}) = total (${money(total)})`,
        bad: `Sous-total (${money(sub)}) + taxe (${money(tax || 0)}) = ${money(attendu)}, mais le total indiqué est ${money(total)}. ${diff >= 0 ? "Il manque " + money(diff) : "Il y a " + money(-diff) + " de trop"}, peut-être un frais de service non extrait.`,
        none: "Le sous-total ou le total n'est pas indiqué, vérification impossible",
      }} />
      <Control title="Taux de taxe" value={a.tax_ok} msgs={{
        ok: `Taxe de ${rate != null ? pct(rate) : "?"}, cohérent avec le taux ${ctyLabel} (≈${expRate} %)`,
        bad: `Taxe de ${rate != null ? pct(rate) : "?"}, inhabituel pour le pays sélectionné (attendu ≈${expRate} %). Vérifiez le montant de la taxe.`,
        none: "Pas de taxe sur ce reçu, non vérifiable",
      }} />
      <Control title="Équilibre comptable" value={balanced} msgs={{
        ok: `Total des débits (${money(td)}) = total des crédits (${money(tc)})`,
        bad: "L'écriture est déséquilibrée, contactez un comptable",
        none: "Écriture non générée, données insuffisantes",
      }} />
    </>
  );
}

export function reviewPoints(audit, balanced, receipt) {
  const a = audit || {};
  const sub = receipt.subtotal, tax = receipt.tax, total = receipt.total;
  const itemsSum = (receipt.items || []).reduce((s, it) => s + (Number(it.line_price) || 0), 0);
  const pts = [];
  if (a.line_sum_ok === false) pts.push(`Somme des articles : écart de ${money(Math.abs(itemsSum - (sub || 0)))} entre les articles et le sous-total`);
  if (a.total_ok === false) {
    const d = (total || 0) - ((sub || 0) + (tax || 0));
    pts.push(`Calcul du total : il ${d >= 0 ? "manque " + money(d) : "y a " + money(-d) + " de trop"} entre sous-total + taxe et le total affiché`);
  }
  if (a.tax_ok === false) pts.push("Taux de taxe : le taux paraît inhabituel pour le pays sélectionné");
  if (balanced === false) pts.push("Équilibre comptable : l'écriture est déséquilibrée");
  return pts;
}

export function ReviewBanner({ pts, editable }) {
  if (!pts.length) return null;
  const close = editable
    ? "→ Corrigez les montants ci-dessus, les contrôles et l'écriture se recalculent automatiquement."
    : "→ Vérifiez ces montants sur le reçu d'origine.";
  return (
    <div className="banner">
      Ce reçu a {pts.length} point{pts.length > 1 ? "s" : ""} à vérifier :
      <ul style={{ margin: "var(--xs) 0 var(--xs) var(--lg)" }}>
        {pts.map((p, i) => <li key={i}>{p}</li>)}
      </ul>
      {close}
    </div>
  );
}

export function receiptStatus(r) {
  const flags = [r.line_sum_ok, r.total_ok, r.tax_ok];
  let fails = flags.filter((f) => f === false).length;
  if (fails === 0 && r.anomaly) fails = 1;
  if (fails > 0) return {
    status: "review", rowClass: "receipt-review",
    badge: <span className="badge badge--review"><Icon name="warn" className="icon" style={{ width: 13, height: 13 }} />{fails} point{fails > 1 ? "s" : ""} à vérifier</span>,
  };
  if (flags.some((f) => f === true)) return {
    status: "conforme", rowClass: "",
    badge: <span className="badge badge--verified"><Icon name="check" className="icon" style={{ width: 13, height: 13 }} />Vérifié</span>,
  };
  return {
    status: "nodata", rowClass: "",
    badge: <span className="badge badge--nodata"><Icon name="minus" className="icon" style={{ width: 13, height: 13 }} />Données insuffisantes</span>,
  };
}

export function receiptLabel(r) {
  const id = r.receipt_id;
  if (r && r.doc_type === "facture") {
    return r.invoice_number ? `Facture n°${r.invoice_number}` : `Facture #${id}`;
  }
  return `Reçu #${id}`;
}

export function EngineBadge({ engine }) {
  if (engine === "llm_fallback")
    return <span className="badge badge--fallback" title="Un modèle d'IA généraliste (LLM) a lu l'image parce que le modèle spécialisé n'y arrivait pas (ex. reçu hors de son domaine)."><Icon name="cpu" className="icon" style={{ width: 13, height: 13 }} />Lecture par IA de secours</span>;
  if (engine === "fallback_indisponible")
    return <span className="badge badge--fallback" title="Aucun modèle de secours accessible avec la clé Groq configurée."><Icon name="warn" className="icon" style={{ width: 13, height: 13 }} />Lecture de secours indisponible, modèle non accessible avec cette clé</span>;
  return <span className="badge badge--donut" title="Modèle spécialisé, entraîné pour la lecture de reçus."><Icon name="cpu" className="icon" style={{ width: 13, height: 13 }} />Lecture par modèle spécialisé</span>;
}

export function FlowDiagram() {
  return (
    <details className="flow-details">
      <summary><Icon name="info" className="icon" style={{ width: 14, height: 14 }} />Comment ça marche ?</summary>
      <div className="flow-wrap">
        <svg viewBox="0 0 600 110" className="flow-svg" role="img" aria-label="Article acheté, puis compte comptable, puis écriture">
          <rect x="10" y="20" width="170" height="60" rx="8" className="flow-box" />
          <text x="95" y="46" className="flow-label" textAnchor="middle">Article acheté</text>
          <text x="95" y="65" className="flow-sub" textAnchor="middle">ex. « Ramette papier »</text>
          <line x1="185" y1="50" x2="211" y2="50" className="flow-arrow" />
          <polygon points="211,43 226,50 211,57" className="flow-arrowhead" />
          <rect x="232" y="20" width="170" height="60" rx="8" className="flow-box" />
          <text x="317" y="46" className="flow-label" textAnchor="middle">Compte comptable</text>
          <text x="317" y="65" className="flow-sub" textAnchor="middle">ex. 601 (Achats)</text>
          <line x1="407" y1="50" x2="433" y2="50" className="flow-arrow" />
          <polygon points="433,43 448,50 433,57" className="flow-arrowhead" />
          <rect x="454" y="20" width="146" height="60" rx="8" className="flow-box flow-box--primary" />
          <text x="527" y="46" className="flow-label flow-label--on-primary" textAnchor="middle">Écriture</text>
          <text x="527" y="65" className="flow-sub flow-label--on-primary" textAnchor="middle">Débit / Crédit</text>
        </svg>
        <p className="muted body-sm">Chaque article est rattaché à un compte comptable selon sa catégorie
          (ex. fournitures → 601), qui devient une ligne de l'écriture ci-dessous : le montant sort en
          Débit (charge), la contrepartie apparaît en Crédit.</p>
      </div>
    </details>
  );
}

export function ImageOrPlaceholder({ file, imageData }) {
  // Un fichier local n'est previsualisable directement QUE si c'est deja une
  // image (URL.createObjectURL d'un PDF ne s'affiche pas dans un <img>) :
  // pour un PDF, on attend la miniature rendue cote serveur (imageData),
  // generee a partir de la page rasterisee (voir src/preprocess.py).
  const isImageFile = file && file.type && file.type.startsWith("image/");
  const src = isImageFile ? URL.createObjectURL(file) : (imageData || null);
  if (src) return <img className="receipt-img" src={src} alt="Image du reçu" />;
  return (
    <div className="card">
      <div className="section-body muted" style={{ textAlign: "center", padding: "var(--xl) var(--md)" }}>
        <Icon name="image" className="icon" style={{ width: 32, height: 32, margin: "0 auto 8px" }} />
        Image non disponible pour ce reçu
      </div>
    </div>
  );
}
