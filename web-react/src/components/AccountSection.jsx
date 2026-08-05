import { useEffect, useState } from "react";
import API from "../api.js";
import { toast } from "../toast.jsx";

function AuthForm({ auth }) {
  const [mode, setMode] = useState("login"); // login | register
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
      toast(mode === "login" ? "✅ Connecté" : "✅ Compte créé");
      setEmail(""); setPassword("");
    } catch (e2) {
      setError(e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card"><div className="section-head"><span className="label-caps">Compte</span></div>
      <div className="section-body">
        <p className="body-sm muted">Optionnel : un compte permet de consentir à l'apprentissage par correction
          (voir plus bas), d'exporter vos données, et de les supprimer. L'app reste utilisable sans compte.</p>
        <form className="auth-form" style={{ margin: 0 }} onSubmit={submit}>
          <div style={{ marginBottom: "var(--sm)" }}>
            <label className="field" htmlFor="auth-email">Email</label>
            <input id="auth-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div style={{ marginBottom: "var(--sm)" }}>
            <label className="field" htmlFor="auth-password">Mot de passe</label>
            <input id="auth-password" type="password" required minLength={8} value={password}
                   onChange={(e) => setPassword(e.target.value)} placeholder="8 caractères minimum" />
          </div>
          {error && <div className="field-error">{error}</div>}
          <div className="btn-row" style={{ marginTop: "var(--sm)" }}>
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
      toast(next ? "✅ Consentement accordé" : "Consentement retiré");
    } catch (e) {
      toast("Échec : " + e.message);
    } finally {
      setBusy(false);
    }
  }

  if (granted === null) return <p className="muted body-sm">Chargement du consentement…</p>;

  return (
    <div className="account-row">
      <div>
        <div className="body-sm"><b>Utiliser mes corrections pour améliorer le modèle</b></div>
        <p className="muted body-sm" style={{ margin: "2px 0 0" }}>
          Quand vous corrigez un reçu tout juste extrait, la différence entre ce que le modèle a lu et votre
          correction peut servir à l'entraîner (utile notamment pour les reçus ivoiriens/français). Aucune image
          n'est conservée pour cet usage, seulement les valeurs corrigées. Vous pouvez retirer ce consentement à
          tout moment.
        </p>
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
      toast("📥 Export téléchargé");
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
        <button className="btn" onClick={exportData}>📥 Exporter mes données</button>
        <button className="btn btn--danger" onClick={() => setShowDelete((v) => !v)}>Supprimer mon compte</button>
      </div>
      {showDelete && (
        <form className="danger-zone" style={{ marginTop: "var(--sm)" }} onSubmit={deleteAccount}>
          <p className="body-sm">Cette action est <b>irréversible</b> et supprime votre compte, vos corrections et
            votre historique de consentement. Confirmez avec votre mot de passe.</p>
          <input type="password" placeholder="Mot de passe" value={password}
                 onChange={(e) => setPassword(e.target.value)} required />
          {error && <div className="field-error">{error}</div>}
          <div className="btn-row" style={{ marginTop: "var(--sm)" }}>
            <button className="btn btn--danger" type="submit" disabled={busy}>Confirmer la suppression</button>
          </div>
        </form>
      )}
    </>
  );
}

export function AccountSection({ auth }) {
  if (auth.loading) return null;
  if (!auth.isAuthenticated) return <AuthForm auth={auth} />;

  return (
    <div className="card"><div className="section-head"><span className="label-caps">Compte</span></div>
      <div className="section-body stack">
        <div className="account-row">
          <span className="body-sm">Connecté</span>
          <button className="btn" onClick={auth.logout}>Se déconnecter</button>
        </div>
        <ConsentToggle />
        <ExportAndDelete auth={auth} />
      </div>
    </div>
  );
}
