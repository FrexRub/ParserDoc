import re


_multi_blank_lines = re.compile(r"\n{3,}")
_spaced_lines = re.compile(r"[ \t]+\n")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _spaced_lines.sub("\n", text)
    text = _multi_blank_lines.sub("\n\n", text)
    return text.strip()

