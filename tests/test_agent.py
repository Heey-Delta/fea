"""Agente da plataforma (Task 33) com um Docker simulado.

O mesmo fluxo foi verificado com Docker real (núcleo + duas operações, isolamento de rede,
parar uma sem afetar a outra, backup e restauração): ver `docs/plataforma.md`.
"""

import json
from datetime import UTC, datetime, timedelta

import core.models as m
from agent import compose as cp
from agent.agent import Agent, state_of
from core import platform as pf
from tests.test_render_job import factory, pytestmark  # noqa: F401


class FakeDocker:
    def __init__(self, versions=("abc1234",)):
        self.versions = list(versions)
        self.calls: list[tuple] = []
        self.running: dict[str, set[str]] = {}

    def images(self):
        return list(self.versions)

    def up(self, project, file):
        self.calls.append(("up", project))
        services = json.loads(file.read_text())["services"]
        self.running[project] = set(services)

    def stop(self, project):
        self.calls.append(("stop", project))
        self.running[project] = set()

    def down(self, project):
        self.calls.append(("down", project))
        self.running.pop(project, None)

    def restart(self, project, file):
        self.calls.append(("restart", project))

    def ps(self, project):
        return [
            {"service": s, "name": f"{project}-{s}-1", "state": "running", "health": "healthy"}
            for s in sorted(self.running.get(project, set()))
        ]

    def projects(self):
        return [p for p, s in self.running.items()]

    def stats(self):
        return {
            f"{p}-{s}-1": {"cpu": 1.0, "mem_mb": 50.0} for p, ss in self.running.items() for s in ss
        }

    def logs(self, project, service, tail=30):
        return [f"{service} ok", "conectando em postgresql://fea:segredo@db/fea"]


def ops(factory, *statuses):  # noqa: F811
    with factory() as s:
        out = []
        for i, st in enumerate(statuses):
            op = m.Operation(name=f"Op {i}", status=st)
            s.add(op)
            s.flush()
            out.append(op.id)
        s.commit()
        return out


def test_primeira_subida_liga_as_ativas_e_isola_cada_uma(factory, tmp_path):  # noqa: F811
    a, b, draft = ops(factory, "active", "active", "draft")
    docker = FakeDocker()
    Agent(factory, tmp_path, docker, server_name="vps").tick()
    assert ("up", "fea-nucleo") in docker.calls
    assert ("up", f"fea-op-{a}") in docker.calls and ("up", f"fea-op-{b}") in docker.calls
    assert f"fea-op-{draft}" not in docker.running
    spec = json.loads((cp.op_dir(tmp_path, a) / "compose.yml").read_text())
    editor = spec["services"]["editor"]
    assert spec["name"] == f"fea-op-{a}" and editor["environment"]["OPERATION_ID"] == str(a)
    assert editor["read_only"] and editor["cap_drop"] == ["ALL"] and "ports" not in editor
    assert editor["security_opt"] == ["no-new-privileges:true"] and editor["pids_limit"] == 256
    assert editor["cpus"] == 0.6 and editor["mem_limit"] == "614m"  # 60% de 1 CPU e 1 GB
    assert all(str(cp.op_dir(tmp_path, a)) in v for v in editor["volumes"])
    with factory() as s:
        rt = s.get(m.OperationRuntime, a)
        assert (rt.desired_state, rt.actual_state, rt.actual_version) == (
            "running",
            "running",
            "abc1234",
        )
        assert rt.usage == {"cpu": 3.0, "mem_mb": 150.0}
        assert all("segredo" not in line for lines in rt.logs.values() for line in lines)
        assert s.get(m.AppSetting, pf.MODE_KEY).value == "plataforma"
        assert s.query(m.InfraServer).one().versions == ["abc1234"]


