import { useEffect, useState } from "react";
import API from "./api.js";
import { useAuth } from "./useAuth.js";
import { toast, Toast } from "./toast.jsx";
import { Icon, IconSprite } from "./Icons.jsx";
import Landing from "./components/Landing.jsx";
import Connexion from "./components/Connexion.jsx";
import { CGU, Confidentialite } from "./components/LegalPage.jsx";
import FAQ from "./components/FAQ.jsx";
import Contact from "./components/Contact.jsx";
import ConsentNotice from "./components/ConsentNotice.jsx";
import AnalyzeTab from "./components/AnalyzeTab.jsx";
import DashboardTab from "./components/DashboardTab.jsx";
import AccountingTab from "./components/AccountingTab.jsx";
import BilanTab from "./components/BilanTab.jsx";
import AskTab from "./components/AskTab.jsx";
import ProfilTab from "./components/ProfilTab.jsx";
import ParametresTab from "./components/ParametresTab.jsx";

// app_mode vient du backend (/api/config, voir api.py APP_MODE) : une seule
// instance = un seul mode, jamais un choix côté front. "demo" par défaut
// tant que la config n'a pas encore chargé -- comportement le moins risqué
// (accès libre, comme avant l'ajout du mode prod).
const FALLBACK_CONFIG = {
  countries: { CI: 0.18, ID: 0.11 }, payment_modes: ["cash", "bank", "credit"],
  chart_of_accounts: {}, groq_configured: false, disclaimer: "", app_mode: "demo",
};
const COUNTRY_LABELS = { CI: "Côte d'Ivoire (TVA 18%)", ID: "Indonésie (TVA 11%)" };
const PAYMENT_LABELS = { cash: "Espèces (caisse)", bank: "Virement bancaire", credit: "À crédit (fournisseur)" };
const NAV_TABS = [
  { id: "analyze", label: "Analyser", icon: "scan" },
  { id: "dashboard", label: "Tableau de bord", icon: "grid" },
  { id: "accounting", label: "Comptabilité", icon: "ledger" },
  { id: "bilan", label: "Bilan", icon: "scale" },
  { id: "ask", label: "Questions", icon: "search" },
];
const FOOT_TABS = [
  { id: "profil", label: "Profil", icon: "user" },
  { id: "parametres", label: "Paramètres", icon: "gear" },
];

