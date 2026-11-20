"""Títulos, descrições e tags (Task 16). Gerados pelo Postador na hora de publicar.

O título nunca vai para dentro do vídeo. Primeiro tenta uma cadeia de Markov de ordem 2 sobre o
corpus (frases do bloco Postagem + textos dos itens da operação). Cada candidato passa por
filtros: tamanho, palavras bloqueadas, não ser cópia de uma frase do corpus e não repetir um
título recente da conta. Se nenhum passar, usa os templates (`title_method = "fallback"`).
"""

import random
import re
from dataclasses import dataclass

START = ("\x02", "\x02")
END = "\x03"
DEFAULT_TEMPLATES = ("{texto}", "Olha isso 👀", "Você precisa ver isso", "Isso é incrível")
DEFAULT_DESCRIPTION = "{titulo}\n\n{hashtags}"
WORD = re.compile(r"\S+")


@dataclass
class Metadata:
    title: str
    description: str
    tags: list[str]
    method: str  # markov | fallback


def tokens(line: str) -> list[str]:
    return WORD.findall(line)


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", text.lower()).split())


class Markov:
    """Cadeia de ordem 2: o próximo token depende dos dois anteriores."""

    def __init__(self, corpus: list[str]):
        self.table: dict[tuple[str, str], list[str]] = {}
        self.lines = [line.strip() for line in corpus if len(tokens(line)) >= 3]
        for line in self.lines:
            words = [*START, *tokens(line), END]
            for a, b, c in zip(words, words[1:], words[2:], strict=False):
                self.table.setdefault((a, b), []).append(c)

    def generate(self, rng: random.Random, max_words: int = 20) -> str:
        state, out = START, []
        for _ in range(max_words):
            options = self.table.get(state)
            if not options:
                break
            word = rng.choice(options)
            if word == END:
                break
            out.append(word)
            state = (state[1], word)
        return " ".join(out)


def is_copy(candidate: str, corpus_norm: set[str], corpus_lines: list[str]) -> bool:
    """Cópia exata, ou 80% das palavras em sequência de uma frase do corpus."""
    norm = normalize(candidate)
    if norm in corpus_norm:
        return True
    words = norm.split()
    for line in corpus_lines:
        other = normalize(line)
        if len(words) >= 4 and norm in other:
            return True
        if (
            words
            and len(set(words) & set(other.split())) / len(words) >= 0.8
            and (abs(len(words) - len(other.split())) <= 1)
        ):
            return True
    return False


def passes(
    title: str,
    *,
    min_chars: int,
    max_chars: int,
    blocked: list[str],
    recent: set[str],
) -> bool:
    if not min_chars <= len(title) <= max_chars:
        return False
    norm = normalize(title)
    if any(normalize(b) and normalize(b) in norm.split() for b in blocked):
        return False
    return norm not in recent


def hashtags_for(config: dict, item_text: str | None, platform_tags: list[str]) -> list[str]:
    tags = [*(config.get("hashtags") or []), *platform_tags]
    seen, out = set(), []
    for tag in tags:
        clean = tag.strip().lstrip("#")
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            out.append(clean)
    return out


def fit_tags(tags: list[str], max_chars: int) -> list[str]:
    """YouTube soma os caracteres de todas as tags (com vírgulas)."""
    out, total = [], 0
    for tag in tags:
        cost = len(tag) + (2 if " " in tag else 0) + (1 if out else 0)
        if total + cost > max_chars:
            break
        out.append(tag)
        total += cost
    return out


def generate(
    config: dict,
    *,
    item_text: str | None,
    corpus: list[str],
    recent_titles: list[str],
    title_max: int = 100,
    description_max: int = 5000,
    tags_max: int = 500,
    platform_tags: list[str] | None = None,
    seed: int | None = None,
) -> Metadata:
    """Título, descrição e tags de um envio. `config` é `titles` do bloco Postagem."""
    rng = random.Random(seed)
    blocked = config.get("blocked_words") or []
    min_chars = int(config.get("min_chars", 15))
    max_chars = min(int(config.get("max_chars", title_max)), title_max)
    recent = {normalize(t) for t in recent_titles if t}
    lines = [*(config.get("corpus") or []), *corpus]
    title, method = None, "fallback"
    if config.get("method", "markov") == "markov" and lines:
        chain = Markov(lines)
        corpus_norm = {normalize(line) for line in chain.lines}
        for _ in range(int(config.get("attempts", 200))):
            candidate = chain.generate(rng)
            if passes(
                candidate, min_chars=min_chars, max_chars=max_chars, blocked=blocked, recent=recent
            ) and not is_copy(candidate, corpus_norm, chain.lines):
                title, method = candidate, "markov"
                break
    if title is None:
        title = fallback_title(config, item_text, rng, max_chars, blocked, recent)
    title = title[:1].upper() + title[1:]
    tags = fit_tags(hashtags_for(config, item_text, platform_tags or []), tags_max)
    hashtags = " ".join(f"#{t.replace(' ', '')}" for t in tags[:5])
    template = config.get("description_template") or DEFAULT_DESCRIPTION
    description = template.replace("{titulo}", title).replace("{hashtags}", hashtags)
    description = description.replace("{texto}", (item_text or "").strip())
    return Metadata(
        title=title, description=description[:description_max].strip(), tags=tags, method=method
    )


def fallback_title(
    config: dict,
    item_text: str | None,
    rng: random.Random,
    max_chars: int,
    blocked: list[str],
    recent: set[str],
) -> str:
    templates = list(config.get("templates") or DEFAULT_TEMPLATES)
    rng.shuffle(templates)
    text = " ".join((item_text or "").split())
    options = []
    for template in templates:
        if "{texto}" in template and not text:
            continue
        title = template.replace("{texto}", text)
        if len(title) > max_chars:
            title = title[: max_chars - 1].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
        options.append(title)
        if passes(title, min_chars=1, max_chars=max_chars, blocked=blocked, recent=recent):
            return title
    return options[0] if options else "Vídeo"
