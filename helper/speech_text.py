"""Turn a markdown reply into something worth reading aloud (stdlib only). Run for the self-check."""
import re

MAX_SPOKEN = 1500   # ponytail: hard cap, cut at a sentence; the system prompt already asks for short replies. Upgrade: summarize long answers with a model.


def speakable(md: str) -> str:
    """Strip what shouldn't be read aloud: code, tables, paths, markdown symbols."""
    text = re.sub(r"```.*?```", " (code on screen) ", md, flags=re.S)
    text = re.sub(r"^\|.*\|\s*$", "", text, flags=re.M)               # table rows
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)              # links -> label
    text = re.sub(r"`([^`]+)`", lambda m: m.group(1) if len(m.group(1)) <= 30 else "that", text)
    text = re.sub(r"(?:[A-Za-z]:)?(?:~|\.{0,2})?[/\\][\w./\\@-]+[/\\][\w.@-]+", "a path", text)  # unix and windows paths
    text = re.sub(r"[*#>]+", "", text).replace("_", " ")  # compute_key -> "compute key"
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_SPOKEN:
        cut = text[:MAX_SPOKEN]
        end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        text = (cut[: end + 1] if end > 0 else cut) + " The rest is on screen."
    return text


if __name__ == "__main__":
    out = speakable("Here's the fix in `compute_key`:\n```rust\nfn x() {}\n```\nSee [docs](https://x.y), /Users/me/proj/src/cache.rs and C:\\proj\\src\\cache.rs.\n- **Done**")
    assert "fn x" not in out and "(code on screen)" in out and "compute key" in out, out
    assert "https" not in out and "cache.rs" not in out and out.count("a path") == 2 and "*" not in out, out
    long = speakable("This is a sentence. " * 200)
    assert len(long) < MAX_SPOKEN + 40 and long.endswith("The rest is on screen."), long[-60:]
    print("ok:", out)
