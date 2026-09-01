import { Icon } from "../Icons.jsx";
import { InfoNav } from "./LegalPage.jsx";

// Adresse de contact PLACEHOLDER : à remplacer par la vraie adresse de
// support avant mise en production (voir résumé de session).
const SUPPORT_EMAIL = "support@receiptflow.app";

export default function Contact({ onNav }) {
  return (
    <div className="info-page">
      <InfoNav onNav={onNav} />
      <div className="info-wrap">
        <h1>Contact</h1>
        <div className="info-updated">Une question sur l'application, vos données, ou un bug à signaler ?</div>

        <div className="card contact-card">
          <Icon name="doc" className="icon-lg" />
          <div>
            <div style={{ fontWeight: 600, fontSize: 15 }}>Par email</div>
            <a href={`mailto:${SUPPORT_EMAIL}`} className="body-sm">{SUPPORT_EMAIL}</a>
          </div>
        </div>

        <p style={{ marginTop: 24 }}>Pour une question sur vos données personnelles (export, suppression,
          consentement), vous pouvez aussi tout gérer vous-même directement depuis la page Profil, sans
          attendre de réponse.</p>
        <p>Consultez aussi la <a onClick={() => onNav("faq")} style={{ cursor: "pointer" }}>FAQ</a>, la{" "}
          <a onClick={() => onNav("cgu")} style={{ cursor: "pointer" }}>page des conditions d'utilisation</a>, ou
          {" "}la <a onClick={() => onNav("confidentialite")} style={{ cursor: "pointer" }}>politique de confidentialité</a>.</p>
      </div>
    </div>
  );
}
