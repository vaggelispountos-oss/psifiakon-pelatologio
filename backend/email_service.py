"""
email_service.py
--------------------------------------------------------------------
Αποστολή email μέσω του REST API του Resend (https://resend.com) — απλή
POST κλήση με το requests που ήδη υπάρχει, χωρίς επιπλέον dependency.

Χρησιμοποιείται ΜΟΝΟ για την επαναφορά κωδικού (auth.py) — σε αντίθεση με
την τηλεμετρία OCR, εδώ ΘΕΛΟΥΜΕ να ξέρουμε αν απέτυχε η αποστολή (log error),
αλλά ο caller πάντα επιστρέφει το ίδιο γενικό μήνυμα στον χρήστη ώστε να μη
διαρρέει αν υπάρχει λογαριασμός με το email.

Χωρίς RESEND_API_KEY (π.χ. τοπικό dev πριν ρυθμιστεί λογαριασμός Resend), ΔΕΝ
στέλνεται πραγματικό email — καταγράφεται το περιεχόμενο (με το link) στο log
ώστε η ροή forgot/reset-password να δοκιμάζεται πλήρως τοπικά.
"""
import requests
from flask import current_app

RESEND_URL = "https://api.resend.com/emails"


def send_email(to, subject, html):
    api_key = current_app.config.get("RESEND_API_KEY")
    if not api_key:
        current_app.logger.info(
            "RESEND_API_KEY δεν έχει ρυθμιστεί — email ΔΕΝ στάλθηκε.\n"
            "Προς: %s\nΘέμα: %s\n%s",
            to,
            subject,
            html,
        )
        return

    try:
        resp = requests.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": current_app.config["RESEND_FROM_EMAIL"],
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )
        if resp.status_code >= 300:
            current_app.logger.error(
                "Αποστολή email απέτυχε (HTTP %d): %s", resp.status_code, resp.text[:300]
            )
    except requests.RequestException as exc:
        current_app.logger.error("Αποστολή email απέτυχε (δίκτυο): %s", exc)
