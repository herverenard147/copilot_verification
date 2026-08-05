import { useState } from "react";

// Porte d'entrée obligatoire : personne n'accède à l'app sans être connecté.
// Réutilise le même src/auth.py côté serveur que la section Compte des
// Réglages (login/register/logout), juste présenté en page pleine plutôt
// qu'en carte dans un panneau.
export default function AuthGate({ auth }) {
  const [mode, setMode] = useState("login"); // login | register
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await auth.login(email, password);
      else await auth.register(email, password);
    } catch (e2) {
      setError(e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--background)" }}>
      <div className="card auth-form">
        <div className="section-body">
          <div className="brand" style={{ justifyContent: "center", marginBottom: "var(--md)" }}>
            🧾 <span>ReceiptFlow</span>
          </div>
          <p className="muted body-sm" style={{ textAlign: "center", marginBottom: "var(--lg)" }}>
            {mode === "login" ? "Connectez-vous pour accéder à vos dépenses." : "Créez un compte pour commencer."}
          </p>
          <form onSubmit={submit}>
            <div style={{ marginBottom: "var(--sm)" }}>
              <label className="field" htmlFor="gate-email">Email</label>
              <input id="gate-email" type="email" required autoFocus value={email}
                     onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div style={{ marginBottom: "var(--sm)" }}>
              <label className="field" htmlFor="gate-password">Mot de passe</label>
              <input id="gate-password" type="password" required minLength={8} value={password}
                     onChange={(e) => setPassword(e.target.value)} placeholder="8 caractères minimum" />
            </div>
            {error && <div className="field-error">{error}</div>}
            <div className="btn-row" style={{ marginTop: "var(--md)" }}>
              <button className="btn btn--primary" type="submit" disabled={busy} style={{ width: "100%" }}>
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
    </div>
  );
}
