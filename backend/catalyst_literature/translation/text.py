from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

BUILTIN_GLOSSARY = {
    "catalyst": "催化剂",
    "catalysis": "催化",
    "active site": "活性位点",
    "turnover frequency": "转换频率",
    "selectivity": "选择性",
    "conversion": "转化率",
    "support": "载体",
}

PROTECTED_PATTERNS = (
    re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE),
    re.compile(r"\[(?:\d+(?:\s*[-,]\s*\d+)*)\]"),
    re.compile(r"\((?:[A-Z][A-Za-z-]+(?:\s+et\s+al\.)?,?\s*\d{4}[a-z]?)\)"),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:K|°C|MPa|kPa|bar|h|min|s|nm|μm|cm|mmol|mol|wt%)\b"),
    re.compile(r"\b(?:[A-Z][a-z]?\d*){2,}(?:[/@-](?:[A-Z][a-z]?\d*)+)*\b"),
)


@dataclass(frozen=True)
class ProtectedText:
    text: str
    values: tuple[str, ...]

    def restore(self, translated: str) -> str:
        restored = translated
        for index, value in enumerate(self.values):
            marker = f"⟦P{index}⟧"
            if restored.count(marker) != 1:
                raise ValueError("翻译结果丢失或重复了受保护内容")
            restored = restored.replace(marker, value)
        return restored


def protect_text(text: str, do_not_translate: list[str] | tuple[str, ...] = ()) -> ProtectedText:
    values: list[str] = []

    def replace(match: re.Match[str]) -> str:
        marker = f"⟦P{len(values)}⟧"
        values.append(match.group(0))
        return marker

    protected = text
    custom = [term for term in do_not_translate if term.strip()]
    if custom:
        protected = re.sub(
            "|".join(re.escape(term) for term in sorted(custom, key=len, reverse=True)),
            replace,
            protected,
            flags=re.IGNORECASE,
        )
    for pattern in PROTECTED_PATTERNS:
        protected = pattern.sub(replace, protected)
    return ProtectedText(protected, tuple(values))


def split_segments(text: str, *, max_chars: int = 1_600) -> list[str]:
    if max_chars < 40:
        raise ValueError("Segment size is too small")
    paragraphs = re.split(r"(\n\s*\n)", text.strip())
    segments: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if not paragraph:
            continue
        pieces = (
            [paragraph]
            if len(paragraph) <= max_chars
            else _split_long_paragraph(paragraph, max_chars)
        )
        for piece in pieces:
            if current and len(current) + len(piece) > max_chars:
                segments.append(current)
                current = ""
            current += piece
    if current:
        segments.append(current)
    return segments


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    sentences = re.split(
        r"(?<=[.!?\u3002\uFF01\uFF1F])(?=\s|[A-Z\u4e00-\u9fff])", paragraph
    )
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(
                sentence[index : index + max_chars]
                for index in range(0, len(sentence), max_chars)
            )
        elif current and len(current) + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        pieces.append(current)
    return pieces


def glossary_version(glossary: dict[str, str], protected_terms: list[str]) -> str:
    serialized = "\n".join(
        [*(f"{key}={value}" for key, value in sorted(glossary.items())), *sorted(protected_terms)]
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def build_instruction(glossary: dict[str, str]) -> str:
    terms = "; ".join(f"{source}→{target}" for source, target in sorted(glossary.items()))
    return (
        "将下面的英文学术文本准确翻译为简体中文. 只输出译文; 保留段落、⟦P数字⟧占位符, "
        "不要添加解释. 催化领域术语优先使用: " + terms
    )
