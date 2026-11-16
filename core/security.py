"""Criptografia dos tokens das contas (OAuth do YouTube etc.) antes de gravar no banco.

Uso pela linha de comando:
    python -m core.security new-keys   # imprime SECRET_KEY e TOKEN_ENCRYPTION_KEY novos
"""

import secrets
import sys

from cryptography.fernet import Fernet, InvalidToken


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
    if len(argv) > 1 and argv[1] == "new-keys":
        print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
        print(f"TOKEN_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
