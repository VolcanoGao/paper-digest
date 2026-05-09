from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    app_env: str = "dev"
    database_url: str = "postgresql+psycopg://paperdigest:paperdigest@localhost:5432/paperdigest"

    # LLM
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"

    # Pipeline
    prompt_version: str = "v1"
    lookback_days: int = 3
    max_fetch_per_category: int = 120

    # Crypto / auth
    fernet_key: str = ""
    secret_key: str = "change-me"
    invite_codes: str = ""

    # Email
    resend_api_key: str = ""
    mail_from: str = "digest@example.com"


settings = Settings()


# arXiv categories the platform monitors.
ARXIV_CATEGORIES: list[str] = ["cs.IR", "cs.LG", "cs.CL", "cs.AI"]


# Platform-wide keyword union. Admin maintains this list.
# A paper is fetched if its title or abstract contains any of these (case-insensitive).
# When a user adds a keyword not in this list, UI warns "not monitored".
PLATFORM_KEYWORDS: list[str] = [
    # original 8 from fetch.py
    "recommend",
    "recommender",
    "ranking",
    "retrieval",
    "ctr",
    "click-through",
    "collaborative filtering",
    "user modeling",
    # additions for v1
    "llm4rec",
    "agent",
    "generative recommendation",
    "sequential recommendation",
    "multimodal",
    "cold-start",
    "cold start",
]


# Default weights for new user configs.
DEFAULT_WEIGHTS: dict[str, float] = {
    "novelty": 0.30,
    "practicality": 0.30,
    "rigor": 0.20,
    "relevance": 0.20,
}
