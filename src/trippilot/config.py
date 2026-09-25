"""Application settings loaded from environment / .env."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

# Export .env into os.environ so libraries that read env vars directly
# (LangSmith tracing, provider SDKs) see them too.
load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    # LLM
    llm_provider: str = Field("google_genai", alias="TRIPPILOT_LLM_PROVIDER")
    llm_model: str = Field("gemini-3.5-flash", alias="TRIPPILOT_LLM_MODEL")
    llm_temperature: float = Field(0.2, alias="TRIPPILOT_LLM_TEMPERATURE")
    google_api_key: SecretStr | None = Field(None, alias="GOOGLE_API_KEY")

    # LangSmith
    langsmith_tracing: bool = Field(False, alias="LANGSMITH_TRACING")
    langsmith_api_key: SecretStr | None = Field(None, alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field("trippilot", alias="LANGSMITH_PROJECT")

    # External APIs
    serpapi_api_key: SecretStr | None = Field(None, alias="SERPAPI_API_KEY")
    tavily_api_key: SecretStr | None = Field(None, alias="TAVILY_API_KEY")

    @property
    def tracing_enabled(self) -> bool:
        return self.langsmith_tracing and self.langsmith_api_key is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()
