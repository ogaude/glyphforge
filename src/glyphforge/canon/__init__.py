from glyphforge.canon.label import CANON_FINGERPRINT, CANON_RULES_VERSION, canonicalize
from glyphforge.canon.normalize import NORMALIZE_RULES_VERSION, canonical, equivalent, normalize_tokens, strip_layout
from glyphforge.canon.safety import FILTER_VERSION, WRAP_VERSION, WRAPPERS, check_safe, wrap
from glyphforge.canon.tokens import DISPLAY_ENVS, detokenize, tokenize

__all__ = [
    "CANON_FINGERPRINT", "CANON_RULES_VERSION", "DISPLAY_ENVS", "FILTER_VERSION", "NORMALIZE_RULES_VERSION", "WRAPPERS", "WRAP_VERSION",
    "canon_versions", "canonical", "canonicalize", "check_safe", "detokenize", "equivalent", "normalize_tokens", "strip_layout", "tokenize", "wrap",
]


def canon_versions() -> dict[str, str]:
    return {
        "canon_rules_version": CANON_RULES_VERSION,
        "normalize_rules_version": NORMALIZE_RULES_VERSION,
        "wrap_version": WRAP_VERSION,
        "filter_version": FILTER_VERSION,
    }
