"""
real_aade.py
--------------------------------------------------------------------
ΠΡΑΓΜΑΤΙΚΗ σύνδεση με το API Ψηφιακού Πελατολογίου της ΑΑΔΕ (myDATA DCL).

⚠️ Έχει ΑΚΡΙΒΩΣ το ίδιο interface με το mock_aade.py (ίδια ονόματα μεθόδων,
ίδιες παράμετροι, ίδια μορφή επιστρεφόμενου dict), ώστε να εναλλάσσονται με
το env USE_MOCK_AADE χωρίς καμία αλλαγή στη λογική των 4 Χρόνων στο app.py.

Η μεταφορά είναι **XML** (όχι JSON): χτίζουμε XML σύμφωνο με τα επίσημα XSD
(backend/aade_specs/DCL_v1_1/), κάνουμε validation, και διαβάζουμε το
ResponseDoc της απάντησης.

Δομή (ώστε αν αλλάξει το schema, π.χ. v1.2, να αλλάζουν μόνο τα build/parse):
    _build_send_client_xml / _build_update_client_xml / _build_correlation_xml
    _post_xml (κοινή HTTPS κλήση + headers + retries)
    _parse_response (κοινό parsing ResponseDoc + statusCode/errors)
--------------------------------------------------------------------
"""
import os
from datetime import datetime, timezone

import requests
from lxml import etree

# --------------------------------------------------------------------
# Namespaces (από τα targetNamespace των επίσημων XSD v1.1)
# ΠΡΟΣΟΧΗ: το dcrudt είναι https://, τα υπόλοιπα http://
# --------------------------------------------------------------------
NS_NEW = "http://www.aade.gr/myDATA/dcrnew/v1.0"       # SendClient
NS_UPD = "https://www.aade.gr/myDATA/dcrudt/v1.0"      # UpdateClient
NS_COR = "http://www.aade.gr/myDATA/dcrudtcor/v1.0"    # ClientCorrelations
XSI = "http://www.w3.org/2001/XMLSchema-instance"

# Endpoint paths (σχετικά με το base_url, π.χ. https://mydataapidev.aade.gr/DCL/)
EP_SEND = "SendClient"
EP_UPDATE = "UpdateClient"
EP_CORRELATE = "ClientCorrelations"
EP_CANCEL = "CancelClient"
EP_REQUEST = "RequestClients"

# XSD αρχεία (root schemas — τα υπόλοιπα φορτώνονται μέσω xs:include)
DEFAULT_SPEC_DIR = os.path.join(os.path.dirname(__file__), "aade_specs", "DCL_v1_1")
SCHEMA_FILES = {
    EP_SEND: "SendClient-v1.1.xsd",
    EP_UPDATE: "updateClient-v1.1.xsd",
    EP_CORRELATE: "clientCorrelations-v1.1.xsd",
}


