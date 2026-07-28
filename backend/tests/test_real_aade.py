"""
test_real_aade.py
--------------------------------------------------------------------
Unit tests για το real_aade.py. Κάνουν mock το HTTP layer (responses)
ώστε να ΜΗΝ χτυπάμε την πραγματική ΑΑΔΕ. Επιβεβαιώνουν:
  - ότι το XML χτίζεται σωστά και περνά XSD validation
  - ότι το parsing του ResponseDoc (Success/ValidationError/401) δουλεύει
  - ότι ελέγχεται ΠΑΝΤΑ το statusCode μέσα στο XML (όχι μόνο το HTTP 200)

Τρέξιμο:
    ./venv/bin/python -m pytest tests/ -v
--------------------------------------------------------------------
"""
import os
import sys

import responses
from lxml import etree

# Πρόσβαση στο real_aade από τον γονικό φάκελο (backend/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from real_aade import (  # noqa: E402
    EP_CORRELATE,
    EP_SEND,
    EP_UPDATE,
    RealAadeService,
)

BASE_URL = "https://mydataapidev.aade.gr/DCL"


def make_service():
    return RealAadeService(
        username="test_user",
        subscription_key="test_key",
        branch=0,
        base_url=BASE_URL,
    )


def resp_doc(inner):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<ResponseDoc><response>" + inner + "</response></ResponseDoc>"
    ).encode("utf-8")


SUCCESS_SEND = resp_doc("<index>1</index><newClientDclID>4400000001</newClientDclID>"
                        "<statusCode>Success</statusCode>")
SUCCESS_UPDATE = resp_doc("<index>1</index><updatedClientDclID>5500000002</updatedClientDclID>"
                          "<statusCode>Success</statusCode>")
SUCCESS_CORRELATE = resp_doc("<index>1</index><correlateId>6600000003</correlateId>"
                             "<statusCode>Success</statusCode>")
SUCCESS_CANCEL = resp_doc("<index>1</index><cancellationID>7700000004</cancellationID>"
                          "<statusCode>Success</statusCode>")
VALIDATION_ERROR = resp_doc(
    "<index>1</index><errors><error><message>branch is mandatory</message>"
    "<code>203</code></error></errors><statusCode>ValidationError</statusCode>"
)


# ====================================================================
# 1) XML build + XSD validation (χωρίς HTTP)
# ====================================================================
def test_send_client_xml_is_xsd_valid():
    svc = make_service()
    root = svc._build_send_client_xml(
        {"vehicleRegistrationNumber": "ABG-1234", "branch": 0, "clientServiceType": 3}
    )
    assert svc._validate(EP_SEND, root) is None
    # namespace + structure
    assert root.tag == "{http://www.aade.gr/myDATA/dcrnew/v1.0}NewDigitalClientDoc"
    xml = etree.tostring(root).decode()
    assert "garage" in xml and "vehicleRegistrationNumber" in xml


def test_update_client_2nd_time_xsd_valid_and_has_category():
    svc = make_service()
    root = svc._build_update_client_xml(
        4400000001, {"providedServiceCategory": 1, "clientServiceType": 3}
    )
    assert svc._validate(EP_UPDATE, root) is None
    xml = etree.tostring(root).decode()
    assert "initialDclId" in xml and "providedServiceCategory" in xml


def test_update_client_3rd_time_resends_category():
    """3ος Χρόνος: το providedServiceCategory ΠΡΕΠΕΙ να ξαναστέλνεται."""
    svc = make_service()
    root = svc._build_update_client_xml(
        4400000001,
        {
            "entryCompletion": True,
            "providedServiceCategory": 1,
            "invoiceKind": 1,
            "clientServiceType": 3,
        },
    )
    assert svc._validate(EP_UPDATE, root) is None
    xml = etree.tostring(root).decode()
    assert "entryCompletion" in xml
    assert "providedServiceCategory" in xml  # ξαναστέλνεται
    assert "invoiceKind" in xml


def test_correlation_xml_xsd_valid():
    svc = make_service()
    root = svc._build_correlation_xml(4400000001, {"mark": "400001234567890"})
    assert svc._validate(EP_CORRELATE, root) is None
    xml = etree.tostring(root).decode()
    assert "mark" in xml and "correlatedDCLids" in xml


def test_category_5_includes_other():
    svc = make_service()
    root = svc._build_update_client_xml(
        1, {"providedServiceCategory": 5, "providedServiceCategoryOther": "Ειδική εργασία"}
    )
    xml = etree.tostring(root, encoding="unicode")
    assert "providedServiceCategoryOther" in xml


# ====================================================================
# 2) HTTP mocked — Success paths
# ====================================================================
@responses.activate
def test_send_client_success():
    responses.add(responses.POST, BASE_URL + "/SendClient",
                  body=SUCCESS_SEND, status=200, content_type="application/xml")
    svc = make_service()
    res = svc.send_client({"vehicleRegistrationNumber": "ABG-1234", "branch": 0})
    assert res.get("idDcl") == "4400000001"
    assert "creationDateTime" in res
    assert "error" not in res
    # έστειλε application/xml
    assert responses.calls[0].request.headers["Content-Type"] == "application/xml"
    assert responses.calls[0].request.headers["aade-user-id"] == "test_user"


