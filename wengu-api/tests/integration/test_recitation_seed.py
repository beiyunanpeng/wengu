"""课标词表灌库：三级查重、原文保真、共用队列与真仓互证。"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from types import MappingProxyType

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine
from app.models import Mistake, RecitationItem
from app.seed.vocab import (
    VocabExamBadges,
    VocabIndex,
    VocabStats,
    VocabWord,
    load_vocab,
)
from app.services.recitation import (
    create_item,
    due_items,
    extract_word_candidates,
)
from app.services.recitation_seed import VocabSeedReport, seed_vocab_items
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[3]
SEEDS_DIR = REPO_ROOT / "seeds"
NOW = datetime(2026, 11, 27, 8, 0, tzinfo=UTC)
TODAY = date(2026, 11, 27)

pytestmark = pytest.mark.integration


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "recitation-seed.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


def _word(
    word: str,
    *,
    stages: tuple[str, ...] = ("junior",),
    translation: str | None = "词义",
) -> VocabWord:
    return VocabWord(
        word=word,
        forms=(word,),
        stages=stages,
        senior_tier=None,
        block=None,
        unaudited=False,
        matched=word if translation is not None else None,
        match_kind="whole" if translation is not None else None,
        phonetic=None,
        definition=None,
        translation=translation,
        pos=None,
        exchange=None,
        collins=None,
        oxford=None,
        exam_badges=VocabExamBadges(collins=None, oxford=None, tags=()),
        bnc=None,
        frq=None,
        root_family=(),
        root_meaning=None,
    )


def _index(*words: VocabWord) -> VocabIndex:
    by_stage = MappingProxyType(
        {
            stage: sum(stage in word.stages for word in words)
            for stage in ("primary", "junior", "senior")
        }
    )
    stats = VocabStats(
        total=len(words),
        primary=by_stage["primary"],
        junior=by_stage["junior"],
        senior=by_stage["senior"],
        supplement=0,
        matched=sum(word.matched is not None for word in words),
        no_detail=sum(word.translation is None for word in words),
        rootless=len(words),
        root_families=0,
        root_word_nodes=0,
        wordroot_entries=0,
        missing=(),
        by_stage=by_stage,
    )
    return VocabIndex(
        words=tuple(words),
        by_word=MappingProxyType({word.word: word for word in words}),
        stats=stats,
    )


async def _items(factory: async_sessionmaker) -> list[RecitationItem]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(RecitationItem).order_by(RecitationItem.id)
                )
            ).all()
        )


async def _mistake_count(factory: async_sessionmaker) -> int:
    async with factory() as session:
        return int(
            await session.scalar(select(func.count()).select_from(Mistake)) or 0
        )


async def test_create_item_source_defaults_to_manual_and_accepts_seed(
    tmp_path: Path,
) -> None:
    factory = _migrated(tmp_path)

    async with factory() as session, session.begin():
        manual = await create_item(session, subject="英语", prompt="manual")
        seed = await create_item(
            session,
            subject="英语",
            prompt="seed",
            source="seed",
            now=NOW,
        )

    assert manual.source == "manual"
    assert seed.source == "seed"
    assert seed.created_at == NOW


async def test_seed_import_is_idempotent(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    index = _index(_word("alpha"), _word("beta"))

    async with factory() as session, session.begin():
        first = await seed_vocab_items(
            session, vocab_index=index, ceiling=9, now=NOW
        )
    async with factory() as session, session.begin():
        second = await seed_vocab_items(
            session, vocab_index=index, ceiling=9, now=NOW
        )

    assert first == VocabSeedReport(
        band=9,
        seen=2,
        created=2,
        duplicate_exact=0,
        duplicate_casefold=0,
        null_answer=0,
    )
    assert second.created == 0
    assert second.duplicate_exact == first.seen
    assert second.seen == (
        second.created + second.duplicate_exact + second.duplicate_casefold
    )
    with pytest.raises(FrozenInstanceError):
        second.created = 1  # type: ignore[misc]


async def test_seed_case_variants_coexist_and_share_due_queue(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    index = _index(
        _word("miss", translation="漏掉"),
        _word("Miss", translation="小姐"),
    )

    async with factory() as session, session.begin():
        report = await seed_vocab_items(
            session, vocab_index=index, ceiling=9, now=NOW
        )
    rows = await _items(factory)
    async with factory() as session:
        due = await due_items(session, TODAY, daily_limit=20)

    assert report.created == 2
    assert report.duplicate_casefold == 0
    assert [(row.prompt, row.source) for row in rows] == [
        ("miss", "seed"),
        ("Miss", "seed"),
    ]
    assert [row.answer for row in rows] == ["漏掉", "小姐"]
    assert {entry.item.prompt for entry in due.items} == {"miss", "Miss"}
    assert due.due_total == 2


async def test_nonseed_casefold_collision_skips_without_mutation(
    tmp_path: Path,
) -> None:
    factory = _migrated(tmp_path)
    index = _index(_word("China", translation="中国"))

    async with factory() as session, session.begin():
        existing = await create_item(
            session,
            subject="英语",
            prompt="china",
            answer="原有释义",
            now=NOW,
        )
        existing_id = existing.id
        report = await seed_vocab_items(
            session, vocab_index=index, ceiling=9, now=NOW
        )
    rows = await _items(factory)

    assert report.created == 0
    assert report.duplicate_casefold == 1
    assert len(rows) == 1
    assert rows[0].id == existing_id
    assert rows[0].prompt == "china"
    assert rows[0].answer == "原有释义"
    assert rows[0].source == "manual"


async def test_retired_exact_row_is_skipped_and_not_reactivated(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    index = _index(_word("retired"))

    async with factory() as session, session.begin():
        existing = await create_item(
            session, subject="英语", prompt="retired", now=NOW
        )
        existing.status = "retired"
        await session.flush()
        report = await seed_vocab_items(
            session, vocab_index=index, ceiling=9, now=NOW
        )
        await session.refresh(existing)

    assert report.created == 0
    assert report.duplicate_exact == 1
    assert existing.status == "retired"
    assert existing.source == "manual"


async def test_multiword_prompt_is_preserved_verbatim(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    phrase = "new zealand"
    index = _index(_word(phrase, stages=("senior",), translation="新西兰"))

    async with factory() as session, session.begin():
        report = await seed_vocab_items(
            session, vocab_index=index, ceiling=16, now=NOW
        )
    rows = await _items(factory)

    assert report.created == 1
    assert len(rows) == 1
    assert rows[0].prompt == phrase
    assert rows[0].source == "seed"


async def test_null_answer_and_crlf_translation_are_preserved(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    translation = "一个\r\nart. 一"
    index = _index(
        _word("a/an", stages=("primary",), translation=translation),
        _word("rootless", stages=("primary",), translation=None),
    )

    async with factory() as session, session.begin():
        report = await seed_vocab_items(
            session, vocab_index=index, ceiling=6, now=NOW
        )
    rows = await _items(factory)

    assert report.null_answer == 1
    assert [(row.prompt, row.answer) for row in rows] == [
        ("a/an", translation),
        ("rootless", None),
    ]


async def test_seed_import_does_not_write_mistakes(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    index = _index(_word("alpha"))
    before = await _mistake_count(factory)

    async with factory() as session, session.begin():
        await seed_vocab_items(session, vocab_index=index, ceiling=9, now=NOW)
    after = await _mistake_count(factory)

    assert after == before


async def test_explicit_ceiling_six_imports_only_primary(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    index = _index(
        _word("primary", stages=("primary",)),
        _word("junior", stages=("junior",)),
        _word("senior", stages=("senior",)),
    )

    async with factory() as session, session.begin():
        report = await seed_vocab_items(
            session, vocab_index=index, ceiling=6, now=NOW
        )
    rows = await _items(factory)

    assert report.band == 6
    assert report.seen == 1
    assert [row.prompt for row in rows] == ["primary"]


async def test_default_ceiling_uses_hot_runtime_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _migrated(tmp_path)
    config_path = tmp_path / "app-config.json"
    with config_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"seed_grade_ceiling": 6}))
    monkeypatch.setenv("WENGU_APP_CONFIG", str(config_path))
    index = _index(
        _word("primary", stages=("primary",)),
        _word("junior", stages=("junior",)),
    )

    async with factory() as session, session.begin():
        report = await seed_vocab_items(session, vocab_index=index, now=NOW)
    rows = await _items(factory)

    assert report.band == 6
    assert [row.prompt for row in rows] == ["primary"]


async def test_candidate_extraction_excludes_seed_casefold_variant(
    tmp_path: Path,
) -> None:
    factory = _migrated(tmp_path)
    index = _index(_word("China", translation="中国"))

    async with factory() as session, session.begin():
        await seed_vocab_items(session, vocab_index=index, ceiling=9, now=NOW)
    async with factory() as session:
        existing = (
            await session.scalars(
                select(RecitationItem.prompt).where(
                    RecitationItem.subject == "英语"
                )
            )
        ).all()
        candidates = extract_word_candidates(
            ["China china"], existing_prompts=existing
        )

    assert candidates == ()


async def test_real_repository_seed_roundtrip_and_timing(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    index = load_vocab(SEEDS_DIR)
    visible = index.visible(16)
    source = json.loads(
        (SEEDS_DIR / "vocab" / "_source_vocab.json").read_text(encoding="utf-8")
    )
    raw_details = json.loads(
        (SEEDS_DIR / "vocab" / "words.json").read_text(encoding="utf-8")
    )["words"]
    translations = {row["word"]: row.get("translation") for row in raw_details}
    expected_no_detail = set(source["no_detail"])
    mistakes_before = await _mistake_count(factory)

    assert {word.word for word in visible if word.translation is None} == (
        expected_no_detail
    )
    started = perf_counter()
    async with factory() as session, session.begin():
        report = await seed_vocab_items(
            session, vocab_index=index, ceiling=16, now=NOW
        )
    elapsed = perf_counter() - started
    rows = await _items(factory)
    by_prompt = {row.prompt: row for row in rows}
    async with factory() as session:
        due = await due_items(session, TODAY, daily_limit=20)
    mistakes_after = await _mistake_count(factory)

    assert len(rows) == len(visible) == index.stats.total == source["counts"][
        "union"
    ]
    assert set(by_prompt) == {word.word for word in visible}
    assert all(row.subject == "英语" for row in rows)
    assert all(row.source == "seed" for row in rows)
    assert all(row.status == "active" for row in rows)
    assert report.created == len(visible)
    assert report.duplicate_exact == 0
    assert report.duplicate_casefold == 0
    assert report.null_answer == len(expected_no_detail)
    assert {prompt for prompt, row in by_prompt.items() if row.answer is None} == (
        expected_no_detail
    )
    for word in visible:
        assert by_prompt[word.word].answer == translations[word.word]
    assert due.due_total == len(rows)
    assert due.items
    assert all(entry.item.source == "seed" for entry in due.items)
    assert mistakes_after == mistakes_before
    print(
        "real_seed_roundtrip "
        f"band={report.band} seen={report.seen} created={report.created} "
        f"duplicate_exact={report.duplicate_exact} "
        f"duplicate_casefold={report.duplicate_casefold} "
        f"null_answer={report.null_answer} due_total={due.due_total} "
        f"mistakes={mistakes_after} elapsed_seconds={elapsed:.3f}"
    )
