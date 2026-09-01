import { useEffect, useState } from "react";
import API from "../api.js";
import { money, barWidth } from "../utils.js";
import { receiptLabel } from "../helpers.jsx";
import { Icon } from "../Icons.jsx";
import { ReceiptList } from "./ReceiptList.jsx";
import { ReceiptDetail } from "./ReceiptDetail.jsx";

export default function DashboardTab({ active, refreshToken, country, demoMode, onSessionChange, onEditReceipt, onGoAnalyze }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [openId, setOpenId] = useState(null);

  async function load() {
    setError(null);
    try {
      const data = await API.dashboard();
      onSessionChange({ demoMode: !!data.demo_mode });
      setD(data);
    } catch (e) {
      setError(e.message);
    }
  }

  // Rechargé à chaque fois que l'onglet redevient actif (fidèle à l'ancien
  // switchTab() qui appelait systématiquement loadDashboard()), plus sur
  // refreshToken (ex. sortie du mode démo depuis le bandeau permanent).
  useEffect(() => { if (active) load(); }, [active, refreshToken]); // eslint-disable-line react-hooks/exhaustive-deps

  async function enableDemo() {
    try { await API.setDemo(true); } catch (e) { /* ignore */ }
    await load();
  }

  if (openId != null) {
    return (
      <ReceiptDetail id={openId} country={demoMode ? "ID" : country} demoMode={demoMode}
        onBack={() => setOpenId(null)}
        onEdit={(id) => onEditReceipt(id)}
        onDeleted={() => { setOpenId(null); load(); }} />
    );
  }

  if (error) return <div className="error-box">{error}</div>;
  if (!d) return <p className="muted">Chargement…</p>;

  if (d.empty) {
    return (
      <>
        <div className="kpi-grid">
          {["Reçus analysés", "Articles", "Dépense totale", "À vérifier"].map((lbl) => (
            <div className="kpi kpi--muted" key={lbl}><div className="label-caps">{lbl}</div><div className="value">0</div></div>
          ))}
        </div>
        <div className="card"><div className="empty-state">
          <div className="empty-icon"><Icon name="wave" className="icon" style={{ width: 32, height: 32 }} /></div>
          <p className="headline-sm">Bienvenue !</p>
          <p className="muted">Commencez par analyser un reçu, ou explorez l'application avec des données d'exemple.</p>
          <div className="btn-row" style={{ justifyContent: "center", marginTop: "var(--md)" }}>
            <button className="btn btn--primary" onClick={onGoAnalyze}><Icon name="camera" className="icon" style={{ width: 16, height: 16 }} />Analyser un reçu</button>
            <button className="btn" onClick={enableDemo}><Icon name="eye" className="icon" style={{ width: 16, height: 16 }} />Voir avec des données d'exemple</button>
          </div>
        </div></div>
      </>
    );
  }

  const k = d.kpis;
  const maxCat = Math.max(...d.by_category.map((c) => c.total), 1);
  const maxD = Math.max(...d.distribution.map((x) => x.count), 1);
  const totalReceipts = k.n_receipts || (d.receipts ? d.receipts.length : 0);
  const anomalyRate = totalReceipts ? (k.n_anomalies / totalReceipts) * 100 : 0;

  return (
    <>
      {/* Niveau 1 : vue d'ensemble chiffrée, toujours en premier */}
      <div className="kpi-grid">
        <div className="kpi"><div className="label-caps">Reçus analysés</div><div className="value">{money(k.n_receipts)}</div></div>
        <div className="kpi"><div className="label-caps">Articles</div><div className="value">{money(k.n_items)}</div></div>
        <div className="kpi"><div className="label-caps">Dépense totale</div><div className="value">{money(k.total_spend)}</div></div>
        <div className={`kpi ${k.n_anomalies ? "kpi--alert" : ""}`}
             style={k.n_anomalies ? { cursor: "pointer" } : undefined}
             title={k.n_anomalies ? "Voir les reçus à vérifier" : undefined}>
          <div className="label-caps">À vérifier</div><div className="value">{money(k.n_anomalies)}</div>
        </div>
      </div>

      {/* Ce qui nécessite une action passe avant l'exploration : jamais l'inverse */}
      {d.anomalies.length > 0 && (
        <div className="alert-section">
          <div className="alert-head">
            <Icon name="warn" className="icon-lg" />
            <span className="alert-title">Reçus à vérifier ({d.anomalies.length})</span>
          </div>
          <div className="alert-body-text">Ces reçus présentent des incohérences dans leurs montants. Cliquez sur un reçu pour voir le détail et corriger si nécessaire. Un signalement ne signifie pas une erreur certaine, il peut s'agir d'un frais de service non extrait ou d'un arrondi de caisse.</div>
          {anomalyRate > 15 && (
            <p className="banner">{money(k.n_anomalies)} reçus sur {money(totalReceipts)} ({anomalyRate.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %) présentent au moins une incohérence. La cause la plus fréquente est un écart entre sous-total + taxe et total, souvent dû à des frais de service ou pourboires non extraits par le modèle.</p>
          )}
          <div className="alert-list">
            {d.anomalies.slice(0, 30).map((a) => (
              <div className="alert-item receipt-open" key={a.receipt_id} title="Voir le détail du reçu" onClick={() => setOpenId(a.receipt_id)}>
                <b>{receiptLabel(a)}</b> : {a.rule}
                {a.a_label && (
                  <div className="detail tabular">{a.a_label} : {money(a.a_value)} · {a.b_label} : {money(a.b_value)}
                    · Écart : {money(Math.abs((a.b_value || 0) - (a.a_value || 0)))}</div>
                )}
              </div>
            ))}
            {d.anomalies.length > 30 && <p className="muted body-sm">… et {d.anomalies.length - 30} autres.</p>}
          </div>
        </div>
      )}

      {/* Niveau 2 — exploration, en retrait visuel par rapport à l'action */}
      <div className="panel-tinted">
        <div className="grid-2">
          <div className="card"><div className="card-head"><span className="card-head-label">Dépenses par catégorie</span></div>
            {d.by_category.length ? (
              <div className="bars">
                {d.by_category.map((c) => (
                  <div className="bar-row" key={c.category}>
                    <span>{c.category}</span>
                    <span className="bar-track"><span className="bar-fill" style={{ width: barWidth(c.total, maxCat) }}></span></span>
                    <span className="num">{money(c.total)}</span>
                  </div>
                ))}
              </div>
            ) : <div className="card-body"><p className="muted body-sm">Aucune catégorie identifiée</p></div>}
          </div>
          <div className="card"><div className="card-head"><span className="card-head-label">Répartition des totaux</span></div>
            <div className="bars">
              {d.distribution.map((x) => (
                <div className="bar-row" key={x.range}>
                  <span className="body-sm">{x.range}</span>
                  <span className="bar-track"><span className="bar-fill" style={{ width: barWidth(x.count, maxD) }}></span></span>
                  <span className="num">{x.count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <ReceiptList receipts={d.receipts} title="Vos reçus" filters onOpen={setOpenId} />
    </>
  );
}
