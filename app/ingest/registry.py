"""Maps a FHIR resourceType to the handler that knows how to store it.

This is the extensibility seam. Supporting a new resource type means writing
one handler module and decorating it -- no loader changes, no schema surgery,
nothing else to remember under time pressure.

    @register("AllergyIntolerance")
    def handle_allergy(resource: dict, ctx: IngestContext) -> None:
        ...

Anything with no registered handler is not an error. The loader files it in
`raw_resources` as `unknown_type`, counts it in the ingest report, and keeps
serving it from the raw endpoint.
"""

from collections.abc import Callable

from app.ingest.context import IngestContext

Handler = Callable[[dict, IngestContext], None]


class Phase:
    """Ingest runs in ordered passes because some records depend on others.

    Patients must exist before any reference to them can resolve, and Binary
    blobs must exist before a DocumentReference can pull text out of one. Rather
    than sort the file or do lazy fixups, we make the dependency explicit.
    """

    # Patients: everything else resolves against them.
    SUBJECTS = 0
    # Binary: content that other resources point at.
    ATTACHMENTS = 1
    # Everything clinical.
    RECORDS = 2


_HANDLERS: dict[str, tuple[int, Handler]] = {}


def register(resource_type: str, phase: int = Phase.RECORDS) -> Callable[[Handler], Handler]:
    def decorator(func: Handler) -> Handler:
        if resource_type in _HANDLERS:
            raise ValueError(f"Duplicate handler registered for {resource_type!r}")
        _HANDLERS[resource_type] = (phase, func)
        return func

    return decorator


def get_handler(resource_type: str) -> Handler | None:
    entry = _HANDLERS.get(resource_type)
    return entry[1] if entry else None


def phase_of(resource_type: str) -> int | None:
    entry = _HANDLERS.get(resource_type)
    return entry[0] if entry else None


def registered_types() -> set[str]:
    return set(_HANDLERS)


def phases() -> list[int]:
    return sorted({phase for phase, _ in _HANDLERS.values()})


def load_handlers() -> None:
    """Import every handler module so its decorator runs."""
    from app.ingest import handlers  # noqa: F401

    handlers.load_all()
