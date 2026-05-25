from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import get_settings

settings = get_settings()


@dataclass
class GuardrailResult:
    original_text: str
    sanitized_text: str
    pii_types: list[str] = field(default_factory=list)
    prompt_injection_detected: bool = False
    policy_flags: list[str] = field(default_factory=list)
    blocked: bool = False
    blocked_reason: str | None = None

    def events(self) -> list[str]:
        events: list[str] = []
        if self.pii_types:
            events.append(f"pii_masked:{','.join(sorted(set(self.pii_types)))}")
        if self.prompt_injection_detected:
            events.append("prompt_injection_detected")
        if self.policy_flags:
            events.extend(f"policy_flag:{flag}" for flag in self.policy_flags)
        if self.blocked and self.blocked_reason:
            events.append(f"blocked:{self.blocked_reason}")
        return events


class GuardrailService:
    EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    PHONE_RE = re.compile(r"(?:(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4})")
    CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
    SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
    GENERIC_TOKEN_RE = re.compile(r"\b(?:ghp|github_pat|xoxb|xoxp|AIza)[A-Za-z0-9_-]{12,}\b")

    PROMPT_INJECTION_PATTERNS = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"ignore (?:all )?(?:previous|prior|above) instructions",
            r"reveal (?:the )?(?:system|developer) prompt",
            r"show (?:the )?(?:system|developer) message",
            r"developer message",
            r"system prompt",
            r"act as (?:the )?system",
            r"bypass (?:the )?(?:rules|guardrails|safety)",
            r"jailbreak",
            r"do not follow the above",
            r"print hidden instructions",
            r"forget your previous instructions",
        ]
    ]

    SECRET_EXFIL_PATTERNS = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\bapi key\b",
            r"\baccess token\b",
            r"\bsecret\b",
            r"\bpassword\b",
            r"\bcredential\b",
            r"\bprivate key\b",
            r"\bconnection string\b",
            r"\benvironment variable\b",
        ]
    ]

    DATA_EXFIL_PATTERNS = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\bexport\b",
            r"\bdump\b",
            r"\bleak\b",
            r"\bexfiltrat(?:e|ion)\b",
            r"\braw database\b",
            r"\bfull customer list\b",
        ]
    ]

    def sanitize_user_text(self, text: str) -> GuardrailResult:
        if not settings.guardrails_enabled:
            return GuardrailResult(original_text=text, sanitized_text=text)

        sanitized, pii_types = self._mask_pii(text)
        injection_detected = settings.prompt_injection_detection_enabled and self._contains_prompt_injection(sanitized)

        policy_flags: list[str] = []
        if settings.policy_filtering_enabled:
            if self._contains_secret_exfiltration_request(sanitized):
                policy_flags.append("secret_exfiltration")
            if self._contains_data_exfiltration_request(sanitized):
                policy_flags.append("data_exfiltration")

        blocked = injection_detected or bool(policy_flags)
        blocked_reason = None
        if injection_detected:
            blocked_reason = "Suspicious prompt-injection pattern detected."
        elif policy_flags:
            blocked_reason = "Request violates support-assistant policy filters."

        return GuardrailResult(
            original_text=text,
            sanitized_text=sanitized,
            pii_types=pii_types,
            prompt_injection_detected=injection_detected,
            policy_flags=policy_flags,
            blocked=blocked,
            blocked_reason=blocked_reason,
        )

    def sanitize_document_text(self, text: str) -> GuardrailResult:
        if not settings.guardrails_enabled:
            return GuardrailResult(original_text=text, sanitized_text=text)

        sanitized, pii_types = self._mask_pii(text)
        if settings.prompt_injection_detection_enabled:
            sanitized = self._remove_suspicious_instructions(sanitized)
        return GuardrailResult(
            original_text=text,
            sanitized_text=sanitized,
            pii_types=pii_types,
        )

    def sanitize_context_blocks(self, context_blocks: list[str]) -> tuple[list[str], list[str]]:
        sanitized_blocks: list[str] = []
        events: list[str] = []
        for block in context_blocks:
            result = self.sanitize_document_text(block)
            sanitized_blocks.append(result.sanitized_text)
            events.extend(result.events())
        return sanitized_blocks, sorted(set(events))

    def sanitize_output_text(self, text: str) -> GuardrailResult:
        if not settings.guardrails_enabled:
            return GuardrailResult(original_text=text, sanitized_text=text)

        sanitized, pii_types = self._mask_pii(text)
        return GuardrailResult(
            original_text=text,
            sanitized_text=sanitized,
            pii_types=pii_types,
        )

    def _mask_pii(self, text: str) -> tuple[str, list[str]]:
        if not settings.pii_masking_enabled:
            return text, []

        pii_types: list[str] = []

        def replace(pattern: re.Pattern[str], replacement: str, pii_label: str, value: str) -> str:
            if pattern.search(value):
                pii_types.append(pii_label)
                return pattern.sub(replacement, value)
            return value

        sanitized = text
        sanitized = replace(self.EMAIL_RE, "[REDACTED_EMAIL]", "email", sanitized)
        sanitized = replace(self.PHONE_RE, "[REDACTED_PHONE]", "phone", sanitized)
        sanitized = replace(self.SSN_RE, "[REDACTED_SSN]", "ssn", sanitized)
        sanitized = replace(self.CREDIT_CARD_RE, "[REDACTED_CARD]", "credit_card", sanitized)
        sanitized = replace(self.OPENAI_KEY_RE, "[REDACTED_API_KEY]", "api_key", sanitized)
        sanitized = replace(self.GENERIC_TOKEN_RE, "[REDACTED_TOKEN]", "token", sanitized)

        return sanitized, sorted(set(pii_types))

    def _contains_prompt_injection(self, text: str) -> bool:
        normalized = text.lower()
        return any(pattern.search(normalized) for pattern in self.PROMPT_INJECTION_PATTERNS)

    def _contains_secret_exfiltration_request(self, text: str) -> bool:
        normalized = text.lower()
        return any(pattern.search(normalized) for pattern in self.SECRET_EXFIL_PATTERNS)

    def _contains_data_exfiltration_request(self, text: str) -> bool:
        normalized = text.lower()
        return any(pattern.search(normalized) for pattern in self.DATA_EXFIL_PATTERNS)

    def _remove_suspicious_instructions(self, text: str) -> str:
        sanitized = text
        for pattern in self.PROMPT_INJECTION_PATTERNS:
            sanitized = pattern.sub("[REMOVED_SUSPICIOUS_INSTRUCTION]", sanitized)
        return sanitized
