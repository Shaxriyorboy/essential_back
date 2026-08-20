"""LLM provayder dispecheri — Azure OpenAI YOKI Gemini.

`speaking_routes` faqat shu modulni chaqiradi: `generate_chat` + `LLMError`.
Qaysi provayder ishlashi env bilan aniqlanadi:

    LLM_PROVIDER = "azure" | "gemini"   (aniq tanlov)

Berilmasa — avtomatik: Azure sozlangan bo'lsa (AZURE_OPENAI_* env bor)
Azure, aks holda Gemini. Shunda kredit tugasa, bitta env o'zgartirib
Gemini'ga qaytiladi.
"""
import os


class LLMError(Exception):
    """Provayderdan qat'i nazar yagona xato turi (speaking_routes shuni ushlaydi)."""


def active_provider() -> str:
    forced = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if forced in ("azure", "gemini"):
        return forced
    # Avtomatik: Azure sozlangan bo'lsa — Azure
    import azure_openai
    return "azure" if azure_openai.is_configured() else "gemini"


def generate_chat(system_instruction: str, contents: list, preferred_model=None) -> dict:
    provider = active_provider()
    if provider == "azure":
        import azure_openai
        try:
            return azure_openai.generate_chat(
                system_instruction, contents, preferred_model)
        except azure_openai.AzureOpenAIError as e:
            raise LLMError(str(e))
    else:
        import gemini
        try:
            return gemini.generate_chat(
                system_instruction, contents, preferred_model)
        except gemini.GeminiError as e:
            raise LLMError(str(e))
