"""Valores válidos de cada campo de estado. O banco recusa qualquer outro (Task 2.10)."""

OPERATION_STATUS = ("draft", "active", "paused", "archived")

SOURCE_STATUS = ("ok", "error", "paused")

ACCOUNT_STATUS = ("connected", "error", "paused", "revoked")

EXECUTION_TRIGGER = ("manual", "scheduled", "stock")
EXECUTION_CRITERIA = ("recent", "heat")
EXECUTION_STATUS = ("running", "paused", "completed", "partial", "cancelled")

PRIORITY = ("low", "normal", "high")

# Máquina de estados do item (seção 6.1 da v2.1). "Agendado", "publicado" e "falha" vêm dos envios.
ITEM_STATUS = (
    "discovered",
    "duplicate",
    "rejected",
    "pending_permission",
    "eligible",
    "rendering",
    "needs_fix",
    "awaiting_approval",
    "approved",
)
APPROVED_BY = ("manual", "auto")

RENDER_STATUS = ("rendering", "ok", "failed")

BATCH_MODE = ("rotation", "all")
BATCH_STATUS = ("active", "completed", "cancelled")

# Máquina de estados do envio (seção 9.4 da v2.1).
PUBLISH_STATUS = (
    "planned",
    "pending_capacity",
    "uploading",
    "scheduled_platform",
    "processing",
    "retry_wait",
    "uncertain",
    "published",
    "failed",
    "skipped",
    "cancelled",
)
TITLE_METHOD = ("markov", "fallback", "manual")

# Filas dos workers: Buscador (collect), Editor (render), Postador (publish e scheduler), Limpeza.
JOB_TYPE = ("collect", "render", "publish", "scheduler", "cleanup")
JOB_STATUS = ("queued", "running", "done", "failed", "cancelled")
