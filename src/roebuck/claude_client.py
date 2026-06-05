import json
from typing import TypeVar, Type

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

from roebuck.config import ClaudeConfig

T = TypeVar("T", bound=BaseModel)


class ClaudeClient:
    def __init__(self, cfg: ClaudeConfig) -> None:
        # Anthropic() reads ANTHROPIC_API_KEY from environment automatically
        self._client = Anthropic()
        self._cfg = cfg

    def analyse(self, system: str, user: str, output_model: Type[T]) -> T:
        """
        Send a request to Claude with JSON schema injection.
        Returns a validated instance of output_model.

        The system prompt is augmented with the model's JSON schema so Claude
        returns a single JSON object that can be directly parsed.
        """
        schema = output_model.model_json_schema()
        full_system = (
            f"{system}\n\n"
            "Return your response as a single JSON object conforming exactly to "
            f"this schema:\n```json\n{json.dumps(schema, indent=2)}\n```\n"
            "Do not include any text, explanation, or markdown outside the JSON object."
        )

        response = self._client.messages.create(
            model=self._cfg.model,
            max_tokens=self._cfg.max_tokens,
            temperature=self._cfg.temperature,
            system=full_system,
            messages=[{"role": "user", "content": user}],
        )

        if response.stop_reason == "max_tokens":
            raise RuntimeError(
                "Claude response was cut off (max_tokens reached). "
                "Increase claude.max_tokens in config.toml or reduce input size."
            )
        if not response.content or response.content[0].type != "text":
            raise RuntimeError(
                f"Unexpected Claude response: no text block returned. "
                f"stop_reason={response.stop_reason!r}, "
                f"content_types={[b.type for b in response.content]}"
            )

        text = response.content[0].text.strip()
        text = _strip_code_fences(text)

        try:
            return output_model.model_validate_json(text)
        except ValidationError as e:
            raise RuntimeError(
                f"Claude returned JSON that did not match the expected schema.\n"
                f"Validation errors: {e}\n"
                f"Raw response (first 500 chars):\n{text[:500]}"
            ) from e


def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences if present."""
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop first line (``` or ```json) and last line (```)
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        return "\n".join(inner).strip()
    return text
