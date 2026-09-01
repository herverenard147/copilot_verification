import { useEffect, useState } from "react";
import API from "../api.js";
import { toast } from "../toast.jsx";
import { Icon } from "../Icons.jsx";

// Logique portée telle quelle de SettingsPanel.jsx (ApiKeySection,
// DemoSection, taux/plan de comptes/mentions) -- la section Compte a été
// déplacée dans ProfilTab.jsx. Présentation alignée sur
// ParametresSidebar.dc.html.

const GROQ_SS_KEY = "receiptflow.groqKey";
const KEY_STATUS_LABEL = {
  session: "Configurée (session)",
  none: "Non configurée, recherche dans vos reçus, sans réponse rédigée",
};
const COUNTRY_LABELS = { CI: "Côte d'Ivoire", ID: "Indonésie" };

function ApiKeySection({ onConfigChange }) {
  const [source, setSource] = useState(null); // "env" | "session" | "none" | null (chargement)
  const [status, setStatus] = useState("Vérification de l'état…");
  const [keyInput, setKeyInput] = useState("");
  const [testResult, setTestResult] = useState("");

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
      setSource(src);
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
      toast("Clé Groq enregistrée (session)");
      refreshStatus();
    } catch (e) {
      toast("Clé refusée : " + e.message);
    }
  }

  async function test() {
    setTestResult("Test en cours…");
    try {
      const d = await API.testKey("groq");
      setTestResult(d.message || "Connexion réussie.");
    } catch (e) {
      setTestResult("Échec : " + e.message + (e.detail ? " : " + e.detail : ""));
    }
  }

  // Clé permanente (variable d'environnement, configurée une fois pour toute
  // l'instance) : rien à saisir ni à gérer ici, juste un statut de contrôle.
  if (source === "env") {
    return (
      <div className="card">
        <div className="card-head"><span className="card-head-label">Lecture de secours (IA)</span></div>
        <div className="card-body">
          <div className="status-line"><Icon name="check" className="icon" style={{ width: 14, height: 14 }} />Configurée pour toute l'application</div>
          <div className="btn-row"><button className="btn" onClick={test}>Tester la connexion</button></div>
          {testResult && <div className="body-sm">{testResult}</div>}
          <p className="disclaimer">Sert de secours quand le modèle spécialisé échoue, à la vérification qu'une
            image est bien un reçu avant analyse, à l'extraction du nom du commerçant, et aux réponses dans l'onglet
            Questions.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-head"><span className="card-head-label">Clé API Groq (lecture de secours)</span></div>
      <div className="card-body">
        <div className="field">
          <span className="field-label">Clé Groq</span>
          <input type="password" autoComplete="off" placeholder="gsk_…" value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)} />
        </div>
        <div className={source && source !== "none" ? "status-line" : "status-line muted"}>
          {source && source !== "none" && <Icon name="check" className="icon" style={{ width: 14, height: 14 }} />}
          {status}
        </div>
        <div className="btn-row">
          <button className="btn" onClick={test}>Tester la connexion</button>
          <button className="btn primary" onClick={save}>Enregistrer</button>
        </div>
        {testResult && <div className="body-sm">{testResult}</div>}
        <p className="disclaimer">Obtenez une clé gratuite sur <b>console.groq.com</b>. Elle sert à la lecture de
          secours quand le modèle spécialisé échoue, à l'extraction du nom du commerçant et de la date, et aux
          réponses dans l'onglet Questions. Elle reste en mémoire, jamais écrite sur disque.</p>
      </div>
    </div>
  );
}

function DemoSection({ demoInfo, onSessionChange }) {
  const [result, setResult] = useState("");

  useEffect(() => {
    if (!demoInfo) return;
    setResult(demoInfo.demoMode
      ? `Mode démonstration actif, ${demoInfo.nReceipts} reçus d'exemple.`
      : (demoInfo.nReceipts ? `${demoInfo.nReceipts} reçu(s) dans votre session.` : "Session vide."));
  }, [demoInfo]);

  async function enable() {
    setResult("Chargement des données d'exemple…");
    try {
      const d = await API.setDemo(true);
      onSessionChange({ demoMode: true, sessionEmpty: !!d.empty, nReceipts: d.n_receipts || 0 });
      toast("Données d'exemple chargées");
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
    <div className="card">
      <div className="card-head"><span className="card-head-label">Données d'exemple</span></div>
      <div className="card-body">
        <p className="disclaimer" style={{ margin: 0 }}>Peuple le tableau de bord et la comptabilité avec un jeu de
          données d'exemple, sans déposer de reçus. Un bandeau permanent le signale, ce ne sont pas vos dépenses
          réelles.</p>
        <div className="btn-row">
          <button className="btn primary" onClick={enable}>Charger les données d'exemple</button>
          <button className="btn" onClick={disable}>Vider ma session</button>
        </div>
        <div className="body-sm muted">{result}</div>
      </div>
    </div>
  );
}

export default function ParametresTab({ config, onConfigChange, demoInfo, onSessionChange, isProd }) {
  if (!config) return null;
  const taxes = Object.entries(config.countries || {});
  const accounts = Object.entries(config.chart_of_accounts || {});

  return (
    <>
      <h1 className="page-title">Paramètres</h1>

      <div className="card">
        <div className="card-head"><span className="card-head-label">Pays et taux de TVA</span></div>
        <div className="card-body" style={{ gap: 0 }}>
          {taxes.map(([k, r]) => (
            <div className="rate-row" key={k}>
              <span className="country">{COUNTRY_LABELS[k] || k}</span>
              <span className="rate num">{(r * 100).toFixed(0)} %</span>
            </div>
          ))}
        </div>
      </div>

      <ApiKeySection onConfigChange={onConfigChange} />
      {/* Corpus de démonstration indisponible en prod (voir APP_MODE côté serveur) */}
      {!isProd && <DemoSection demoInfo={demoInfo} onSessionChange={onSessionChange} />}

      <div className="card">
        <div className="card-head"><span className="card-head-label">Plan de comptes (SYSCOHADA)</span></div>
        <table>
          <thead><tr><th>Compte</th><th>Libellé</th></tr></thead>
          <tbody>{accounts.map(([code, lbl]) => <tr key={code}><td>{code}</td><td>{lbl}</td></tr>)}</tbody>
        </table>
      </div>

      <p className="disclaimer">{config.disclaimer}</p>
    </>
  );
}
