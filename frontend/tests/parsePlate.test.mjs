// tests/parsePlate.test.mjs
// Unit tests για την parsePlate (built-in node:test — χωρίς εξαρτήσεις).
// Τρέξιμο:  npm test    (ή: node --test tests/)
import test from "node:test";
import assert from "node:assert/strict";
import {
  parsePlate,
  parsePlateDetailed,
  findClosestKnownPlate,
} from "../src/utils.js";

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

test("ΜΗΧΑΝΗ — ελληνικοί χαρακτήρες κανονικοποιούνται σε λατινικούς", () => {
  // Η ΑΑΔΕ και η βάση περιμένουν ΠΑΝΤΑ λατινικά γράμματα — «ΟΤΜ» και «OTM»
  // πρέπει να καταλήγουν στην ΙΔΙΑ πινακίδα, αλλιώς σπάει το matching πελάτη.
  assert.equal(parsePlate("ΟΤΜ 776"), "OTM-776");
});

test("ΑΥΤΟΚΙΝΗΤΟ — 3 γράμματα + 4 ψηφία (ABH-1234)", () => {
  assert.equal(parsePlate("ABH 1234"), "ABH-1234");
  assert.equal(parsePlate("ABH1234"), "ABH-1234");
  assert.equal(parsePlate("plate: ΑΒΗ-1234 GR"), "ABH-1234");
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

test("ΓΝΩΣΤΗ ΠΙΝΑΚΙΔΑ — προτείνει διόρθωση όταν διαφέρει 1 χαρακτήρα", () => {
  const known = [{ plate: "IKX-1833", name: "Παπαδόπουλος" }];
  assert.deepEqual(findClosestKnownPlate("IKX-1533", known), known[0]);
  // Λειτουργεί ΚΑΙ όταν η γνωστή πινακίδα είναι αποθηκευμένη σε ελληνικά.
  assert.deepEqual(
    findClosestKnownPlate("IKX-1533", [{ plate: "ΙΚΧ-1833" }]),
    { plate: "ΙΚΧ-1833" }
  );
});

test("ΓΝΩΣΤΗ ΠΙΝΑΚΙΔΑ — καμία πρόταση αν ήδη ταιριάζει ακριβώς", () => {
  const known = [{ plate: "IKX-1833" }];
  assert.equal(findClosestKnownPlate("IKX-1833", known), null);
  assert.equal(findClosestKnownPlate("ΙΚΧ-1833", known), null); // ίδια, ελληνικά
});

test("ΓΝΩΣΤΗ ΠΙΝΑΚΙΔΑ — καμία πρόταση αν η απόκλιση είναι μεγάλη ή ασαφής", () => {
  const known = [{ plate: "IKX-1833" }];
  assert.equal(findClosestKnownPlate("ABC-9999", known), null); // πολύ διαφορετική
  assert.equal(findClosestKnownPlate("IKX-183", known), null); // διαφορετικό μήκος (μηχανή 3 ψηφία vs αυτοκίνητο 4) -> δεν συγκρίνεται καν
  // Δύο εξίσου κοντινές -> ασαφές, μην μαντεύεις
  const ambiguous = [{ plate: "IKX-1533" }, { plate: "IKX-1933" }];
  assert.equal(findClosestKnownPlate("IKX-1833", ambiguous), null);
});
