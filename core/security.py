"""Hash da senha do usuário único e criptografia dos tokens das contas.

Uso pela linha de comando:
    python -m core.security hash-password   # pede a senha e imprime APP_PASSWORD_HASH
    python -m core.security new-keys        # imprime SECRET_KEY e TOKEN_ENCRYPTION_KEY novos
"""

import hashlib
import hmac
import os
import secrets
import sys
from getpass import getpass

from cryptography.fernet import Fernet, InvalidToken

# Separador ":" e não "$", para o valor não ser interpolado pelo Docker Compose.
_SCHEME = "scrypt"
_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"{_SCHEME}:{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split(":")
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    if scheme != _SCHEME:
        return False
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return hmac.compare_digest(digest.hex(), digest_hex)


class TokenCipher:
    """Criptografa tokens OAuth antes de gravar no banco."""

    def __init__(self, key: str):
        if not key:
            raise ValueError("TOKEN_ENCRYPTION_KEY não configurada")
        self._fernet = Fernet(key.encode())

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt(self, encrypted: str) -> str:
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Token inválido ou chave errada") from exc


def _main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command == "hash-password":
        password = getpass("Senha: ")
        if password != getpass("Repita a senha: "):
            print("As senhas não conferem.", file=sys.stderr)
            return 1
        print(f"APP_PASSWORD_HASH={hash_password(password)}")
        return 0
    if command == "new-keys":
        print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
        print(f"TOKEN_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
