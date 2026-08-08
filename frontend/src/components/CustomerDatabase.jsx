// components/CustomerDatabase.jsx
// Βάση Πελατών/Οχημάτων — μία γραμμή ανά πινακίδα, με τα πραγματικά στοιχεία
// επαφής (όνομα/ΑΦΜ/τηλέφωνο) από το backend (Customer model), αναζήτηση, και
// inline επεξεργασία. Το πλήθος επισκέψεων/τελευταία κατάσταση προκύπτουν από
// τις εγγραφές πελατολογίου (entries prop), ήδη φορτωμένες στο App.
import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getCustomers, updateCustomer } from "../services/api";
import { STATUS_LABELS } from "../constants";

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("el-GR");
  } catch {
    return iso;
  }
}

function EditRow({ customer, onCancel, onSaved }) {
  const [name, setName] = useState(customer.name || "");
  const [vat, setVat] = useState(customer.vat || "");
  const [phone, setPhone] = useState(customer.phone || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const updated = await updateCustomer(customer.id, {
        name: name.trim(),
        vat: vat.trim(),
        phone: phone.trim(),
      });
      onSaved(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <tr className="customer-edit-row">
      <td colSpan={6}>
        <form onSubmit={handleSave} className="customer-edit-form">
          <label className="field-label">
            Όνομα
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field-label">
            ΑΦΜ
            <input
              className="input"
              inputMode="numeric"
              value={vat}
              onChange={(e) => setVat(e.target.value)}
              placeholder="9 ψηφία"
            />
          </label>
          <label className="field-label">
            Τηλέφωνο
            <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </label>
          {error && (
            <div className="alert alert-error" style={{ flex: "1 1 100%" }}>
              {error}
            </div>
          )}
          <div style={{ display: "flex", gap: "8px", flex: "1 1 100%" }}>
            <button className="btn btn-primary btn-sm" disabled={saving}>
              {saving ? "Αποθήκευση…" : "Αποθήκευση"}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onCancel}
              disabled={saving}
            >
              Ακύρωση
            </button>
          </div>
        </form>
      </td>
    </tr>
  );
}

export default function CustomerDatabase({ entries, loading: entriesLoading, onRefresh }) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [editingId, setEditingId] = useState(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const customersQuery = useQuery({
    queryKey: ["customers", debouncedSearch],
    queryFn: () => getCustomers(debouncedSearch),
    placeholderData: (prev) => prev,
  });
  const customers = customersQuery.data || [];
  const loading = customersQuery.isFetching;
  const error = customersQuery.error?.message || "";

  const refreshCustomers = () =>
    queryClient.invalidateQueries({ queryKey: ["customers"] });

  // Πλήθος επισκέψεων + τελευταία κατάσταση ανά πινακίδα, από τις entries.
  const statsByPlate = useMemo(() => {
    const m = {};
    for (const e of entries) {
      if (!m[e.plate]) m[e.plate] = { count: 0, last: e };
      m[e.plate].count += 1;
      if (new Date(e.createdAt) > new Date(m[e.plate].last.createdAt)) {
        m[e.plate].last = e;
      }
    }
    return m;
  }, [entries]);

  function handleRefresh() {
    refreshCustomers();
    onRefresh();
  }

  return (
    <div className="card">
      <div className="list-header">
        <h2>Βάση Πελατών / Οχημάτων</h2>
        <button className="btn btn-ghost btn-sm" onClick={handleRefresh}>
          ↻ Ανανέωση
        </button>
      </div>
      <p className="muted">
        ΜΙΑ γραμμή ανά πινακίδα, με στοιχεία επαφής. Για τις επιμέρους
        επισκέψεις, δες το tab «Ιστορικό».
      </p>

      <input
        className="input"
        type="search"
        placeholder="Αναζήτηση με πινακίδα, όνομα, ΑΦΜ ή τηλέφωνο…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ marginBottom: "12px" }}
      />

      {error && <div className="alert alert-error">{error}</div>}
      {(loading || entriesLoading) && <p className="muted">Φόρτωση…</p>}
      {!loading && !entriesLoading && customers.length === 0 && (
        <p className="muted">
          {search ? "Καμία αντιστοιχία." : "Δεν υπάρχουν πελάτες/οχήματα ακόμη."}
        </p>
      )}

      <div className="table-wrap">
        {customers.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Πινακίδα</th>
                <th>Όνομα</th>
                <th>ΑΦΜ</th>
                <th>Τηλέφωνο</th>
                <th>Επισκέψεις</th>
                <th>Τελ. κατάσταση</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {customers.map((c) => {
                const stats = statsByPlate[c.plate];
                const s = stats
                  ? STATUS_LABELS[stats.last.status] || { text: stats.last.status }
                  : null;
                if (editingId === c.id) {
                  return (
                    <EditRow
                      key={c.id}
                      customer={c}
                      onCancel={() => setEditingId(null)}
                      onSaved={() => {
                        refreshCustomers();
                        setEditingId(null);
                      }}
                    />
                  );
                }
                return (
                  <tr key={c.id}>
                    <td className="mono">{c.plate}</td>
                    <td>{c.name || "—"}</td>
                    <td className="mono">{c.vat || "—"}</td>
                    <td>{c.phone || "—"}</td>
                    <td>{stats ? stats.count : 0}</td>
                    <td>{s ? s.text : "—"}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setEditingId(c.id)}
                      >
                        ✎ Επεξεργασία
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
