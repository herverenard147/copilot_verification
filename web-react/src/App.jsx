import { useEffect, useState } from "react";
import API from "./api.js";
import { useAuth } from "./useAuth.js";
import { toast, Toast } from "./toast.jsx";
import AnalyzeTab from "./components/AnalyzeTab.jsx";
import DashboardTab from "./components/DashboardTab.jsx";
import AccountingTab from "./components/AccountingTab.jsx";
import AskTab from "./components/AskTab.jsx";
import TechnicalTab from "./components/TechnicalTab.jsx";
import SettingsPanel from "./components/SettingsPanel.jsx";
import AuthGate from "./components/AuthGate.jsx";

// app_mode vient du backend (/api/config, voir api.py APP_MODE) : une seule
// instance = un seul mode, jamais un choix côté front. "demo" par défaut
// tant que la config n'a pas encore chargé -- comportement le moins risqué
// (accès libre, comme avant l'ajout du mode prod).
const FALLBACK_CONFIG = {
  countries: { CI: 0.18, ID: 0.11 }, payment_modes: ["cash", "bank", "credit"],
  chart_of_accounts: {}, groq_configured: false, disclaimer: "", app_mode: "demo",
};
const COUNTRY_LABELS = { CI: "Côte d'Ivoire — TVA 18%", ID: "Indonésie — TVA 11%" };
const PAYMENT_LABELS = { cash: "Espèces (caisse)", bank: "Virement bancaire", credit: "À crédit (fournisseur)" };
const BASE_TABS = [
  { id: "analyze", label: "Analyser" },
  { id: "dashboard", label: "Tableau de bord" },
  { id: "accounting", label: "Comptabilité" },
  { id: "ask", label: "Questions" },
];
// Onglet Technique (comparatif Donut/baseline, courbe de perte) : utile pour
// une démonstration/soutenance, pas pour un utilisateur du produit -- visible
// seulement en mode demo.
const TABS_WITH_TECHNICAL = [...BASE_TABS, { id: "technical", label: "Technique" }];

