import re


LEGAL_WORDS_RE = re.compile(
    r"\b(пao|пао|ao|ао|ooo|ооо|pjsc|jsc|plc|inc|corp|corporation|company|group|holdings?)\b",
    re.IGNORECASE,
)
NON_WORD_RE = re.compile(r"[^a-zа-яё0-9]+", re.IGNORECASE)
SINGLE_LATIN_WORD_RE = re.compile(r"^[a-z]{3,10}$")


def normalize_asset_text(value: str) -> str:
    lowered = (value or "").lower().replace("ё", "е")
    lowered = LEGAL_WORDS_RE.sub(" ", lowered)
    lowered = NON_WORD_RE.sub(" ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def is_contextual_alias(symbol: str, normalized_alias: str) -> bool:
    symbol_token = (symbol or "").strip().lower()
    return normalized_alias != symbol_token and bool(SINGLE_LATIN_WORD_RE.fullmatch(normalized_alias or ""))


def build_asset_aliases(symbol: str, name: str, exchange: str = "", aliases: list[str] | None = None) -> set[str]:
    output = {symbol.strip().upper()}
    normalized_name = normalize_asset_text(name)
    if normalized_name and not is_contextual_alias(symbol, normalized_name):
        output.add(normalized_name)

    cleaned_name = (name or "").replace("ё", "е").strip()
    if cleaned_name:
        parts = [
            part.strip()
            for part in re.split(r"[-–—,/()\"«»]+", cleaned_name)
            if len(part.strip()) >= 3
        ]
        for part in parts:
            normalized_part = normalize_asset_text(part)
            if normalized_part and not is_contextual_alias(symbol, normalized_part):
                output.add(normalized_part)

    for alias in aliases or []:
        normalized_alias = normalize_asset_text(str(alias))
        if normalized_alias and not is_contextual_alias(symbol, normalized_alias):
            output.add(normalized_alias)

    return {alias for alias in output if alias}


def build_contextual_asset_aliases(symbol: str, name: str, aliases: list[str] | None = None) -> set[str]:
    candidates = []
    normalized_name = normalize_asset_text(name)
    if normalized_name:
        candidates.append(normalized_name)

    cleaned_name = (name or "").replace("ё", "е").strip()
    if cleaned_name:
        candidates.extend(
            part.strip()
            for part in re.split(r"[-–—,/()\"«»]+", cleaned_name)
            if len(part.strip()) >= 3
        )
    candidates.extend(str(alias) for alias in aliases or [])

    return {
        normalized
        for candidate in candidates
        if is_contextual_alias(symbol, normalized := normalize_asset_text(candidate))
    }
