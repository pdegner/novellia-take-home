"""ClinicalNote and DocumentReference -> notes.

Two source shapes, one output shape. This is the clearest example in the
project of the API being domain-first rather than a FHIR mirror: the consumer
asks for a patient's notes and gets text, without needing to know that some
arrived inline and others were base64 behind a reference.
"""

from sqlalchemy import select

from app.ingest import normalize
from app.ingest.context import IngestContext
from app.ingest.references import reference_id, resolve_subject
from app.ingest.registry import register
from app.models import IssueCode, Note, RawResource


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
    patient_id = resolve_subject(resource.get("subject"), ctx)
    authored_at, authored_precision = normalize.parse_fhir_datetime(resource.get("date"))

    author = resource.get("author")
    author_ref = author.get("reference") if isinstance(author, dict) else None

    ctx.session.add(
        Note(
            id=ctx.resource_id,
            patient_id=patient_id,
            source_type="ClinicalNote",
            status=resource.get("status"),
            authored_at=authored_at,
            authored_precision=authored_precision,
            author_ref=author_ref,
            text=normalize._as_text(resource.get("content")),
            raw_json=resource,
        )
    )


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
    patient_id = resolve_subject(resource.get("subject"), ctx)
    type_concept = normalize.extract_concept(resource.get("type"))
    authored_at, authored_precision = normalize.parse_fhir_datetime(resource.get("date"))

    author = resource.get("author")
    first_author = author[0] if isinstance(author, list) and author else None
    author_ref = first_author.get("reference") if isinstance(first_author, dict) else None

    content = resource.get("content")
    first_content = content[0] if isinstance(content, list) and content else None
    attachment = first_content.get("attachment") if isinstance(first_content, dict) else None
    attachment = attachment if isinstance(attachment, dict) else {}

    binary_id = reference_id(attachment.get("url"), expected_type="Binary")
    binary = load_binary(ctx, binary_id) if binary_id else None

    content_type: str | None = None
    text: str | None = None
    text_unavailable_reason: str | None = None

    if binary is None:
        ctx.error(
            IssueCode.ATTACHMENT_UNRESOLVED,
            f"Referenced attachment {attachment.get('url')!r} was not found in the file",
        )
        text_unavailable_reason = "Referenced attachment could not be found"
    else:
        content_type = binary.get("contentType")
        try:
            text = normalize.decode_attachment(binary.get("data"), content_type)
        except ValueError as exc:
            ctx.error(IssueCode.ATTACHMENT_UNDECODABLE, f"Attachment could not be decoded: {exc}")
            text_unavailable_reason = str(exc)

    ctx.session.add(
        Note(
            id=ctx.resource_id,
            patient_id=patient_id,
            source_type="DocumentReference",
            type_code=type_concept["code"],
            type_display=type_concept["display"],
            status=resource.get("status"),
            authored_at=authored_at,
            authored_precision=authored_precision,
            author_ref=author_ref,
            content_type=content_type,
            text=text,
            text_unavailable_reason=text_unavailable_reason,
            raw_json=resource,
        )
    )


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
