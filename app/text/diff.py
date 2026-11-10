import difflib


def sentence_changes(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    """문장 단위 차이. (삭제·수정 전 문장들, 추가·수정 후 문장들)"""
    removed: list[str] = []
    added: list[str] = []
    sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            removed.extend(old[i1:i2])
        if tag in ("replace", "insert"):
            added.extend(new[j1:j2])
    return removed, added
