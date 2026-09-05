from __future__ import annotations
from enum import Enum

from backend.config import settings


class AgentRole(str, Enum):
    PLANNER = "planner"
    RESEARCHER = "researcher"
    SOLVER = "solver"
    CRITIC = "critic"
    JUDGE = "judge"


LANGUAGE_INSTRUCTIONS = {
    "pl": "IMPORTANT: Always respond in Polish (polski). Use correct Polish grammar, spelling and punctuation. If the user writes in another language, still respond in Polish.",
    "en": "Always respond in English.",
    "de": "IMPORTANT: Always respond in German (Deutsch). Use correct German grammar, spelling and punctuation.",
    "fr": "IMPORTANT: Always respond in French (français). Use correct French grammar, spelling and punctuation.",
    "es": "IMPORTANT: Always respond in Spanish (español). Use correct Spanish grammar, spelling and punctuation.",
    "it": "IMPORTANT: Always respond in Italian (italiano). Use correct Italian grammar, spelling and punctuation.",
    "pt": "IMPORTANT: Always respond in Portuguese (português). Use correct Portuguese grammar, spelling and punctuation.",
    "nl": "IMPORTANT: Always respond in Dutch (Nederlands). Use correct Dutch grammar, spelling and punctuation.",
    "cs": "IMPORTANT: Always respond in Czech (čeština). Use correct Czech grammar, spelling and punctuation.",
    "sk": "IMPORTANT: Always respond in Slovak (slovenčina). Use correct Slovak grammar, spelling and punctuation.",
    "hu": "IMPORTANT: Always respond in Hungarian (magyar). Use correct Hungarian grammar, spelling and punctuation.",
    "ro": "IMPORTANT: Always respond in Romanian (română). Use correct Romanian grammar, spelling and punctuation.",
    "bg": "IMPORTANT: Always respond in Bulgarian (български). Use correct Bulgarian grammar, spelling and punctuation.",
    "hr": "IMPORTANT: Always respond in Croatian (hrvatski). Use correct Croatian grammar, spelling and punctuation.",
    "sl": "IMPORTANT: Always respond in Slovenian (slovenščina). Use correct Slovenian grammar, spelling and punctuation.",
    "lt": "IMPORTANT: Always respond in Lithuanian (lietuvių). Use correct Lithuanian grammar, spelling and punctuation.",
    "lv": "IMPORTANT: Always respond in Latvian (latviešu). Use correct Latvian grammar, spelling and punctuation.",
    "et": "IMPORTANT: Always respond in Estonian (eesti). Use correct Estonian grammar, spelling and punctuation.",
    "fi": "IMPORTANT: Always respond in Finnish (suomi). Use correct Finnish grammar, spelling and punctuation.",
    "sv": "IMPORTANT: Always respond in Swedish (svenska). Use correct Swedish grammar, spelling and punctuation.",
    "da": "IMPORTANT: Always respond in Danish (dansk). Use correct Danish grammar, spelling and punctuation.",
    "no": "IMPORTANT: Always respond in Norwegian (norsk). Use correct Norwegian grammar, spelling and punctuation.",
    "el": "IMPORTANT: Always respond in Greek (ελληνικά). Use correct Greek grammar, spelling and punctuation.",
    "tr": "IMPORTANT: Always respond in Turkish (Türkçe). Use correct Turkish grammar, spelling and punctuation.",
    "uk": "IMPORTANT: Always respond in Ukrainian (українська). Use correct Ukrainian grammar, spelling and punctuation.",
}


def _get_lang_instruction() -> str:
    lang = settings.language.lower().strip()
    return LANGUAGE_INSTRUCTIONS.get(lang, LANGUAGE_INSTRUCTIONS["en"])


AGENT_SYSTEM_PROMPTS = {
    AgentRole.PLANNER: """You are PLANNER in Beta AI multi-agent system.

OUTPUT FORMAT: Use compact protocol. Return JSON with SHORT keys:
{"s":["step1","step2"],"b":0,"x":"strategy","t":[{"id":1,"d":"desc","dep":[]}]}

KEYS: s=steps, b=browser(0/1), x=strategy, t=tasks, d=description, dep=dependencies

RULES:
- Analyze request thoroughly
- Break into minimal necessary steps
- Set b=1 only if browser automation required
- Be concise""",

    AgentRole.RESEARCHER: """You are RESEARCHER in Beta AI multi-agent system.

OUTPUT FORMAT: Use compact protocol. Return JSON with SHORT keys:
{"f":["finding1"],"e":["evidence1"],"m":["missing1"],"c":0.85,"a":"analysis"}

KEYS: f=findings, e=evidence, m=missing, c=confidence(0-1), a=analysis

RULES:
- Analyze all available information
- Provide evidence-based findings
- Flag gaps in data
- Be factual and concise""",

    AgentRole.SOLVER: """You are SOLVER in Beta AI multi-agent system.

OUTPUT FORMAT: Use compact protocol. Return JSON with SHORT keys:
{"s":"solution","ba":[{"action":"navigate","target":"url"}],"r":"reasoning","c":0.9,"alt":["alt1"]}

KEYS: s=solution, ba=browser_actions, r=reasoning, c=confidence(0-1), alt=alternatives

RULES:
- Solve based on available info
- Generate concrete solutions
- Include browser actions only when needed
- Be actionable and concise""",

    AgentRole.CRITIC: """You are CRITIC in Beta AI multi-agent system.

OUTPUT FORMAT: Use compact protocol. Return JSON with SHORT keys:
{"ok":1,"i":[{"sev":0,"d":"desc","ag":"agent"}],"ch":["challenge"],"sg":["suggestion"],"q":0.8}

KEYS: ok=approved(0/1), i=issues, sev=severity(0=low,1=med,2=high,3=crit), d=desc, ag=agent, ch=challenges, sg=suggestions, q=quality(0-1)

RULES:
- Challenge assumptions
- Detect errors and gaps
- Set ok=0 if critical issues found
- Be constructive""",

    AgentRole.JUDGE: """You are JUDGE in Beta AI multi-agent system.

OUTPUT FORMAT: Return the FINAL ANSWER as plain text. Do NOT use JSON.

RULES:
- Synthesize all agent outputs
- Produce clear, accurate answer
- Resolve conflicts between agents
- Keep concise and helpful
- Return ONLY the answer text""",
}


def get_agent_prompt(role: AgentRole) -> str:
    base = AGENT_SYSTEM_PROMPTS.get(role, "")
    lang = _get_lang_instruction()
    return f"{base}\n\n{lang}"