export default function App() {
  const auth = useAuth();
  const [config, setConfig] = useState(null);
  // "landing" | "login" | "register" | "app" -- landing/auth précèdent
  // l'app tant que la session n'est pas authentifiée (mode prod) ou tant
  // que l'utilisateur n'a pas choisi d'entrer (mode démo).
  const [view, setView] = useState("landing");
  const [activeTab, setActiveTab] = useState("analyze");
  const [country, setCountry] = useState("CI");
  const [payment, setPayment] = useState("cash");
  const [docType, setDocType] = useState("ticket");
  const [sessionInfo, setSessionInfo] = useState({ demoMode: false, sessionEmpty: true, nReceipts: 0 });
  const [pendingEdit, setPendingEdit] = useState(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [showConsentNotice, setShowConsentNotice] = useState(false);

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

  // Une session déjà authentifiée saute la landing/connexion à l'ouverture
  // et après un login/register réussi depuis la page Connexion.
  useEffect(() => {
    if (auth.isAuthenticated) setView("app");
  }, [auth.isAuthenticated]);

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
    // Un compte déjà connecté retrouve simplement son (vrai) espace vide.
    // Une session anonyme, elle, n'a plus rien à montrer une fois le corpus
    // de démo retiré : on la ramène vers la connexion plutôt que de laisser
    // l'app apparaître soudainement vide.
    if (!auth.isAuthenticated) setView("login");
  }

  const cfg = config || FALLBACK_CONFIG;
  const isProd = cfg.app_mode === "prod";

  // Tant que la config ou la vérification d'auth n'ont pas répondu, écran
  // vide plutôt que de risquer un flash (landing, puis app, puis retour).
  if (auth.loading || config === null) {
    return <div style={{ minHeight: "100vh" }} />;
  }

  if (view === "landing") {
    return (
      <>
        <IconSprite />
        <Landing
          onTryFree={() => setView(isProd ? "register" : "app")}
          onLogin={() => setView("login")}
          onRegister={() => setView("register")}
          onNav={setView}
        />
        <Toast />
      </>
    );
  }

  if (view === "login" || view === "register") {
    return (
      <>
        <IconSprite />
        <Connexion auth={auth} initialMode={view === "login" ? "login" : "register"}
          onBack={() => setView("landing")} onRegistered={() => setShowConsentNotice(true)} />
        <Toast />
      </>
    );
  }

  if (view === "cgu" || view === "confidentialite" || view === "faq" || view === "contact") {
    return (
      <>
        <IconSprite />
        {view === "cgu" && <CGU onNav={setView} />}
        {view === "confidentialite" && <Confidentialite onNav={setView} />}
        {view === "faq" && <FAQ onNav={setView} />}
        {view === "contact" && <Contact onNav={setView} />}
        <Toast />
      </>
    );
  }

  return (
    <>
      <IconSprite />
      <div className="layout">
        <aside className="sidebar">
          <button className="brand brand-link" onClick={() => setActiveTab(NAV_TABS[0].id)} title="Accueil">
            <span className="brand-mark"><Icon name="doc" className="icon" /></span>ReceiptFlow
          </button>
          <nav className="nav-list">
            {NAV_TABS.map((t) => (
              <button key={t.id} className={`nav-item${activeTab === t.id ? " active" : ""}`} onClick={() => setActiveTab(t.id)}>
                <Icon name={t.icon} />{t.label}
              </button>
            ))}
          </nav>
          <div className="sidebar-foot">
            {FOOT_TABS.map((t) => (
              <button key={t.id} className={`nav-item${activeTab === t.id ? " active" : ""}`} onClick={() => setActiveTab(t.id)}>
                <Icon name={t.icon} />{t.label}
              </button>
            ))}
          </div>
        </aside>

        <div className="content">
          {sessionInfo.demoMode && (
            <div className="demo-banner">
              <b>Mode démonstration</b> : données d'exemple, pas vos dépenses réelles.
              <button className="btn btn--ghost" onClick={handleExitDemo}>Quitter le mode démo</button>
            </div>
          )}

          <section className={activeTab === "analyze" ? "page" : "hidden"}>
            <div className="page-head"><h1 className="page-title">Analyser un reçu</h1></div>
            <div className="row">
              <div className="field">
                <span className="field-label">Type de document</span>
                <select value={docType} onChange={(e) => setDocType(e.target.value)}>
                  <option value="ticket">Ticket de caisse</option>
                  <option value="facture">Facture</option>
                </select>
              </div>
              <div className="field">
                <span className="field-label">Pays</span>
                <select value={country} onChange={(e) => setCountry(e.target.value)}>
                  {Object.keys(cfg.countries).map((k) => <option key={k} value={k}>{COUNTRY_LABELS[k] || k}</option>)}
                </select>
              </div>
              <div className="field">
                <span className="field-label">Mode de paiement</span>
                <select value={payment} onChange={(e) => setPayment(e.target.value)}>
                  {cfg.payment_modes.map((k) => <option key={k} value={k}>{PAYMENT_LABELS[k] || k}</option>)}
                </select>
              </div>
            </div>
            <AnalyzeTab country={country} payment={payment} docType={docType} config={cfg}
              pendingEdit={pendingEdit} onConsumeEdit={() => setPendingEdit(null)}
              onSaved={handleAnalyzeSaved} onRequireAccount={() => setActiveTab("profil")} />
          </section>

          <section className={activeTab === "dashboard" ? "page" : "hidden"}>
            <DashboardTab active={activeTab === "dashboard"} refreshToken={refreshToken} country={country}
              demoMode={sessionInfo.demoMode} onSessionChange={handleSessionChange}
              onEditReceipt={handleEditReceipt} onGoAnalyze={() => setActiveTab("analyze")} />
          </section>

          <section className={activeTab === "accounting" ? "page" : "hidden"}>
            <AccountingTab active={activeTab === "accounting"} refreshToken={refreshToken}
              country={country} payment={payment} demoMode={sessionInfo.demoMode}
              onSessionChange={handleSessionChange} onEditReceipt={handleEditReceipt}
              onGoAnalyze={() => setActiveTab("analyze")} />
          </section>

          <section className={activeTab === "bilan" ? "page" : "hidden"}>
            <BilanTab active={activeTab === "bilan"} refreshToken={refreshToken}
              country={country} payment={payment} isAuthenticated={auth.isAuthenticated} />
          </section>

          <section className={activeTab === "ask" ? "page" : "hidden"}>
            <AskTab country={country} demoMode={sessionInfo.demoMode} sessionEmpty={sessionInfo.sessionEmpty}
              groqConfigured={!!cfg.groq_configured} onEditReceipt={handleEditReceipt} />
          </section>

          <section className={activeTab === "profil" ? "page page-narrow" : "hidden"}>
            <ProfilTab auth={auth} />
          </section>

          <section className={activeTab === "parametres" ? "page" : "hidden"}>
            <ParametresTab config={config} onConfigChange={handleConfigChange}
              demoInfo={sessionInfo} onSessionChange={handleSessionChange} isProd={isProd} />
          </section>
        </div>
      </div>

      <ConsentNotice open={showConsentNotice} onClose={() => setShowConsentNotice(false)} />
      <Toast />
    </>
  );
}
