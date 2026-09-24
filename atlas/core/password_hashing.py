import hashlib
import secrets

ITERATIONS = 200_000


# מחשבת hash מסולסל (PBKDF2) לסיסמה. אם salt לא מסופק, נוצר salt אקראי חדש (יצירת משתמש)
def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS).hex()
    return digest, salt


# משווה סיסמה שהוזנה מול ה-hash השמור, ללא חשיפת הסיסמה עצמה וללא timing attack
def verify_password(password, salt, expected_hash):
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, expected_hash)
