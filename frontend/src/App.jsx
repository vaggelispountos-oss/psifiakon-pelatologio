// App.jsx
// --------------------------------------------------------------------
// Κεντρική εφαρμογή — ενορχηστρώνει τη ροή των 4 Χρόνων της ΑΑΔΕ.
// Όλα τα δεδομένα περνούν από το backend (καθόλου localStorage).
// --------------------------------------------------------------------
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  API_URL,
  addService,
  cancelEntry,
  completeExit,
  correlateMark,
  createEntry,
  getEntries,
  getHealth,
  getSettings,
  getStoredWorkshop,
  getToken,
  logout,
  setStoredWorkshop,
  setUnauthorizedHandler,
} from "./services/api";
import { STATUS_LABELS, STATUS_LABELS_RENTAL } from "./constants";
import CameraCapture from "./components/CameraCapture";
import Stepper from "./components/Stepper";
import RentalTodayPanel from "./components/RentalTodayPanel";
import RentalVehiclePicker from "./components/RentalVehiclePicker";
import ServiceForm from "./components/ServiceForm";
import ExitForm from "./components/ExitForm";
import QrScanner from "./components/QrScanner";
import EntriesList from "./components/EntriesList";
import Archive from "./components/Archive";
import OcrStats from "./components/OcrStats";
import { SettingsAccordion } from "./components/SettingsPanel";
import Login from "./components/Login";
import { PrivacyPolicy, TermsOfService } from "./components/LegalPages";
import ResetPassword from "./components/ResetPassword";

// Πελάτες/Ιστορικό/Οχήματα ήταν 3 ξεχωριστά tabs που έδειχναν την ΙΔΙΑ λίστα
// εγγραφών, απλά ομαδοποιημένη διαφορετικά — μπερδεμένο ΠΟΙΟ tab έχει τι
// χωρίς να διαβάσεις hint. Τώρα είναι ΕΝΑ tab «Αρχείο» με εσωτερικό
// segmented control (δες components/Archive.jsx).
const TABS = [
  { id: "flow", label: "Λειτουργία" },
  {
    id: "entries",
    label: "Εγγραφές",
    hint: "Ενεργές εργασίες — δράσε πάνω σε ανοιχτά οχήματα",
  },
  {
    id: "archive",
    label: "Αρχείο",
    hint: "Πελάτες, ιστορικό επισκέψεων και ο στόλος σου",
  },
  { id: "settings", label: "Ρυθμίσεις" },
];

// Tabs που ΔΕΝ πρέπει να βλέπει ο πελάτης-συνεργείο (εσωτερικά εργαλεία του
// πωλητή του λογισμικού). Εμφανίζονται ΜΟΝΟ σε "dev mode" — ενεργοποιείται
// πατώντας 5 φορές τον τίτλο της εφαρμογής μέσα σε 2 δευτερόλεπτα (δες
// `useSecretDevMode` παρακάτω). Η πραγματική πηγή αλήθειας για σένα είναι
// έτσι κι αλλιώς ο κεντρικός telemetry server (δες telemetry-server/), όχι
// αυτό το tab — αυτό εδώ είναι βολικό μόνο για επιτόπιο έλεγχο.
const HIDDEN_TABS = [
  {
    id: "ocr-stats",
    label: "OCR",
    hint: "Στατιστικά αναγνώρισης πινακίδας — πόσο καλά δουλεύει το AI",
  },
];

const DEV_MODE_KEY = "dcl_dev_mode";
const DEV_MODE_TAPS = 5;
const DEV_MODE_WINDOW_MS = 2000;

/**
 * Κρυφή χειρονομία: 5 tap στον τίτλο μέσα σε 2s -> toggle dev mode.
 *
 * Η updater function του setDevMode πρέπει να είναι ΚΑΘΑΡΗ (χωρίς side
 * effects) — το React Strict Mode την καλεί ΔΥΟ ΦΟΡΕΣ σε development για
 * να εντοπίσει ακριβώς τέτοια bugs. Το localStorage.setItem γράφεται σε
 * ξεχωριστό useEffect συγχρονισμένο με το state, όχι μέσα στο toggle.
 */
