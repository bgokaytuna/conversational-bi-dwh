"""
claude_client.py
================
Anthropic API için ince bir sarmalayıcı katman.

Kullanım:
    from utils.claude_client import ask, ask_streaming

    response = ask(
        system="Sen bir SQL uzmanısın.",
        user="2023 yılı toplam prim geliri nedir?",
    )
    print(response)
"""

import os
import anthropic
from typing import Iterator

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL        = "claude-sonnet-4-20250514"
MAX_TOKENS   = 2048
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Singleton Anthropic istemcisi. API key env'den okunur."""
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY ortam değişkeni bulunamadı.\n"
                "Lütfen .env dosyasına veya shell'e ekleyin:\n"
                "  export ANTHROPIC_API_KEY=sk-ant-..."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def ask(
    user: str,
    system: str = "",
    max_tokens: int = MAX_TOKENS,
    temperature: float = 0.0,
) -> str:
    """
    Tek seferlik, blokaj API çağrısı.
    SQL üretimi gibi deterministik görevlerde temperature=0 kullan.

    Returns
    -------
    str  — modelin text yanıtı
    """
    client = _get_client()
    kwargs: dict = dict(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": user}],
    )
    if system:
        kwargs["system"] = system
    if temperature != 0.0:
        kwargs["temperature"] = temperature

    message = client.messages.create(**kwargs)
    # content listesinden text bloklarını birleştir
    return "".join(
        block.text for block in message.content if hasattr(block, "text")
    )


def ask_streaming(
    user: str,
    system: str = "",
    max_tokens: int = MAX_TOKENS,
    temperature: float = 0.7,
) -> Iterator[str]:
    """
    Streaming API çağrısı — Streamlit st.write_stream ile uyumlu.
    Insight / yorum gibi uzun metin üretiminde kullan.

    Yields
    ------
    str  — her token chunk'ı
    """
    client = _get_client()
    kwargs: dict = dict(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": user}],
    )
    if system:
        kwargs["system"] = system
    if temperature != 0.0:
        kwargs["temperature"] = temperature

    with client.messages.stream(**kwargs) as stream:
        for text in stream.text_stream:
            yield text


def is_api_key_set() -> bool:
    """Streamlit sidebar'da API key durumunu göstermek için."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
