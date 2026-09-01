import { useState } from "react";
import { Icon } from "../Icons.jsx";
import { InfoNav } from "./LegalPage.jsx";

const QUESTIONS = [
  {
    q: "Comment fonctionne l'extraction ?",
    a: "Un modèle spécialisé lit la photo et en extrait les articles, montants et taxes en JSON structuré. Quand ce modèle échoue, ou pour un reçu ivoirien, un modèle vision généraliste prend le relais (« lecture par IA de secours »), toujours indiqué à l'écran.",
  },
  {
    q: "L'application fonctionne-t-elle pour des reçus ivoiriens ?",
    a: "Oui, mais en mode expérimental : le modèle principal n'a jamais vu de reçus ivoiriens à l'entraînement. Les règles comptables SYSCOHADA, elles, s'appliquent pleinement quels que soient les montants extraits. Un bandeau le rappelle sur chaque analyse en Côte d'Ivoire.",
  },
  {
    q: "Que faire si l'application se trompe sur un montant ?",
    a: "Chaque champ (articles, sous-total, taxe, total) reste modifiable directement dans l'écran Analyser : les contrôles et l'écriture comptable se recalculent automatiquement dès que vous corrigez une valeur.",
  },
  {
    q: "Mes données sont-elles utilisées pour entraîner le modèle ?",
    a: "Uniquement si vous y consentez (Profil > Confidentialité), et seulement la différence entre la lecture automatique et votre correction, jamais l'image. Ce consentement est activé par défaut à la création d'un compte, avec un message explicite et la possibilité de le désactiver immédiatement.",
  },
  {
    q: "Puis-je utiliser ReceiptFlow sans créer de compte ?",
    a: "Oui : une session anonyme suffit pour analyser des reçus, dans la limite d'une utilisation raisonnable au-delà de laquelle un compte devient nécessaire. Créer un compte ajoute l'export de vos données, leur suppression, et le consentement à l'amélioration du modèle.",
  },
  {
    q: "Puis-je importer une facture au format PDF ?",
    a: "Oui : le dépôt accepte les images (JPG, PNG) et les PDF de facture, dont la première page est convertie automatiquement en image avant analyse.",
  },
  {
    q: "Est-ce un logiciel de comptabilité certifié ?",
    a: "Non. ReceiptFlow est un outil d'aide à la saisie : chaque écriture proposée est indicative et doit être validée par un professionnel (expert-comptable) avant tout usage officiel.",
  },
  {
    q: "Comment supprimer mon compte et mes données ?",
    a: "Depuis Profil > Vos données, le bouton « Supprimer mon compte » efface immédiatement votre compte, vos reçus, vos corrections et votre historique de consentement, sans délai.",
  },
];

export default function FAQ({ onNav }) {
  const [open, setOpen] = useState(0);
  return (
    <div className="info-page">
      <InfoNav onNav={onNav} />
      <div className="info-wrap">
        <h1>Questions fréquentes</h1>
        <div className="info-updated">Tout ce qu'il faut savoir avant de déposer votre premier reçu.</div>
        {QUESTIONS.map((item, i) => (
          <div key={i} className={`faq-item${open === i ? " open" : ""}`}>
            <div className="faq-q" onClick={() => setOpen(open === i ? -1 : i)}>
              {item.q}
              <Icon name="chevron" className="icon" style={{ width: 16, height: 16 }} />
            </div>
            <div className="faq-a">{item.a}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
