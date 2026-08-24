from __future__ import annotations

import logging

from backend.ai.providers import BaseAIProvider
from backend.models.schemas import AISelectors, DOMElement

logger = logging.getLogger(__name__)

ELEMENT_IDENTIFICATION_PROMPT = """\
You are an expert at identifying web page elements for automated testing.

Given the following DOM elements from a login page, identify the best CSS selectors for:
1. The username/email input field
2. The password input field
3. The submit/login button

Respond ONLY with valid JSON in this exact format:
{
  "username_selector": "CSS or XPath selector for username field",
  "password_selector": "CSS or XPath selector for password field",
  "submit_selector": "CSS or XPath selector for submit button",
  "confidence": 0.0 to 1.0,
  "reason": "Brief explanation of your selections"
}

DOM Elements:
{elements}

Instructions:
- Prefer stable selectors (id, name) over positional ones
- If an element has an id, use #id selector
- If it has a name, use [name="..."] selector
- Consider placeholder text, aria-labels, and labels
- Confidence should reflect certainty about selections
- Only return the JSON, no other text
"""


def _format_element(e: DOMElement) -> str:
    return (
        f"- <{e.tag}> id={e.id} name={e.name} "
        f"type={e.type} placeholder={e.placeholder} "
        f"aria-label={e.aria_label} text={e.text} "
        f"role={e.role} css={e.css_selector} "
        f"xpath={e.xpath}"
    )


class ElementIdentifier:
    def __init__(self, ai_provider: BaseAIProvider) -> None:
        self._ai = ai_provider

    async def identify_elements(
        self, elements: list[DOMElement]
    ) -> AISelectors | None:
        elements_text = "\n".join(
            _format_element(e) for e in elements
        )
        prompt = (
            ELEMENT_IDENTIFICATION_PROMPT.format(
                elements=elements_text
            )
        )
        return await self._ai.parse_selectors(prompt)