def test_parar_uma_nao_mexe_na_outra_e_ciclo_e_idempotente(factory, tmp_path):  # noqa: F811
    a, b = ops(factory, "active", "active")
    docker = FakeDocker()
    agent = Agent(factory, tmp_path, docker)
    agent.tick()
    docker.calls.clear()
    agent.tick()
    assert docker.calls == []  # nada mudou: nada a fazer
    with factory() as s:
        pf.set_desired(s, s.get(m.Operation, a), "stopped")
        s.commit()
    agent.tick()
    assert docker.calls == [("stop", f"fea-op-{a}")]
    assert docker.running[f"fea-op-{b}"] == {"buscador", "editor", "postador"}
    with factory() as s:
        assert s.get(m.OperationRuntime, a).actual_state == "absent"  # sem containers rodando


def test_limites_versao_reinicio_e_operacao_apagada(factory, tmp_path):  # noqa: F811
    (a,) = ops(factory, "active")
    docker = FakeDocker(versions=("new0000", "old0000"))
    agent = Agent(factory, tmp_path, docker)
    agent.tick()
    with factory() as s:
        op = s.get(m.Operation, a)
        pf.set_limits(s, op, 2.0, 2048)
        pf.set_version(s, op, "old0000")  # rollback
        pf.request_restart(s, op)
        s.commit()
    docker.calls.clear()
    agent.tick()
    spec = json.loads((cp.op_dir(tmp_path, a) / "compose.yml").read_text())
    assert spec["services"]["editor"]["image"] == "fea-worker:old0000"
    assert spec["services"]["editor"]["cpus"] == 1.2
    assert ("up", f"fea-op-{a}") in docker.calls and ("restart", f"fea-op-{a}") in docker.calls
    with factory() as s:
        rt = s.get(m.OperationRuntime, a)
        assert rt.actual_version == "old0000" and rt.restart_done_at is not None
        s.delete(s.get(m.Operation, a))
        s.commit()
    agent.tick()
    assert ("down", f"fea-op-{a}") in docker.calls


def test_versao_inexistente_vira_erro_sem_derrubar(factory, tmp_path):  # noqa: F811
    (a,) = ops(factory, "active")
    docker = FakeDocker(versions=())
    Agent(factory, tmp_path, docker).tick()
    with factory() as s:
        rt = s.get(m.OperationRuntime, a)
        assert rt.actual_state == "error" and "Nenhuma imagem" in rt.error
    assert docker.calls == []


def test_backup_e_restauracao_dos_arquivos_da_operacao(factory, tmp_path):  # noqa: F811
    (a,) = ops(factory, "active")
    docker = FakeDocker()
    clock = [datetime(2026, 11, 21, 10, tzinfo=UTC)]
    agent = Agent(factory, tmp_path, docker, clock=lambda: clock[0])
    agent.tick()
    marker = cp.op_dir(tmp_path, a) / "status" / "editor.json"
    marker.write_text('{"state": "idle"}')
    with factory() as s:
        pf.request_backup(s, s.get(m.Operation, a))
        s.commit()
    clock[0] += timedelta(minutes=1)
    agent.tick()
    with factory() as s:
        rt = s.get(m.OperationRuntime, a)
        name = rt.backups[0]["name"]
        assert name.startswith(f"op-{a}-") and rt.backup_done_at is not None
    marker.write_text("estragado")
    with factory() as s:
        pf.request_restore(s, s.get(m.Operation, a), name)
        s.commit()
    clock[0] += timedelta(minutes=1)
    agent.tick()
    assert marker.read_text() == '{"state": "idle"}'
    with factory() as s:
        assert s.get(m.OperationRuntime, a).restore_done_at is not None


def test_estado_real_a_partir_dos_containers():
    def c(state, health=""):
        return {"service": "x", "state": state, "health": health}

    assert state_of([]) == "absent"
    assert state_of([c("running", "healthy")] * 3) == "running"
    assert state_of([c("running", "starting"), c("running", "healthy")]) == "starting"
    assert state_of([c("running", "unhealthy")]) == "degraded"
    assert state_of([c("running"), c("exited")]) == "degraded"
    assert state_of([c("restarting")]) == "degraded"
    assert state_of([c("exited"), c("exited")]) == "stopped"
