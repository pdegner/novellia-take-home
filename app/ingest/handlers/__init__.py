"""Handler modules, one per FHIR resource type.

To support a new type: add a module here, decorate its function with
`@register("TypeName")`, and add the import to `load_all()`. Nothing else in
the system needs to change.
"""

from importlib import import_module

# Every module that registers a handler. Order does not matter -- execution
# order comes from each handler's declared Phase, not from this list.
HANDLER_MODULES = [
    "app.ingest.handlers.patient",
    "app.ingest.handlers.binary",
    "app.ingest.handlers.condition",
    "app.ingest.handlers.medication",
    "app.ingest.handlers.observation",
    "app.ingest.handlers.procedure",
    "app.ingest.handlers.note",
]

_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    for module in HANDLER_MODULES:
        import_module(module)
    _loaded = True
