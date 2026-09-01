import { useEffect, useRef, useState } from "react";
import API from "../api.js";
import { money } from "../utils.js";
import { toast } from "../toast.jsx";
import { Icon } from "../Icons.jsx";

function ImportSection({ onImported }) {
  const fileRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function handleFile(file) {
    if (!file) return;
    setBusy(true); setError(null); setResult(null);
    try {
      const d = await API.importBilan(file);
      setResult(d);
      toast(`${d.imported} écriture(s) importée(s)`);
      onImported();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="card">
      <div className="card-head"><span className="card-head-label">Importer un bilan / des écritures</span></div>
      <div className="card-body stack">
        <p className="body-sm muted">
          Un reçu d'achat ne peut pas dire ce qu'est votre capital ou votre chiffre d'affaires.
          Importez un fichier Excel, CSV ou Word contenant vos écritures (colonnes <b>Compte</b>,
          <b> Libellé</b>, <b>Débit</b>, <b>Crédit</b>) pour compléter le bilan.
        </p>
        <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.csv,.docx"
               onChange={(e) => handleFile(e.target.files[0])} disabled={busy} />
        {busy && <p className="muted body-sm">Import en cours…</p>}
        {error && (
          <div className="error-box">
            <b>{error.message}</b>{error.detail && <><br />{error.detail}</>}
          </div>
        )}
        {result && (
          <div className="banner">
            {result.imported} ligne(s) importée(s), {result.skipped} ignorée(s).
            {result.skipped > 0 && (
              <ul style={{ margin: "var(--xs) 0 0 var(--lg)" }}>
                {result.errors.slice(0, 10).map((e, i) => (
                  <li key={i}>Ligne {e.row} : {e.reason}</li>
                ))}
              </ul>
            )}
            {!result.balanced && (
              <p style={{ marginTop: "var(--xs)" }}>
                Ce fichier seul n'est pas équilibré (débit {money(result.total_debit)} ≠
                crédit {money(result.total_credit)}), vérifiez qu'aucune ligne n'a été oubliée.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ManualEntrySection({ onAdded }) {
  const [account, setAccount] = useState("");
  const [label, setLabel] = useState("");
  const [debit, setDebit] = useState("");
  const [credit, setCredit] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await API.addBilanEntry({
        account, label: label || null,
        debit: debit === "" ? 0 : Number(debit),
        credit: credit === "" ? 0 : Number(credit),
      });
      setAccount(""); setLabel(""); setDebit(""); setCredit("");
      toast("Écriture ajoutée");
      onAdded();
    } catch (e2) {
      toast("Ajout impossible : " + e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-head"><span className="card-head-label">Ajouter une écriture manuellement</span></div>
      <div className="card-body">
        <form onSubmit={submit} className="row" style={{ alignItems: "flex-end" }}>
          <div>
            <label className="field" htmlFor="be-account">Compte</label>
            <input id="be-account" required placeholder="ex. 101" value={account}
                   onChange={(e) => setAccount(e.target.value)} />
          </div>
          <div>
            <label className="field" htmlFor="be-label">Libellé</label>
            <input id="be-label" placeholder="ex. Capital" value={label}
                   onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div>
            <label className="field" htmlFor="be-debit">Débit</label>
            <input id="be-debit" type="number" value={debit} onChange={(e) => setDebit(e.target.value)} />
          </div>
          <div>
            <label className="field" htmlFor="be-credit">Crédit</label>
            <input id="be-credit" type="number" value={credit} onChange={(e) => setCredit(e.target.value)} />
          </div>
          <div>
            <button className="btn btn--primary" type="submit" disabled={busy}><Icon name="plus" className="icon" style={{ width: 14, height: 14 }} />Ajouter</button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function BilanTab({ active, refreshToken, country, payment, isAuthenticated }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [localRefresh, setLocalRefresh] = useState(0);

  async function load() {
    setError(null);
    try {
      setData(await API.bilan(payment, country));
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { if (active) load(); }, [active, refreshToken, localRefresh, country, payment]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleClear() {
    if (!window.confirm("Effacer toutes vos écritures importées/manuelles ? Les reçus ne sont pas touchés.")) return;
    try {
      await API.clearBilanEntries();
      toast("Écritures importées effacées");
      setLocalRefresh((n) => n + 1);
    } catch (e) {
      toast("Échec : " + e.message);
    }
  }

  if (error) return <div className="error-box">{error}</div>;
  if (!data) return <p className="muted">Chargement…</p>;

  return (
    <div className="stack">
      <div className="notice">
        <Icon name="info" className="icon" />
        <span>{data.disclaimer}</span>
      </div>

      {!data.has_imported_entries && (
        <div className="notice">
          <Icon name="info" className="icon" />
          <span>Ce bilan ne reflète pour l'instant que vos reçus (charges). Le capital, les
            immobilisations, les stocks et le chiffre d'affaires ne peuvent pas venir d'un reçu
            d'achat, importez-les ci-dessous pour un bilan complet.</span>
        </div>
      )}

      <div className="kpi-grid">
        <div className="kpi"><div className="label-caps">Total Actif</div><div className="value">{money(data.total_actif)}</div></div>
        <div className="kpi"><div className="label-caps">Total Passif</div><div className="value">{money(data.total_passif)}</div></div>
        <div className={`kpi ${data.resultat_exercice < 0 ? "kpi--alert" : ""}`}>
          <div className="label-caps">Résultat de l'exercice</div><div className="value">{money(data.resultat_exercice)}</div>
        </div>
        <div className={`kpi balance${data.balanced ? "" : " bad"}`}>
          <span className="status-dot"><Icon name={data.balanced ? "check" : "warn"} className="icon" style={{ width: 18, height: 18 }} /></span>
          <div><div className="label-caps">Équilibre</div>
            <div className="value" style={{ fontSize: 16, color: data.balanced ? "var(--ok)" : "var(--alert)" }}>
              {data.balanced ? "Équilibré" : "Déséquilibré"}
            </div>
          </div>
        </div>
      </div>
      {!data.balanced && (
        <div className="banner">Actif ≠ Passif : une écriture importée est probablement
          incomplète (une ligne sans sa contrepartie). Vérifiez les écritures importées.</div>
      )}

      <div className="grid-2">
        <div className="card">
          <div className="card-head"><span className="card-head-label">Actif</span></div>
          <table>
            <thead><tr><th>Compte</th><th>Libellé</th><th className="num">Montant</th></tr></thead>
            <tbody>
              {data.actif.length ? data.actif.map((l) => (
                <tr key={l.account}><td>{l.account}</td><td>{l.label}</td><td className="num">{money(l.amount)}</td></tr>
              )) : <tr><td colSpan={3} className="muted">Aucune ligne</td></tr>}
            </tbody>
            <tfoot><tr><td colSpan={2}>Total</td><td className="num">{money(data.total_actif)}</td></tr></tfoot>
          </table>
        </div>
        <div className="card">
          <div className="card-head"><span className="card-head-label">Passif</span></div>
          <table>
            <thead><tr><th>Compte</th><th>Libellé</th><th className="num">Montant</th></tr></thead>
            <tbody>
              {data.passif.length ? data.passif.map((l) => (
                <tr key={l.account}><td>{l.account}</td><td>{l.label}</td><td className="num">{money(l.amount)}</td></tr>
              )) : <tr><td colSpan={3} className="muted">Aucune ligne</td></tr>}
            </tbody>
            <tfoot><tr><td colSpan={2}>Total</td><td className="num">{money(data.total_passif)}</td></tr></tfoot>
          </table>
        </div>
      </div>

      {isAuthenticated ? (
        <>
          <ImportSection onImported={() => setLocalRefresh((n) => n + 1)} />
          <ManualEntrySection onAdded={() => setLocalRefresh((n) => n + 1)} />
          {data.has_imported_entries && (
            <div className="btn-row">
              <button className="btn btn--danger" onClick={handleClear}>Effacer les écritures importées</button>
            </div>
          )}
        </>
      ) : (
        <div className="lock-panel">
          <Icon name="lock" className="icon" />
          <span>Connectez-vous pour importer un fichier d'écritures ou saisir
            manuellement le capital / les immobilisations.</span>
        </div>
      )}
    </div>
  );
}
