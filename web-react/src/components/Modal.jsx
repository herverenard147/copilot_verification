import { useEffect } from "react";
import { Icon } from "../Icons.jsx";

export function Modal({ open, onClose, children, wide }) {
  useEffect(() => {
    if (!open) return;
    function onKey(e) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className={`modal-panel${wide ? " modal-panel--wide" : ""}`} onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Fermer"><Icon name="close" className="icon" style={{ width: 18, height: 18 }} /></button>
        {children}
      </div>
    </div>
  );
}
