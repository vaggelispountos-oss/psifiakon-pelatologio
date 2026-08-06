"""
migrate_encrypt_settings.py
Μία φορά, μετά το deploy της κρυπτογράφησης (models.py): οι ήδη αποθηκευμένες
τιμές aade_subscription_key είναι plaintext (γράφτηκαν πριν το crypto.py) —
αυτό το script τις διαβάζει, τις κρυπτογραφεί, και τις ξαναγράφει στη θέση
τους. Idempotent: τιμές που είναι ήδη έγκυρο Fernet token (ξανατρέχεις χωρίς
βλάβη) παραμένουν όπως είναι.

Χρήση:
    cd backend && python migrate_encrypt_settings.py
"""
from cryptography.fernet import InvalidToken

import crypto
from app import create_app
from models import Settings, db


def main():
    app = create_app()
    with app.app_context():
        rows = Settings.query.all()
        migrated = 0
        for row in rows:
            raw = row._aade_subscription_key_enc
            if not raw:
                continue
            try:
                crypto._get_fernet().decrypt(raw.encode())
                continue  # ήδη κρυπτογραφημένο, τίποτα να κάνουμε
            except (InvalidToken, ValueError):
                pass  # plaintext legacy value -> κρυπτογράφησε
            row._aade_subscription_key_enc = crypto.encrypt(raw)
            migrated += 1
        db.session.commit()
        print(f"{migrated} από {len(rows)} settings rows κρυπτογραφήθηκαν.")


if __name__ == "__main__":
    main()
