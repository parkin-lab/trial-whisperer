from enum import StrEnum


class UserRole(StrEnum):
    owner = "owner"
    pi = "pi"
    coordinator = "coordinator"
    collaborator = "collaborator"


class Indication(StrEnum):
    aml = "aml"
    all = "all"
    lymphoma = "lymphoma"
    mm = "mm"
    transplant = "transplant"
    gvhd = "gvhd"


class TrialStatus(StrEnum):
    draft = "draft"
    active = "active"
    archived = "archived"


class CriteriaType(StrEnum):
    inclusion = "inclusion"
    exclusion = "exclusion"


class ConfidenceLevel(StrEnum):
    high = "high"
    needs_review = "needs_review"


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
