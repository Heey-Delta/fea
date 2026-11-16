"""Pesca (Tasks 6 e 7): regras do item, hashes, duplicados e o Buscador de ponta a ponta."""

import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, text

import core.models as m
from core import executions, fishing
from core import operations as ops
from core.config import Settings
from core.operations import OperationError
from core.storage import LocalStorage
from tests.test_sources import FakeReddit, video_post

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg não instalado")
DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL não definida")


# --- texto e mídia ----------------------------------------------------------------------


def test_classify_scores_tags_and_heat_tags_without_accents():
    result = fishing.classify_text(
        "Treino de MUSCULAÇÃO e memes de academia",
        ["musculacao", "luta"],
        ["memes de academia"],
        [],
    )
    assert result == fishing.TextResult(3, None)


def test_classify_rejects_blocked_word_and_out_of_niche():
    assert fishing.classify_text("conteúdo NSFW aqui", [], [], ["nsfw"]).reject_reason == (
        "palavra bloqueada: nsfw"
    )
    assert fishing.classify_text("receita de bolo", ["academia"], [], []).reject_reason == (
        "fora do nicho"
    )


def test_classify_matches_whole_words_only():
    assert fishing.classify_text("lutador", ["luta"], [], []).score == 0
    assert fishing.classify_text("luta!", ["luta"], [], []).score == 1


def test_no_tags_accepts_everything():
    assert fishing.classify_text("qualquer coisa", [], [], []) == fishing.TextResult(0, None)


def test_check_media():
    assert fishing.check_media("image", None, ["video"], 60) == "mídia não aceita: image"
    assert "acima do limite" in fishing.check_media("video", 90, ["video"], 60)
    assert fishing.check_media("video", 30, ["video"], 60) is None


# --- arquivos e hashes ------------------------------------------------------------------


def make_video(path: Path, source: str, crf: int = 23) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"{source}=size=320x568:rate=30:duration=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            str(crf),
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg não instalado")
    d = tmp_path_factory.mktemp("media")
    return {
        "a": make_video(d / "a.mp4", "testsrc"),
        "a_reencoded": make_video(d / "a2.mp4", "testsrc", crf=35),
        "b": make_video(d / "b.mp4", "testsrc2"),
        "c": make_video(d / "c.mp4", "smptebars"),
        "d": make_video(d / "d.mp4", "rgbtestsrc"),
    }


def test_video_phash_has_three_frames(media):
    assert len(fishing.video_phash(media["a"])) == 48


def test_reencoded_video_is_similar_and_other_is_not(media):
    a = fishing.video_phash(media["a"])
    assert fishing.phash_distance(a, fishing.video_phash(media["a_reencoded"])) <= 6
    assert fishing.phash_distance(a, fishing.video_phash(media["b"])) > 6


def test_phash_of_video_and_image_are_not_compared():
    assert fishing.phash_distance("0" * 48, "0" * 16) is None


def test_invalid_file_raises(tmp_path):
    bad = tmp_path / "x.mp4"
    bad.write_bytes(b"isso nao e video")
    with pytest.raises(ValueError):
        fishing.video_duration(bad)


# --- Buscador de ponta a ponta ----------------------------------------------------------


@pytest.fixture
def factory():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.db import sqlalchemy_url

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url(DATABASE_URL))
    command.upgrade(cfg, "head")
    engine = create_engine(sqlalchemy_url(DATABASE_URL))
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE operations, jobs, events RESTART IDENTITY CASCADE"))
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


SETTINGS = Settings(_env_file=None, reddit_client_id="id", reddit_client_secret="s")


def setup_operation(factory, rules=None, permission="autorizado", reference="r/GymMemes"):
    config = ops.default_config()
    config["nodes"][0]["config"].update(
        {"tags": ["academia"], "heat_tags": ["supino"], "blocked_words": ["nsfw"], **(rules or {})}
    )
    config["nodes"] += [
        {
            "id": "f1",
            "type": "source",
            "config": {"type": "reddit", "reference": reference, "permission_note": permission},
        },
        {"id": "c1", "type": "account", "config": {}},
    ]
    config["edges"] += [{"from": "f1", "to": "pesca"}, {"from": "c1", "to": "postagem"}]
    with factory() as s:
        op = ops.create_operation(s, "Op", config)
        ops.change_status(s, op, "active")
        s.commit()
        return op.id


def post(post_id, title):
    return video_post(post_id, title=title)


def reddit_with(media, posts_files):
    files = {}
    posts = []
    for post_id, title, video in posts_files:
        posts.append(post(post_id, title))
        if video is not None:
            files[f"https://v.redd.it/{post_id}/DASH_720.mp4"] = Path(video).read_bytes()
    return FakeReddit(posts=posts, files=files)


def run(factory, op_id, fake, tmp_path, **play):
    from worker.collect import run_collect

    with factory() as s:
        ex = executions.start_execution(s, s.get(m.Operation, op_id), **play)
        s.commit()
        ex_id = ex.id
    storage = LocalStorage(tmp_path / "storage")
    kwargs = {"client": httpx.Client(transport=httpx.MockTransport(fake)), "sleep": lambda s: None}
    progress = run_collect(factory, ex_id, SETTINGS, storage, kwargs)
    return ex_id, progress, storage


