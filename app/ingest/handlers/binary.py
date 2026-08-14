"""Binary -> no table of its own.

Binary resources hold the actual bytes a DocumentReference points at. They are
already persisted verbatim in `raw_resources` by the loader, and the note
handler reads them back from there in a later phase. Giving them a dedicated
table would duplicate that for no query benefit -- nobody asks "list all
Binaries", they ask for a patient's notes.

The handler still exists so that Binary is a *registered* type. Without it,
every Binary line would be reported as UNKNOWN_RESOURCE_TYPE, which would be
misleading: we do understand these, we just deliberately do not model them.
"""

from app.ingest.context import IngestContext
from app.ingest.registry import Phase, register


@register("Binary", phase=Phase.ATTACHMENTS)
def handle_binary(resource: dict, ctx: IngestContext) -> None:
    if not resource.get("data"):
        ctx.warn(
            "MALFORMED_RESOURCE",
            "Binary has no data payload; any note referencing it will have no text",
        )
