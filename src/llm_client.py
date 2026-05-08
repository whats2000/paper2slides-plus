"""LLM client functions for interacting with language models."""

import logging
import os
import re
from openai import OpenAI
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletion,
)

from prompts import PromptManager
from .latex_utils import sanitize_frametitles

# Initialize prompt manager
prompt_manager = PromptManager()


def extract_content_from_response(
    response: ChatCompletion, language: str = "latex"
) -> str | None:
    """
    :param response: Response from the language model
    :param language: Language to extract (default is 'latex')
    :return: Extracted content
    """
    pattern = re.compile(rf"```{language}\s*(.*?)```", re.DOTALL)
    match = pattern.search(response.choices[0].message.content)
    content = match.group(1).strip() if match else None
    return content


def resolve_api_credentials(
    api_key: str | None = None, base_url: str | None = None
) -> tuple[str, str | None]:
    """
    Resolve API key and base URL from provided values or environment variables.

    Args:
        api_key: Optional API key (will check environment if None)
        base_url: Optional base URL (will check environment if None)

    Returns:
        Tuple of (resolved_api_key, resolved_base_url)

    Raises:
        RuntimeError: If no API key can be found
    """
    resolved_api_key = (
        api_key
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
    )
    if not resolved_api_key:
        raise RuntimeError(
            "No API key provided. Set OPENAI_API_KEY or DASHSCOPE_API_KEY."
        )

    # Determine base_url
    resolved_base_url = base_url
    if not resolved_base_url:
        if resolved_api_key == os.environ.get("DASHSCOPE_API_KEY"):
            # DashScope provider
            resolved_base_url = (
                os.environ.get("DASHSCOPE_BASE_URL")
                or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
        elif os.environ.get("OPENAI_BASE_URL"):
            # Custom OpenAI-compatible provider
            resolved_base_url = os.environ.get("OPENAI_BASE_URL")

    return resolved_api_key, resolved_base_url


def get_model_name(model_name: str, base_url: str | None) -> str:
    """
    Auto-adjust model name for DashScope if needed.

    Args:
        model_name: Requested model name
        base_url: Base URL being used

    Returns:
        Adjusted model name
    """
    if (
        isinstance(base_url, str)
        and "dashscope.aliyuncs.com" in base_url
        and isinstance(model_name, str)
        and (
            model_name.startswith("gpt-")
            or model_name.startswith("o1")
            or model_name.startswith("o3")
        )
    ):
        return os.environ.get("DASHSCOPE_MODEL", "qwen-plus")
    return model_name


def create_llm_client(
    api_key: str | None = None, base_url: str | None = None
) -> OpenAI:
    """
    Create an OpenAI client with resolved credentials.

    Args:
        api_key: Optional API key
        base_url: Optional base URL

    Returns:
        Configured OpenAI client
    """
    resolved_api_key, resolved_base_url = resolve_api_credentials(api_key, base_url)

    client_kwargs = {"api_key": resolved_api_key}
    if resolved_base_url:
        client_kwargs["base_url"] = resolved_base_url

    return OpenAI(**client_kwargs)


def call_llm(
    system_message: str,
    user_prompt: str,
    api_key: str,
    model_name: str,
    base_url: str | None = None,
    extract_code: bool = True,
    code_language: str = "latex",
) -> str | None:
    """
    Call the LLM with system and user messages.

    Args:
        system_message: System message for the LLM
        user_prompt: User prompt for the LLM
        api_key: API key
        model_name: Model name
        base_url: Optional base URL
        extract_code: Whether to extract code from markdown blocks (default True)
        code_language: Language to extract if extract_code is True (default "latex")

    Returns:
        Extracted content from response (or raw content if extract_code is False), or None on error
    """
    try:
        client = create_llm_client(api_key, base_url)
        resolved_base_url = (
            client.base_url.host
            if hasattr(client.base_url, "host")
            else str(client.base_url)
        )
        model_to_use = get_model_name(model_name, resolved_base_url)

        response = client.chat.completions.create(
            model=model_to_use,
            messages=[
                ChatCompletionSystemMessageParam(content=system_message, role="system"),
                ChatCompletionUserMessageParam(content=user_prompt, role="user"),
            ],
        )

        if extract_code:
            content = extract_content_from_response(response, code_language)
            if content:
                return sanitize_frametitles(content)
            return None
        else:
            # Return raw response content without code extraction
            return response.choices[0].message.content

    except Exception as e:
        logging.error(f"Error calling LLM: {e}")
        # Provide guidance for DashScope access issues
        if "dashscope.aliyuncs.com" in str(base_url or "") and (
            "403" in str(e) or "access_denied" in str(e)
        ):
            logging.error(
                "DashScope access denied. Ensure your key has access to the model. "
                "Set DASHSCOPE_MODEL to a model you can use (e.g., qwen-plus)."
            )
        return None
