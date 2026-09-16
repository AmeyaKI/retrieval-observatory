What this demo does not show

Being straight about the boundaries:





It is not a competitive retrieval system. Widths and models were chosen for legibility
and cheap reruns. Every scenario compares two runs with the same components, so absolute
quality cancels.



It does not prove retobs is easy to adopt. This pipeline was built inside the retobs
repository against its internals. Whether an agent can wire retobs into someone else's
project from one instruction is a separate question, tested separately, and not answered
here.



Ground truth is positive-only, so most retrieved documents are unknown_relevance — not
a tracing failure, but a limit on how much the lineage read-out can say. Tracing health
(lineage_incomplete) is 0.0%.



One lineage requirement is genuinely unmet and left visible in every report: this
pipeline records no document content hashes, so lineage_document_identity_partial fires.
That is retobs correctly reporting a real limitation.