import { useEffect, useState } from "react";
import API from "../api.js";
import { toast } from "../toast.jsx";
import { Icon } from "../Icons.jsx";

// Logique portée telle quelle de AccountSection.jsx (AuthForm/ConsentToggle/
// ExportAndDelete) -- seule la présentation change (nouvelle maquette,
// voir ProfilSidebar.dc.html).

function AuthForm({ auth }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null); setBusy(true);
    try {
      if (mode === "login") await auth.login(email, password);
      else await auth.register(email, password);
      toast(mode === "login" ? "Connecté" : "Compte créé");
      setEmail(""); setPassword("");
    } catch (e2) {
      setError(e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-head"><span className="card-head-label">Compte</span></div>
      <div className="card-body">
        <p className="body-sm muted" style={{ margin: 0 }}>Optionnel : un compte permet de consentir à l'apprentissage par correction
          (voir plus bas), d'exporter vos données, et de les supprimer. L'application reste utilisable sans compte.</p>
        <form onSubmit={submit}>
          <div className="field" style={{ marginBottom: "14px" }}>
            <span className="field-label">Email</span>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field" style={{ marginBottom: "14px" }}>
            <span className="field-label">Mot de passe</span>
            <input type="password" required minLength={8} value={password}
              onChange={(e) => setPassword(e.target.value)} placeholder="8 caractères minimum" />
          </div>
          {error && <div className="field-error">{error}</div>}
          <div className="btn-row">
            <button className="btn btn--primary" type="submit" disabled={busy}>
              {mode === "login" ? "Se connecter" : "Créer le compte"}
            </button>
          </div>
        </form>
        <div className="auth-switch">
          {mode === "login" ? (
            <>Pas de compte ? <button onClick={() => setMode("register")}>Créer un compte</button></>
          ) : (
            <>Déjà un compte ? <button onClick={() => setMode("login")}>Se connecter</button></>
          )}
        </div>
      </div>
    </div>
  );
}

function ProfileFields({ auth }) {
  const p = auth.profile || {};
  const [fullName, setFullName] = useState(p.full_name || "");
  const [jobTitle, setJobTitle] = useState(p.job_title || "");
  const [company, setCompany] = useState(p.company || "");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setFullName(p.full_name || ""); setJobTitle(p.job_title || ""); setCompany(p.company || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.full_name, p.job_title, p.company]);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await auth.updateProfile({ full_name: fullName, job_title: jobTitle, company: company });
      toast("Profil mis à jour");
    } catch (e2) {
      toast("Échec : " + e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="field" style={{ marginBottom: "14px" }}>
        <span className="field-label">Nom complet</span>
        <input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="ex. Aïcha Konaté" />
      </div>
      <div className="field" style={{ marginBottom: "14px" }}>
        <span className="field-label">Poste</span>
        <input value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} placeholder="ex. Comptable" />
      </div>
      <div className="field" style={{ marginBottom: "14px" }}>
        <span className="field-label">Entreprise</span>
        <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="ex. Boutique Aïcha" />
      </div>
      <div className="btn-row">
        <button className="btn btn--primary" type="submit" disabled={busy}>Enregistrer</button>
      </div>
    </form>
  );
}

function ConsentToggle() {
  const [granted, setGranted] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    API.getConsent().then((d) => setGranted(d.granted)).catch(() => setGranted(false));
  }, []);

  async function toggle() {
    setBusy(true);
    try {
      const next = !granted;
      await API.setConsent(next);
      setGranted(next);
      toast(next ? "Consentement accordé" : "Consentement retiré");
    } catch (e) {
      toast("Échec : " + e.message);
    } finally {
      setBusy(false);
    }
  }

  if (granted === null) return <p className="muted body-sm">Chargement du consentement…</p>;

  return (
    <div className="toggle-row">
      <div>
        <div className="label">Utiliser mes corrections pour améliorer le modèle</div>
        <div className="desc">Quand vous corrigez un reçu tout juste extrait, la différence entre ce que le modèle a lu
          et votre correction peut servir à l'entraîner (utile notamment pour les reçus ivoiriens/français). Aucune
          image n'est conservée pour cet usage, seulement les valeurs corrigées. Retirable à tout moment.</div>
      </div>
      <label className="switch">
        <input type="checkbox" checked={!!granted} disabled={busy} onChange={toggle} />
        <span className="track"></span>
      </label>
    </div>
  );
}

function ExportAndDelete({ auth }) {
  const [showDelete, setShowDelete] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function exportData() {
    try {
      const data = await API.exportData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "receiptflow_mes_donnees.json";
      a.click();
      toast("Export téléchargé");
    } catch (e) {
      toast("Export impossible : " + e.message);
    }
  }

  async function deleteAccount(e) {
    e.preventDefault();
    setError(null); setBusy(true);
    try {
      await API.deleteAccount(password);
      toast("Compte supprimé");
      await auth.refresh();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="btn-row">
        <button className="btn" onClick={exportData}><Icon name="download" className="icon" style={{ width: 14, height: 14 }} />Exporter mes données</button>
        <button className="btn btn--danger" onClick={() => setShowDelete((v) => !v)}>Supprimer mon compte</button>
      </div>
      {showDelete && (
        <form className="danger-zone" onSubmit={deleteAccount}>
          <p>Cette action est <b>irréversible</b> et supprime votre compte, vos corrections et votre historique de
            consentement. Confirmez avec votre mot de passe.</p>
          <input type="password" placeholder="Mot de passe" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
          {error && <div className="field-error">{error}</div>}
          <div className="btn-row">
            <button className="btn btn--danger" type="submit" disabled={busy}>Confirmer la suppression</button>
          </div>
        </form>
      )}
    </>
  );
}

export default function ProfilTab({ auth }) {
  if (auth.loading) return null;

  return (
    <>
      <h1 className="page-title">Profil</h1>

      {!auth.isAuthenticated ? (
        <AuthForm auth={auth} />
      ) : (
        <div className="card">
          <div className="card-head"><span className="card-head-label">Compte</span></div>
          <div className="card-body">
            <div className="account-row">
              <div className="account-identity">
                <span className="avatar"><Icon name="user" className="icon" /></span>
                <div>
                  <div className="account-email">{auth.profile?.email}</div>
                  <div className="account-status">Connecté</div>
                </div>
              </div>
              <button className="btn" onClick={auth.logout}>Se déconnecter</button>
            </div>
          </div>
        </div>
      )}

      {auth.isAuthenticated && (
        <>
          <div className="card">
            <div className="card-head"><span className="card-head-label">Informations</span></div>
            <div className="card-body"><ProfileFields auth={auth} /></div>
          </div>

          <div className="card">
            <div className="card-head"><span className="card-head-label">Confidentialité</span></div>
            <div className="card-body"><ConsentToggle /></div>
          </div>

          <div className="card">
            <div className="card-head"><span className="card-head-label">Vos données</span></div>
            <div className="card-body"><ExportAndDelete auth={auth} /></div>
          </div>
        </>
      )}
    </>
  );
}
