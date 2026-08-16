"""Domena corpus: modele, porty, identyfikatory, indeks, kolektory."""

from domains.corpus.id_norm import (
    from_canonical,
    strip_desktop_suffix,
    to_canonical,
)
from domains.corpus.index import IndexWriter
from domains.corpus.models import (
    CorpusEntry,
    CorpusIndex,
    Distro,
    SourceKind,
)

__all__ = [
    "CorpusEntry",
    "CorpusIndex",
    "Distro",
    "IndexWriter",
    "SourceKind",
    "from_canonical",
    "strip_desktop_suffix",
    "to_canonical",
]
