"""把 10-K / 10-Q 纯文本按 Part / Item 切分，再按段落合并成 chunk。

chunk_id 格式: {TICKER}-{FORM}-{SECTION}-{序号}，例如 NVDA-10K-1A-007、AAPL-10Q-P2-1A-003。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from .. import config

ITEM_RE = re.compile(r"^item\s+(\d{1,2}[a-c]?)\s*[\.:]?\s*(.*)$", re.I)
PART_RE = re.compile(r"^part\s+(iv|i{1,3})\b", re.I)
MAX_CHARS = 1500

# 标准条目名称。部分公司排版会把标题拆碎（如 MSFT 的 "RIS"），统一用 SEC 表格的标准名称。
TITLES_10K = {
    "1": "Business", "1A": "Risk Factors", "1B": "Unresolved Staff Comments", "1C": "Cybersecurity",
    "2": "Properties", "3": "Legal Proceedings", "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity", "6": "[Reserved]",
    "7": "Management's Discussion and Analysis", "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data", "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures", "9B": "Other Information", "9C": "Disclosure Regarding Foreign Jurisdictions",
    "10": "Directors, Executive Officers and Corporate Governance", "11": "Executive Compensation",
    "12": "Security Ownership", "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services", "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}
TITLES_10Q = {
    ("I", "1"): "Financial Statements", ("I", "2"): "Management's Discussion and Analysis",
    ("I", "3"): "Quantitative and Qualitative Disclosures About Market Risk", ("I", "4"): "Controls and Procedures",
    ("II", "1"): "Legal Proceedings", ("II", "1A"): "Risk Factors",
    ("II", "2"): "Unregistered Sales of Equity Securities and Use of Proceeds", ("II", "3"): "Defaults Upon Senior Securities",
    ("II", "4"): "Mine Safety Disclosures", ("II", "5"): "Other Information", ("II", "6"): "Exhibits",
}
MIN_SECTION_CHARS = 300


@dataclass
class Chunk:
    chunk_id: str
    ticker: str
    company: str
    form: str
    period: str
    section: str        # 例如 "Item 1A" 或 "Part II Item 1A"
    section_title: str
    text: str
    url: str


def split_sections(text: str, form: str) -> list[tuple[str, str, str]]:
    """返回 [(section_key, title, body)]。目录行（标题为空、正文过短）会被丢弃。"""
    lines = text.splitlines()
    heads = []  # (line_idx, part, item, title, title_inline)
    part = ""
    for i, ln in enumerate(lines):
        s = ln.strip()
        if len(s) > 250:
            continue
        m = PART_RE.match(s)
        if m:
            part = m.group(1).upper()
            continue
        m = ITEM_RE.match(s)
        if m:
            title = m.group(2).strip()
            inline = bool(title)
            if not title:
                for j in range(i + 1, min(i + 4, len(lines))):
                    if lines[j].strip():
                        nxt = lines[j].strip()
                        if not ITEM_RE.match(nxt) and not PART_RE.match(nxt) and len(nxt) < 200:
                            title = nxt
                        break
            heads.append((i, part, m.group(1).upper(), title, inline))
    # 有些公司（如 MSFT）每页都重复 "PART I / Item 1" 页眉，所以同一 Item 的多个片段要拼接，而不是只取一段。
    sections: dict[str, list] = {}
    for k, (i, part, item, title, inline) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        body = "\n".join(lines[i + 1:end]).strip()
        if len(body) < 80:  # 目录行
            continue
        key = f"Item {item}" if form == "10-K" else f"Part {part or 'I'} Item {item}"
        ent = sections.setdefault(key, ["", [], False])
        std = TITLES_10K.get(item) if form == "10-K" else TITLES_10Q.get((part or "I", item))
        if std:
            ent[0] = std
        elif title and (not ent[0] or (inline and not ent[2])):
            ent[0], ent[2] = title, inline
        ent[1].append(body)
    sections = {k: (v[0], "\n\n".join(v[1])) for k, v in sections.items()
                if sum(len(b) for b in v[1]) >= MIN_SECTION_CHARS}
    return [(k, t, b) for k, (t, b) in sections.items()]


def _paragraphs(body: str) -> list[str]:
    paras = [re.sub(r"\s*\n\s*", " ", p).strip() for p in re.split(r"\n\s*\n", body)]
    return [p for p in paras if p]


def chunk_section(body: str) -> list[str]:
    out, buf = [], ""
    for p in _paragraphs(body):
        while len(p) > MAX_CHARS:  # 超长段落硬切
            cut = p.rfind(". ", 0, MAX_CHARS)
            cut = cut + 1 if cut > MAX_CHARS // 2 else MAX_CHARS
            if buf:
                out.append(buf)
                buf = ""
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if len(buf) + len(p) + 1 > MAX_CHARS and buf:
            out.append(buf)
            buf = p
        else:
            buf = f"{buf} {p}".strip()
    if buf:
        out.append(buf)
    return [c for c in out if len(c) >= 40]


def section_code(key: str) -> str:
    # "Item 1A" -> "1A"; "Part II Item 1A" -> "P2-1A"
    m = re.match(r"Part (IV|I{1,3}) Item (\w+)", key)
    if m:
        roman = {"I": 1, "II": 2, "III": 3, "IV": 4}[m.group(1)]
        return f"P{roman}-{m.group(2)}"
    return key.replace("Item ", "")


def build_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    for meta_path in sorted(config.FILINGS_DIR.glob("*.meta.json")):
        meta = json.loads(meta_path.read_text())
        text = meta_path.with_name(meta_path.name.replace(".meta.json", ".txt")).read_text(encoding="utf-8")
        form = meta["form"]
        for key, title, body in split_sections(text, form):
            for n, c in enumerate(chunk_section(body)):
                cid = f"{meta['ticker']}-{form.replace('-', '')}-{section_code(key)}-{n:03d}"
                chunks.append(Chunk(cid, meta["ticker"], meta["company"], form, meta["report_date"],
                                    key, title, c, meta["url"]))
    return chunks


def save_chunks(chunks: list[Chunk]) -> None:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.INDEX_DIR / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")


def load_chunks() -> list[Chunk]:
    path = config.INDEX_DIR / "chunks.jsonl"
    if not path.exists():
        chunks = build_chunks()
        save_chunks(chunks)
        return chunks
    return [Chunk(**json.loads(l)) for l in path.read_text(encoding="utf-8").splitlines() if l]
