"""
test_aade_idempotency.py
--------------------------------------------------------------------
Τα POST της ΑΑΔΕ ΔΕΝ είναι idempotent: κάθε SendClient δημιουργεί ΝΕΑ εγγραφή
στο Ψηφιακό Πελατολόγιο, και δεν υπάρχει τρόπος να αναιρεθεί μια διπλή
καταχώρηση πέρα από CancelClient. Άρα ένα τυφλό retry είναι ΧΕΙΡΟΤΕΡΟ από ένα
σφάλμα — ο χρήστης δεν το βλέπει ποτέ και ο πελάτης του μένει με διπλή εγγραφή.

Τα τεστ εδώ καλύπτουν τις δύο διαδρομές που παράγουν διπλές εγγραφές:

  1) ΜΕΣΑ στο transport (real_aade._post_xml): retry μετά από read timeout.
  2) ΜΕΣΑ στη ροή (app.resend_entry): «Επαναποστολή» εγγραφής που η ΑΑΔΕ
     έχει ήδη καταχωρήσει.

Καμία πραγματική κλήση δικτύου — το HTTP layer γίνεται mock με `responses`,
και η υπηρεσία ΑΑΔΕ με ένα fake ίδιου interface.
--------------------------------------------------------------------
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests
import responses

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
from app import app  # noqa: E402
from models import AadeLog, Customer, DclEntry, db  # noqa: E402
from real_aade import EP_SEND, RealAadeService  # noqa: E402

BASE_URL = "https://mydataapidev.aade.gr/DCL"
SEND_URL = f"{BASE_URL}/{EP_SEND}"

TEST_EMAIL = "idempotency.test@example.com"
TEST_PASSWORD = "testpass1234"
PLATE = "IKX-1833"


# ====================================================================
# 1) Transport layer — πότε επιτρέπεται retry και πότε ΟΧΙ
# ====================================================================
def make_service():
    return RealAadeService(
        username="u", subscription_key="k", branch=0, base_url=BASE_URL, retries=2
    )


@responses.activate
def test_read_timeout_is_never_retried_and_is_flagged_indeterminate():
    """
    Read timeout = ΣΤΑΛΘΗΚΕ, δεν ξέρουμε αν εκτελέστηκε. Το retry εδώ είναι
    ακριβώς το bug: η ΑΑΔΕ μπορεί να έχει ήδη δημιουργήσει την εγγραφή.
    """
    responses.add(responses.POST, SEND_URL, body=requests.ReadTimeout("timed out"))

    res = make_service().send_client(
        {"vehicleRegistrationNumber": PLATE, "branch": 0, "clientServiceType": 3}
    )

    assert res.get("indeterminate") is True
    assert "error" in res
    # ΤΟ ΚΡΙΣΙΜΟ: ΜΙΑ και μόνο απόπειρα, παρότι retries=2.
    assert len(responses.calls) == 1


@responses.activate
def test_connection_error_is_retried_because_nothing_was_sent():
    """Connection refused/DNS = η ΑΑΔΕ δεν είδε τίποτα -> ασφαλές retry."""
    responses.add(responses.POST, SEND_URL, body=requests.ConnectionError("refused"))
    responses.add(responses.POST, SEND_URL, body=requests.ConnectionError("refused"))

    res = make_service().send_client(
        {"vehicleRegistrationNumber": PLATE, "branch": 0, "clientServiceType": 3}
    )

    assert len(responses.calls) == 2  # έγινε retry
    assert "error" in res
    assert not res.get("indeterminate")  # βέβαιη αποτυχία, όχι άγνωστη


@responses.activate
def test_connection_error_then_success_recovers():
    """Το retry εξακολουθεί να δουλεύει εκεί που είναι ασφαλές."""
    responses.add(responses.POST, SEND_URL, body=requests.ConnectionError("refused"))
    responses.add(
        responses.POST,
        SEND_URL,
        body=(
            '<?xml version="1.0" encoding="UTF-8"?><ResponseDoc><response>'
            "<newClientDclID>4400000001</newClientDclID>"
            "<statusCode>Success</statusCode></response></ResponseDoc>"
        ).encode(),
        status=200,
        content_type="application/xml",
    )

    res = make_service().send_client(
        {"vehicleRegistrationNumber": PLATE, "branch": 0, "clientServiceType": 3}
    )

    assert res.get("idDcl") == "4400000001"
    assert len(responses.calls) == 2


@responses.activate
def test_http_500_is_indeterminate_not_retried():
    """Το αίτημα έφτασε στην ΑΑΔΕ — μπορεί να καταχωρήθηκε πριν σκάσει."""
    responses.add(responses.POST, SEND_URL, status=500, body="boom")

    res = make_service().send_client(
        {"vehicleRegistrationNumber": PLATE, "branch": 0, "clientServiceType": 3}
    )

    assert res.get("indeterminate") is True
    assert len(responses.calls) == 1


@responses.activate
def test_unparseable_200_response_is_indeterminate():
    """HTTP 200 σημαίνει ότι η ΑΑΔΕ ΔΕΧΤΗΚΕ το αίτημα, ό,τι κι αν απάντησε."""
    responses.add(responses.POST, SEND_URL, status=200, body=b"<not-xml")

    res = make_service().send_client(
        {"vehicleRegistrationNumber": PLATE, "branch": 0, "clientServiceType": 3}
    )

    assert res.get("indeterminate") is True


@responses.activate
def test_request_clients_still_retries_on_read_timeout():
    """
    Το GET είναι idempotent (δεν αλλάζει τίποτα στην ΑΑΔΕ) — εκεί το retry
    πρέπει να παραμείνει, αλλιώς χαλάει ο ίδιος ο έλεγχος διπλοεγγραφής.
    """
    url = f"{BASE_URL}/RequestClients"
    responses.add(responses.GET, url, body=requests.ReadTimeout("timed out"))
    responses.add(
        responses.GET,
        url,
        status=200,
        body=b"<RequestedDoc></RequestedDoc>",
        content_type="application/xml",
    )

    res = make_service().request_clients(dclid=1)

    assert "error" not in res
    assert len(responses.calls) == 2


# ====================================================================
# 2) Επίπεδο ροής — «Επαναποστολή» δεν πρέπει ΠΟΤΕ να διπλασιάζει
# ====================================================================
class FakeAade:
    """
    Fake υπηρεσία ΑΑΔΕ με ΤΟ ΙΔΙΟ interface (mock_aade/real_aade). Μετράει
    κλήσεις ώστε τα τεστ να αποδεικνύουν ότι ΔΕΝ στάλθηκε δεύτερη εγγραφή.
    """

    def __init__(self, send_result=None, clients=None, correlations=None):
        self.send_result = send_result or {}
        self.clients = clients or []
        self.correlations = correlations or []
        self.send_calls = 0
        self.update_calls = 0
        self.correlate_calls = 0
        self.request_calls = 0

    def send_client(self, data):
        self.send_calls += 1
        return self.send_result

    def update_client(self, id_dcl, data):
        self.update_calls += 1
        return {"updateUniqueId": "1"}

    def client_correlations(self, id_dcl, data):
        self.correlate_calls += 1
        return {"correlateId": "9"}

    def cancel_client(self, id_dcl, entity_vat=None):
        return {"cancellationId": "8"}

    def request_clients(self, dclid, max_dclid=None, entity_vat=None,
                        continuation_token=None):
        self.request_calls += 1
        return {
            "entityVatNumber": None,
            "continuationToken": None,
            "clients": self.clients,
            "updates": [],
            "correlations": self.correlations,
            "cancellations": [],
        }


def aade_client_record(id_dcl, plate, created=None, completion=False):
    """Μία εγγραφή όπως τη γυρνά το _parse_requested_doc του real_aade."""
    created = created or datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "InitialClientData": {
            "idDcl": id_dcl,
            "creationDateTime": created.isoformat(),
            "branch": "0",
            "clientServiceType": "3",
            "useCase": {"garage": {"vehicleRegistrationNumber": plate}},
        },
        "UpdatedClientData": {
            "entryCompletion": "true" if completion else "false",
        },
    }


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def headers(client):
    res = client.post(
        "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    if res.status_code != 200:
        res = client.post(
            "/api/auth/register",
            json={
                "name": "Idempotency Test Workshop",
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
                "businessType": "garage",
                "termsAccepted": True,
            },
        )
    h = {"Authorization": f"Bearer {res.get_json()['accessToken']}"}
    # Κωδικοί ΑΑΔΕ — χωρίς αυτούς το _require_credentials μπλοκάρει τη ροή.
    client.put(
        "/api/settings",
        json={
            "aade_username": "testuser",
            "aade_subscription_key": "testkey",
            "branch": 0,
        },
        headers=h,
    )
    return h


@pytest.fixture
def real_mode():
    """
    Οι έλεγχοι διπλοεγγραφής έχουν νόημα ΜΟΝΟ εκτός mock — στο mock δεν
    υπάρχει πραγματική κατάσταση στην ΑΑΔΕ για να ελεγχθεί.
    """
    previous = app.config.get("USE_MOCK_AADE")
    app.config["USE_MOCK_AADE"] = False
    yield
    app.config["USE_MOCK_AADE"] = previous


@pytest.fixture
def fake_aade(monkeypatch):
    """Αντικαθιστά το _build_aade ώστε να ελέγχουμε πλήρως τις απαντήσεις."""
    holder = {}

    def install(service):
        holder["svc"] = service
        monkeypatch.setattr(app_module, "_build_aade", lambda settings: service)
        return service

    yield install


@pytest.fixture(autouse=True)
def cleanup_entries():
    """Καθαρίζει ό,τι έφτιαξε το test ώστε να μη μολύνεται η dev βάση."""
    yield
    with app.app_context():
        entries = DclEntry.query.filter_by(plate=PLATE).all()
        ids = [e.id for e in entries]
        if ids:
            AadeLog.query.filter(AadeLog.dcl_entry_id.in_(ids)).delete(
                synchronize_session=False
            )
            DclEntry.query.filter(DclEntry.id.in_(ids)).delete(
                synchronize_session=False
            )
        Customer.query.filter_by(plate=PLATE).delete(synchronize_session=False)
        db.session.commit()


def create_indeterminate_entry(client, headers, fake_aade):
    """1ος Χρόνος που έμεινε σε άγνωστη κατάσταση (read timeout)."""
    svc = fake_aade(
        FakeAade(send_result={"error": "timeout", "indeterminate": True})
    )
    res = client.post("/api/dcl/entry", json={"plate": PLATE}, headers=headers)
    assert res.status_code == 502
    with app.app_context():
        entry = DclEntry.query.filter_by(plate=PLATE).order_by(
            DclEntry.id.desc()
        ).first()
        return entry.id, svc


def test_indeterminate_send_marks_entry_and_blocks_resend(
    client, headers, real_mode, fake_aade
):
    """
    Η καρδιά του θέματος: μετά από αποστολή άγνωστης έκβασης, η
    «Επαναποστολή» ΠΡΕΠΕΙ να μπλοκάρεται — αλλιώς δημιουργεί δεύτερη
    εγγραφή στο Ψηφιακό Πελατολόγιο.
    """
    entry_id, svc = create_indeterminate_entry(client, headers, fake_aade)

    with app.app_context():
        entry = db.session.get(DclEntry, entry_id)
        assert entry.aade_state == "indeterminate"
        assert entry.aade_pending_method == "entry"
        assert entry.id_dcl is None

    res = client.post(f"/api/dcl/entries/{entry_id}/resend", headers=headers)

    assert res.status_code == 409
    assert "Έλεγχος στην ΑΑΔΕ" in res.get_json()["error"]
    assert svc.send_calls == 1  # ΔΕΝ στάλθηκε δεύτερη φορά


def test_verify_adopts_existing_aade_record_instead_of_duplicating(
    client, headers, real_mode, fake_aade
):
    """
    Το SendClient ΕΙΧΕ πετύχει, απλώς χάθηκε η απάντηση. Ο έλεγχος πρέπει να
    βρει την εγγραφή στην ΑΑΔΕ και να τη ΣΥΝΔΕΣΕΙ, όχι να στείλει νέα.
    """
    entry_id, _ = create_indeterminate_entry(client, headers, fake_aade)

    svc = fake_aade(
        FakeAade(clients=[aade_client_record("4400000123", PLATE)])
    )
    res = client.post(f"/api/dcl/entries/{entry_id}/verify", headers=headers)

    assert res.status_code == 200
    body = res.get_json()
    assert body["verification"] == "adopted"
    assert body["idDcl"] == "4400000123"
    assert body["aadeState"] is None
    assert svc.send_calls == 0  # ΚΑΜΙΑ νέα εγγραφή στην ΑΑΔΕ


def test_verify_not_found_unblocks_resend(client, headers, real_mode, fake_aade):
    """
    Αν η ΑΑΔΕ δεν έχει τίποτα, η επαναποστολή είναι ασφαλής και πρέπει να
    ξεμπλοκάρει — αλλιώς η εγγραφή θα έμενε κολλημένη για πάντα.
    """
    entry_id, _ = create_indeterminate_entry(client, headers, fake_aade)

    fake_aade(FakeAade(clients=[]))
    res = client.post(f"/api/dcl/entries/{entry_id}/verify", headers=headers)
    assert res.get_json()["verification"] == "not_found"

    svc = fake_aade(FakeAade(send_result={"idDcl": "77", "creationDateTime": "x"}))
    res = client.post(f"/api/dcl/entries/{entry_id}/resend", headers=headers)

    assert res.status_code == 200
    assert res.get_json()["idDcl"] == "77"
    assert svc.send_calls == 1


def test_verify_ignores_dclid_already_used_by_another_entry(
    client, headers, real_mode, fake_aade
):
    """
    Η αναζήτηση ορφανής εγγραφής δεν επιτρέπεται να «υιοθετήσει» idDcl που
    ανήκει ήδη σε άλλη τοπική εγγραφή — θα δημιουργούσε δύο τοπικές εγγραφές
    που δείχνουν στην ΙΔΙΑ εγγραφή της ΑΑΔΕ.
    """
    fake_aade(FakeAade(send_result={"idDcl": "4400000900", "creationDateTime": "x"}))
    first = client.post("/api/dcl/entry", json={"plate": PLATE}, headers=headers)
    assert first.status_code == 201

    entry_id, _ = create_indeterminate_entry(client, headers, fake_aade)

    # Η ΑΑΔΕ γυρνά ΜΟΝΟ την ήδη γνωστή εγγραφή.
    fake_aade(FakeAade(clients=[aade_client_record("4400000900", PLATE)]))
    res = client.post(f"/api/dcl/entries/{entry_id}/verify", headers=headers)

    assert res.get_json()["verification"] == "not_found"


def test_resend_skips_call_when_aade_already_has_correlation(
    client, headers, real_mode, fake_aade
):
    """
    Ο 4ος Χρόνος είχε φτάσει στην ΑΑΔΕ αλλά όχι η απάντηση. Η επαναποστολή
    πρέπει να το ανακαλύψει και να συγχρονιστεί, όχι να στείλει δεύτερη
    συσχέτιση ΜΑΡΚ.
    """
    with app.app_context():
        entry = DclEntry(
            workshop_id=_workshop_id_from(client, headers),
            plate=PLATE,
            branch=0,
            client_service_type=3,
            id_dcl="4400000555",
            status="completed",
            mark="400001234567890",
            entry_completion=True,
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id
        assert entry.pending_action == "correlate"

    svc = fake_aade(
        FakeAade(
            clients=[aade_client_record("4400000555", PLATE, completion=True)],
            correlations=[
                {
                    "correlatedDCLids": ["4400000555"],
                    "mark": "400001234567890",
                    "correlateId": "6600000777",
                }
            ],
        )
    )
    res = client.post(f"/api/dcl/entries/{entry_id}/resend", headers=headers)

    assert res.status_code == 200
    body = res.get_json()
    assert body["resendResult"] == "already_recorded"
    assert body["correlateId"] == "6600000777"
    assert body["status"] == "correlated"
    assert svc.correlate_calls == 0  # ΚΑΜΙΑ δεύτερη συσχέτιση


def _workshop_id_from(client, headers):
    return client.get("/api/auth/me", headers=headers).get_json()["id"]


def test_resend_still_works_when_aade_has_nothing(
    client, headers, real_mode, fake_aade
):
    """Regression: ο νέος έλεγχος δεν πρέπει να σπάσει τη νόμιμη επαναποστολή."""
    with app.app_context():
        entry = DclEntry(
            workshop_id=_workshop_id_from(client, headers),
            plate=PLATE,
            branch=0,
            client_service_type=3,
            id_dcl="4400000556",
            status="completed",
            mark="400009999999999",
            entry_completion=True,
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    svc = fake_aade(FakeAade(clients=[], correlations=[]))
    res = client.post(f"/api/dcl/entries/{entry_id}/resend", headers=headers)

    assert res.status_code == 200
    assert res.get_json()["resendResult"] == "sent"
    assert svc.correlate_calls == 1
