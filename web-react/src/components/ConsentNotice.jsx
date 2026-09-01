import { useState } from "react";
import API from "../api.js";
import { toast } from "../toast.jsx";
import { Icon } from "../Icons.jsx";
import { Modal } from "./Modal.jsx";

// Popup affichée UNE FOIS, juste après la création d'un compte : le
// consentement "utiliser mes corrections pour améliorer le modèle" est
// accordé par défaut (src/auth.py:register_user), ce message l'annonce
// clairement avec un moyen immédiat de le retirer.
export default function ConsentNotice({ open, onClose }) {
  const [busy, setBusy] = useState(false);

  async function disable() {
    setBusy(true);
    try {
      await API.setConsent(false);
      toast("Consentement retiré");
    } catch (e) {
      toast("Échec : " + e.message);
    } finally {
      setBusy(false);
      onClose();
    }
  }

  return (
    <Modal open={open} onClose={onClose}>
      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <span className="avatar" style={{ flexShrink: 0 }}><Icon name="shield" className="icon" /></span>
        <div>
          <h2 style={{ margin: "0 0 8px" }}>Vos corrections aident le modèle</h2>
          <p className="body-sm muted" style={{ margin: 0 }}>
            Par défaut, quand vous corrigez un reçu tout juste extrait, la différence entre ce que le modèle a
            lu et votre correction peut servir à l'entraîner, utile notamment pour les reçus ivoiriens et
            français. Aucune image n'est conservée pour cet usage, seulement les valeurs corrigées.
          </p>
          <p className="body-sm muted" style={{ marginTop: 10 }}>
            Vous pouvez désactiver ce consentement à tout moment depuis Profil, ou tout de suite ci-dessous.
          </p>
          <div className="btn-row" style={{ marginTop: 18 }}>
            <button className="btn btn--primary" onClick={onClose}>Garder activé</button>
            <button className="btn" onClick={disable} disabled={busy}>Désactiver maintenant</button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
