from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Union


def resolve_config_paths(cfg: Any, base_dir: Path) -> None:
    """Resolve relative dataset paths against the config file directory."""
    ds = cfg.dataset
    for attr in ("queries_path", "corpus_path", "qrels_path"):
        value = getattr(ds, attr, None)
        if value and not Path(value).is_absolute():
            setattr(ds, attr, str((base_dir / value).resolve()))


def prepare_config_runtime(
    cfg: Any,
    config_base_dir: Union[str, Path, None],
) -> None:
    """Apply CLI-equivalent path resolution and sys.path setup for adapter.import factories."""
    if not config_base_dir:
        return
    base = Path(config_base_dir).resolve()
    resolve_config_paths(cfg, base)
    config_dir = str(base)
    if config_dir not in sys.path:
        sys.path.insert(0, config_dir)
