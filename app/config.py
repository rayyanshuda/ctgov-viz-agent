# runtime configuration, loaded from env vars

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Service Settings
    # every field except ANTHROPIC_API_KEY (that's in .env) has a usable default,
    # so the only required configuration is the LLM API key.

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CTGOV_VIZ_",
        extra="ignore",
    )

    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CTGOV_VIZ_ANTHROPIC_API_KEY"),
    )

    model: str = "claude-opus-5"
    # Planner model: Outputs only structured plans, doesn't give data values (reduces hallucinations)

    max_plan_tokens: int = 4096

    max_tool_iterations: int = 5
    # Hard celing on planner tool calls, so a confused model doesn't tool forever in my tool-use loop

    max_repair_attempts: int = 2
    # Number of times a schema-invalid plan is handed back to the model (basically a retry limit)

    ctgov_base_url: str = "https://clinicaltrials.gov/api/v2"
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 3

    page_size: int = 1000
    # ClinicalTrials.gov caps the pageSize at 1000

    max_studies: int = 5000
    # This is the default ceiling on records that is fetched per cohort. 

    max_studies_hard_limit: int = 20000
    # This is the ceiling a caller can't exceed as per `options.max_studies`

    rate_limit_enabled: bool = True
    # Caps how often one caller can hit the endpoints that spend Anthropic credits.
    # Matters for the public demo URL; turn it off locally with
    # CTGOV_VIZ_RATE_LIMIT_ENABLED=false

    rate_limit_per_hour: int = 20

    cache_dir: str = ".cache"
    cache_ttl_seconds: int = 86_400
    cache_enabled: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