@responses.activate
def test_update_client_success_with_completion():
    responses.add(responses.POST, BASE_URL + "/UpdateClient",
                  body=SUCCESS_UPDATE, status=200)
    svc = make_service()
    res = svc.update_client(4400000001, {
        "entryCompletion": True, "providedServiceCategory": 1, "invoiceKind": 1,
    })
    assert res.get("updateUniqueId") == "5500000002"
    assert "completionDateTime" in res


@responses.activate
def test_correlation_success():
    responses.add(responses.POST, BASE_URL + "/ClientCorrelations",
                  body=SUCCESS_CORRELATE, status=200)
    svc = make_service()
    res = svc.client_correlations(4400000001, {"mark": "400001234567890"})
    assert res.get("correlateId") == "6600000003"


@responses.activate
def test_cancel_success_uses_url_params_no_body():
    responses.add(responses.POST, BASE_URL + "/CancelClient",
                  body=SUCCESS_CANCEL, status=200)
    svc = make_service()
    res = svc.cancel_client(4400000001)
    assert res.get("cancellationId") == "7700000004"
    # params στο URL, ΧΩΡΙΣ xml body
    assert "DCLID=4400000001" in responses.calls[0].request.url
    assert not responses.calls[0].request.body


# ====================================================================
# 3) Επιχειρησιακά σφάλματα (HTTP 200 αλλά ValidationError μέσα στο XML)
# ====================================================================
@responses.activate
def test_validation_error_is_not_treated_as_success():
    responses.add(responses.POST, BASE_URL + "/SendClient",
                  body=VALIDATION_ERROR, status=200)
    svc = make_service()
    res = svc.send_client({"vehicleRegistrationNumber": "ABG-1234", "branch": 0})
    # ⚠️ ΔΕΝ πρέπει να θεωρηθεί επιτυχία παρότι HTTP=200
    assert "idDcl" not in res
    assert "error" in res
    assert res["statusCode"] == "ValidationError"
    assert res["errors"][0]["code"] == "203"
    assert "branch is mandatory" in res["error"]


# ====================================================================
# 4) Τεχνικά σφάλματα (HTTP status)
# ====================================================================
@responses.activate
def test_401_returns_clear_credentials_message():
    responses.add(responses.POST, BASE_URL + "/SendClient", status=401)
    svc = make_service()
    res = svc.send_client({"vehicleRegistrationNumber": "ABG-1234", "branch": 0})
    assert "error" in res
    assert "Λάθος κωδικοί ΑΑΔΕ" in res["error"]


@responses.activate
def test_500_returns_technical_error():
    responses.add(responses.POST, BASE_URL + "/SendClient", status=500)
    svc = make_service()
    res = svc.send_client({"vehicleRegistrationNumber": "ABG-1234", "branch": 0})
    assert "error" in res
    assert "Τεχνικό σφάλμα" in res["error"]


# ====================================================================
# 5) RequestClients — πλήρες parsing του RequestedDoc
# ====================================================================
REQUESTED_DOC = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<RequestedDoc xmlns="http://www.aade.gr/myDATA/dcr/v1.0">'
    "<continuationToken>tok-123</continuationToken>"
    "<entityVatNumber>123456789</entityVatNumber>"
    "<clientsDoc><DigitalClient>"
    "<InitialClientData><idDcl>4400000001</idDcl>"
    "<clientServiceType>3</clientServiceType>"
    "<creationDateTime>2026-07-27T10:00:00</creationDateTime>"
    "<useCase><garage><vehicleRegistrationNumber>ABG-1234</vehicleRegistrationNumber>"
    "</garage></useCase></InitialClientData>"
    "<UpdatedClientData><updateUniqueId>55</updateUniqueId>"
    "<entryCompletion>true</entryCompletion>"
    "<providedServiceCategory>1</providedServiceCategory>"
    "<completionDateTime>2026-07-27T11:30:00</completionDateTime></UpdatedClientData>"
    "</DigitalClient></clientsDoc>"
    "</RequestedDoc>"
).encode("utf-8")


@responses.activate
def test_request_clients_full_parse():
    responses.add(responses.GET, BASE_URL + "/RequestClients",
                  body=REQUESTED_DOC, status=200)
    svc = make_service()
    res = svc.request_clients(dclid=4400000001)
    assert "error" not in res
    assert res["entityVatNumber"] == "123456789"
    assert res["continuationToken"] == "tok-123"
    assert len(res["clients"]) == 1
    client = res["clients"][0]
    init = client["InitialClientData"]
    assert init["idDcl"] == "4400000001"
    assert init["creationDateTime"] == "2026-07-27T10:00:00"
    # nested useCase>garage
    assert init["useCase"]["garage"]["vehicleRegistrationNumber"] == "ABG-1234"
    upd = client["UpdatedClientData"]
    assert upd["completionDateTime"] == "2026-07-27T11:30:00"
    assert upd["providedServiceCategory"] == "1"
