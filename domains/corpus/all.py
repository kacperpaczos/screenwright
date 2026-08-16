"""Orkiestracja korpusu (CLI: `python -m cli collect`)."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from shared.http_client import HttpClient
from shared.logging import log_entry
from shared.media import fetch_to_corpus
from shared.pydantic_utils import strict_validate
from shared.types import AppId

from domains.corpus.index import IndexWriter
from domains.corpus.models import CorpusEntry
from domains.corpus.sources.debian import DebianSource
from domains.corpus.sources.elementary import ElementarySource
from domains.corpus.sources.fedora import FedoraSource
from domains.corpus.sources.flathub import FlathubSource
from domains.corpus.sources.mint import MintSource
from domains.corpus.sources.snap import SnapSource
from domains.corpus.sources.ubuntu_dep11 import UbuntuDep11Source

SOURCE_REGISTRY: dict[str, type] = {
    "fedora": FedoraSource,
    "flathub": FlathubSource,
    "ubuntu": UbuntuDep11Source,
    "snap": SnapSource,
    "debian": DebianSource,
    "mint": MintSource,
    "elementary": ElementarySource,
}


@dataclass(frozen=True)
class CollectSpec:
    apps: tuple[AppId, ...]
    distros: tuple[str, ...]
    output_root: Path
    dry_run: bool = False
    download_media: bool = False

    @classmethod
    def from_cli(
        cls,
        apps: Iterable[str],
        distros: Iterable[str],
        output_root: Path,
        dry_run: bool = False,
        download_media: bool = False,
    ) -> "CollectSpec":
        return cls(
            apps=tuple(AppId(a) for a in apps),
            distros=tuple(distros),
            output_root=output_root,
            dry_run=dry_run,
            download_media=download_media,
        )


class CollectRunner:
    def __init__(
        self,
        spec: CollectSpec,
        *,
        client: HttpClient | None = None,
    ) -> None:
        self._spec = spec
        self._client = client or HttpClient()

    def run(self) -> dict[str, int]:
        results: dict[str, int] = {d: 0 for d in self._spec.distros}
        writer = IndexWriter(self._spec.output_root)
        if not self._spec.dry_run:
            writer.root.mkdir(parents=True, exist_ok=True)
        for app in self._spec.apps:
            for distro_name in self._spec.distros:
                source_cls = SOURCE_REGISTRY.get(distro_name)
                if source_cls is None:
                    log_entry(40, "corpus.unknown_distro", distro=distro_name)
                    continue
                source = source_cls(client=self._client)
                raw_entries = source.fetch(app)
                if not raw_entries:
                    continue
                if self._spec.download_media and not self._spec.dry_run:
                    raw_entries = fetch_to_corpus(raw_entries, writer.root, client=self._client)
                for raw in raw_entries:
                    try:
                        entry = strict_validate(CorpusEntry, raw)
                    except Exception as exc:
                        log_entry(
                            20,
                            "corpus.entry_invalid",
                            error=str(exc),
                            app=app,
                            distro=distro_name,
                        )
                        continue
                    if not self._spec.dry_run:
                        writer.append(entry)
                    results[distro_name] += 1
        if not self._spec.dry_run:
            writer.flush()
        return results


__all__ = ["SOURCE_REGISTRY", "CollectRunner", "CollectSpec"]
