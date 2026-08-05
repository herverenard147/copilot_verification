import { useEffect, useState } from "react";
import API from "../api.js";
import { toast } from "../toast.jsx";
import { AccountSection } from "./AccountSection.jsx";

const GROQ_SS_KEY = "receiptflow.groqKey";
const KEY_STATUS_LABEL = {
  env: "✅ Configurée (variable d'environnement) — saisissez une clé pour la remplacer",
  session: "✅ Configurée (session)",
  none: "➖ Non configurée — recherche dans vos reçus, sans réponse rédigée",
};

function ApiKeySection({ onConfigChange }) {
  const [status, setStatus] = useState("Vérification de l'état…");
  const [keyInput, setKeyInput] = useState("");
  const [testResult, setTestResult] = useState("");
  const [modelsResult, setModelsResult] = useState("");

  async function refreshStatus() {
    try {
      let s = await API.keyStatus();
      let src = s.groq.source;
      if (src === "none") {
        const saved = sessionStorage.getItem(GROQ_SS_KEY);
        if (saved) {
          try { await API.setKey("groq", saved); s = await API.keyStatus(); src = s.groq.source; }
          catch (e) { sessionStorage.removeItem(GROQ_SS_KEY); }
        }
      }
      setStatus(KEY_STATUS_LABEL[src] || src);
      onConfigChange({ groq_configured: src !== "none" });
    } catch (e) {
      setStatus("État indisponible.");
    }
  }

  useEffect(() => { refreshStatus(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    const key = keyInput.trim();
    try {
      await API.setKey("groq", key);
      sessionStorage.setItem(GROQ_SS_KEY, key);
      setKeyInput(""); setTestResult("");
      toast("✅ Clé Groq enregistrée (session)");
      refreshStatus();
    } catch (e) {
      toast("Clé refusée : " + e.message);
    }
  }

  async function clear() {
    try { await API.clearKey("groq"); } catch (e) { /* on efface côté nav quoi qu'il arrive */ }
    sessionStorage.removeItem(GROQ_SS_KEY);
    setKeyInput(""); setTestResult("");
    toast("Clé effacée");
    refreshStatus();
  }

  async function test() {
    setTestResult("Test en cours…");
    try {
      const typed = keyInput.trim();
      if (typed) {
        await API.setKey("groq", typed);
        sessionStorage.setItem(GROQ_SS_KEY, typed);
        setKeyInput("");
      }
      const d = await API.testKey("groq");
      setTestResult("✅ " + (d.message || "Connexion réussie."));
      refreshStatus();
    } catch (e) {
      setTestResult("❌ " + e.message + (e.detail ? " — " + e.detail : ""));
      refreshStatus();
    }
  }

  async function listModels() {
    setModelsResult("Interrogation des modèles…");
    try {
      const d = await API.models();
      const visionLine = d.vision_available
        ? `✅ Vision utilisable : ${d.vision_selected}`
        : "⚠️ Aucun modèle vision accessible avec cette clé — le fallback vision est indisponible.";
      setModelsResult(visionLine + " — " + (d.vision.join(", ") || "—"));
    } catch (e) {
      setModelsResult("❌ " + e.message);
    }
  }

  return (
    <div className="card"><div className="section-head"><span className="label-caps">Clés API</span></div>
      <div className="section-body stack">
        <div>
          <label className="field" htmlFor="in-groq-key">Clé Groq</label>
          <input id="in-groq-key" type="password" autoComplete="off" placeholder="gsk_…"
                 value={keyInput} onChange={(e) => setKeyInput(e.target.value)} />
          <div className="body-sm muted" style={{ marginTop: "var(--xs)" }}>{status}</div>
        </div>
        <div className="btn-row">
          <button className="btn" onClick={test}>Tester la connexion</button>
          <button className="btn btn--primary" onClick={save}>Enregistrer</button>
          <button className="btn" onClick={clear}>Effacer</button>
        </div>
        {testResult && <div className="body-sm">{testResult}</div>}
        <div className="btn-row"><button className="btn" onClick={listModels}>Voir les modèles disponibles</button></div>
        {modelsResult && <div className="body-sm">{modelsResult}</div>}
        <p className="muted body-sm">🔒 Obtenez une clé gratuite sur <b>console.groq.com</b>.
          Elle sert à la lecture de secours quand Donut échoue, à l'extraction du nom du commerçant et de la date,
          et à la rédaction des réponses dans l'onglet Questions.
          La clé reste <b>en mémoire</b> (jamais écrite sur disque, jamais renvoyée par le serveur).</p>
      </div>
    </div>
  );
}

function DemoSection({ demoInfo, onSessionChange }) {
  const [result, setResult] = useState("");

  useEffect(() => {
    if (!demoInfo) return;
    setResult(demoInfo.demoMode
      ? `🔬 Mode démonstration actif — ${demoInfo.nReceipts} reçus du corpus CORD.`
      : (demoInfo.nReceipts ? `${demoInfo.nReceipts} reçu(s) dans votre session.` : "Session vide."));
  }, [demoInfo]);

  async function enable() {
    setResult("Chargement du corpus…");
    try {
      const d = await API.setDemo(true);
      onSessionChange({ demoMode: true, sessionEmpty: !!d.empty, nReceipts: d.n_receipts || 0 });
      toast("🔬 Données de démonstration chargées");
    } catch (e) { setResult("Échec : " + e.message); }
  }
  async function disable() {
    try {
      const d = await API.clearSession();
      onSessionChange({ demoMode: false, sessionEmpty: !!d.empty, nReceipts: d.n_receipts || 0 });
      toast("Session vidée");
    } catch (e) { setResult("Échec : " + e.message); }
  }

  return (
    <div className="card"><div className="section-head"><span className="label-caps">Données de démonstration</span></div>
      <div className="section-body stack">
        <p className="body-sm">Peuple le tableau de bord et la comptabilité avec le <b>corpus CORD</b>
          (≈800 reçus indonésiens) pour une démonstration, sans déposer de reçus. Un bandeau permanent
          le signale. Ce ne sont <b>pas</b> vos dépenses réelles.</p>
        <div className="btn-row">
          <button className="btn btn--primary" onClick={enable}>Charger les données de démonstration</button>
          <button className="btn" onClick={disable}>Vider mes données de session</button>
        </div>
        <div className="body-sm muted">{result}</div>
      </div>
    </div>
  );
}

export default function SettingsPanel({ config, onConfigChange, demoInfo, onSessionChange, auth }) {
  if (!config) return null;
  const taxes = Object.entries(config.countries || {});
  const accounts = Object.entries(config.chart_of_accounts || {});

  return (
    <div className="stack">
      <AccountSection auth={auth} />

      <div className="card"><div className="section-head"><span className="label-caps">Pays et taux de TVA</span></div>
        <div className="section-body">
          {taxes.map(([k, r]) => <div className="muted body-sm" key={k}>{k} : {(r * 100).toFixed(0)} %</div>)}
        </div>
      </div>

      <ApiKeySection onConfigChange={onConfigChange} />
      <DemoSection demoInfo={demoInfo} onSessionChange={onSessionChange} />

      <div className="card"><div className="section-head"><span className="label-caps">Plan de comptes (SYSCOHADA)</span></div>
        <table><thead><tr><th>Compte</th><th>Libellé</th></tr></thead>
          <tbody>{accounts.map(([code, lbl]) => <tr key={code}><td>{code}</td><td>{lbl}</td></tr>)}</tbody>
        </table>
      </div>
      <p className="muted body-sm">ℹ️ {config.disclaimer}</p>
    </div>
  );
}
