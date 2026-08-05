import { useState } from "react";
import API from "../api.js";
import { QuestionFlowDiagram } from "../helpers.jsx";
import { ReceiptDetail } from "./ReceiptDetail.jsx";

const SUGGESTIONS = [
  "Combien ai-je dépensé en boissons ?",
  "Montre-moi les reçus de plus de 100 000",
  "Quel est le total du dernier trimestre ?",
];

export default function AskTab({ country, demoMode, sessionEmpty, groqConfigured, onEditReceipt }) {
  const [q, setQ] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState([]);
  const [openId, setOpenId] = useState(null);

  async function doAsk(question) {
    const text = (question ?? q).trim();
    if (!text) return;
    setQ(text);
    setLoading(true); setError(null);
    try {
      const d = await API.search(text);
      setResult(d);
      setHistory((h) => [text, ...h].slice(0, 10));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  if (openId != null) {
    return (
      <ReceiptDetail id={openId} country={demoMode ? "ID" : country} demoMode={demoMode}
        onBack={() => setOpenId(null)}
        onEdit={(id) => onEditReceipt(id)}
        onDeleted={() => setOpenId(null)} />
    );
  }

  return (
    <div>
      <h2 className="headline-sm" style={{ marginTop: 0 }}>Interroger l'historique de dépenses</h2>
      <QuestionFlowDiagram />
      <div style={{ margin: "var(--md) 0" }}>
        <input placeholder="Ex. : combien ai-je dépensé en boissons ?" value={q}
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") doAsk(); }} />
      </div>
      <div className="pill-row" style={{ marginBottom: "var(--md)" }}>
        {SUGGESTIONS.map((s) => (
          <span key={s} className="pill" onClick={() => doAsk(s)}>{s}</span>
        ))}
      </div>
      <div className="btn-row" style={{ marginBottom: "var(--lg)" }}>
        <button className="btn btn--primary" onClick={() => doAsk()}>Chercher</button>
      </div>

      <div className="stack">
        {sessionEmpty && !demoMode && !result && (
          <div className="banner">🔬 Vous n'avez pas encore de reçus personnels. La recherche porte sur le
            <b> corpus de référence CORD</b> (800 reçus indonésiens). Analysez vos propres reçus dans l'onglet Analyser pour interroger VOS dépenses.</div>
        )}
        {loading && <p className="muted">Recherche…</p>}
        {error && <div className="error-box">{error}</div>}
        {result && !loading && (result.search_available === false ? (
          <div className="banner">{result.note}</div>
        ) : (
          <>
            {result.reference_corpus ? (
              <div className="banner">🔬 Recherche dans le <b>corpus de référence CORD</b> (aucun reçu personnel pour l'instant — ce ne sont pas vos dépenses).</div>
            ) : result.demo_mode ? (
              <div className="banner">🔬 <b>Mode démonstration</b> : recherche dans le corpus CORD, pas vos dépenses réelles.</div>
            ) : (
              <div className="banner">🔎 Recherche dans <b>vos reçus</b> ({result.sources ? result.sources.length : 0} résultat(s) le(s) plus pertinent(s)).</div>
            )}
            <div className="card"><div className="section-head"><span className="label-caps">Réponse</span></div>
              <div className="section-body">
                {result.answer ? result.answer : (
                  <>D'après les reçus les plus pertinents pour : <i>{q}</i>.{!groqConfigured && (
                    <span className="muted body-sm"> (réponse LLM désactivée : aucune clé Groq)</span>
                  )}</>
                )}
              </div>
            </div>
            <div className="card">
              <div className="section-head">
                <span className="label-caps" title="Recherche augmentée par récupération (RAG) : la réponse est construite à partir de ces documents réels, pas inventée par l'IA.">
                  Reçus sources — la réponse est construite à partir d'eux, pas inventée
                </span>
              </div>
              <div className="section-body stack">
                {(result.sources || []).map((s, i) => {
                  const clickable = s.receipt_id != null;
                  return (
                    <div key={i} className={`card${clickable ? " receipt-open" : ""}`}
                         title={clickable ? "Voir le détail de ce reçu" : undefined}
                         onClick={clickable ? () => setOpenId(s.receipt_id) : undefined}>
                      <div className="section-body">
                        <span className="score">Pertinence {(s.score * 100).toFixed(0)}%</span>
                        <div className="bar-track" style={{ margin: "6px 0" }}>
                          <span className="bar-fill" style={{ width: Math.max(0, Math.min(100, s.score * 100)) + "%" }}></span>
                        </div>
                        {s.text}{clickable && <span className="muted body-sm"> — cliquer pour le détail</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        ))}
      </div>

      {history.length > 0 && (
        <div style={{ marginTop: "var(--lg)" }}>
          <div className="label-caps">Questions précédentes</div>
          {history.map((h, i) => <div key={i} className="muted body-sm">• {h}</div>)}
        </div>
      )}
    </div>
  );
}
