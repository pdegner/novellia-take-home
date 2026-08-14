"""ClinicalNote and DocumentReference -> notes.

Two source shapes, one output shape. This is the clearest example in the
project of the API being domain-first rather than a FHIR mirror: the consumer
asks for a patient's notes and gets text, without needing to know that some
arrived inline and others were base64 behind a reference.
"""

from sqlalchemy import select

from app.ingest.context import IngestContext
from app.ingest.registry import register
from app.models import RawResource


@register("ClinicalNote")
def handle_clinical_note(resource: dict, ctx: IngestContext) -> None:
    """Store an inline note.

    `ClinicalNote` is **not a real FHIR resource type** -- there is no such
    thing in the spec, and `note-robby-001` is the only one in the file. This
    is exactly what a real clinic feed looks like: a partner invented a type
    that suited their EHR export.

    Handling it is a deliberate choice over rejecting it as non-conformant. The
    text is real clinical content and the patient reference is well-formed, so
    refusing it on a technicality would lose data for no safety benefit. Record
    the provenance in `source_type` so nobody later mistakes it for standard
    FHIR.

    Fields: status, subject, author, date, content (plain text, already inline).
    """
    # TODO(Patti): source_type="ClinicalNote", text=resource["content"].
    raise NotImplementedError("handle_clinical_note")


@register("DocumentReference")
def handle_document_reference(resource: dict, ctx: IngestContext) -> None:
    """Store a note whose text lives in a separate Binary resource.

    `content[].attachment.url` is `"Binary/binary-001"`, and that Binary's
    `data` is base64. Resolve the pointer, decode, store the text.

    Failure modes to handle rather than crash on:
      * the referenced Binary is not in the file -> ATTACHMENT_UNRESOLVED
      * its payload will not base64-decode -> ATTACHMENT_UNDECODABLE

    In both cases still write the note row, with `text_unavailable_reason` set.
    The note demonstrably exists and a consumer should be told it exists but is
    unreadable, rather than shown a chart with a silent hole in it.
    """
    # TODO(Patti): use references.reference_id(url, expected_type="Binary"),
    # then load_binary below, then normalize.decode_attachment.
    raise NotImplementedError("handle_document_reference")


def load_binary(ctx: IngestContext, binary_id: str) -> dict | None:
    """Fetch a Binary resource's JSON back out of `raw_resources`.

    Binaries are not modelled as a table -- see handlers/binary.py. They are
    read back from the raw store, which works because the loader runs
    Phase.ATTACHMENTS before Phase.RECORDS, so every Binary line is already
    committed to the session by the time a note asks for one.
    """
    stmt = select(RawResource).where(
        RawResource.resource_type == "Binary",
        RawResource.resource_id == binary_id,
    )
    row = ctx.session.execute(stmt).scalars().first()
    return row.raw_json if row else None
