"""Chat model factory. Provider/model are swappable via config or arguments."""

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from trippilot.config import get_settings


def get_llm(
    model: str | None = None,
    provider: str | None = None,
    temperature: float | None = None,
    **kwargs,
) -> BaseChatModel:
    """Return a chat model; defaults come from settings (Gemini unless overridden)."""
    settings = get_settings()
    return init_chat_model(
        model or settings.llm_model,
        model_provider=provider or settings.llm_provider,
        temperature=settings.llm_temperature if temperature is None else temperature,
        **kwargs,
    )


if __name__ == "__main__":
    settings = get_settings()
    llm = get_llm()
    reply = llm.invoke("In one sentence, what makes Istanbul great for a food-loving traveler?")
    print(f"[{settings.llm_provider}:{settings.llm_model}] {reply.text}")
    if settings.tracing_enabled:
        print(f"LangSmith tracing ON -> project '{settings.langsmith_project}'")
    else:
        print("LangSmith tracing OFF (set LANGSMITH_TRACING=true and LANGSMITH_API_KEY)")
