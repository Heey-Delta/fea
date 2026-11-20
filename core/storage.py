"""Armazenamento de arquivos: Cloudflare R2 em produção, disco local em desenvolvimento.

Chaves seguem a organização da especificação:
    operations/{op}/items/{item}/original.mp4
    operations/{op}/items/{item}/renders/{versão}.mp4
    operations/{op}/masks/{mask}/{versão}.png
    uploads/{op}/{source}/{arquivo}
"""

import shutil
import time
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from core.config import Settings, get_settings


class Storage(Protocol):
    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None: ...
    def get_file(self, key: str, path: Path) -> None: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def list(self, prefix: str, after: str | None = None) -> list[str]: ...
    def url(self, key: str, expires_s: int = 3600) -> str: ...
    def upload_url(self, key: str, content_type: str, expires_s: int = 3600) -> str | None: ...


def _safe_key(key: str) -> str:
    parts = [p for p in key.split("/") if p not in ("", ".", "..")]
    if not parts:
        raise ValueError("chave vazia")
    return "/".join(parts)


class LocalStorage:
    """Disco local. Sem URL pública: a interface serve os arquivos pela rota /arquivos."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / _safe_key(key)).resolve()
        if self.root not in path.parents:
            raise ValueError("chave fora do armazenamento")
        return path

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def get_file(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(key), path)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list(self, prefix: str, after: str | None = None) -> list[str]:
        base = self._path(prefix) if prefix.strip("/") else self.root
        if not base.exists():
            return []
        keys = sorted(
            str(p.relative_to(self.root)).replace("\\", "/") for p in base.rglob("*") if p.is_file()
        )
        return [k for k in keys if after is None or k > after]

    def url(self, key: str, expires_s: int = 3600) -> str:
        return f"/arquivos/{_safe_key(key)}"

    def upload_url(self, key: str, content_type: str, expires_s: int = 3600) -> str | None:
        return None  # sem R2, o upload passa pela própria interface


class R2Storage:
    """Cloudflare R2 pela API compatível com S3, com URLs assinadas."""

    def __init__(self, settings: Settings):
        import boto3
        from botocore.config import Config

        self.bucket = settings.r2_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else None
        self.client.upload_file(str(path), self.bucket, _safe_key(key), ExtraArgs=extra)

    def get_file(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, _safe_key(key), str(path))

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=_safe_key(key))
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_safe_key(key))

    def list(self, prefix: str, after: str | None = None) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        kwargs = {"Bucket": self.bucket, "Prefix": prefix}
        if after:
            kwargs["StartAfter"] = after
        for page in paginator.paginate(**kwargs):
            keys += [obj["Key"] for obj in page.get("Contents", [])]
        return keys

    def url(self, key: str, expires_s: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": _safe_key(key)}, ExpiresIn=expires_s
        )

    def upload_url(self, key: str, content_type: str, expires_s: int = 3600) -> str | None:
        return self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": _safe_key(key), "ContentType": content_type},
            ExpiresIn=expires_s,
        )


def make_storage(settings: Settings) -> Storage:
    return R2Storage(settings) if settings.r2_configured else LocalStorage(settings.storage_dir)


class DynamicStorage:
    """Armazenamento escolhido na hora: R2 se as chaves existem (variável de ambiente ou tela
    Acessos), senão o disco local. Relê as chaves no banco a cada `ttl` segundos, então salvar
    o R2 na interface vale para a interface e para os workers sem reiniciar nada.
    """

    def __init__(self, settings: Settings, session_factory=None, ttl: float = 60.0):
        self.settings = settings
        self.session_factory = session_factory
        self.ttl = ttl
        self._inner: Storage | None = None
        self._key: tuple | None = None
        self._at = -1e9

    def _effective(self) -> Settings:
        if self.session_factory is None:
            return self.settings
        try:
            from core.credentials import effective

            with self.session_factory() as session:
                return effective(session, self.settings)
        except Exception:  # noqa: BLE001 - sem banco: só as variáveis de ambiente
            return self.settings

    def current(self) -> Storage:
        now = time.monotonic()
        if self._inner is not None and now - self._at < self.ttl:
            return self._inner
        eff = self._effective()
        key = (
            eff.r2_account_id,
            eff.r2_access_key_id,
            eff.r2_secret_access_key,
            eff.r2_bucket,
            eff.storage_dir,
        )
        if key != self._key or self._inner is None:
            self._inner = make_storage(eff)
            self._key = key
        self._at = now
        return self._inner

    def refresh(self) -> None:
        self._at = -1e9

    def __getattr__(self, name: str):
        return getattr(self.current(), name)


def unwrap(storage) -> Storage:
    return storage.current() if isinstance(storage, DynamicStorage) else storage


@lru_cache
def get_storage() -> Storage:
    """Workers: R2 da variável de ambiente ou da tela Acessos."""
    from core.db import get_sessionmaker

    return DynamicStorage(get_settings(), get_sessionmaker())
