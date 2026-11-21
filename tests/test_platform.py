"""Plataforma: estado desejado de cada ambiente e servidores com o agente (Task 32)."""

from datetime import UTC, datetime, timedelta

import pytest

import core.models as m
from core import platform as pf
from core.operations import OperationError
from tests.test_render_job import factory, pytestmark  # noqa: F401


def make_op(s, status="active"):
    op = m.Operation(name="Op", status=status)
    s.add(op)
    s.flush()
    return op


def test_ligar_so_operacao_ativa_e_limites_validos(factory):  # noqa: F811
    with factory() as s:
        draft, active = make_op(s, "draft"), make_op(s)
        with pytest.raises(OperationError, match="Só operações ativas"):
            pf.set_desired(s, draft, "running")
        row = pf.set_desired(s, active, "running")
        assert (row.desired_state, row.actual_state, row.cpu_limit, row.memory_mb) == (
            "running",
            "absent",
            1.0,
            1024,
        )
        with pytest.raises(OperationError, match="CPU"):
            pf.set_limits(s, active, 0.1, 1024)
        with pytest.raises(OperationError, match="Memória"):
            pf.set_limits(s, active, 1, 128)
        row = pf.set_limits(s, active, 1.5, 2048)
        assert (row.cpu_limit, row.memory_mb) == (1.5, 2048)
        assert s.query(m.Event).filter_by(entity="runtime", entity_id=active.id).count() == 2
        s.commit()


def test_versao_so_entre_as_disponiveis_e_restauracao_so_de_backup_existente(factory):  # noqa: F811
    with factory() as s:
        op = make_op(s)
        s.add(m.InfraServer(name="vps", versions=["b2c3d4e", "a1b2c3d"]))
        s.flush()
        with pytest.raises(OperationError, match="não disponível"):
            pf.set_version(s, op, "zzzzzzz")
        assert pf.set_version(s, op, "a1b2c3d").version == "a1b2c3d"  # rollback
        assert pf.set_version(s, op, "").version == ""  # acompanhar a mais nova
        with pytest.raises(OperationError, match="Backup não encontrado"):
            pf.request_restore(s, op, "op-1-x.tar.gz")
        pf.runtime(s, op.id).backups = [{"name": "op-1-x.tar.gz", "size": 10}]
        assert pf.request_restore(s, op, "op-1-x.tar.gz").restore_request["name"] == "op-1-x.tar.gz"
        s.commit()


def test_plataforma_ativa_so_com_agente_no_ar(factory):  # noqa: F811
    now = datetime.now(UTC)
    with factory() as s:
        assert not pf.platform_active(s, now)
        s.add(m.AppSetting(name=pf.MODE_KEY, value="plataforma"))
        server = m.InfraServer(name="vps", last_seen=now - timedelta(minutes=5))
        s.add(server)
        s.flush()
        assert not pf.platform_active(s, now)  # agente sumiu: o celular pode voltar
        server.last_seen = now
        assert pf.platform_active(s, now)
        view = pf.servers(s, now)[0]
        server.mem_total_mb, server.mem_used_mb = 8000, 2000
        server.disk_total_gb, server.disk_free_gb = 100, 75
        assert (view.online, view.mem_pct, view.disk_pct) == (True, 25, 25)
        s.commit()
