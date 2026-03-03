from pydantic import BaseModel, field_validator


class AwarenessCardGenerateRequest(BaseModel):
    disease_setting: str | None = None
    mechanism: str | None = None
    trial_purpose: str | None = None
    intervention_class: str | None = None
    why_it_matters: str | None = None
    when_to_think: str | None = None
    referral_contact: str | None = None

    @field_validator(
        "disease_setting",
        "mechanism",
        "trial_purpose",
        "intervention_class",
        "why_it_matters",
        "when_to_think",
        "referral_contact",
        mode="before",
    )
    @classmethod
    def normalize_optional_string(cls, value: object) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class AwarenessCardVisual(BaseModel):
    title: str
    subtitle: str
    lines: list[str]


class AwarenessCardResponse(BaseModel):
    text_card: str
    visual: AwarenessCardVisual
    fields: dict[str, str]
