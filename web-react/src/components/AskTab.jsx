import { useState } from "react";
import API from "../api.js";
import { Icon } from "../Icons.jsx";
import { Modal } from "./Modal.jsx";
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

  return (
    <>
      <div style={{ textAlign: "center" }}>
        <h1 className="page-title" style={{ textAlign: "center" }}>Interrogez vos dépenses</h1>
        <p className="page-sub">La réponse n'est pas inventée : elle est construite à partir de vos reçus réels.</p>
      </div>

      <div className="search-box">
        <Icon name="search" className="icon" />
        <input placeholder="Ex. : combien ai-je dépensé en boissons ?" value={q}
               name="ask-question" autoComplete="off"
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") doAsk(); }} />
      </div>
      <div className="chip-row">
        {SUGGESTIONS.map((s) => (
          <span key={s} className="pill" onClick={() => doAsk(s)}>{s}</span>
        ))}
      </div>
      <div className="btn-row" style={{ justifyContent: "center" }}>
        <button className="btn btn--primary" onClick={() => doAsk()}>Chercher</button>
      </div>

      {demoMode && !result && (
        <div className="banner">Vous n'avez pas encore de reçus personnels. La recherche porte sur des
          <b> données d'exemple</b>. Analysez vos propres reçus dans l'onglet Analyser pour interroger VOS dépenses.</div>
      )}
      {loading && <p className="muted">Recherche…</p>}
      {error && <div className="error-box">{error}</div>}
      {result && !loading && (result.search_available === false ? (
        <div className="banner">{result.note}</div>
      ) : (
        <>
          {result.reference_corpus ? (
            <div className="banner">Recherche dans des <b>données de référence</b> (aucun reçu personnel pour l'instant, ce ne sont pas vos dépenses).</div>
          ) : result.demo_mode ? (
            <div className="banner"><b>Mode démonstration</b> : recherche dans des données d'exemple, pas vos dépenses réelles.</div>
          ) : (
            <div className="banner">Recherche dans <b>vos reçus</b> ({result.sources ? result.sources.length : 0} résultat(s) le(s) plus pertinent(s)).</div>
          )}

          <div className="answer-card">
            <div className="answer-q">{q}</div>
            <div className="answer-text">
              {result.answer ? result.answer : (
                <>D'après les reçus les plus pertinents pour : <i>{q}</i>.{!groqConfigured && (
                  <span className="muted body-sm"> (réponse LLM désactivée : aucune clé Groq)</span>
                )}</>
              )}
            </div>

            <div className="sources-label" title="Recherche augmentée par récupération (RAG) : la réponse est construite à partir de ces documents réels, pas inventée par l'IA.">
              Sources : la réponse est construite à partir d'eux, pas inventée
            </div>
            <div className="source-list">
              {(result.sources || []).map((s, i) => {
                const clickable = s.receipt_id != null;
                return (
                  <div key={i} className="source-item"
                       title={clickable ? "Voir le détail de ce reçu" : undefined}
                       onClick={clickable ? () => setOpenId(s.receipt_id) : undefined}
                       style={clickable ? undefined : { cursor: "default" }}>
                    <div><b>{s.text}</b></div>
                    <div className="source-meta">
                      <span className="score">{(s.score * 100).toFixed(0)}%</span>
                      {clickable && <span className="view-link">Voir le détail</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      ))}

      {history.length > 0 && (
        <div>
          <div className="label-caps">Questions précédentes</div>
          {history.map((h, i) => <div key={i} className="muted body-sm">{h}</div>)}
        </div>
      )}

      <Modal open={openId != null} onClose={() => setOpenId(null)} wide>
        {openId != null && (
          <ReceiptDetail id={openId} country={demoMode ? "ID" : country} demoMode={demoMode} inModal
            onBack={() => setOpenId(null)}
            onEdit={(id) => onEditReceipt(id)}
            onDeleted={() => setOpenId(null)} />
        )}
      </Modal>
    </>
  );
}
