"""Short com várias imagens e música aleatória (Task 39)."""

import subprocess

from sqlalchemy import select

import core.models as m
from core.editor import preset as pr
from core.editor import render as rd
from tests.test_render_job import (  # noqa: F401
    factory,
    make_video,
    pytestmark,
    run,
    setup,
    state,
    storage,
)


def make_image(path, color="red", size="640x360"):
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color={color}:s={size}"]
        + ["-frames:v", "1", str(path)],
        check=True,
    )
    return path


def make_audio(path, seconds=3):
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=duration={seconds}"]
        + [str(path)],
        check=True,
    )
    return path


def add_images(factory, storage, tmp_path, op_id, count, first_item_id):
    """Cria `count` imagens elegíveis na operação (além do item de vídeo do setup)."""
    ids = []
    with factory() as s:
        template = s.get(m.Item, first_item_id)
        for i in range(count):
            key = f"operations/{op_id}/items/img{i}/original.jpg"
            storage.put_file(key, make_image(tmp_path / f"i{i}.jpg", size=f"{500 + i * 40}x400"))
            item = m.Item(
                operation_id=op_id,
                execution_id=template.execution_id,
                source_id=template.source_id,
                external_id=f"img{i}",
                media_type="image",
                status="eligible",
                original_file=key,
            )
            s.add(item)
            s.flush()
            ids.append(item.id)
        s.commit()
    return ids


def test_validacao_do_preset():
    assert pr.validate({"video": {"group_images": 5}}) == []
    assert pr.validate({"video": {"group_images": 0}}) == []
    assert any("Agrupar imagens" in e for e in pr.validate({"video": {"group_images": 1}}))
    assert any("Agrupar imagens" in e for e in pr.validate({"video": {"group_images": 21}}))
    assert any("Música aleatória" in e for e in pr.validate({"audio": {"mode": "random"}}))
    ok = pr.validate({"audio": {"mode": "random", "library": ["music/a.mp3"]}})
    assert ok == []


def test_slideshow_tem_a_duracao_de_n_imagens_com_e_sem_musica(tmp_path):
    images = [make_image(tmp_path / f"i{i}.jpg", c) for i, c in enumerate(("red", "blue", "green"))]
    preset = pr.resolve({"video": {"width": 360, "height": 640, "image_duration_s": 2}})
    for music, expects_audio in ((None, False), (make_audio(tmp_path / "m.wav"), True)):
        plan = rd.plan_slideshow(preset, images, tmp_path / "o.mp4", replacement_audio=music)
        rd.run(plan)
        info = rd.analyze(tmp_path / "o.mp4", "video")
        assert abs(info.duration - 6) < 0.5 and info.has_audio is expects_audio


def test_slideshow_respeita_o_limite_da_rede(tmp_path):
    images = [make_image(tmp_path / f"i{i}.jpg") for i in range(4)]
    preset = pr.resolve({"video": {"image_duration_s": 30}})
    plan = rd.plan_slideshow(preset, images, tmp_path / "o.mp4", max_duration_s=60)
    assert plan.duration == 60 and any("reduzida" in w for w in plan.warnings)


def test_agrupa_n_imagens_num_unico_video(factory, storage, tmp_path):  # noqa: F811
    group = {"video": {"group_images": 3, "image_duration_s": 1}}
    op_id, video_id, _ = setup(factory, storage, tmp_path, preset=group)
    first, second, third, fourth = add_images(factory, storage, tmp_path, op_id, 4, video_id)
    run(factory, storage, first)
    lead, renders = state(factory, first)
    assert lead.status == "awaiting_approval" and [r.status for r in renders] == ["ok"]
    with factory() as s:
        statuses = {i.id: i.status for i in s.scalars(select(m.Item))}
    assert statuses[second] == statuses[third] == "grouped"  # entraram no vídeo do primeiro
    assert statuses[fourth] == "eligible" and statuses[video_id] == "eligible"  # ficam para depois
    assert renders[0].qa_result["passed"] is True
    out = tmp_path / "out.mp4"
    storage.get_file(renders[0].output_file, out)
    assert abs(rd.analyze(out, "video").duration - 3) < 0.5


def test_sem_imagens_suficientes_espera_sem_falhar(factory, storage, tmp_path):  # noqa: F811
    group = {"video": {"group_images": 5}}
    op_id, video_id, _ = setup(factory, storage, tmp_path, preset=group)
    first, second = add_images(factory, storage, tmp_path, op_id, 2, video_id)
    assert run(factory, storage, first) is None
    item, renders = state(factory, first)
    assert item.status == "eligible" and renders == []
    assert state(factory, second)[0].status == "eligible"


def test_render_que_falha_devolve_as_imagens_extras(factory, storage, tmp_path):  # noqa: F811
    group = {"video": {"group_images": 2}}
    op_id, video_id, _ = setup(factory, storage, tmp_path, preset=group)
    first, second = add_images(factory, storage, tmp_path, op_id, 2, video_id)
    with factory() as s:  # arquivo corrompido na segunda imagem
        key = s.get(m.Item, second).original_file
    storage.put_file(key, tmp_path / "i0.jpg")
    (tmp_path / "bad.jpg").write_bytes(b"nao e imagem")
    storage.put_file(key, tmp_path / "bad.jpg")
    run(factory, storage, first)
    assert state(factory, first)[0].status in ("needs_fix", "eligible")
    assert state(factory, second)[0].status == "eligible"  # voltou para a pesca


def test_musica_aleatoria_sorteia_da_biblioteca_e_sem_musica_fica_mudo(  # noqa: F811
    factory, storage, tmp_path
):
    storage.put_file("music/a.wav", make_audio(tmp_path / "a.wav"))
    storage.put_file("music/b.wav", make_audio(tmp_path / "b.wav"))
    random_mode = {"audio": {"mode": "random", "library": ["music/a.wav", "music/b.wav"]}}
    op_id, video_id, _ = setup(factory, storage, tmp_path, preset=random_mode, audio=False)
    run(factory, storage, video_id)
    renders = state(factory, video_id)[1]
    out = tmp_path / "r.mp4"
    storage.get_file(renders[0].output_file, out)
    assert rd.analyze(out, "video").has_audio is True  # vídeo sem som ganhou a música sorteada
    chosen = {
        pick
        for pick in (
            __import__("worker.render", fromlist=["x"]).pick_music(pr.resolve(random_mode))
            for _ in range(40)
        )
    }
    assert chosen == {"music/a.wav", "music/b.wav"}


def test_sem_musica_o_video_fica_mudo(factory, storage, tmp_path):  # noqa: F811
    mute = {"audio": {"mode": "remove"}}
    _, item_id, _ = setup(factory, storage, tmp_path, preset=mute)
    run(factory, storage, item_id)
    out = tmp_path / "r2.mp4"
    storage.get_file(state(factory, item_id)[1][0].output_file, out)
    assert rd.analyze(out, "video").has_audio is False
