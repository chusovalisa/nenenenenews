import re

NOISE_TICKERS = {
    "ISIN", "RUB", "USD", "EUR", "CNY", "BYN", "KZT", "HKD", "INR", "XAU",
    "HTTP", "API", "ETF", "FIXED", "FAQ", "FAST", "SAFE", "TOD", "TODAY",
    "IPO", "IFRS", "IOSCO", "ISSB", "ISS", "WEB", "DATA", "LLM", "CIB",
    "II", "III", "IV", "XI", "SN", "EQ", "BND", "IND", "FX", "MSK",
}
ISIN_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{9}\d")


def _isin_luhn_is_valid(value: str) -> bool:
    expanded = []
    for char in value.upper():
        if char.isdigit():
            expanded.append(char)
        elif "A" <= char <= "Z":
            expanded.append(str(ord(char) - 55))
        else:
            return False
    digits = [int(char) for char in "".join(expanded)]
    checksum = 0
    should_double = False
    for digit in reversed(digits):
        current = digit * 2 if should_double else digit
        checksum += current // 10 + current % 10
        should_double = not should_double
    return checksum % 10 == 0


def extract_isins(text: str) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for match in ISIN_RE.findall(text.upper()):
        if match in seen:
            continue
        if _isin_luhn_is_valid(match):
            seen.add(match)
            output.append(match)
    return output
