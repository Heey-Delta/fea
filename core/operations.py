"""Operações: configuração versionada, grafo de blocos e estados (Task 4).

A configuração é o grafo do canvas: blocos (`nodes`) ligados por arestas (`edges`), cada
bloco com sua própria configuração. Cada salvamento cria uma versão nova e imutável
(REQ-UI-003). Execuções guardam a versão que usaram.
"""

import copy
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.connectors import SOURCE_TYPES
from core.models import Event, Operation, OperationConfig
from core.sources import sync_sources

NODE_TYPES = {
    "source": "Fonte",
    "fishing": "Pesca",
    "edit": "Motor Editor",
    "approval": "Aprovação",
    "publish": "Publicador",
    "network": "Rede",
    "account": "Conta",
}

# Ligações permitidas (docs/fluxo-operacao.md §4.3). Qualquer outra é recusada.
ALLOWED_EDGES = {
    ("source", "fishing"),
    ("fishing", "edit"),
    ("edit", "approval"),
    ("approval", "publish"),
    ("network", "edit"),
    ("network", "publish"),
    ("account", "publish"),
}

# Blocos que existem exatamente uma vez por operação.
SINGLE_NODES = ("fishing", "edit", "approval", "publish", "network")

STATUS_TRANSITIONS = {
    "draft": {"active", "archived"},
    "active": {"paused", "archived"},
    "paused": {"active", "archived"},
    "archived": set(),
}


class OperationError(Exception):
    """Ação recusada. A mensagem vai para a interface."""


@dataclass(frozen=True)
class Issue:
    level: str  # "error" bloqueia a ativação; "warning" só avisa
    message: str
    node_id: str | None = None


def default_config() -> dict[str, Any]:
    """Fluxo inicial de uma operação nova: os blocos já ligados, faltando fonte e conta."""
    return {
        "nodes": [
            {
                "id": "pesca",
                "type": "fishing",
                "config": {
                    "tags": [],
                    "heat_tags": [],
                    "blocked_words": [],
                    "target_x": 10,
                    "search_budget": 300,
                    "criteria": "recent",
                    "accepted_media": ["video"],
                    "max_duration_s": 60,
                    "reject_watermarks": True,
                },
            },
            {"id": "edicao", "type": "edit", "config": {"preset": {}}},
            {"id": "aprovacao", "type": "approval", "config": {"auto_approve": False}},
            {
                "id": "postagem",
                "type": "publish",
                "config": {
                    "mode": "rotation",
                    "automatic": False,
                    "interval_min": 30,
                    "first_immediate": False,
                    "window": {"start": "08:00", "end": "23:00"},
                    "timezone": "America/Sao_Paulo",
                    # Sem a auditoria do Google, a API deixa os vídeos privados mesmo assim.
                    "privacy": "public",
                    # Gerados pelo Postador na hora de publicar (Task 16).
                    "titles": {
                        "method": "markov",
                        "corpus": [],
                        "templates": ["{texto}"],
                        "blocked_words": [],
                        "hashtags": ["shorts"],
                        "description_template": "{titulo}\n\n{hashtags}",
                        "min_chars": 15,
                    },
                },
            },
            {"id": "rede", "type": "network", "config": {"profile": "youtube_shorts"}},
        ],
        "edges": [
            {"from": "pesca", "to": "edicao"},
            {"from": "edicao", "to": "aprovacao"},
            {"from": "aprovacao", "to": "postagem"},
            {"from": "rede", "to": "edicao"},
            {"from": "rede", "to": "postagem"},
        ],
        "automation": {
            "daily_play_at": None,
            "daily_target": 30,
            "stock_enabled": False,
            "stock_min_days": 3,
        },
        "retention": {"delete_after_minutes": 30},
    }


def edge_allowed(from_type: str, to_type: str) -> bool:
    return (from_type, to_type) in ALLOWED_EDGES


