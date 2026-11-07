import dataclasses

import pytest

from qjig.contracts import ContractError
from qjig.indexing import index_entries
from qjig.sources import SourceRevision, decode_source
from qjig.topics import TopicIndex, span_ref


def entries():
    r = SourceRevision.create(
        "p/policy.md", "/x", decode_source(b"# Refunds\nRefund within 30 days.\n# Other\nx\n", encoding="utf-8")
    )
    return index_entries(r)


def test_multi_topic_links():
    refunds, other = entries()
    topics = TopicIndex()
    a = topics.attach("refunds", refunds)
    b = topics.attach("customer-rights", refunds)
    # two topic views point at the same immutable span identity, not copies of the text
    assert a.span_ref == b.span_ref == span_ref(refunds.span)
    assert a.topic != b.topic and a.entry_id == b.entry_id == refunds.entry_id
    assert "text" not in {f.name for f in dataclasses.fields(a)}
    assert topics.topics_for(refunds.entry_id) == ["customer-rights", "refunds"]
    assert topics.entry_ids_for("refunds") == [refunds.entry_id]
    assert topics.entry_ids_for("customer-rights") == [refunds.entry_id]
    # another entry is not dragged in; unknown topic is empty, not an error
    topics.attach("misc", other)
    assert topics.entry_ids_for("refunds") == [refunds.entry_id]
    assert topics.entry_ids_for("nothing") == []
    # links are proposals with a named method, never accepted authority
    assert a.state == "proposed" and a.method


def test_attach_is_idempotent_and_validates():
    refunds, _ = entries()
    topics = TopicIndex()
    first = topics.attach("refunds", refunds)
    assert topics.attach("refunds", refunds) == first
    assert len(topics.links()) == 1
    with pytest.raises(ContractError):
        topics.attach("", refunds)
    with pytest.raises(ContractError):
        topics.attach("   ", refunds)
    assert topics.topics_for("missing-entry") == []