def _utc_now_iso():
    """UTC σε μορφή yyyy-MM-ddTHH:mm:ssZ (όπως θέλει η ΑΑΔΕ)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _el(parent, ns, tag, text=None):
    """Δημιουργεί qualified υποστοιχείο (elementFormDefault=qualified)."""
    e = etree.SubElement(parent, "{%s}%s" % (ns, tag))
    if text is not None:
        e.text = str(text)
    return e


def _localname(tag):
    if not isinstance(tag, str):
        return ""
    return etree.QName(tag).localname


def _elem_to_dict(elem):
    """
    Γενικό XML->dict (namespace-agnostic). Leaf -> string· με παιδιά -> dict.
    Επαναλαμβανόμενα ονόματα (π.χ. correlatedDCLids) -> λίστα.
    """
    children = [c for c in elem if isinstance(c.tag, str)]
    if not children:
        return (elem.text or "").strip()
    out = {}
    for c in children:
        name = _localname(c.tag)
        val = _elem_to_dict(c)
        if name in out:
            if not isinstance(out[name], list):
                out[name] = [out[name]]
            out[name].append(val)
        else:
            out[name] = val
    return out


class RealAadeService:
    """Πραγματική υπηρεσία ΑΑΔΕ (Ψηφιακό Πελατολόγιο)."""

    def __init__(
        self,
        username=None,
        subscription_key=None,
        branch=0,
        entity_vat_number=None,
        base_url=None,
        spec_dir=None,
        timeout=30,
        retries=2,
    ):
        self.username = username
        self.subscription_key = subscription_key
        self.branch = branch
        self.entity_vat_number = entity_vat_number
        self.base_url = (base_url or "https://mydataapidev.aade.gr/DCL/").rstrip("/")
        self.spec_dir = spec_dir or DEFAULT_SPEC_DIR
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self._schema_cache = {}

    # ================================================================
    # HTTP layer
    # ================================================================
    def _headers(self):
        # Τα credentials μπαίνουν στα headers ΚΑΘΕ κλήσης (ταυτοποίηση).
        return {
            "aade-user-id": self.username or "",
            "ocp-apim-subscription-key": self.subscription_key or "",
            "Content-Type": "application/xml",
        }

    def _handle_http(self, resp):
        """
        Χειρισμός ΤΕΧΝΙΚΩΝ σφαλμάτων (HTTP status). Επιστρέφει είτε
        {"error": ...} (τεχνικό), είτε το normalized parse του ResponseDoc.
        """
        if resp.status_code == 401:
            return {"error": "Λάθος κωδικοί ΑΑΔΕ (401) — έλεγξε το Όνομα "
                             "Χρήστη και το Subscription Key στις Ρυθμίσεις."}
        if resp.status_code == 400:
            return {"error": "Σφάλμα αιτήματος προς ΑΑΔΕ (400): %s"
                             % (resp.text or "")[:300]}
        if resp.status_code != 200:
            return {"error": "Τεχνικό σφάλμα ΑΑΔΕ (HTTP %d)." % resp.status_code}
        # HTTP 200 -> τα ΕΠΙΧΕΙΡΗΣΙΑΚΑ σφάλματα κρύβονται ΜΕΣΑ στο XML
        return self._parse_response(resp.content)

    def _post_xml(self, path, xml_bytes, params=None):
        """Κοινή POST κλήση με retries για δικτυακά σφάλματα."""
        url = "%s/%s" % (self.base_url, path)
        last_exc = None
        for _ in range(self.retries):
            try:
                resp = requests.post(
                    url,
                    data=xml_bytes,
                    params=params,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                return self._handle_http(resp)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                continue
        return {"error": "Δικτυακό σφάλμα επικοινωνίας με ΑΑΔΕ: %s" % last_exc}

    def _get(self, path, params=None):
        url = "%s/%s" % (self.base_url, path)
        last_exc = None
        for _ in range(self.retries):
            try:
                resp = requests.get(
                    url, params=params, headers=self._headers(), timeout=self.timeout
                )
                if resp.status_code == 401:
                    return {"error": "Λάθος κωδικοί ΑΑΔΕ (401)."}
                if resp.status_code != 200:
                    return {"error": "Τεχνικό σφάλμα ΑΑΔΕ (HTTP %d)." % resp.status_code}
                return {"raw_xml": resp.text, "content": resp.content}
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                continue
        return {"error": "Δικτυακό σφάλμα επικοινωνίας με ΑΑΔΕ: %s" % last_exc}

    # ================================================================
    # XSD validation
    # ================================================================
    def _get_schema(self, path):
        if path in self._schema_cache:
            return self._schema_cache[path]
        fname = SCHEMA_FILES.get(path)
        if not fname:
            return None
        full = os.path.join(self.spec_dir, fname)
        if not os.path.exists(full):
            # Χωρίς XSD -> προχωράμε χωρίς validation (με προειδοποίηση).
            self._schema_cache[path] = None
            return None
        schema = etree.XMLSchema(etree.parse(full))
        self._schema_cache[path] = schema
        return schema

    def _validate(self, path, root):
        """
        Validation του XML πάνω στο XSD ΠΡΙΝ την αποστολή.
        Επιστρέφει None αν ΟΚ, αλλιώς string με το σφάλμα.
        """
        schema = self._get_schema(path)
        if schema is None:
            return None  # δεν βρέθηκε XSD -> skip (δες requirements/aade_specs)
        if not schema.validate(root):
            return "; ".join(str(e.message) for e in schema.error_log)
        return None

    # ================================================================
    # Response parsing (κοινό ResponseDoc parsing — namespace-agnostic)
    # ================================================================
    def _parse_response(self, content):
        """
        Parse του ResponseDoc. Επιστρέφει normalized dict του ΠΡΩΤΟΥ response
        item (οι κλήσεις μας αφορούν μία οντότητα):
            {"statusCode": ..., "newClientDclID": ..., "updatedClientDclID": ...,
             "cancellationID": ..., "correlateId": ..., "errors": [...]}
        Σε αποτυχία parsing επιστρέφει {"error": ...}.
        """
        try:
            root = etree.fromstring(content)
        except etree.XMLSyntaxError as exc:
            return {"error": "Μη έγκυρο XML απάντησης από ΑΑΔΕ: %s" % exc}

        # Βρες το πρώτο <response> (ανεξαρτήτως namespace)
        responses = [c for c in root.iter() if _localname(c.tag) == "response"]
        if not responses:
            return {"error": "Η απάντηση ΑΑΔΕ δεν περιέχει στοιχείο <response>."}

        resp = responses[0]
        out = {"errors": []}
        for child in resp:
            name = _localname(child.tag)
            if name == "errors":
                for err in child:
                    if _localname(err.tag) != "error":
                        continue
                    e = {"message": None, "code": None}
                    for sub in err:
                        e[_localname(sub.tag)] = (sub.text or "").strip()
                    out["errors"].append(e)
            elif name in (
                "index",
                "newClientDclID",
                "updatedClientDclID",
                "cancellationID",
                "correlateId",
                "statusCode",
            ):
                out[name] = (child.text or "").strip()
        return out

    def _business_error(self, parsed):
        """Μορφοποίηση ΕΠΙΧΕΙΡΗΣΙΑΚΟΥ σφάλματος (statusCode != Success)."""
        errs = parsed.get("errors") or []
        if errs:
            msg = "; ".join(
                "%s: %s" % (e.get("code"), e.get("message")) for e in errs
            )
        else:
            msg = "statusCode=%s" % parsed.get("statusCode")
        return {
            "error": "ΑΑΔΕ σφάλμα — " + msg,
            "errors": errs,
            "statusCode": parsed.get("statusCode"),
        }

    def _finish(self, parsed, success_builder):
        """
        Κοινός χειρισμός: αν parsed έχει τεχνικό error -> επίστρεψέ το.
        Αλλιώς έλεγξε ΠΑΝΤΑ το statusCode (ΟΧΙ μόνο το HTTP 200).
        """
        if "error" in parsed:
            return parsed  # τεχνικό / δικτυακό / XML syntax
        if parsed.get("statusCode") == "Success":
            return success_builder(parsed)
        return self._business_error(parsed)

    # ================================================================
    # XML builders
    # ================================================================
    def _build_send_client_xml(self, data):
        """
        1ος Χρόνος — NewDigitalClientDoc > newDigitalClient (garage/Συνεργεία).
        Σειρά πεδίων ΑΚΡΙΒΩΣ κατά το XSD (xs:sequence).
        """
        root = etree.Element(
            "{%s}NewDigitalClientDoc" % NS_NEW, nsmap={"dcrnew": NS_NEW}
        )
        nc = _el(root, NS_NEW, "newDigitalClient")

        # clientServiceType (3 = Συνεργεία)
        _el(nc, NS_NEW, "clientServiceType", data.get("clientServiceType", 3))

        # creationDateTime: ΜΟΝΟ αν transmissionFailure=1 (αλλιώς το βάζει η ΑΑΔΕ)
        transmission_failure = data.get("transmissionFailure")
        if transmission_failure == 1:
            _el(nc, NS_NEW, "creationDateTime", _utc_now_iso())

        # entityVatNumber: μόνο αν διαβιβάζει λογιστής για λογαριασμό πελάτη
        entity_vat = data.get("entityVatNumber") or self.entity_vat_number
        if entity_vat:
            _el(nc, NS_NEW, "entityVatNumber", entity_vat)

        # branch [υποχρεωτικό]
        branch = data.get("branch")
        if branch is None:
            branch = self.branch
        _el(nc, NS_NEW, "branch", int(branch))

        # transmissionFailure (θέση κατά XSD: μετά customerCountry)
        if transmission_failure == 1:
            _el(nc, NS_NEW, "transmissionFailure", 1)

        # comments (max 150)
        comments = data.get("comments")
        if comments:
            _el(nc, NS_NEW, "comments", str(comments)[:150])

        # useCase > garage (GarageType)
        uc = _el(nc, NS_NEW, "useCase")
        garage = _el(uc, NS_NEW, "garage")
        if data.get("vehicleRegistrationNumber"):
            _el(garage, NS_NEW, "vehicleRegistrationNumber",
                str(data["vehicleRegistrationNumber"])[:50])
        if data.get("vehicleCategory"):
            _el(garage, NS_NEW, "vehicleCategory", str(data["vehicleCategory"])[:100])
        if data.get("vehicleFactory"):
            _el(garage, NS_NEW, "vehicleFactory", str(data["vehicleFactory"])[:100])

        return root

    def _build_update_client_xml(self, id_dcl, data):
        """
        2ος & 3ος Χρόνος — UpdateClientDoc > updateClient.
        ⚠️ Για Συνεργεία το providedServiceCategory είναι ΥΠΟΧΡΕΩΤΙΚΟ σε ΚΑΘΕ
        κλήση (και στον 2ο και στον 3ο Χρόνο).
        Σειρά πεδίων ΑΚΡΙΒΩΣ κατά το XSD.
        """
        root = etree.Element(
            "{%s}UpdateClientDoc" % NS_UPD, nsmap={"dcrudt": NS_UPD}
        )
        uc = _el(root, NS_UPD, "updateClient")

        # initialDclId [υποχρεωτικό] + clientServiceType=3 [υποχρεωτικό]
        _el(uc, NS_UPD, "initialDclId", id_dcl)
        _el(uc, NS_UPD, "clientServiceType", data.get("clientServiceType", 3))

        # entryCompletion (3ος Χρόνος)
        if data.get("entryCompletion") is True:
            _el(uc, NS_UPD, "entryCompletion", "true")

        # nonIssueInvoice (όταν δεν εκδίδεται παραστατικό)
        if data.get("nonIssueInvoice") is True:
            _el(uc, NS_UPD, "nonIssueInvoice", "true")

        # providedServiceCategory [ΥΠΟΧΡΕΩΤΙΚΟ για Συνεργεία — κάθε φορά]
        cat = data.get("providedServiceCategory")
        if cat is not None:
            _el(uc, NS_UPD, "providedServiceCategory", int(cat))
            if int(cat) == 5:
                # providedServiceCategoryOther υποχρεωτικό όταν cat=5 (Λοιπά)
                other = data.get("providedServiceCategoryOther")
                if other:
                    _el(uc, NS_UPD, "providedServiceCategoryOther",
                        str(other)[:100])

        # invoiceKind (1/2/3)
        if data.get("invoiceKind") is not None:
            _el(uc, NS_UPD, "invoiceKind", int(data["invoiceKind"]))

        # entityVatNumber (λογιστής)
        entity_vat = data.get("entityVatNumber") or self.entity_vat_number
        if entity_vat:
            _el(uc, NS_UPD, "entityVatNumber", entity_vat)

        # reasonNonIssueType (1/2/3)
        if data.get("reasonNonIssueType") is not None:
            _el(uc, NS_UPD, "reasonNonIssueType", int(data["reasonNonIssueType"]))

        # comments (max 150)
        if data.get("comments"):
            _el(uc, NS_UPD, "comments", str(data["comments"])[:150])

        return root

    def _build_correlation_xml(self, id_dcl, data):
        """
        4ος Χρόνος — ClientCorrelationDoc > clientCorrelation.
        Choice: είτε mark (xs:long) είτε FIM. correlatedDCLids [υποχρεωτικό].
        """
        root = etree.Element(
            "{%s}ClientCorrelationDoc" % NS_COR, nsmap={"dcrudtcor": NS_COR}
        )
        cc = _el(root, NS_COR, "clientCorrelation")

        entity_vat = data.get("entityVatNumber") or self.entity_vat_number
        if entity_vat:
            _el(cc, NS_COR, "entityVatNumber", entity_vat)

        # Choice: mark Ή FIM (ένα από τα δύο)
        fim = data.get("FIM")
        if fim:
            fim_el = _el(cc, NS_COR, "FIM")
            _el(fim_el, NS_COR, "FIMNumber", fim.get("FIMNumber"))
            _el(fim_el, NS_COR, "FIMAA", fim.get("FIMAA"))
            _el(fim_el, NS_COR, "FIMIssueDate", fim.get("FIMIssueDate"))
            _el(fim_el, NS_COR, "FIMIssueTime", fim.get("FIMIssueTime"))
        else:
            # mark είναι xs:long -> πρέπει να είναι ακέραιος
            _el(cc, NS_COR, "mark", str(data.get("mark")))

        # correlatedDCLids [υποχρεωτικό, max 50] — εδώ μία εγγραφή
        _el(cc, NS_COR, "correlatedDCLids", id_dcl)

        return root

    def _serialize(self, root):
        return etree.tostring(
            root, xml_declaration=True, encoding="UTF-8", pretty_print=True
        )

    # ================================================================
    # Public API — ΙΔΙΟ interface με το MockAadeService
    # ================================================================
    def send_client(self, data):
        """1ος Χρόνος — SendClient."""
        if not data.get("vehicleRegistrationNumber"):
            return {"error": "Λείπει το vehicleRegistrationNumber (πινακίδα)."}
        branch = data.get("branch", self.branch)
        if branch is None:
            return {"error": "Λείπει το branch (αριθμός εγκατάστασης)."}

        root = self._build_send_client_xml(data)
        invalid = self._validate(EP_SEND, root)
        if invalid:
            return {"error": "Το XML SendClient δεν περνά XSD validation: %s" % invalid}

        parsed = self._post_xml(EP_SEND, self._serialize(root))
        return self._finish(
            parsed,
            lambda p: {
                "idDcl": str(p.get("newClientDclID")),
                # Η ΑΑΔΕ δεν επιστρέφει creationDateTime στο ResponseDoc·
                # κρατάμε τοπικό UTC (η αυθεντική τιμή αντλείται με RequestClients).
                "creationDateTime": _utc_now_iso(),
            },
        )

    def update_client(self, id_dcl, data):
        """2ος & 3ος Χρόνος — UpdateClient."""
        root = self._build_update_client_xml(id_dcl, data)
        invalid = self._validate(EP_UPDATE, root)
        if invalid:
            return {"error": "Το XML UpdateClient δεν περνά XSD validation: %s"
                             % invalid}

        parsed = self._post_xml(EP_UPDATE, self._serialize(root))

        def _ok(p):
            res = {"updateUniqueId": str(p.get("updatedClientDclID"))}
            # completionDateTime δεν επιστρέφεται από το ResponseDoc·
            # στον 3ο Χρόνο δίνουμε τοπικό UTC (auth. τιμή: RequestClients).
            if data.get("entryCompletion") is True:
                res["completionDateTime"] = _utc_now_iso()
            return res

        return self._finish(parsed, _ok)

    def client_correlations(self, id_dcl, data):
        """4ος Χρόνος — ClientCorrelations."""
        if not data.get("mark") and not data.get("FIM"):
            return {"error": "Απαιτείται mark ή FIM για τη συσχέτιση."}

        root = self._build_correlation_xml(id_dcl, data)
        invalid = self._validate(EP_CORRELATE, root)
        if invalid:
            return {"error": "Το XML ClientCorrelations δεν περνά XSD "
                             "validation: %s" % invalid}

        parsed = self._post_xml(EP_CORRELATE, self._serialize(root))
        return self._finish(
            parsed, lambda p: {"correlateId": str(p.get("correlateId"))}
        )

    def cancel_client(self, id_dcl, entity_vat=None):
        """Ακύρωση — CancelClient (POST ΧΩΡΙΣ xml body, params στο URL)."""
        params = {"DCLID": id_dcl}
        entity_vat = entity_vat or self.entity_vat_number
        if entity_vat:
            params["entityVatNumber"] = entity_vat

        parsed = self._post_xml(EP_CANCEL, xml_bytes=None, params=params)
        return self._finish(
            parsed, lambda p: {"cancellationId": str(p.get("cancellationID"))}
        )

    def request_clients(
        self, dclid, max_dclid=None, entity_vat=None, continuation_token=None
    ):
        """
        Λήψη/έλεγχος — RequestClients (GET). Χρήσιμο για reconciliation/audit:
        επιβεβαίωση ότι όντως καταχωρήθηκαν στην ΑΑΔΕ.
        """
        params = {"DCLID": dclid}
        if max_dclid is not None:
            params["maxdclid"] = max_dclid
        entity_vat = entity_vat or self.entity_vat_number
        if entity_vat:
            params["entityVatNumber"] = entity_vat
        if continuation_token:
            params["continuationToken"] = continuation_token

        res = self._get(EP_REQUEST, params=params)
        if "error" in res:
            return res

        return self._parse_requested_doc(res.get("content"), res.get("raw_xml"))

    def _parse_requested_doc(self, content, raw_xml=None):
        """
        Πλήρες parsing του RequestedDoc σε καθαρή δομή:
            {
              "entityVatNumber": str,
              "continuationToken": str|None,
              "clients": [ {InitialClientData:{...}, UpdatedClientData:{...}}, ... ],
              "updates": [ {...updateClientType...}, ... ],
              "correlations": [ {...clientCorrelationType...}, ... ],
              "cancellations": [ {...CancelledClientType...}, ... ],
            }
        ⚠️ Οι ημερομηνίες (creationDateTime/completionDateTime κ.λπ.) έρχονται σε
        ώρα Ελλάδος (Europe/Athens), ΟΧΙ UTC — τις κρατάμε όπως έρχονται.
        """
        out = {
            "entityVatNumber": None,
            "continuationToken": None,
            "clients": [],
            "updates": [],
            "correlations": [],
            "cancellations": [],
            "raw_xml": raw_xml,
        }
        if not content:
            return out
        try:
            root = etree.fromstring(content)
        except etree.XMLSyntaxError as exc:
            return {"error": "Μη έγκυρο XML RequestedDoc: %s" % exc}

        for c in root:
            name = _localname(c.tag)
            if name == "continuationToken":
                out["continuationToken"] = (c.text or "").strip()
            elif name == "entityVatNumber":
                out["entityVatNumber"] = (c.text or "").strip()
            elif name == "clientsDoc":
                out["clients"] = [_elem_to_dict(x) for x in c]
            elif name == "updateclientRequestsDoc":
                out["updates"] = [_elem_to_dict(x) for x in c]
            elif name == "clientcorrelationsRequestsDoc":
                out["correlations"] = [_elem_to_dict(x) for x in c]
            elif name == "cancelClientRequestsDoc":
                out["cancellations"] = [_elem_to_dict(x) for x in c]
        return out