def validate_graph(config: dict[str, Any]) -> list[Issue]:
    """Confere o fluxo antes de ativar (Task 4.11). Rascunho pode ter erros; ativa, não."""
    issues: list[Issue] = []
    nodes = config.get("nodes") or []
    edges = config.get("edges") or []
    by_id: dict[str, dict] = {}
    for node in nodes:
        node_id, node_type = node.get("id"), node.get("type")
        if not node_id or node_type not in NODE_TYPES:
            issues.append(Issue("error", f"Bloco inválido: {node_id or '?'} ({node_type})"))
            continue
        if node_id in by_id:
            issues.append(Issue("error", f"Dois blocos com o mesmo id: {node_id}", node_id))
        by_id[node_id] = node

    by_type: dict[str, list[str]] = defaultdict(list)
    for node_id, node in by_id.items():
        by_type[node["type"]].append(node_id)

    for node_type in SINGLE_NODES:
        count = len(by_type[node_type])
        if count != 1:
            label = NODE_TYPES[node_type]
            issues.append(Issue("error", f"A operação precisa de exatamente um bloco {label}."))

    links: set[tuple[str, str]] = set()
    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        a, b = edge.get("from"), edge.get("to")
        if a not in by_id or b not in by_id:
            issues.append(Issue("error", f"Ligação com bloco inexistente: {a} → {b}"))
            continue
        ta, tb = by_id[a]["type"], by_id[b]["type"]
        if not edge_allowed(ta, tb):
            issues.append(
                Issue(
                    "error",
                    f"{NODE_TYPES[ta]} não pode ligar em {NODE_TYPES[tb]}.",
                    a,
                )
            )
            continue
        links.add((ta, tb))
        outgoing[a].add(b)

    if _has_cycle(by_id, outgoing):
        issues.append(Issue("error", "O fluxo tem um ciclo."))

    connected_sources = [
        sid
        for sid in by_type["source"]
        if any(by_id[t]["type"] == "fishing" for t in outgoing[sid])
    ]
    if not connected_sources:
        issues.append(Issue("error", "Adicione ao menos uma fonte de busca na Pesca."))
    for required, message in (
        (("fishing", "edit"), "Ligue a Pesca ao Motor Editor."),
        (("edit", "approval"), "Ligue o Motor Editor à Aprovação."),
        (("approval", "publish"), "Ligue a Aprovação ao Publicador."),
        (("network", "edit"), "Ligue a Rede ao Motor Editor."),
        (("network", "publish"), "Ligue a Rede ao Publicador."),
        (("account", "publish"), "Escolha ao menos uma conta no Publicador."),
    ):
        if required not in links:
            issues.append(Issue("error", message))

    for sid in by_type["source"]:
        cfg = by_id[sid].get("config") or {}
        source_type = cfg.get("type") or "reddit"
        if source_type not in SOURCE_TYPES:
            issues.append(Issue("error", f"Tipo de fonte desconhecido: {source_type}.", sid))
        elif source_type == "reddit" and not (cfg.get("reference") or "").strip():
            issues.append(Issue("error", "Fonte do Reddit sem comunidade (ex.: r/nome).", sid))
        elif source_type == "x" and not (cfg.get("reference") or "").strip():
            issues.append(Issue("error", "Fonte do X sem @usuario ou termo de busca.", sid))
    for sid in by_type["source"]:
        if not (by_id[sid].get("config") or {}).get("permission_note"):
            issues.append(
                Issue(
                    "warning",
                    "Fonte sem permissão registrada: "
                    "os itens entram como pendentes de autorização.",
                    sid,
                )
            )
    return issues


def _has_cycle(by_id: dict[str, dict], outgoing: dict[str, set[str]]) -> bool:
    state: dict[str, int] = {}  # 1 = visitando, 2 = visto

    def visit(node: str) -> bool:
        state[node] = 1
        for nxt in outgoing[node]:
            if state.get(nxt) == 1 or (state.get(nxt) is None and visit(nxt)):
                return True
        state[node] = 2
        return False

    return any(state.get(n) is None and visit(n) for n in by_id)


