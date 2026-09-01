import { useState } from "react";
import { Icon } from "../Icons.jsx";

// Une seule page pour connexion et inscription (bascule par mode) : même
// mécanisme réel du produit (email + mot de passe, src/auth.py côté
// serveur), pas de téléphone/OTP -- ce n'est pas ce que fait ReceiptFlow.
export default function Connexion({ auth, initialMode, onBack, onRegistered }) {
  const [mode, setMode] = useState(initialMode === "register" ? "register" : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") {
        await auth.login(email, password);
      } else {
        await auth.register(email, password);
        // Consentement "amelioration du modele" accorde par defaut a
        // l'inscription (src/auth.py:register_user) : on doit le dire
        // immediatement, avec un moyen de le retirer -- voir App.jsx.
        if (onRegistered) onRegistered();
      }
      // La transition vers l'app se fait dans App.jsx (effet sur
      // auth.isAuthenticated), pas ici -- une seule source de vérité.
    } catch (e2) {
      setError(e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-wrap">
        <button className="brand brand-link" style={{ marginBottom: "32px" }} onClick={onBack}>
          <span className="brand-mark"><Icon name="doc" className="icon" style={{ width: 18, height: 18 }} /></span>ReceiptFlow
        </button>

        <div className="auth-card">
          <div className="auth-card-title">{mode === "login" ? "Se connecter" : "Créer un compte"}</div>
          <div className="auth-card-sub">
            {mode === "login"
              ? "L'application reste utilisable sans compte : un compte permet d'exporter vos données et de consentir à l'amélioration du modèle."
              : "Optionnel : permet de consentir à l'amélioration du modèle par vos corrections, d'exporter vos données, et de les supprimer à tout moment."}
          </div>

          <form onSubmit={submit}>
            <div className="field" style={{ marginTop: "20px" }}>
              <span className="field-label">Email</span>
              <input type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field" style={{ marginTop: "20px" }}>
              <span className="field-label">Mot de passe</span>
              <input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)}
                     placeholder="8 caractères minimum" />
            </div>
            {error && <div className="field-error">{error}</div>}
            <button className="btn btn--primary" type="submit" disabled={busy} style={{ width: "100%", justifyContent: "center", marginTop: "24px" }}>
              {mode === "login" ? "Se connecter" : "Créer le compte"}
            </button>
          </form>

          <div className="auth-switch">
            {mode === "login" ? (
              <>Pas de compte ? <button onClick={() => setMode("register")}>Créer un compte</button></>
            ) : (
              <>Déjà un compte ? <button onClick={() => setMode("login")}>Se connecter</button></>
            )}
          </div>
        </div>

        <button className="auth-back" onClick={onBack}><Icon name="arrow-left" className="icon" style={{ width: 15, height: 15 }} />Retour à l'accueil</button>
      </div>
    </div>
  );
}
