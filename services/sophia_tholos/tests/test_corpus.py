from __future__ import annotations

from pathlib import Path

from sophia_tholos.core import corpus as corpus_module


def test_init_engine_falls_back_to_lexical_only_when_embeddings_fail(
    monkeypatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chunks.sqlite"
    npz_path = tmp_path / "embeddings.npz"
    db_path.write_text("db", encoding="utf-8")
    npz_path.write_text("npz", encoding="utf-8")

    calls: list[tuple[Path, Path | None, str]] = []

    class _FakeEngine:
        def __init__(
            self,
            *,
            db_path: Path,
            npz_path: Path | None,
            model_name: str,
            semantic_enabled: bool = True,
            semantic_local_files_only: bool = False,
            model_cache_dir: Path | None = None,
        ) -> None:
            calls.append((Path(db_path), Path(npz_path) if npz_path else None, model_name))
            if npz_path is not None:
                raise RuntimeError("bad npz")
            self.chunk_count = 7
            self.npz_dims = None

    monkeypatch.setattr(corpus_module, "HybridSearchEngine", _FakeEngine)
    monkeypatch.setattr(corpus_module, "_engine", None)

    corpus_module.init_engine(str(db_path), str(npz_path), model_name="test-model")

    assert len(calls) == 2
    assert calls[0] == (db_path, npz_path, "test-model")
    assert calls[1] == (db_path, None, "test-model")
    assert corpus_module.get_engine() is not None