def linked_account_ids(config: dict[str, Any]) -> list[int]:
    """Contas ligadas ao bloco Postagem (ids da tabela accounts)."""
    nodes = {n.get("id"): n for n in config.get("nodes") or []}
    ids = []
    for edge in config.get("edges") or []:
        node = nodes.get(edge.get("from"))
        target = nodes.get(edge.get("to"))
        if node and target and node.get("type") == "account" and target.get("type") == "publish":
            account_id = (node.get("config") or {}).get("account_id")
            if isinstance(account_id, int) and account_id not in ids:
                ids.append(account_id)
    return ids


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "error" for i in issues)


# --- persistência -----------------------------------------------------------------------


def _event(session: Session, op: Operation, action: str, detail: dict | None = None) -> None:
    session.add(
        Event(entity="operation", entity_id=op.id, operation_id=op.id, action=action, detail=detail)
    )


def create_operation(session: Session, name: str, config: dict | None = None) -> Operation:
    name = name.strip()
    if not name:
        raise OperationError("Dê um nome à operação.")
    op = Operation(name=name, status="draft")
    session.add(op)
    session.flush()
    config = config or default_config()
    _new_version(session, op, config)
    sync_sources(session, op, config)
    _event(session, op, "created")
    return op


def _new_version(session: Session, op: Operation, config: dict) -> OperationConfig:
    current = session.scalar(
        select(func.max(OperationConfig.version)).where(OperationConfig.operation_id == op.id)
    )
    version = OperationConfig(
        operation_id=op.id, version=(current or 0) + 1, config=copy.deepcopy(config)
    )
    session.add(version)
    session.flush()
    op.current_config_id = version.id
    session.flush()
    return version


def current_config(session: Session, op: Operation) -> OperationConfig:
    return session.get(OperationConfig, op.current_config_id)


def save_config(session: Session, op: Operation, config: dict) -> OperationConfig:
    """Salva uma nova versão. Operação ativa não aceita fluxo com erro."""
    if op.status == "archived":
        raise OperationError("Operação arquivada é somente leitura.")
    issues = validate_graph(config)
    if op.status == "active" and has_errors(issues):
        raise OperationError("Corrija os erros do fluxo antes de salvar uma operação ativa.")
    if config == current_config(session, op).config:
        return current_config(session, op)
    version = _new_version(session, op, config)
    sync_sources(session, op, config)
    _event(session, op, "config_saved", {"version": version.version})
    return version


def change_status(session: Session, op: Operation, new_status: str) -> None:
    if new_status not in STATUS_TRANSITIONS.get(op.status, set()):
        raise OperationError(f"Não é possível passar de {op.status} para {new_status}.")
    if new_status == "active" and has_errors(validate_graph(current_config(session, op).config)):
        raise OperationError("O fluxo tem erros. Corrija antes de ativar.")
    old = op.status
    op.status = new_status
    session.flush()
    _event(session, op, "status_changed", {"from": old, "to": new_status})


def duplicate_operation(session: Session, op: Operation) -> Operation:
    copy_op = create_operation(session, f"{op.name} (cópia)", current_config(session, op).config)
    _event(session, copy_op, "duplicated_from", {"operation_id": op.id})
    return copy_op


def list_operations(session: Session, status: str | None = None) -> list[Operation]:
    stmt = select(Operation).order_by(Operation.updated_at.desc(), Operation.id.desc())
    if status:
        stmt = stmt.where(Operation.status == status)
    return list(session.scalars(stmt))


def versions(session: Session, op: Operation) -> list[OperationConfig]:
    return list(
        session.scalars(
            select(OperationConfig)
            .where(OperationConfig.operation_id == op.id)
            .order_by(OperationConfig.version.desc())
        )
    )