export default function App() {
  const auth = useAuth();
  const [config, setConfig] = useState(null);
  const [activeTab, setActiveTab] = useState("analyze");
  const [country, setCountry] = useState("CI");
  const [payment, setPayment] = useState("cash");
  const [docType, setDocType] = useState("ticket");
  const [sessionInfo, setSessionInfo] = useState({ demoMode: false, sessionEmpty: true, nReceipts: 0 });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pendingEdit, setPendingEdit] = useState(null);
  const [refreshToken, setRefreshToken] = useState(0);

  async function refreshSessionInfo() {
    try {
      const s = await API.session();
      setSessionInfo({ demoMode: !!s.demo_mode, sessionEmpty: !!s.empty, nReceipts: s.n_receipts || 0 });
    } catch (e) {
      setSessionInfo({ demoMode: false, sessionEmpty: true, nReceipts: 0 });
    }
  }

  useEffect(() => {
    API.config().then(setConfig).catch(() => setConfig(FALLBACK_CONFIG));
    refreshSessionInfo();
  }, []);

  function handleSessionChange(partial) {
    setSessionInfo((s) => ({ ...s, ...partial }));
  }
  function handleConfigChange(partial) {
    setConfig((c) => ({ ...c, ...partial }));
  }

  async function handleEditReceipt(id) {
    try {
      const data = await API.receipt(id, country);
      setPendingEdit({ id, data });
      setActiveTab("analyze");
    } catch (e) {
      toast("Ouverture impossible : " + e.message);
    }
  }

  async function handleAnalyzeSaved(wasEdit) {
    await refreshSessionInfo();
    if (wasEdit) setActiveTab("dashboard");
  }

  async function handleExitDemo() {
    try { await API.setDemo(false); } catch (e) { /* ignore */ }
    await refreshSessionInfo();
    setRefreshToken((t) => t + 1);
    toast("Mode démonstration désactivé");
  }

  const cfg = config || FALLBACK_CONFIG;
  const isProd = cfg.app_mode === "prod";
  const tabs = isProd ? BASE_TABS : TABS_WITH_TECHNICAL;

  // Connexion obligatoire seulement en mode prod. Tant que la config ou la
  // vérification d'auth n'ont pas répondu, on affiche un écran vide plutôt
  // que de risquer un flash (page de connexion, puis app, puis retour) --
  // le mode par défaut (demo) n'exige rien, donc rien à décider tant qu'on
  // ne sait pas encore dans quel mode on tourne.
  if (auth.loading || config === null) {
    return <div style={{ minHeight: "100vh" }} />;
  }
  if (isProd && !auth.isAuthenticated) {
    return <AuthGate auth={auth} />;
  }

  return (
    <>
      <header className="app-header">
        <div className="brand">🧾 <span>ReceiptFlow</span></div>
        <nav className="nav">
          {tabs.map((t) => (
            <button key={t.id} className={activeTab === t.id ? "active" : ""} onClick={() => setActiveTab(t.id)}>
              {t.label}
            </button>
          ))}
        </nav>
        <div className="header-actions">
          <button className="btn" title="Réglages" onClick={() => setSettingsOpen(true)}>⚙️ Réglages</button>
        </div>
      </header>

      {sessionInfo.demoMode && (
        <div className="demo-banner">
          🔬 <b>Mode démonstration</b> — données du corpus CORD, pas vos dépenses réelles.
          <button className="btn btn--ghost" onClick={handleExitDemo}>Quitter le mode démo</button>
        </div>
      )}

      <main className="container">
        <section className={activeTab === "analyze" ? "" : "hidden"}>
          <div className="row" style={{ marginBottom: "var(--lg)" }}>
            <div>
              <label className="field" htmlFor="sel-doctype">Type de document</label>
              <select id="sel-doctype" value={docType} onChange={(e) => setDocType(e.target.value)}>
                <option value="ticket">Ticket de caisse</option>
                <option value="facture">Facture</option>
              </select>
            </div>
            <div>
              <label className="field" htmlFor="sel-country">Pays</label>
              <select id="sel-country" value={country} onChange={(e) => setCountry(e.target.value)}>
                {Object.keys(cfg.countries).map((k) => <option key={k} value={k}>{COUNTRY_LABELS[k] || k}</option>)}
              </select>
            </div>
            <div>
              <label className="field" htmlFor="sel-payment">Mode de paiement</label>
              <select id="sel-payment" value={payment} onChange={(e) => setPayment(e.target.value)}>
                {cfg.payment_modes.map((k) => <option key={k} value={k}>{PAYMENT_LABELS[k] || k}</option>)}
              </select>
            </div>
          </div>
          <AnalyzeTab country={country} payment={payment} docType={docType} config={cfg}
            pendingEdit={pendingEdit} onConsumeEdit={() => setPendingEdit(null)}
            onSaved={handleAnalyzeSaved} />
        </section>

        <section className={activeTab === "dashboard" ? "" : "hidden"}>
          <DashboardTab active={activeTab === "dashboard"} refreshToken={refreshToken} country={country}
            demoMode={sessionInfo.demoMode} onSessionChange={handleSessionChange}
            onEditReceipt={handleEditReceipt} onGoAnalyze={() => setActiveTab("analyze")} />
        </section>

        <section className={activeTab === "accounting" ? "" : "hidden"}>
          <AccountingTab active={activeTab === "accounting"} refreshToken={refreshToken}
            country={country} payment={payment} demoMode={sessionInfo.demoMode}
            onSessionChange={handleSessionChange} onEditReceipt={handleEditReceipt}
            onGoAnalyze={() => setActiveTab("analyze")} />
        </section>

        <section className={activeTab === "ask" ? "" : "hidden"}>
          <AskTab country={country} demoMode={sessionInfo.demoMode} sessionEmpty={sessionInfo.sessionEmpty}
            groqConfigured={!!cfg.groq_configured} onEditReceipt={handleEditReceipt} />
        </section>

        {!isProd && (
          <section className={activeTab === "technical" ? "" : "hidden"}>
            <TechnicalTab />
          </section>
        )}
      </main>

      <div className={`overlay${settingsOpen ? " open" : ""}`} onClick={() => setSettingsOpen(false)}></div>
      <aside className={`panel${settingsOpen ? " open" : ""}`}>
        <div className="panel-head">
          <h3 className="headline-sm" style={{ margin: 0 }}>⚙️ Réglages</h3>
          <button className="btn" onClick={() => setSettingsOpen(false)}>Fermer</button>
        </div>
        <div className="section-body stack">
          <SettingsPanel config={config} onConfigChange={handleConfigChange}
            demoInfo={sessionInfo} onSessionChange={handleSessionChange} auth={auth} isProd={isProd} />
        </div>
      </aside>

      <Toast />
    </>
  );
}