def items_by_external(factory, ex_id):
    with factory() as s:
        rows = s.scalars(select(m.Item).where(m.Item.execution_id == ex_id)).all()
        return {i.external_id: i for i in rows}


def render_jobs(factory):
    with factory() as s:
        return sorted(s.scalars(select(m.Job.ref_id).where(m.Job.type == "render")).all())


@needs_db
@needs_ffmpeg
def test_collect_applies_every_rule(factory, media, tmp_path):
    op_id = setup_operation(factory)
    fake = reddit_with(
        media,
        [
            ("p1", "Dia de academia", media["a"]),
            ("p2", "Receita de bolo", media["b"]),  # fora do nicho
            ("p3", "academia nsfw", media["c"]),  # palavra bloqueada
            ("p4", "academia de novo", media["a"]),  # mesmo arquivo de p1
            ("p5", "academia reencodado", media["a_reencoded"]),  # parecido com p1
            ("p6", "supino na academia", media["d"]),
        ],
    )
    ex_id, progress, storage = run(factory, op_id, fake, tmp_path, target_x=5)
    found = items_by_external(factory, ex_id)
    status = {k: (v.status, v.status_reason) for k, v in found.items()}
    assert status["p1"] == ("eligible", None)
    assert status["p2"] == ("rejected", "fora do nicho")
    assert status["p3"] == ("rejected", "palavra bloqueada: nsfw")
    assert status["p4"][0] == "duplicate" and status["p4"][1] == "mesmo arquivo"
    assert status["p5"][0] == "duplicate" and status["p5"][1].startswith("imagem parecida")
    assert found["p4"].duplicate_of == found["p1"].id
    assert found["p6"].score == 3  # academia (1) + supino (2)
    assert storage.exists(found["p1"].original_file)
    assert found["p1"].sha256 and len(found["p1"].phash) == 48
    # Fontes esgotadas antes de X: parcial, com o motivo.
    with factory() as s:
        ex = s.get(m.Execution, ex_id)
        assert ex.status == "partial" and "2 elegíveis de 5" in ex.shortfall_reason
        counts = executions.counters(s, ex_id)
    assert counts["examinados"] == 6 and counts["elegiveis"] == 2
    assert counts["duplicados"] == 2 and counts["rejeitados"] == 2
    assert render_jobs(factory) == sorted([found["p1"].id, found["p6"].id])


@needs_db
@needs_ffmpeg
def test_second_play_skips_posts_already_seen(factory, media, tmp_path):
    op_id = setup_operation(factory)
    fake = reddit_with(media, [("p1", "academia", media["a"])])
    run(factory, op_id, fake, tmp_path, target_x=1)
    ex_id, progress, _ = run(factory, op_id, fake, tmp_path, target_x=1)
    assert progress.already_seen == 1 and items_by_external(factory, ex_id) == {}
    with factory() as s:
        assert executions.counters(s, ex_id)["duplicados"] == 1


@needs_db
@needs_ffmpeg
def test_recent_stops_at_target(factory, media, tmp_path):
    op_id = setup_operation(factory)
    fake = reddit_with(
        media,
        [
            ("p1", "academia", media["a"]),
            ("p2", "academia", media["b"]),
            ("p3", "academia", media["c"]),
        ],
    )
    ex_id, progress, _ = run(factory, op_id, fake, tmp_path, target_x=2)
    assert progress.examined == 2
    with factory() as s:
        assert s.get(m.Execution, ex_id).status == "completed"


@needs_db
@needs_ffmpeg
def test_heat_criteria_picks_highest_scores(factory, media, tmp_path):
    op_id = setup_operation(factory)
    fake = reddit_with(
        media,
        [
            ("p1", "academia", media["a"]),
            ("p2", "supino academia", media["b"]),
            ("p3", "supino", media["c"]),
            ("p4", "academia", media["d"]),
        ],
    )
    ex_id, _, _ = run(factory, op_id, fake, tmp_path, target_x=2, criteria="heat")
    found = items_by_external(factory, ex_id)
    assert render_jobs(factory) == sorted([found["p2"].id, found["p3"].id])
    assert found["p1"].status_reason == "reserva" and found["p4"].status_reason == "reserva"
    with factory() as s:
        assert executions.counters(s, ex_id)["reserva"] == 2


@needs_db
@needs_ffmpeg
def test_budget_limits_examined_posts(factory, media, tmp_path):
    op_id = setup_operation(factory)
    fake = reddit_with(
        media,
        [("p1", "bolo", media["a"]), ("p2", "bolo", media["b"]), ("p3", "academia", media["c"])],
    )
    ex_id, progress, _ = run(factory, op_id, fake, tmp_path, target_x=5, search_budget=2)
    assert progress.examined == 2
    with factory() as s:
        assert "orçamento de 2 itens esgotado" in s.get(m.Execution, ex_id).shortfall_reason


