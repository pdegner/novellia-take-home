"""Domain errors, raised by services and translated to HTTP at the edge.

Services should not know about status codes. Keeping these separate is what
lets the service layer be called from a test, a script, or a future worker
without dragging FastAPI along.
"""


class DomainError(Exception):
    code = "DOMAIN_ERROR"
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    code = "NOT_FOUND"
    status_code = 404


class PatientNotFoundError(NotFoundError):
    code = "PATIENT_NOT_FOUND"

    def __init__(self, patient_id: str):
        super().__init__(f"No patient with id {patient_id!r}")
        self.patient_id = patient_id
