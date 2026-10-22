"""The model files, each pinned to one commit, so a start never needs the internet (HF_HUB_OFFLINE=1) and never picks up a
changed model. `python -m aikos_tts fetch --engine X` downloads them once; the installer does it.

Libraries that load a second repository by name (mlx-audio's S3TokenizerV2) ask for "main": the cache's main is pointed at
the pinned commit, so they get exactly that one, offline.
"""

from __future__ import annotations

from pathlib import Path

PINS: dict[str, list[tuple[str, str, list[str] | None]]] = {
    "chatterbox": [("ResembleAI/chatterbox", "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18",
                    ["ve.pt", "t3_mtl23ls_v2.safetensors", "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json", "conds.pt",
                     "Cangjie5_TC.json"])],
    "chatterbox-mlx": [("mlx-community/chatterbox-multilingual-v3", "03565773edd72e949572557597af8063bb49a18a", None),
                       ("mlx-community/S3TokenizerV2", "e0c9886f0e1c35ae85b1f27277416fb19fc72bec", None)],
}


def revision(engine: str) -> str:
    """For the health answer: which model, at which commit."""
    return ", ".join(f"{repo}@{rev[:12]}" for repo, rev, _ in PINS.get(engine, []))


def _point_main(repo: str, rev: str) -> None:
    from huggingface_hub import constants
    refs = Path(constants.HF_HUB_CACHE) / f"models--{repo.replace('/', '--')}" / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(rev, encoding="ascii")


def fetch(engine: str) -> list[Path]:
    """Download the engine's pinned files (online, once)."""
    from huggingface_hub import snapshot_download
    out = []
    for repo, rev, patterns in PINS[engine]:
        out.append(Path(snapshot_download(repo_id=repo, revision=rev, allow_patterns=patterns)))
        _point_main(repo, rev)
    return out


def local(engine: str, index: int = 0) -> Path:
    """Where a pinned repository lies in the cache; raises if it was never fetched."""
    from huggingface_hub import snapshot_download
    repo, rev, patterns = PINS[engine][index]
    return Path(snapshot_download(repo_id=repo, revision=rev, allow_patterns=patterns, local_files_only=True))
