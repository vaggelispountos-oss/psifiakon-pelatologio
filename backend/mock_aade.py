"""
mock_aade.py
--------------------------------------------------------------------
ΨΕΥΤΙΚΗ (mock) υλοποίηση της υπηρεσίας ΑΑΔΕ για το Ψηφιακό Πελατολόγιο.

ΔΕΝ κάνει πραγματικά HTTP calls — απλώς προσομοιώνει τις απαντήσεις
της ΑΑΔΕ ώστε να αναπτύξουμε/δοκιμάσουμε τη λογική των 4 Χρόνων.

ΠΡΟΣΟΧΗ: Το αρχείο αυτό είναι σχεδιασμένο ώστε αργότερα να αντικατασταθεί
από ένα real_aade.py (RealAadeService) με ΤΗΝ ΙΔΙΑ διεπαφή (interface):
    send_client(data)
    update_client(id_dcl, data)
    client_correlations(id_dcl, data)
    cancel_client(id_dcl)
Έτσι, ο υπόλοιπος κώδικας (app.py) δεν χρειάζεται καμία αλλαγή.
--------------------------------------------------------------------
"""
import random
from datetime import datetime, timezone


def _now_iso():
    """Τρέχουσα ώρα σε UTC ISO-8601 (όπως θα την έδινε η ΑΑΔΕ)."""
    return datetime.now(timezone.utc).isoformat()


def _random_digits(n):
    """Επιστρέφει string με n τυχαία ψηφία."""
    return "".join(str(random.randint(0, 9)) for _ in range(n))


class MockAadeService:
    """Προσομοίωση των μεθόδων του Ψηφιακού Πελατολογίου της ΑΑΔΕ.

    Δέχεται τα credentials από τις Ρυθμίσεις. Στο mock δεν χρησιμοποιούνται
    λειτουργικά, αλλά το real_aade.py θα τα βάζει στα HTTP headers:
        aade-user-id             <- username
        ocp-apim-subscription-key <- subscription_key
    Έτσι η διεπαφή (interface) παραμένει ίδια όταν αλλάξουμε αρχείο.
    """

    def __init__(
        self,
        username=None,
        subscription_key=None,
        branch=0,
        entity_vat_number=None,
    ):
        self.username = username
        self.subscription_key = subscription_key
        self.branch = branch
        self.entity_vat_number = entity_vat_number

    def send_client(self, data):
        """
        1ος Χρόνος — SendClient.
        Δημιουργεί εγγραφή στην (ψεύτικη) ΑΑΔΕ και επιστρέφει τον
        Μοναδικό Αριθμό Εγγραφής (idDcl) + την ώρα δημιουργίας.
        """
        # Validation: branch και plate είναι υποχρεωτικά
        if not data.get("branch") and data.get("branch") != 0:
            return {"error": "Λείπει το πεδίο 'branch' (αριθμός εγκατάστασης)."}
        if not data.get("vehicleRegistrationNumber"):
            return {"error": "Λείπει το πεδίο 'vehicleRegistrationNumber' (πινακίδα)."}

        return {
            "idDcl": "DCL" + _random_digits(12),
            "creationDateTime": _now_iso(),
        }

    def update_client(self, id_dcl, data):
        """
        2ος & 3ος Χρόνος — UpdateClient.
        Ενημερώνει την εγγραφή. Αν το data περιέχει entryCompletion=true
        (3ος Χρόνος), επιστρέφει και completionDateTime.
        """
        if not id_dcl:
            return {"error": "Λείπει το idDcl για την ενημέρωση."}

        response = {"updateUniqueId": _random_digits(15)}

        if data.get("entryCompletion") is True:
            response["completionDateTime"] = _now_iso()

        return response

    def client_correlations(self, id_dcl, data):
        """
        4ος Χρόνος — ClientCorrelations.
        Συσχετίζει το παραστατικό (ΜΑΡΚ) με την εγγραφή και
        επιστρέφει correlateId.
        """
        if not id_dcl:
            return {"error": "Λείπει το idDcl για τη συσχέτιση."}

        return {"correlateId": _random_digits(16)}

    def cancel_client(self, id_dcl, entity_vat=None):
        """
        CancelClient — ακύρωση εγγραφής.
        (entity_vat για parity με το real_aade.py — αγνοείται στο mock.)
        """
        if not id_dcl:
            return {"error": "Λείπει το idDcl για την ακύρωση."}

        return {"cancellationId": _random_digits(14)}

    def request_clients(
        self, dclid, max_dclid=None, entity_vat=None, continuation_token=None
    ):
        """
        RequestClients — parity με real_aade.py. Στο mock δεν γίνεται πραγματική
        κλήση· επιστρέφουμε κενή (αλλά έγκυρη) δομή.
        """
        return {
            "entityVatNumber": entity_vat,
            "continuationToken": None,
            "clients": [],
            "updates": [],
            "correlations": [],
            "cancellations": [],
        }
