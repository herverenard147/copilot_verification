import { Icon } from "../Icons.jsx";

export function InfoNav({ onNav }) {
  return (
    <nav className="info-nav">
      <button className="brand brand-link" onClick={() => onNav("landing")}>
        <span className="brand-mark"><Icon name="doc" className="icon" /></span>ReceiptFlow
      </button>
      <button className="btn btn-sm" onClick={() => onNav("landing")}><Icon name="arrow-left" className="icon" style={{ width: 14, height: 14 }} />Retour à l'accueil</button>
    </nav>
  );
}

export function CGU({ onNav }) {
  return (
    <div className="info-page">
      <InfoNav onNav={onNav} />
      <div className="info-wrap">
        <h1>Conditions générales d'utilisation</h1>
        <div className="info-updated">Dernière mise à jour : 1er septembre 2026</div>

        <h2>1. Ce qu'est ReceiptFlow</h2>
        <p>ReceiptFlow est un copilote de reçus et de dépenses : il lit la photo d'un reçu ou d'une facture,
          vérifie la cohérence des montants et propose une écriture comptable (norme SYSCOHADA). C'est un
          <strong> outil d'aide à la saisie</strong>, pas un logiciel de comptabilité certifié. Chaque écriture
          proposée doit être validée par un professionnel (expert-comptable) avant tout usage officiel.</p>

        <h2>2. Compte et session anonyme</h2>
        <p>L'application reste utilisable sans compte : une session anonyme est créée automatiquement
          (cookie technique), et purgée après <strong>24 heures d'inactivité</strong>. Elle est soumise à une
          limite d'utilisation (nombre de reçus analysables) au-delà de laquelle la création d'un compte est
          nécessaire pour continuer. Créer un compte (email et mot de passe) est optionnel et permet en plus
          d'exporter vos données, de les supprimer, et de consentir à l'amélioration du modèle par vos
          corrections.</p>

        <h2>3. Fiabilité de l'extraction</h2>
        <p>L'extraction automatique peut se tromper, en particulier hors du domaine sur lequel le modèle
          principal a été entraîné. L'application le signale explicitement (mode
          expérimental, contrôles à trois états) plutôt que de masquer l'incertitude. Vous restez responsable
          de vérifier les montants avant toute utilisation comptable ou fiscale.</p>

        <h2>4. Mode démonstration</h2>
        <p>Le mode démonstration peuple l'application avec un jeu de données d'exemple public (environ 800
          reçus), clairement signalé par un bandeau permanent. Ce ne sont jamais vos données réelles.</p>

        <h2>5. Utilisation interdite</h2>
        <ul>
          <li>Déposer des documents illégaux, frauduleux, ou appartenant à un tiers sans autorisation.</li>
          <li>Tenter de contourner les limites techniques (débit, quotas) ou de perturber le service.</li>
          <li>Utiliser l'application pour produire de fausses écritures comptables destinées à tromper un tiers.</li>
        </ul>

        <h2>6. Limitation de responsabilité</h2>
        <p>ReceiptFlow est fourni « en l'état ». L'éditeur ne garantit pas l'exactitude des montants extraits
          ni des écritures proposées, et ne peut être tenu responsable des conséquences d'une utilisation des
          résultats sans vérification humaine.</p>

        <h2>7. Modification des présentes conditions</h2>
        <p>Ces conditions peuvent évoluer avec le service. La date de dernière mise à jour ci-dessus reflète
          la version en vigueur.</p>

        <h2>8. Contact</h2>
        <p>Des questions sur ces conditions ? Voir la page <a onClick={() => onNav("contact")} style={{ cursor: "pointer" }}>Contact</a>.</p>
      </div>
    </div>
  );
}

export function Confidentialite({ onNav }) {
  return (
    <div className="info-page">
      <InfoNav onNav={onNav} />
      <div className="info-wrap">
        <h1>Politique de confidentialité</h1>
        <div className="info-updated">Dernière mise à jour : 1er septembre 2026</div>

        <h2>1. Quelles données sont collectées</h2>
        <ul>
          <li><strong>Session anonyme</strong> : un identifiant technique (cookie), aucune donnée personnelle.</li>
          <li><strong>Compte (optionnel)</strong> : votre email et un mot de passe (chiffré avec Argon2, jamais
            stocké ni journalisé en clair), et si vous les renseignez, votre nom, poste et entreprise (page Profil).</li>
          <li><strong>Reçus</strong> : la photo que vous déposez, les montants extraits, et une miniature de
            l'image conservée pour l'affichage du détail.</li>
          <li><strong>Corrections</strong> : si vous y consentez, la différence entre ce que le modèle a lu et
            votre correction, pour améliorer l'extraction (jamais l'image elle-même dans ce cas).</li>
        </ul>

        <h2>2. Partage avec des tiers</h2>
        <p>Aucune donnée n'est vendue. Un seul partage technique existe : quand le modèle principal (qui
          tourne localement) ne parvient pas à lire un reçu, ou pour rédiger une réponse dans l'onglet
          Questions, l'image ou la question peut être envoyée à <strong>Groq</strong> (fournisseur
          d'inférence IA tiers) pour cet appel précis. C'est signalé dans l'interface (badge « Lecture par IA
          de secours »), jamais fait silencieusement.</p>

        <h2>3. Durée de conservation</h2>
        <p>Une session anonyme et ses reçus sont supprimés après 24 heures d'inactivité. Les données d'un
          compte sont conservées tant qu'il existe, et supprimées immédiatement (avec vos reçus, corrections
          et historique de consentement) si vous supprimez votre compte.</p>

        <h2>4. Vos droits</h2>
        <p>Depuis la page Profil, vous pouvez à tout moment :</p>
        <ul>
          <li><strong>Exporter</strong> l'intégralité de vos données dans un fichier JSON.</li>
          <li><strong>Supprimer</strong> votre compte et toutes les données associées, sans délai.</li>
          <li><strong>Retirer votre consentement</strong> à l'utilisation de vos corrections pour l'entraînement, à tout moment.</li>
        </ul>

        <h2>5. Amélioration du modèle par vos corrections</h2>
        <p>Ce consentement est activé par défaut à la création d'un compte (vous en êtes informé
          immédiatement après l'inscription, avec la possibilité de le désactiver aussitôt) : il aide à
          améliorer la lecture des reçus ivoiriens et français, hors du domaine d'origine du modèle. Vous
          pouvez le désactiver à tout moment depuis Profil, sans affecter le reste de votre compte.</p>

        <h2>6. Cookies</h2>
        <p>Seuls des cookies techniques sont utilisés (identifiant de session, jeton de connexion) : aucun
          cookie publicitaire ou de suivi tiers.</p>

        <h2>7. Contact</h2>
        <p>Pour toute question sur vos données, voir la page <a onClick={() => onNav("contact")} style={{ cursor: "pointer" }}>Contact</a>.</p>
      </div>
    </div>
  );
}
