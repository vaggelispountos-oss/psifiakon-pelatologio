// tests/parsePlate.test.mjs
// Unit tests για την parsePlate (built-in node:test — χωρίς εξαρτήσεις).
// Τρέξιμο:  npm test    (ή: node --test tests/)
import test from "node:test";
import assert from "node:assert/strict";
import { parsePlate, parsePlateDetailed } from "../src/utils.js";

test("ΜΗΧΑΝΗ — 3 γράμματα + 3 ψηφία (ΟΤΜ-776)", () => {
  assert.equal(parsePlate("OTM 776"), "OTM-776");
  assert.equal(parsePlate("OTM776"), "OTM-776");
  assert.equal(parsePlate("OTM-776"), "OTM-776");
});

test("ΜΗΧΑΝΗ — δίσειρη πλάκα (γράμματα πάνω, ψηφία κάτω)", () => {
  assert.equal(parsePlate("OTM\n776"), "OTM-776");
  assert.equal(parsePlate("GR\nOTM\n776\n27"), "OTM-776");
});

test("ΜΗΧΑΝΗ — αγνοεί GR και το αυτοκόλλητο ΚΤΕΟ (27)", () => {
  // Το «27» του ΚΤΕΟ ΔΕΝ πρέπει να κολλήσει στα ψηφία της πλάκας.
  assert.equal(parsePlate("GR OTM 776 27"), "OTM-776");
  assert.equal(parsePlate("GR OTM 776"), "OTM-776");
});

test("ΜΗΧΑΝΗ — ελληνικοί χαρακτήρες", () => {
  assert.equal(parsePlate("ΟΤΜ 776"), "ΟΤΜ-776");
});

test("ΑΥΤΟΚΙΝΗΤΟ — 3 γράμματα + 4 ψηφία (ΑΒΓ-1234)", () => {
  assert.equal(parsePlate("ABG 1234"), "ABG-1234");
  assert.equal(parsePlate("ABG1234"), "ABG-1234");
  assert.equal(parsePlate("plate: ΑΒΓ-1234 GR"), "ΑΒΓ-1234");
});

test("ΘΟΡΥΒΟΣ — δεν βρίσκει πλάκα -> null", () => {
  assert.equal(parsePlate("noise xy 12"), null);
  assert.equal(parsePlate(""), null);
  assert.equal(parsePlate(null), null);
  assert.equal(parsePlate("HONDA"), null);
});

test("ΘΟΡΥΒΟΣ — τυχαίες λέξεις δεν περνούν για πινακίδα", () => {
  // Το «χαλαρό» πέρασμα απαιτεί γράμματα του αλφαβήτου πινακίδας, αλλιώς
  // το «CIVIC 2020» θα γινόταν «VIC-2020».
  assert.equal(parsePlate("HONDA CIVIC 2020"), null);
  assert.equal(parsePlate("SERVICE 2024"), null);
});

test("ΠΑΡΑΠΑΝΩ ΨΗΦΙΑ — ο διαχωριστής διαβάζεται ως ψηφίο", () => {
  // Πραγματικό δείγμα: πλάκα «ΙΚΧ-1833», το OCR έδωσε «HKX21833» (η παύλα
  // + η βίδα έγιναν «2»). Ο θόρυβος είναι ΜΠΡΟΣΤΑ -> κρατάμε τα 4 τελευταία.
  assert.equal(parsePlate("HKX21833"), "HKX-1833");
  assert.equal(parsePlate("IKX 71833"), "IKX-1833");

  const res = parsePlateDetailed("HKX21833");
  assert.equal(res.plate, "HKX-1833");
  assert.equal(res.corrected, true);
  assert.match(res.warnings[0], /5 ψηφία/);
});

test("ΠΑΡΑΠΑΝΩ ΓΡΑΜΜΑΤΑ — αυτοκόλλητο αριστερά της πλάκας", () => {
  // Το «R» του αυτοκόλλητου κολλάει μπροστά -> κρατάμε τα 3 τελευταία.
  assert.equal(parsePlate("RIKX 1833"), "IKX-1833");
  assert.equal(parsePlate("RIKX1833"), "IKX-1833");
});

test("ΣΥΓΧΥΣΗ ΤΥΠΟΥ — ψηφίο σε θέση γράμματος (Ι -> 1, Ο -> 0)", () => {
  // Εδώ ο διαχωρισμός γραμμάτων/ψηφίων αποτυγχάνει εντελώς και δουλεύει
  // το 2ο πέρασμα (εξαναγκασμός μορφής 3 γράμματα + ψηφία).
  assert.equal(parsePlate("1KX1833"), "IKX-1833");
  assert.equal(parsePlate("0TM776"), "OTM-776");
  assert.equal(parsePlateDetailed("1KX1833").corrected, true);
});

test("ΚΑΘΑΡΗ ΑΝΑΓΝΩΣΗ — δεν σημαδεύεται ως διορθωμένη", () => {
  const res = parsePlateDetailed("IKX-1833");
  assert.equal(res.plate, "IKX-1833");
  assert.equal(res.corrected, false);
  assert.deepEqual(res.warnings, []);
});