function useSecretDevMode() {
  const [devMode, setDevMode] = useState(
    () => localStorage.getItem(DEV_MODE_KEY) === "1"
  );
  // Timestamps των πρόσφατων tap — απλή λίστα αντί για setTimeout, ώστε να
  // μην εξαρτόμαστε από χρονισμό τρίτου timer (πιο προβλέψιμο σε StrictMode).
  const tapsRef = useRef([]);

  useEffect(() => {
    localStorage.setItem(DEV_MODE_KEY, devMode ? "1" : "0");
  }, [devMode]);

  const onSecretTap = useCallback(() => {
    const now = Date.now();
    const recent = tapsRef.current.filter((t) => now - t < DEV_MODE_WINDOW_MS);
    recent.push(now);
    tapsRef.current = recent;

    if (recent.length >= DEV_MODE_TAPS) {
      tapsRef.current = [];
      setDevMode((v) => !v);
    }
  }, []);

  return [devMode, onSecretTap];
}

export default function App() {
  const [workshop, setWorkshop] = useState(() => getStoredWorkshop());
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    // Σε 401 από οποιοδήποτε request (π.χ. έληξε το token), γύρνα στο login.
    setUnauthorizedHandler(() => setWorkshop(null));
    setAuthChecked(true);
  }, []);

  const isAuthenticated = authChecked && !!getToken() && !!workshop;

  // /privacy και /terms είναι δημόσιες σελίδες — προσβάσιμες ΧΩΡΙΣ σύνδεση
  // (π.χ. πριν την εγγραφή), γι' αυτό ελέγχονται πριν το auth gate.
  if (window.location.pathname === "/privacy") {
    return <PrivacyPolicy />;
  }
  if (window.location.pathname === "/terms") {
    return <TermsOfService />;
  }
  if (window.location.pathname === "/reset-password") {
    return <ResetPassword />;
  }

  if (!isAuthenticated) {
    return <Login onAuthenticated={(w) => setWorkshop(w)} />;
  }

  return (
    <AuthenticatedApp
      workshop={workshop}
      onLogout={() => {
        logout();
        setWorkshop(null);
      }}
      onWorkshopUpdated={(w) => {
        setStoredWorkshop(w);
        setWorkshop(w);
      }}
    />
  );
}

