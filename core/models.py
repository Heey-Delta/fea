"""As tabelas da ferramenta (Task 2, seção 12 da v2.1 com os ajustes da seção 18).

As 14 do MVP mais `app_credentials` (chaves das redes preenchidas pela interface, Task 28).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core import states
from core.db import Base


def one_of(column: str, values: tuple[str, ...]) -> CheckConstraint:
    """Constraint que só aceita os valores listados em core.states."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"{column}_valid")


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = (one_of("status", states.OPERATION_STATUS),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    current_config_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("operation_configs.id", use_alter=True, ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class OperationConfig(Base):
    """Versão imutável da configuração: grafo do canvas, preset, rede, automação e retenção."""

    __tablename__ = "operation_configs"
    __table_args__ = (UniqueConstraint("operation_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("operations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        one_of("status", states.SOURCE_STATUS),
        UniqueConstraint("operation_id", "node_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("operations.id", ondelete="CASCADE"), index=True
    )
    # Bloco Fonte do canvas que criou esta fonte (Task 5.9).
    node_id: Mapped[str | None] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(40))
    reference: Mapped[str] = mapped_column(String(500))
    # Sem nota de permissão, os itens da fonte entram como pending_permission (REQ-UI-004).
    permission_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="ok")
    cursor: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("platform", "external_id"),
        one_of("status", states.ACCOUNT_STATUS),
        CheckConstraint("daily_limit >= 0", name="daily_limit_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    platform: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[str] = mapped_column(String(200))
    # Criptografado com TOKEN_ENCRYPTION_KEY; nunca vai ao navegador nem aos logs.
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="connected")
    daily_limit: Mapped[int] = mapped_column(Integer, server_default="3")
    timezone: Mapped[str] = mapped_column(String(64), server_default="America/Sao_Paulo")
    created_at: Mapped[datetime] = created_at()


class OperationAccount(Base):
    __tablename__ = "operation_accounts"
    __table_args__ = (PrimaryKeyConstraint("operation_id", "account_id"),)

    operation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("operations.id", ondelete="CASCADE")
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (
        one_of("trigger", states.EXECUTION_TRIGGER),
        one_of("criteria", states.EXECUTION_CRITERIA),
        one_of("priority", states.PRIORITY),
        one_of("status", states.EXECUTION_STATUS),
        CheckConstraint("target_x > 0", name="target_x_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("operations.id", ondelete="CASCADE"), index=True
    )
    # Configuração congelada no início (REQ-EXEC-005).
    config_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("operation_configs.id"))
    trigger: Mapped[str] = mapped_column(String(20), server_default="manual")
    target_x: Mapped[int] = mapped_column(Integer)
    search_budget: Mapped[int] = mapped_column(Integer)
    criteria: Mapped[str] = mapped_column(String(20), server_default="recent")
    priority: Mapped[str] = mapped_column(String(10), server_default="normal")
    status: Mapped[str] = mapped_column(String(20), server_default="running")
    shortfall_reason: Mapped[str | None] = mapped_column(Text)
    # Fontes escolhidas no Play (None = todas as ativas).
    source_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    # Contagens da busca que não viram linhas em items (ex.: posts já vistos antes).
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id"),
        one_of("status", states.ITEM_STATUS),
        one_of("priority", states.PRIORITY),
        CheckConstraint(
            "approved_by IS NULL OR approved_by IN ('manual', 'auto')", name="approved_by_valid"
        ),
        Index("ix_items_operation_status", "operation_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("operations.id", ondelete="CASCADE")
    )
    execution_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("executions.id", ondelete="SET NULL"), index=True
    )
    source_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sources.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(200))
    media_type: Mapped[str | None] = mapped_column(String(20))
    text: Mapped[str | None] = mapped_column(Text)
    duration_s: Mapped[float | None]
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    phash: Mapped[str | None] = mapped_column(String(64), index=True)
    score: Mapped[int] = mapped_column(Integer, server_default="0")
    priority: Mapped[str] = mapped_column(String(10), server_default="normal")
    status: Mapped[str] = mapped_column(String(30), server_default="discovered")
    status_reason: Mapped[str | None] = mapped_column(Text)
    duplicate_of: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("items.id", ondelete="SET NULL")
    )
    original_file: Mapped[str | None] = mapped_column(Text)
    # Aprovação vale para um render exato e para as contas listadas (REQ-APP-004).
    approved_render_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("renders.id", use_alter=True, ondelete="SET NULL")
    )
    approved_account_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    approved_by: Mapped[str | None] = mapped_column(String(10))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Retenção: arquivos apagados X minutos após a última publicação (Task 2.11).
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    files_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class MaskAsset(Base):
    __tablename__ = "mask_assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("operations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at()


