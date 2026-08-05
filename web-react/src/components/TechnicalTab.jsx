import { useEffect, useState } from "react";
import API from "../api.js";

function LossCurveSvg({ points }) {
  if (!points || !points.length) return <p className="muted">Pas de données de perte.</p>;
  const W = 600, H = 200, pad = 30;
  const xs = points.map((p) => p.iteration), ys = points.map((p) => p.loss);
  const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
  const sx = (i) => pad + ((i - xmin) / (xmax - xmin || 1)) * (W - 2 * pad);
  const sy = (l) => H - pad - ((l - ymin) / (ymax - ymin || 1)) * (H - 2 * pad);
  const path = points.map((p, i) => `${i ? "L" : "M"}${sx(p.iteration).toFixed(1)},${sy(p.loss).toFixed(1)}`).join(" ");
  return (
    <svg className="loss" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="var(--outline-variant)" />
      <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="var(--outline-variant)" />
      <path d={path} fill="none" stroke="var(--primary-container)" strokeWidth="2" />
      <text x={pad} y={pad - 8} fontSize="11" fill="var(--on-surface-variant)">perte {ymax.toFixed(2)} → {ymin.toFixed(2)}</text>
    </svg>
  );
}

export default function TechnicalTab() {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    API.technical().then(setD).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="error-box">{error}</div>;
  if (!d) return <p className="muted">Chargement…</p>;

  const of = d.overfitting;

  return (
    <div className="stack">
      <div className="card"><div className="section-head"><span className="label-caps">Donut vs baseline</span></div>
        <table>
          <thead><tr><th>Modèle</th><th className="num">Exactitude</th><th className="num">JSON valide</th><th>Entraîné par moi</th></tr></thead>
          <tbody>
            {d.results.map((r, i) => (
              <tr key={i}>
                <td>{r.modele}</td>
                <td className="num">{r.exactitude_total != null ? (r.exactitude_total * 100).toFixed(1) + "%" : "—"}</td>
                <td className="num">{r.json_valide != null ? (r.json_valide * 100).toFixed(1) + "%" : "—"}</td>
                <td>{r.entraine_par_moi ? "oui" : "non"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {of.length > 0 && (
        <div className="card"><div className="section-head"><span className="label-caps">Sur-apprentissage (baseline maison)</span></div>
          <div className="section-body kpi-grid">
            <div className="kpi"><div className="label-caps">Écart sans régularisation</div><div className="value">{(of[0].ecart * 100).toFixed(1)}%</div></div>
            <div className="kpi kpi--alert"><div className="label-caps">Écart avec régularisation</div><div className="value">{(of[of.length - 1].ecart * 100).toFixed(1)}%</div></div>
            <div className="kpi"><div className="label-caps">Train (régularisé)</div><div className="value">{(of[of.length - 1].train * 100).toFixed(1)}%</div></div>
            <div className="kpi"><div className="label-caps">Validation (régularisé)</div><div className="value">{(of[of.length - 1].validation * 100).toFixed(1)}%</div></div>
          </div>
          <table>
            <thead><tr><th>Config</th><th className="num">Train</th><th className="num">Validation</th><th className="num">Écart</th></tr></thead>
            <tbody>
              {of.map((r, i) => (
                <tr key={i}>
                  <td>{r.config}</td><td className="num">{(r.train * 100).toFixed(1)}%</td>
                  <td className="num">{(r.validation * 100).toFixed(1)}%</td><td className="num">{(r.ecart * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card"><div className="section-head"><span className="label-caps">Courbe de perte (entraînement baseline)</span></div>
        <div className="section-body"><LossCurveSvg points={d.loss_curve} /></div>
      </div>

      <div className="card"><div className="section-body">
        <div className="label-caps">Méthodologie : drapeau binaire plutôt que pourcentage de confiance</div>
        <p className="body-sm">Un champ est marqué <b>« à vérifier »</b> (booléen) s'il est absent, nul, ou s'il fait échouer une règle.
          Nous n'affichons <b>volontairement aucun pourcentage de confiance</b> : un score comme « 85 % » laisse croire à une
          fiabilité mesurée alors qu'il ne reflète que la confiance interne du modèle, pas l'exactitude réelle du champ.
          Le binaire évite ce faux sentiment de certitude et pousse à la vérification humaine.</p>
      </div></div>
    </div>
  );
}
