"""从 data/cache/filings 重新切分财报，生成 data/index/chunks.jsonl。"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finagent.rag.chunker import build_chunks, save_chunks  # noqa: E402

chunks = build_chunks()
save_chunks(chunks)
print(f"{len(chunks)} chunks")
for (t, f), n in sorted(Counter((c.ticker, c.form) for c in chunks).items()):
    print(f"  {t} {f}: {n}")
