"""
crypto.py
Κρυπτογράφηση ευαίσθητων στηλών στη βάση (π.χ. Settings.aade_subscription_key)
με Fernet (symmetric, AES128-CBC + HMAC). Το κλειδί έρχεται από
Config.ENCRYPTION_KEY (.env). Αν λείπει (μόνο dev), παράγεται ένα εφήμερο
κλειδί στη μνήμη — δεδομένα κρυπτογραφημένα μ' αυτό γίνονται μη αναγνώσιμα
μετά από restart, βλ. config.validate_production_config.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from config import Config

_fernet = None


def _derive_fernet_key(secret):
    """
    Fernet απαιτεί ΑΚΡΙΒΩΣ 32 urlsafe-base64 bytes. Το ENCRYPTION_KEY μπορεί να
    είναι οτιδήποτε (π.χ. τυχαίο αλφαριθμητικό από Render generateValue) —
    το περνάμε από SHA-256 ώστε πάντα να καταλήγουμε σε έγκυρο κλειδί.
    """
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet():
    global _fernet
    if _fernet is None:
        secret = Config.ENCRYPTION_KEY or Fernet.generate_key().decode()
        _fernet = Fernet(_derive_fernet_key(secret))
    return _fernet


def encrypt(plaintext):
    """str|None -> str|None (urlsafe-base64 token)."""
    if not plaintext:
        return None
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token):
    """
    str|None -> str|None. Αν το token δεν είναι έγκυρο (π.χ. δεδομένα από πριν
    την κρυπτογράφηση, ή restart χωρίς σταθερό ENCRYPTION_KEY), γυρνάει None
    αντί να σκάει — το site απλά θα δείχνει «δεν έχει οριστεί κλειδί».
    """
    if not token:
        return None
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
