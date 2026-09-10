"""Parses a small config DSL into a dict."""

def parse_line(line: str) -> tuple[str, str]:
    key, _, value = line.partition("=")
    return key.strip(), value.strip()

def parse(text: str) -> dict:
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = parse_line(line)
        result[key] = value
    return result