class MaskVersion(Base):
    __tablename__ = "mask_versions"
    __table_args__ = (UniqueConstraint("mask_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mask_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mask_assets.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    file_key: Mapped[str] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    has_alpha: Mapped[bool] = mapped_column(Boolean)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()


class Render(Base):
    """Uma versão editada de um item. Nunca sobrescreve a anterior."""

    __tablename__ = "renders"
    __table_args__ = (
        UniqueConstraint("item_id", "version"),
        one_of("status", states.RENDER_STATUS),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("items.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    # Versão da configuração (preset) e da máscara usadas: reprodutibilidade.
    config_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("operation_configs.id"))
    mask_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("mask_versions.id"))
    output_file: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="rendering")
    qa_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    files_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (
        one_of("mode", states.BATCH_MODE),
        one_of("status", states.BATCH_STATUS),
        CheckConstraint("interval_min >= 0", name="interval_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("operations.id", ondelete="CASCADE"), index=True
    )
    # Duplo clique ou reenvio não cria um segundo lote (REQ-DIST-011).
    request_key: Mapped[str] = mapped_column(String(100), unique=True)
    mode: Mapped[str] = mapped_column(String(20), server_default="rotation")
    automatic: Mapped[bool] = mapped_column(Boolean, server_default="false")
    interval_min: Mapped[int] = mapped_column(Integer)
    first_immediate: Mapped[bool] = mapped_column(Boolean, server_default="false")
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), server_default="active")
    created_at: Mapped[datetime] = created_at()


class PublishJob(Base):
    """Um envio: um vídeo para uma conta. Título e tags são gerados pelo Postador."""

    __tablename__ = "publish_jobs"
    __table_args__ = (
        UniqueConstraint("render_id", "account_id"),
        one_of("status", states.PUBLISH_STATUS),
        CheckConstraint(
            "title_method IS NULL OR title_method IN ('markov', 'fallback', 'manual')",
            name="title_method_valid",
        ),
        Index("ix_publish_jobs_status_planned_at", "status", "planned_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    render_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("renders.id"))
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"), index=True)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    title_method: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), server_default="planned")
    status_reason: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    external_id: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Métricas da plataforma (visualizações, curtidas…), atualizadas pelo Postador (Task 28.3).
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metrics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Job(Base):
    """Fila de tarefas dos workers, lida com FOR UPDATE SKIP LOCKED (Task 3)."""

    __tablename__ = "jobs"
    __table_args__ = (
        one_of("type", states.JOB_TYPE),
        one_of("status", states.JOB_STATUS),
        Index("ix_jobs_pick", "status", "type", "priority", "run_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[int | None] = mapped_column(BigInteger)
    operation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("operations.id", ondelete="CASCADE")
    )
    execution_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("executions.id", ondelete="CASCADE"), index=True
    )
    # Prioridade numérica para ordenar: alta = 2, normal = 1, baixa = 0.
    priority: Mapped[int] = mapped_column(Integer, server_default="1")
    status: Mapped[str] = mapped_column(String(20), server_default="queued")
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="3")
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    # Dados extras da tarefa (ex.: versão da configuração de um novo render).
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Event(Base):
    """Auditoria e log: renders, alterações de preset e máscara, erros, aprovações."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_entity", "entity", "entity_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = created_at()
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    operation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("operations.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AppCredential(Base):
    """Chave de serviço (Reddit, X, Google, TikTok, Instagram) preenchida na tela Acessos.

    O valor fica criptografado com TOKEN_ENCRYPTION_KEY. Variável de ambiente tem precedência.
    """

    __tablename__ = "app_credentials"

    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    value_encrypted: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = updated_at()


class WorkerHeartbeat(Base):
    """Sinal de vida de cada worker da VPS (um por papel e máquina), mostrado na tela Acessos."""

    __tablename__ = "worker_heartbeats"
    __table_args__ = (PrimaryKeyConstraint("role", "host"),)

    role: Mapped[str] = mapped_column(String(20))
    host: Mapped[str] = mapped_column(String(100))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