@needs_db
def test_source_without_permission_is_pending_and_not_downloaded(factory, tmp_path):
    op_id = setup_operation(factory, permission="")
    fake = FakeReddit(posts=[post("p1", "academia")])
    ex_id, _, _ = run(factory, op_id, fake, tmp_path, target_x=1)
    assert items_by_external(factory, ex_id)["p1"].status == "pending_permission"
    assert not any(c.url.host == "v.redd.it" for c in fake.calls)


@needs_db
def test_broken_source_is_marked_and_execution_ends(factory, tmp_path):
    op_id = setup_operation(factory)
    fake = FakeReddit(listing_status=404)
    ex_id, _, _ = run(factory, op_id, fake, tmp_path, target_x=1)
    with factory() as s:
        source = s.scalars(select(m.Source)).one()
        assert source.status == "error" and "Comunidade" in source.last_error
        assert s.get(m.Execution, ex_id).status == "partial"


@needs_db
def test_cancelled_execution_does_nothing(factory, tmp_path):
    from worker.collect import run_collect

    op_id = setup_operation(factory)
    with factory() as s:
        ex = executions.start_execution(s, s.get(m.Operation, op_id), target_x=1)
        executions.cancel(s, ex)
        s.commit()
        ex_id = ex.id
    fake = FakeReddit()
    run_collect(
        factory,
        ex_id,
        SETTINGS,
        LocalStorage(tmp_path),
        {"client": httpx.Client(transport=httpx.MockTransport(fake))},
    )
    assert fake.calls == []
    with factory() as s:
        job = s.scalars(select(m.Job).where(m.Job.type == "collect")).one()
        assert job.status == "cancelled"


@needs_db
def test_play_requires_active_operation_and_valid_values(factory):
    with factory() as s:
        op = ops.create_operation(s, "Rascunho")
        with pytest.raises(OperationError, match="ativas"):
            executions.start_execution(s, op)


@needs_db
def test_play_uses_fishing_defaults_and_enqueues_once(factory):
    op_id = setup_operation(factory, rules={"target_x": 7, "search_budget": 70})
    with factory() as s:
        ex = executions.start_execution(s, s.get(m.Operation, op_id))
        s.commit()
        assert (ex.target_x, ex.search_budget, ex.criteria) == (7, 70, "recent")
        jobs = s.scalars(select(m.Job).where(m.Job.execution_id == ex.id)).all()
        assert [(j.type, j.idempotency_key) for j in jobs] == [("collect", f"collect:{ex.id}")]


@needs_db
def test_pause_resume_cancel(factory):
    op_id = setup_operation(factory)
    with factory() as s:
        ex = executions.start_execution(s, s.get(m.Operation, op_id))
        executions.pause(s, ex)
        with pytest.raises(OperationError):
            executions.pause(s, ex)
        executions.resume(s, ex)
        executions.cancel(s, ex)
        with pytest.raises(OperationError):
            executions.cancel(s, ex)
        s.commit()
        assert ex.status == "cancelled" and ex.finished_at is not None


# --- interface do Play ------------------------------------------------------------------


@needs_db
def test_play_from_the_interface(factory, logged_client):
    op_id = setup_operation(factory)
    form = logged_client.get(f"/operacoes/{op_id}/play")
    assert form.status_code == 200 and "r/GymMemes" in form.text
    with factory() as s:
        source_id = s.scalars(select(m.Source.id)).one()
    started = logged_client.post(
        f"/operacoes/{op_id}/play",
        data={
            "target_x": 3,
            "search_budget": 50,
            "criteria": "heat",
            "priority": "high",
            "source_ids": [source_id],
        },
        follow_redirects=False,
    )
    assert started.status_code == 303
    page = logged_client.get(started.headers["location"])
    assert "Rodando" in page.text and "de <strong>3</strong> elegíveis" in page.text
    with factory() as s:
        ex = s.scalars(select(m.Execution)).one()
        assert (ex.criteria, ex.priority, ex.source_ids) == ("heat", "high", [source_id])
    paused = logged_client.post(f"/execucoes/{ex.id}/pausar")
    assert "Pausada" in paused.text and "Retomar" in paused.text
    cancelled = logged_client.post(f"/execucoes/{ex.id}/cancelar")
    assert "Cancelada" in cancelled.text
    tab = logged_client.get(f"/operacoes/{op_id}?aba=execucoes")
    assert f"#{ex.id}" in tab.text


@needs_db
def test_play_page_refuses_inactive_operation(factory, logged_client):
    with factory() as s:
        op = ops.create_operation(s, "Rascunho")
        s.commit()
        op_id = op.id
    assert "Só operações ativas" in logged_client.get(f"/operacoes/{op_id}/play").text
    refused = logged_client.post(
        f"/operacoes/{op_id}/play", data={"target_x": 1, "search_budget": 1}
    )
    assert "Só operações ativas aceitam Play" in refused.text


@needs_db
def test_unknown_execution_action(factory, logged_client):
    op_id = setup_operation(factory)
    with factory() as s:
        ex = executions.start_execution(s, s.get(m.Operation, op_id))
        s.commit()
    assert logged_client.post(f"/execucoes/{ex.id}/explodir").status_code == 404