function AuthenticatedApp({ workshop, onLogout, onWorkshopUpdated }) {
  const isRental = workshop?.businessType === "rental";
  const [tab, setTab] = useState("flow");
  // Ποια εσωτερική προβολή του tab «Αρχείο» είναι ενεργή — ελεγχόμενο εδώ
  // (όχι τοπικό state μέσα στο Archive) ώστε το «Λεπτομέρειες» στο tab
  // «Εγγραφές» να μπορεί να ανοίξει κατευθείαν στο Ιστορικό.
  const [archiveView, setArchiveView] = useState("customers");
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  // Ρητή αναφορά στο συγκεκριμένο όχημα (entry_id). ΔΕΝ υπάρχει global
  // «τρέχον στάδιο» — το στάδιο ΠΑΡΑΓΕΤΑΙ από το status της κάθε εγγραφής.
  const [activeEntryId, setActiveEntryId] = useState(null);

  const [toast, setToast] = useState(null); // {type, text}
  const [health, setHealth] = useState("unknown"); // ok | down | unknown
  const [hasKey, setHasKey] = useState(null); // null=unknown, true/false
  const [devMode, onSecretTap] = useSecretDevMode();

  const activeEntry = useMemo(
    () => entries.find((e) => e.id === activeEntryId) || null,
    [entries, activeEntryId]
  );

  // Πόσα ενοικιαζόμενα οχήματα καθυστερούν να επιστραφούν — δείχνεται ως
  // κόκκινο badge πάνω στο tab «Λειτουργία» ώστε να μη χρειάζεται να το
  // ανοίξεις για να ξέρεις ότι κάτι εκκρεμεί.
  const overdueCount = useMemo(
    () => (isRental ? entries.filter((e) => e.isOverdue).length : 0),
    [entries, isRental]
  );

  const notify = useCallback((type, text) => {
    setToast({ type, text });
    if (type === "success") {
      setTimeout(() => setToast(null), 4000);
    }
  }, []);

  const visibleTabs = useMemo(() => {
    const base = TABS.filter((t) => !t.rentalOnly || isRental);
    if (!devMode) return base;
    const withoutSettings = base.filter((t) => t.id !== "settings");
    const settingsTab = base.find((t) => t.id === "settings");
    const hiddenTabs = isRental ? [] : HIDDEN_TABS;
    return [...withoutSettings, ...hiddenTabs, settingsTab];
  }, [devMode, isRental]);

  // Αν ο χρήστης απενεργοποιήσει το dev mode ενώ βρίσκεται σε κρυφό tab,
  // γύρνα τον σε ασφαλές έδαφος (το tab δεν θα υπάρχει πια στο μενού).
  useEffect(() => {
    if (
      (!devMode || isRental) &&
      HIDDEN_TABS.some((t) => t.id === tab)
    ) {
      setTab("flow");
    }
  }, [devMode, isRental, tab]);

  const firstDevModeRender = useRef(true);
  useEffect(() => {
    if (firstDevModeRender.current) {
      firstDevModeRender.current = false;
      return; // μη δείξεις toast απλά επειδή φορτώθηκε από localStorage
    }
    notify(
      "success",
      devMode ? "🔓 Dev mode ενεργό (tab «OCR» ορατό)" : "🔒 Dev mode ανενεργό"
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [devMode]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getEntries();
      setEntries(Array.isArray(data) ? data : []);
    } catch (err) {
      notify("error", err.message);
    } finally {
      setLoading(false);
    }
  }, [notify]);

  const refreshSettings = useCallback(async () => {
    try {
      const s = await getSettings();
      setHasKey(!!s.has_key);
    } catch {
      // αν αποτύχει, άφησέ το unknown — το health banner θα ενημερώσει
    }
  }, []);

  // Έλεγχος backend + αρχική φόρτωση
  useEffect(() => {
    (async () => {
      try {
        await getHealth();
        setHealth("ok");
      } catch {
        setHealth("down");
      }
    })();
    refresh();
    refreshSettings();
  }, [refresh, refreshSettings]);

  // ---- 1ος Χρόνος ----
  async function handleCreateEntry(plate, extra = {}) {
    setBusy(true);
    try {
      const res = await createEntry({ plate, branch: 0, ...extra });
      notify(
        "success",
        `Δημιουργήθηκε εγγραφή! idDcl: ${res.idDcl} (ώρα: ${res.creationDateTime})`
      );
      await refresh();
      // Συνεργεία: ανοίγει κατευθείαν στον 2ο Χρόνο (κατηγορία εργασίας) —
      // γίνεται την ίδια στιγμή, έχει νόημα να συνεχίσεις αμέσως.
      // Ενοικιάσεις: η Ολοκλήρωση (3ος Χρόνος) γίνεται μέρες αργότερα, στην
      // επιστροφή — η «Λειτουργία» πρέπει να ξαναδείξει καθαρή τη λίστα
      // οχημάτων, όχι τη φόρμα Ολοκλήρωσης. Η επιστροφή γίνεται από το tab
      // «Εγγραφές» όταν έρθει η ώρα.
      if (!isRental) {
        setActiveEntryId(res.entry_id);
      }
    } catch (err) {
      notify("error", err.message);
    } finally {
      setBusy(false);
    }
  }

  // ---- 2ος Χρόνος ----
  async function handleService(data) {
    if (!activeEntry) return;
    setBusy(true);
    try {
      const res = await addService({ entry_id: activeEntry.id, ...data });
      notify("success", `Καταχωρήθηκε η εργασία (updateUniqueId: ${res.updateUniqueId}).`);
      await refresh(); // status -> in_progress -> εμφανίζεται ο 3ος Χρόνος
    } catch (err) {
      notify("error", err.message);
    } finally {
      setBusy(false);
    }
  }

  // ---- 3ος Χρόνος ----
  async function handleExit(data) {
    if (!activeEntry) return;
    setBusy(true);
    try {
      const res = await completeExit({ entry_id: activeEntry.id, ...data });
      notify("success", `Ολοκληρώθηκε! Ώρα ολοκλήρωσης: ${res.completionDateTime}`);
      await refresh(); // status -> completed -> εμφανίζεται ο 4ος Χρόνος
    } catch (err) {
      notify("error", err.message);
    } finally {
      setBusy(false);
    }
  }

  // ---- 4ος Χρόνος ----
  async function handleCorrelate(mark) {
    if (!activeEntry) return;
    setBusy(true);
    try {
      const res = await correlateMark({ entry_id: activeEntry.id, mark });
      notify("success", `Έγινε συσχέτιση ΜΑΡΚ! correlateId: ${res.correlateId}`);
      await refresh();
      setActiveEntryId(null);
    } catch (err) {
      notify("error", err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel() {
    if (!activeEntry) return;
    if (!window.confirm(`Ακύρωση εγγραφής για ${activeEntry.plate};`)) return;
    setBusy(true);
    try {
      await cancelEntry({ entry_id: activeEntry.id });
      notify("success", "Η εγγραφή ακυρώθηκε.");
      await refresh();
      setActiveEntryId(null);
    } catch (err) {
      notify("error", err.message);
    } finally {
      setBusy(false);
    }
  }

  // «Νέο όχημα» — πατιέται όταν μπαίνει νέος πελάτης στο μαγαζί.
  // Καθαρίζει το ενεργό όχημα και πάει στην κάμερα (1ος Χρόνος).
  // Δεν επηρεάζει τα άλλα ανοιχτά οχήματα.
  function handleNewVehicle() {
    setActiveEntryId(null);
    setTab("flow");
  }

  // Από τη λίστα «Εγγραφές» -> άνοιγμα συγκεκριμένου οχήματος.
  // Το στάδιο παράγεται από το status του — συνεχίζει ΑΚΡΙΒΩΣ από εκεί.
  function handleActOnEntry(entry, requestedStage) {
    if (requestedStage === "details") {
      setActiveEntryId(entry.id);
      setArchiveView("history");
      setTab("archive");
      return;
    }
    setActiveEntryId(entry.id);
    setTab("flow");
  }

  function renderStage() {
    if (!activeEntry) {
      // Πρώτο πράγμα που βλέπει ο χρήστης rental κάθε φορά που ανοίγει την
      // εφαρμογή: τι καθυστερεί / τι γυρνάει σήμερα. Ανεξάρτητο από τους
      // κωδικούς ΑΑΔΕ — είναι απλή ανάγνωση, όχι δημιουργία εγγραφής.
      const todayPanel = isRental && (
        <RentalTodayPanel entries={entries} onAct={handleActOnEntry} />
      );

      // Μπλοκάρισμα «Νέας εγγραφής» χωρίς κωδικούς ΑΑΔΕ
      if (hasKey === false) {
        return (
          <>
            {todayPanel}
            <div className="card">
              <h2>Απαιτούνται κωδικοί ΑΑΔΕ</h2>
              <div className="alert alert-error">
                ⚠️ Δεν έχουν οριστεί οι κωδικοί ΑΑΔΕ. Για να δημιουργήσεις εγγραφή,
                συμπλήρωσέ τους πρώτα στις Ρυθμίσεις.
              </div>
              <button
                className="btn btn-primary btn-block"
                onClick={() => setTab("settings")}
              >
                ⚙️ Μετάβαση στις Ρυθμίσεις
              </button>
            </div>
          </>
        );
      }
      return (
        <>
          {todayPanel}
          <Stepper status={null} isRental={isRental} />
          {isRental ? (
            <RentalVehiclePicker
              onConfirm={handleCreateEntry}
              disabled={busy}
              entries={entries}
            />
          ) : (
            <CameraCapture onConfirm={handleCreateEntry} disabled={busy} isRental={isRental} />
          )}
        </>
      );
    }

    const statusLabels = isRental ? STATUS_LABELS_RENTAL : STATUS_LABELS;
    const s = statusLabels[activeEntry.status] || { text: activeEntry.status };

    return (
      <>
        <Stepper status={activeEntry.status} isRental={isRental} />
        <div className="card active-entry">
          <div className="list-header">
            <h2>Ενεργή εγγραφή</h2>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setActiveEntryId(null)}
            >
              Κλείσιμο
            </button>
          </div>
          <div className="kv">
            <span>Πινακίδα</span>
            <b className="mono">{activeEntry.plate}</b>
          </div>
          <div className="kv">
            <span>idDcl</span>
            <b className="mono">{activeEntry.idDcl || "—"}</b>
          </div>
          <div className="kv">
            <span>Κατάσταση</span>
            <b style={{ color: s.color }}>{s.text}</b>
          </div>
          {activeEntry.completionDateTime && (
            <div className="kv">
              <span>Ολοκλήρωση</span>
              <b>{new Date(activeEntry.completionDateTime).toLocaleString("el-GR")}</b>
            </div>
          )}
          {activeEntry.status !== "correlated" &&
            activeEntry.status !== "cancelled" && (
              <button
                className="btn btn-danger btn-sm"
                onClick={handleCancel}
                disabled={busy}
              >
                Ακύρωση εγγραφής
              </button>
            )}
        </div>

        {/* Το στάδιο παράγεται από το status της συγκεκριμένης εγγραφής.
            Ενοικιάσεις ΔΕΝ έχουν 2ο Χρόνο — από "open" πάνε κατευθείαν στην
            Ολοκλήρωση (ExitForm), όχι στην Κατηγορία Εργασίας (ServiceForm). */}
        {activeEntry.status === "open" && !isRental && (
          <ServiceForm onSubmit={handleService} disabled={busy} />
        )}
        {activeEntry.status === "open" && isRental && (
          <ExitForm onSubmit={handleExit} disabled={busy} isRental />
        )}
        {activeEntry.status === "in_progress" && (
          <ExitForm onSubmit={handleExit} disabled={busy} />
        )}
        {activeEntry.status === "completed" && (
          <QrScanner onCorrelate={handleCorrelate} disabled={busy} isRental={isRental} />
        )}
        {activeEntry.status === "correlated" && (
          <div className="card">
            <h2>✅ Ολοκληρωμένη ροή</h2>
            <p className="muted">
              Και οι 4 Χρόνοι ολοκληρώθηκαν για αυτό το όχημα.
            </p>
          </div>
        )}
        {activeEntry.status === "cancelled" && (
          <div className="card">
            <h2>Ακυρωμένη εγγραφή</h2>
            <p className="muted">Αυτή η εγγραφή έχει ακυρωθεί.</p>
          </div>
        )}
      </>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        {/* onClick: 5 tap μέσα σε 2s ενεργοποιεί κρυφό dev-mode tab (OCR
            στατιστικά) — δες useSecretDevMode(). Αόρατο στον πελάτη. */}
        <div className="brand" onClick={onSecretTap}>
          {isRental ? "🚗 Ψηφιακό Πελατολόγιο Ενοικιάσεων" : "🔧 Ψηφιακό Πελατολόγιο"}
        </div>
        <div className="topbar-right">
          {health === "down" && (
            <div
              className={`health health-${health}`}
              title={`Backend: ${API_URL}`}
            >
              ● Offline
            </div>
          )}
          <span className="muted" title={workshop?.email}>
            {workshop?.name}
          </span>
          <button className="btn btn-ghost btn-sm" onClick={onLogout}>
            Αποσύνδεση
          </button>
        </div>
      </header>

      <nav className="tabs">
        {visibleTabs.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? "tab-active" : ""}`}
            onClick={() => setTab(t.id)}
            title={t.hint}
          >
            {t.label}
            {t.id === "flow" && overdueCount > 0 && (
              <span className="tab-badge">{overdueCount}</span>
            )}
          </button>
        ))}
      </nav>

      {health === "down" && (
        <div className="alert alert-error banner">
          Το backend δεν είναι προσβάσιμο ({API_URL}). Τρέξε το Flask backend.
        </div>
      )}

      {toast && (
        <div
          className={`alert alert-${toast.type === "error" ? "error" : "info"} toast-float`}
        >
          {toast.text}
        </div>
      )}

      <main className="content">
        {tab === "flow" && renderStage()}
        {tab === "entries" && (
          <EntriesList
            entries={entries}
            loading={loading}
            onAct={handleActOnEntry}
            onRefresh={refresh}
            isRental={isRental}
          />
        )}
        {tab === "archive" && (
          <Archive
            view={archiveView}
            onViewChange={setArchiveView}
            entries={entries}
            loading={loading}
            onRefresh={refresh}
            isRental={isRental}
          />
        )}
        {tab === "ocr-stats" && <OcrStats />}
        {tab === "settings" && (
          <SettingsAccordion
            onSaved={(s) => setHasKey(!!s.has_key)}
            onLogout={onLogout}
            workshop={workshop}
            onWorkshopUpdated={onWorkshopUpdated}
          />
        )}
      </main>

      {/* Ένα και μοναδικό σημείο για «νέο όχημα» — ορατό από ΟΠΟΥΔΗΠΟΤΕ ΕΚΤΟΣ
          του tab «Λειτουργία», που έχει ήδη δικό του πλήρους-πλάτους CTA σε
          κάθε βήμα (Σκάναρε/Καταχώρηση/Ολοκλήρωση/Συσχέτιση) — το FAB εκεί
          θα κάλυπτε μέρος του κουμπιού σε κοντές οθόνες. */}
      {tab !== "flow" && (
        <button
          className="fab"
          onClick={handleNewVehicle}
          title="Νέο όχημα"
          aria-label="Νέο όχημα"
        >
          ＋
        </button>
      )}
    </div>
  );
}
