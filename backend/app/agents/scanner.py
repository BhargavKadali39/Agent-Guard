"""Heuristic scanner for instruction-like content in untrusted text.

This is a *detector*, not a security boundary. Its only job is to raise a flag so the
workflow can escalate suspicious requests to a human and record a security event. The
actual protections are backend authorization, the deterministic policy engine and the
approval binding, all of which hold even when this scanner misses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_previous_instructions": re.compile(
        r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|earlier|all|your|the)\b"
        r".{0,20}\b(instructions?|rules?|guidelines?|polic(y|ies)|prompt)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "role_reassignment": re.compile(
        r"\b(you are now|you're now|act as|pretend to be|from now on you)\b", re.IGNORECASE
    ),
    "system_override_marker": re.compile(
        r"(\bsystem\s*(override|prompt|message|instruction)\b|^\s*(system|assistant|developer)\s*:)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "approve_without_checks": re.compile(
        r"\b(approve|process|issue|release|refund)\b.{0,60}\bwithout\b.{0,40}"
        r"\b(check(ing)?|verif(y|ying|ication)|polic(y|ies)|approval|review)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "bypass_or_skip_controls": re.compile(
        r"\b(bypass|override|skip|disable|turn off)\b.{0,30}"
        r"\b(polic(y|ies)|verification|approval|checks?|limits?|rules?|controls?)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "authority_claim": re.compile(
        r"\b(as|i am|i'm)\s+(an?\s+|the\s+)?(admin(istrator)?|developer|supervisor|manager|"
        r"senior reviewer|ceo|owner)\b.{0,40}\b(authori[sz]e|approve|instruct|order)",
        re.IGNORECASE | re.DOTALL,
    ),
    "do_not_verify": re.compile(
        r"\b(do not|don't|never)\s+(check|verify|validate|review|ask)\b", re.IGNORECASE
    ),
    "markup_injection": re.compile(
        r"<\s*/?\s*(system|instruction|admin|prompt)[^>]*>|\[\s*(system|instruction)\s*\]",
        re.IGNORECASE,
    ),
    "new_instructions": re.compile(
        r"\b(new|updated|secret|confidential|hidden)\s+(instructions?|directive|rules?)\b",
        re.IGNORECASE,
    ),
}


@dataclass
class ScanResult:
    suspicious: bool
    matched_patterns: list[str] = field(default_factory=list)
    excerpts: list[str] = field(default_factory=list)


class UntrustedContentScanner:
    def scan(self, text: str) -> ScanResult:
        matched: list[str] = []
        excerpts: list[str] = []
        for name, pattern in _PATTERNS.items():
            match = pattern.search(text)
            if match:
                matched.append(name)
                excerpt = match.group(0).strip().replace("\n", " ")
                excerpts.append(excerpt[:120])
        return ScanResult(suspicious=bool(matched), matched_patterns=matched, excerpts=excerpts)


scanner = UntrustedContentScanner()
