"""Policy RAG: chunk coverage policies by criterion and retrieve (plan T2.1).

Each checklist criterion becomes one retrievable chunk, tagged with payer,
procedure and the policy's effective window. Retrieval filters on those tags
*inside* the query, so a search for a case only ever sees the in-force policy
for that payer and procedure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clearance.policies.checklist import Checklist
from clearance.retrieval.hybrid import Document, HybridRetriever


def criterion_chunks(
    checklist: Checklist,
    *,
    payer: str,
    procedure: str,
    version: str,
    effective_from: str | None = None,
    effective_to: str | None = None,
) -> list[Document]:
    docs: list[Document] = []
    for c in checklist.criteria:
        text = c.text
        if c.source_quote:
            text = f"{text}\n\nPolicy basis: {c.source_quote}"
        docs.append(
            Document(
                doc_id=f"{payer}:{procedure}:{version}:{c.id}",
                text=text,
                metadata={
                    "payer": payer,
                    "procedure": procedure,
                    "version": version,
                    "criterion_id": c.id,
                    "kind": c.kind,
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                },
            )
        )
    return docs


class PolicyIndex:
    """A hybrid index over criterion chunks for one or more policies."""

    def __init__(self, retriever: HybridRetriever | None = None) -> None:
        self._retriever = retriever or HybridRetriever()
        self._docs: list[Document] = []

    def add_checklist(self, checklist: Checklist, **meta: Any) -> None:
        self._docs.extend(criterion_chunks(checklist, **meta))
        self._retriever.index(self._docs)

    def search(
        self, query: str, *, payer: str, procedure: str, as_of: str, top_k: int = 5
    ) -> list[dict[str, Any]]:
        where = {"payer": payer, "procedure": procedure, "as_of": as_of}
        hits = self._retriever.search(query, top_k=top_k, where=where)
        return [
            {"criterion_id": h.metadata.get("criterion_id"), "text": h.text, "score": h.score}
            for h in hits
        ]


def load_and_index(parsed_paths: dict[str, Path], specs: dict[str, dict[str, Any]]) -> PolicyIndex:
    """Build a PolicyIndex from parsed checklist files + their policy metadata."""
    from clearance.policies.checklist import load_checklist

    index = PolicyIndex()
    for procedure, path in parsed_paths.items():
        checklist = load_checklist(path)
        index.add_checklist(checklist, **specs[procedure])
    return index
