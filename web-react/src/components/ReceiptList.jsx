import { useState } from "react";
import { money } from "../utils.js";
import { receiptLabel, receiptStatus } from "../helpers.jsx";
import { Icon } from "../Icons.jsx";

export function ReceiptList({ receipts, title, filters, onOpen }) {
  const [filter, setFilter] = useState("all");
  if (!receipts || !receipts.length) return null;
  const total = receipts.length;
  const review = receipts.filter((r) => receiptStatus(r).status === "review").length;
  const visible = receipts.filter((r) => {
    if (filter === "all") return true;
    const st = receiptStatus(r).status;
    return filter === "review" ? st === "review" : st !== "review";
  });

  return (
    <div className="card">
      <div className="card-head">
        <span className="card-head-label">{title} ({receipts.length})</span>
        <span className="muted body-sm">Cliquez une ligne pour voir le détail</span>
      </div>
      {filters && (
        <div className="filter-bar">
          <button className={`btn filter-btn${filter === "all" ? " active" : ""}`} onClick={() => setFilter("all")}>Tous ({total})</button>
          <button className={`btn filter-btn${filter === "conforme" ? " active" : ""}`} onClick={() => setFilter("conforme")}><Icon name="check" className="icon" style={{ width: 13, height: 13 }} />Conformes ({total - review})</button>
          <button className={`btn filter-btn${filter === "review" ? " active" : ""}`} onClick={() => setFilter("review")}><Icon name="warn" className="icon" style={{ width: 13, height: 13 }} />À vérifier ({review})</button>
        </div>
      )}
      <table>
        <thead>
          <tr><th>Reçu</th><th>Catégorie</th><th className="num">Articles</th><th className="num">Total</th><th>Contrôle</th></tr>
        </thead>
        <tbody>
          {visible.map((r) => {
            const st = receiptStatus(r);
            return (
              <tr key={r.receipt_id} className={`receipt-open ${st.rowClass}`}
                  title="Voir le détail du reçu" onClick={() => onOpen(r.receipt_id)}>
                <td><b>{receiptLabel(r)}</b></td>
                <td>{r.category || "-"}</td>
                <td className="num">{r.n_items}</td>
                <td className="num">{money(r.total)}</td>
                <td>{st.badge}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
