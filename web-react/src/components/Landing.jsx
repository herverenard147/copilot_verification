import { Icon } from "../Icons.jsx";

// Copy réelle tirée du README du projet (résultats mesurés, pipeline,
// limites assumées) -- jamais de texte générique. Voir la maquette de
// référence (receiptflow/maquette-entreprise/Landing.dc.html).
function scrollToSection(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

export default function Landing({ onTryFree, onLogin, onRegister, onNav }) {
  return (
    <div>
      <nav className="landing-nav">
        <button className="brand brand-link" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>
          <span className="brand-mark"><Icon name="doc" className="icon" /></span>ReceiptFlow
        </button>
        <div className="landing-nav-links">
          <button className="nav-link" onClick={() => scrollToSection("probleme")}>Le problème</button>
          <button className="nav-link" onClick={() => scrollToSection("comment")}>Comment ça marche</button>
          <button className="nav-link" onClick={() => scrollToSection("resultats")}>Résultats</button>
          <button className="nav-link" onClick={() => scrollToSection("honnetete")}>Honnêteté</button>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn" onClick={onLogin}>Se connecter</button>
          <button className="btn btn--primary" onClick={onTryFree}>Essayer gratuitement</button>
        </div>
      </nav>

      <section className="landing-hero">
        <div>
          <div className="landing-eyebrow">Copilote de reçus &amp; dépenses</div>
          <h1>De la photo d'un reçu à une écriture comptable vérifiée</h1>
          <p className="landing-lead">Photographiez un reçu, ReceiptFlow lit les montants, vérifie leur cohérence et propose une écriture SYSCOHADA, sans jamais prétendre être plus sûr qu'il ne l'est.</p>
          <div className="landing-hero-actions">
            <button className="btn btn--primary btn-sm" style={{ height: 48, padding: "0 26px", fontSize: 15 }} onClick={onTryFree}>Essayer gratuitement</button>
            <button className="btn" style={{ height: 48, padding: "0 26px", fontSize: 15 }}>Voir comment ça marche</button>
          </div>
          <div className="landing-hero-note">Aucune carte requise. Démonstration avec des données d'exemple disponible immédiatement.</div>
        </div>
        <div className="hero-visual">
          <span className="badge badge--donut">Lecture par modèle spécialisé</span>
          <div className="hero-items">
            <div className="hero-item"><span>Atarax 25mg cpr drg bt 30</span><span className="num"><b>2 345</b></span></div>
            <div className="hero-item"><span>Dermosone crème tb 15g</span><span className="num"><b>1 285</b></span></div>
            <div className="hero-item"><span>Paracétamol UPSA 500mg cpr</span><span className="num"><b>2 895</b></span></div>
          </div>
          <div className="hero-total"><span>Total</span><span className="num">8 790</span></div>
          <div className="hero-controls">
            <div className="hero-control"><span className="status-dot ok" style={{ width: 16, height: 16 }}><Icon name="check" className="icon" style={{ width: 10, height: 10 }} /></span>Calcul du total vérifié</div>
            <div className="hero-control"><span className="status-dot ok" style={{ width: 16, height: 16 }}><Icon name="check" className="icon" style={{ width: 10, height: 10 }} /></span>Écriture équilibrée</div>
          </div>
        </div>
      </section>

      <section className="landing-section" id="probleme">
        <div className="landing-eyebrow">Le problème</div>
        <h2 className="landing-h2">Traiter des notes de frais à la main coûte du temps et des erreurs</h2>
        <p className="landing-lead">Saisie ligne par ligne, vérification manuelle des montants, classement comptable approximatif : ce travail répétitif prend des heures chaque mois et laisse passer des incohérences que personne ne relit vraiment. ReceiptFlow automatise cette chaîne, d'une simple photo à une écriture comptable proposée, sans remplacer le jugement d'un comptable, en le déchargeant de la saisie.</p>
      </section>

      <section className="landing-section" id="comment">
        <div className="landing-eyebrow">Comment ça marche</div>
        <h2 className="landing-h2">Un pipeline en 5 étapes, chacune vérifiable</h2>
        <div className="pipeline">
          <div className="pipe-step"><div className="n">1</div><div className="t">Photo</div><div className="d">Un reçu, une facture, photographié ou importé</div></div>
          <div className="pipe-step"><div className="n">2</div><div className="t">Extraction</div><div className="d">Modèle spécialisé, JSON structuré</div></div>
          <div className="pipe-step"><div className="n">3</div><div className="t">Vérification</div><div className="d">4 règles métier, jamais un simple pourcentage</div></div>
          <div className="pipe-step"><div className="n">4</div><div className="t">Comptabilité</div><div className="d">Écriture SYSCOHADA proposée</div></div>
          <div className="pipe-step"><div className="n">5</div><div className="t">Recherche</div><div className="d">Interrogez vos dépenses en langage naturel</div></div>
        </div>
      </section>

      <section className="landing-section" id="resultats">
        <div className="landing-eyebrow">Résultats mesurés</div>
        <h2 className="landing-h2">Des chiffres vérifiés, pas des promesses</h2>
        <p className="landing-lead">Évalué sur 800 reçus réels, pas une démonstration théorique.</p>
        <div className="stat-grid">
          <div className="stat-card"><div className="stat-value">97,87 %</div><div className="stat-label">Exactitude d'extraction sur le corpus de test</div></div>
          <div className="stat-card"><div className="stat-value">100 %</div><div className="stat-label">JSON structuré valide en sortie</div></div>
          <div className="stat-card"><div className="stat-value num">19,5 %</div><div className="stat-label">Anomalies détectées automatiquement sur le corpus de test</div></div>
        </div>
      </section>

      <section className="landing-section" id="honnetete">
        <div className="landing-eyebrow">Ce qui nous différencie</div>
        <h2 className="landing-h2">Honnête sur ce qu'il sait et ce qu'il ne sait pas</h2>
        <p className="landing-lead">La plupart des outils affichent un pourcentage de confiance qui rassure sans rien garantir. ReceiptFlow préfère un signal binaire clair : conforme, à vérifier, ou non vérifiable, jamais alarmiste sur une donnée simplement absente.</p>
        <div className="honesty-grid">
          <div className="honesty-card">
            <div className="chip-demo">
              <div className="chip-demo-row"><span className="chip chip--ok"><Icon name="check" className="icon" style={{ width: 14, height: 14 }} />Conforme</span><span className="chip-desc">Le contrôle passe, chiffres cohérents</span></div>
              <div className="chip-demo-row"><span className="chip chip--bad"><Icon name="warn" className="icon" style={{ width: 14, height: 14 }} />À vérifier</span><span className="chip-desc">Écart détecté, à votre attention</span></div>
              <div className="chip-demo-row"><span className="chip chip--neutral"><Icon name="minus" className="icon" style={{ width: 14, height: 14 }} />Non vérifiable</span><span className="chip-desc">Donnée absente, jamais traité comme une erreur</span></div>
            </div>
          </div>
          <div className="honesty-points">
            <div className="honesty-point"><Icon name="eye" className="icon" /><div><div className="t">Provenance toujours visible</div><div className="d">Chaque montant affiché indique s'il vient d'une lecture directe, d'une estimation, ou d'un exemple de démonstration.</div></div></div>
            <div className="honesty-point"><Icon name="globe" className="icon" /><div><div className="t">Limites géographiques assumées</div><div className="d">Le modèle spécialisé a été entraîné sur un corpus international de reçus : les résultats sur reçus ivoiriens sont encore expérimentaux, et l'application le signale à chaque fois plutôt que de le cacher.</div></div></div>
            <div className="honesty-point"><Icon name="shield" className="icon" /><div><div className="t">Comptabilité indicative, jamais définitive</div><div className="d">Chaque écriture proposée porte le rappel qu'elle doit être validée par un professionnel avant tout usage officiel.</div></div></div>
          </div>
        </div>
      </section>

      <section className="landing-section">
        <div className="cta-band">
          <h2>Essayez avec vos propres reçus</h2>
          <p>Gratuit, sans carte bancaire. Une démonstration avec des données d'exemple est disponible en un clic.</p>
          <div className="btn-row">
            <button className="btn" onClick={onTryFree}>Essayer gratuitement</button>
            <button className="btn ghost" onClick={onTryFree}>Voir la démonstration</button>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <div className="footer-cols">
          <div>
            <div className="footer-brand"><span className="brand-mark"><Icon name="doc" className="icon" style={{ width: 16, height: 16 }} /></span>ReceiptFlow</div>
            <p className="footer-desc">Copilote de reçus et dépenses. Extraction, vérification et comptabilisation, sans jamais inventer une donnée.</p>
          </div>
          <div className="footer-col">
            <div className="footer-col-title">Produit</div>
            <a onClick={() => scrollToSection("comment")} style={{ cursor: "pointer" }}>Comment ça marche</a>
            <a onClick={() => scrollToSection("resultats")} style={{ cursor: "pointer" }}>Résultats</a>
            <a onClick={onTryFree} style={{ cursor: "pointer" }}>Essayer gratuitement</a>
          </div>
          <div className="footer-col">
            <div className="footer-col-title">Compte</div>
            <a onClick={onLogin} style={{ cursor: "pointer" }}>Se connecter</a>
            <a onClick={onRegister} style={{ cursor: "pointer" }}>Créer un compte</a>
          </div>
          <div className="footer-col">
            <div className="footer-col-title">Ressources</div>
            <a onClick={() => onNav("faq")} style={{ cursor: "pointer" }}>FAQ</a>
            <a onClick={() => onNav("contact")} style={{ cursor: "pointer" }}>Contact</a>
          </div>
          <div className="footer-col">
            <div className="footer-col-title">Légal</div>
            <a onClick={() => onNav("confidentialite")} style={{ cursor: "pointer" }}>Confidentialité</a>
            <a onClick={() => onNav("cgu")} style={{ cursor: "pointer" }}>Conditions d'utilisation</a>
          </div>
        </div>
        <div className="footer-bottom">© 2026 ReceiptFlow. L'affectation comptable proposée est indicative et doit être validée par un professionnel.</div>
      </footer>
    </div>
  );
}
