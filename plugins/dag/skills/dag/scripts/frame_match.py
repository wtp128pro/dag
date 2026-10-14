#!/usr/bin/env python3
"""frame_match.py - the dag skill's single path matcher (stdlib only, no side effects on import).

Every consumer of frame patterns (validate_run.py and every blast-radius script) imports this module; none
keeps a private copy. The semantics are ported from a reference implementation and restated here so this file
is the contract:

Pattern language (one pattern = '/'-separated segments, workspace-relative):
  * Surrounding whitespace is stripped, '\\' is rewritten to '/', leading './' segments are dropped and '//'
    collapses. There is no escape character; a literal glob char is matched with a class, e.g. 'a[*]b'.
  * Inside a segment: '*' matches any run of characters (runs of '*' collapse), '?' one character, '[...]' a
    character class ('!' or '^' first negates, 'a-c' is a range; '[' with no ']' at least two characters later
    is a literal). '*' and '?' NEVER cross '/'. There is no dotfile rule ('*' matches '.env').
  * A whole segment '**' matches zero or more segments (consecutive '**' collapse; '**' inside 'a**b' is '*').
  * A pattern COVERS everything beneath what it matches iff it is glob-free, or ends in '/', or ends in '/**'
    (the trailing '**' is then dropped). Any other glob pattern must full-match the path ('src/*' does not match
    'src/x/y'). A bare '**' matches every non-empty path.
  * Rejected (invalid; matches nothing, overlaps nothing, never raises): non-str, empty or blank, '.' / './',
    absolute ('/x'), drive-letter ('C:x'), any '..' segment, any NUL, more than MAX_PATTERN_CHARS characters
    or more than MAX_PATTERN_SEGMENTS segments. Unsafe PATHS ('..', absolute, NUL, empty) never match.

Overlap is EXACT: path_overlaps(p, q) is True iff some concrete path is matched by both patterns (a state-pair
search over the two parsed patterns; a shared segment name is never '', '.', '..' and never contains '/').

Public API: is_valid_pattern(pattern), match_any_pattern(path, patterns), path_overlaps(p, q),
set_overlaps(list_a, list_b) -> list of (a, b) pairs.

CLI:
  python3 frame_match.py overlap <graph.json>
      Reads units[] ({id, deps, frame.modifies}) and edges[] ({from, to}; 'to' depends on 'from'). Prints one
      line per unordered pair of units with NO dependency path either way whose frame.modifies overlap.
      Exit 1 if any pair is printed, 0 if none, 2 on unreadable or malformed input.
  python3 frame_match.py --self-test
      One line per case: 'case <rule> pos|neg ok' (or FAIL); exit 0 iff every case is ok.
"""
import functools
import itertools
import json
import posixpath
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

MAX_PATTERN_CHARS = 512
MAX_PATTERN_SEGMENTS = 64
_GLOB_CHARS = "*?["


def _strip_dot_slash(path_str: str) -> str:
    """Strip surrounding whitespace, rewrite '\\' to '/', drop leading './' segments (never other characters)."""
    clean = str(path_str).strip().replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    return clean


def is_unsafe_path(path_str: Any) -> bool:
    """True for anything that is not a plain workspace-relative path below the root: non-str, empty/blank, NUL,
    '.' or './' (the root itself), absolute (POSIX, UNC or drive-letter) or any '..' segment. Rejected, never
    normalized away."""
    if not isinstance(path_str, str) or not path_str.strip() or "\0" in path_str:
        return True
    clean = _strip_dot_slash(path_str)
    if clean.startswith("/") or re.match(r"^[A-Za-z]:", clean) or ".." in clean.split("/"):
        return True
    return posixpath.normpath(clean or ".") == "."


def _norm(path_str: str) -> str:
    clean = posixpath.normpath(_strip_dot_slash(path_str))
    return "" if clean == "." else clean


def _tokenize_segment(seg: str) -> List[Tuple[Any, ...]]:
    """Tokens of one segment: ('*',), ('?',), ('set', negate, ranges) or ('lit', char). Runs of '*' collapse."""
    tokens: List[Tuple[Any, ...]] = []
    i = 0
    while i < len(seg):
        c = seg[i]
        if c == "*":
            if not tokens or tokens[-1] != ("*",):
                tokens.append(("*",))
            i += 1
        elif c == "?":
            tokens.append(("?",))
            i += 1
        elif c == "[" and seg.find("]", i + 2) != -1:
            j = seg.find("]", i + 2)
            body = seg[i + 1:j]
            negate = body[:1] in ("!", "^")
            if negate:
                body = body[1:]
            items: List[Tuple[str, str]] = []
            k = 0
            while k < len(body):
                if k + 2 < len(body) and body[k + 1] == "-":
                    items.append((body[k], body[k + 2]))
                    k += 3
                else:
                    items.append((body[k], body[k]))
                    k += 1
            tokens.append(("set", negate, tuple(items)))
            i = j + 1
        else:
            tokens.append(("lit", c))
            i += 1
    return tokens


def _segment_matches(tokens: List[Tuple[Any, ...]], text: str) -> bool:
    """Full match of one segment's tokens against `text` (DP, O(len(tokens) * len(text)), no backtracking)."""
    n = len(text)
    prev = [True] + [False] * n
    for tok in tokens:
        cur = [False] * (n + 1)
        if tok[0] == "*":
            carry = False
            for j in range(n + 1):
                carry = carry or prev[j]
                cur[j] = carry
        else:
            for j in range(1, n + 1):
                if not prev[j - 1]:
                    continue
                ch = text[j - 1]
                if tok[0] == "?":
                    cur[j] = True
                elif tok[0] == "lit":
                    cur[j] = ch == tok[1]
                else:
                    cur[j] = any(lo <= ch <= hi for lo, hi in tok[2]) != tok[1]
        prev = cur
    return prev[n]


def _parse_pattern(pattern: Any) -> Optional[Tuple[List[str], bool]]:
    """(segments, covers) for a valid pattern, else None. Consecutive '**' collapse; covers is True only for
    glob-free patterns and patterns ending in '/' or '/**' (the trailing '**' is then dropped)."""
    if not isinstance(pattern, str) or is_unsafe_path(pattern) or len(pattern) > MAX_PATTERN_CHARS:
        return None
    raw = _strip_dot_slash(pattern)
    dir_flag = raw.endswith("/")
    norm = _norm(raw.rstrip("/"))
    if not norm:
        return None
    segs = norm.split("/")
    if len(segs) > MAX_PATTERN_SEGMENTS:
        return None
    collapsed: List[str] = []
    for seg in segs:
        if seg == "**" and collapsed and collapsed[-1] == "**":
            continue
        collapsed.append(seg)
    covers = dir_flag or not any(ch in seg for seg in collapsed for ch in _GLOB_CHARS)
    if len(collapsed) > 1 and collapsed[-1] == "**":
        collapsed = collapsed[:-1]
        covers = True
    return collapsed, covers


def is_valid_pattern(pattern: Any) -> bool:
    """True iff `pattern` is a usable, bounded, workspace-relative pattern."""
    return _parse_pattern(pattern) is not None


def _pattern_matches(segs: List[str], covers: bool, path_segs: List[str]) -> bool:
    """Segment-level DP. '**' matches zero or more path segments; with `covers`, any non-empty leading part of the
    path may be the match."""
    m, n = len(segs), len(path_segs)
    seg_tokens = [None if sg == "**" else _tokenize_segment(sg) for sg in segs]
    f = [[False] * (n + 1) for _ in range(m + 1)]
    f[0][0] = True
    for i in range(1, m + 1):
        for j in range(n + 1):
            if seg_tokens[i - 1] is None:
                f[i][j] = f[i - 1][j] or (j > 0 and f[i][j - 1])
            else:
                f[i][j] = j > 0 and f[i - 1][j - 1] and _segment_matches(seg_tokens[i - 1], path_segs[j - 1])
    return any(f[m][j] for j in range(1, n + 1)) if covers else f[m][n]


def match_any_pattern(path_str: Any, patterns: List[Any]) -> bool:
    """True iff the path matches some valid pattern. Unsafe paths never match; invalid patterns are ignored."""
    if is_unsafe_path(path_str):
        return False
    clean_p = _norm(path_str)
    if not clean_p:
        return False
    path_segs = clean_p.split("/")
    for pat in patterns:
        parsed = _parse_pattern(pat)
        if parsed is not None and _pattern_matches(parsed[0], parsed[1], path_segs):
            return True
    return False


# --- exact overlap ----------------------------------------------------------------------------------------------

def _accepts(token: Tuple[Any, ...], ch: str) -> bool:
    if token[0] in ("*", "?"):
        return True
    if token[0] == "lit":
        return ch == token[1]
    return any(lo <= ch <= hi for lo, hi in token[2]) != token[1]


def _common_chars(*tokens: Tuple[Any, ...]) -> Set[bool]:
    """Kinds of characters accepted by ALL tokens: True = '.', False = any other non-'/' character. Exact: each
    token is a union of code-point intervals bounded by the breakpoints below (plus '.', '/', '0' as atoms), so the
    first code point of every atom represents the whole atom."""
    points = {0, 46, 47, 48}
    for tok in tokens:
        if tok[0] == "lit":
            points.update((ord(tok[1]), ord(tok[1]) + 1))
        elif tok[0] == "set":
            for lo, hi in tok[2]:
                points.update((ord(lo), ord(hi) + 1))
    return {chr(p) == "." for p in points if p <= 0x10FFFF and p != 47 and all(_accepts(t, chr(p)) for t in tokens)}


def _segments_share_name(xs: List[Tuple[Any, ...]], ys: List[Tuple[Any, ...]]) -> bool:
    """Whether some valid segment NAME (non-empty, no '/', not '.' or '..') fully matches both token lists.
    Product-automaton search over (pos in xs, pos in ys, d), d: 0 empty, 1 '.', 2 '..', 3 other (absorbing)."""
    star = ("*",)
    start = (0, 0, 0)
    seen, stack = {start}, [start]
    while stack:
        a, b, d = stack.pop()
        if d == 3 and all(t == star for t in xs[a:]) and all(t == star for t in ys[b:]):
            return True
        moves = []
        if a < len(xs) and xs[a] == star:
            moves.append((a + 1, b, d))
        if b < len(ys) and ys[b] == star:
            moves.append((a, b + 1, d))
        if a < len(xs) and b < len(ys):
            na, nb = a if xs[a] == star else a + 1, b if ys[b] == star else b + 1
            for dot in _common_chars(xs[a], ys[b]):
                moves.append((na, nb, {(0, True): 1, (1, True): 2}.get((d, dot), 3)))
        for move in moves:
            if move not in seen:
                seen.add(move)
                stack.append(move)
    return False


_ANY_NAME: List[Tuple[Any, ...]] = [("*",)]


def _patterns_overlap(pat_p: Tuple[List[str], bool], pat_q: Tuple[List[str], bool]) -> bool:
    """Exact: some concrete path is matched by both parsed patterns. Search over states (i, j) = segments of each
    pattern consumed by the shared path prefix; at most (|P|+1)(|Q|+1) states."""
    segs_p, covers_p = pat_p
    segs_q, covers_q = pat_q
    toks_p = [None if s == "**" else _tokenize_segment(s) for s in segs_p]  # None marks a '**' segment
    toks_q = [None if s == "**" else _tokenize_segment(s) for s in segs_q]

    def names_at(toks: List[Any], covers: bool, i: int) -> Optional[List[Tuple[Any, ...]]]:
        """Tokens the next path segment must match at state i, or None if no further segment can be consumed."""
        if i == len(toks):
            return _ANY_NAME if covers else None
        return _ANY_NAME if toks[i] is None else toks[i]

    shares: Dict[Tuple[int, int], bool] = {}
    seen, stack = {(0, 0)}, [(0, 0)]
    while stack:
        i, j = stack.pop()
        if all(t is None for t in toks_p[i:]) and all(t is None for t in toks_q[j:]):
            return True
        moves = []
        if i < len(toks_p) and toks_p[i] is None:
            moves.append((i + 1, j))
        if j < len(toks_q) and toks_q[j] is None:
            moves.append((i, j + 1))
        names_p, names_q = names_at(toks_p, covers_p, i), names_at(toks_q, covers_q, j)
        if names_p is not None and names_q is not None:
            if (i, j) not in shares:
                shares[(i, j)] = _segments_share_name(names_p, names_q)
            if shares[(i, j)]:
                moves.append((i if i == len(toks_p) or toks_p[i] is None else i + 1,
                              j if j == len(toks_q) or toks_q[j] is None else j + 1))
        for move in moves:
            if move not in seen:
                seen.add(move)
                stack.append(move)
    return False


@functools.lru_cache(maxsize=1 << 14)
def _path_overlaps(pat1: str, pat2: str) -> bool:
    c1, c2 = _parse_pattern(pat1), _parse_pattern(pat2)
    return c1 is not None and c2 is not None and _patterns_overlap(c1, c2)


def path_overlaps(pat1: Any, pat2: Any) -> bool:
    """Exact: can some concrete path be matched by both patterns (same language and covers rule as
    match_any_pattern)? 'src/auth' overlaps 'src/auth/token.ts'; 'src/*.ts' does not overlap 'src/a.ts/deep.py'.
    An invalid pattern overlaps nothing."""
    return isinstance(pat1, str) and isinstance(pat2, str) and _path_overlaps(pat1, pat2)


def set_overlaps(list_a: List[Any], list_b: List[Any]) -> List[Tuple[Any, Any]]:
    """Every (a, b) with a in list_a, b in list_b and path_overlaps(a, b), in input order."""
    return [(a, b) for a in list_a for b in list_b if path_overlaps(a, b)]


# --- CLI: overlap <graph.json> ----------------------------------------------------------------------------------

class _Malformed(Exception):
    pass


def _load_graph(path: str) -> Tuple[List[str], Dict[str, List[str]], Dict[str, Set[str]]]:
    """(unit ids in order, id -> modifies, id -> direct deps). Raises OSError/ValueError/_Malformed."""
    with open(path, "r", encoding="utf-8") as fh:
        graph = json.load(fh)
    if not isinstance(graph, dict):
        raise _Malformed("top level is not an object")
    units, edges = graph.get("units"), graph.get("edges")
    if not isinstance(units, list) or not isinstance(edges, list):
        raise _Malformed("units[] and edges[] must both be arrays")
    order: List[str] = []
    modifies: Dict[str, List[str]] = {}
    deps: Dict[str, Set[str]] = {}
    for u in units:
        uid = u.get("id") if isinstance(u, dict) else None
        if not isinstance(uid, str) or not uid or uid in modifies:
            raise _Malformed("unit without a unique string id: %r" % (uid if isinstance(u, dict) else u,))
        frame = u.get("frame", {})
        mods = frame.get("modifies", []) if isinstance(frame, dict) else None
        d = u.get("deps", [])
        if not isinstance(mods, list) or not all(isinstance(p, str) for p in mods):
            raise _Malformed("%s: frame.modifies must be an array of strings" % uid)
        if not isinstance(d, list) or not all(isinstance(x, str) for x in d):
            raise _Malformed("%s: deps must be an array of unit ids" % uid)
        order.append(uid)
        modifies[uid] = mods
        deps[uid] = set(d)
    for e in edges:
        src, dst = (e.get("from"), e.get("to")) if isinstance(e, dict) else (None, None)
        if not isinstance(src, str) or not isinstance(dst, str):
            raise _Malformed("edge without string from/to: %r" % (e,))
        if dst not in deps:
            raise _Malformed("edge to unknown unit %r" % dst)
        deps[dst].add(src)
    for uid, ds in deps.items():
        unknown = sorted(ds - set(deps))
        if unknown:
            raise _Malformed("%s depends on unknown unit(s) %s" % (uid, ", ".join(unknown)))
    return order, modifies, deps


def _ancestors(deps: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    anc: Dict[str, Set[str]] = {}
    for uid in deps:
        seen: Set[str] = set()
        stack = list(deps[uid])
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x)
                stack.extend(deps[x])
        anc[uid] = seen
    return anc


def cmd_overlap(path: str) -> int:
    try:
        order, modifies, deps = _load_graph(path)
    except (OSError, UnicodeDecodeError, ValueError, _Malformed) as exc:
        print("frame_match overlap: unreadable or malformed graph %s: %s" % (path, exc), file=sys.stderr)
        return 2
    anc = _ancestors(deps)
    found = 0
    for a, b in itertools.combinations(order, 2):
        if a in anc[b] or b in anc[a]:
            continue
        pairs = set_overlaps(modifies[a], modifies[b])
        if pairs:
            found += 1
            print("OVERLAP %s %s: %s" % (a, b, "; ".join("%s ~ %s" % (p, q) for p, q in pairs)))
    print("frame_match overlap: %d independent overlapping pair(s)" % found, file=sys.stderr)
    return 1 if found else 0


# --- self-test --------------------------------------------------------------------------------------------------

def _self_test() -> int:
    m = match_any_pattern
    cases = [
        ("star", "pos", lambda: m("src/a.py", ["src/*.py"]) and m("src/.env", ["src/*"])),
        ("star", "neg", lambda: not m("src/x/a.py", ["src/*.py"]) and not m("a/b", ["a*b"])),
        ("qmark", "pos", lambda: m("abc", ["a?c"]) and m("d/x", ["d/?"])),
        ("qmark", "neg", lambda: not m("a/c", ["a?c"]) and not m("d/xy", ["d/?"])),
        ("globstar", "pos", lambda: m("src/a.py", ["src/**/*.py"]) and m("src/x/y/a.py", ["src/**/*.py"])
            and m("x", ["**/x"]) and m("a/b", ["a/**/b"]) and m("a/b", ["a/**/**/b"])),
        ("globstar", "neg", lambda: not m("src/x/a.ts", ["src/**/*.py"]) and not m("a/b", ["a**b"])
            and not m("b", ["a/**/b"])),
        ("covers", "pos", lambda: m("src/x/y", ["src"]) and m("src/x", ["src/"]) and m("src/x/y", ["src/**"])),
        ("covers", "neg", lambda: not m("src/x/y", ["src/*"]) and not m("srcx/y", ["src"])
            and not m("src", ["src/x"])),
        ("unsafe", "pos", lambda: all(not is_valid_pattern(p) for p in
            ["", "  ", ".", "./", "..", "/a", "a/../b", "C:/x", "a\x00b", "x" * 513, "/".join(["a"] * 65), 5, None])
            and not m("src/../src/a", ["src/**"]) and not m("/src/a", ["**"])),
        ("unsafe", "neg", lambda: is_valid_pattern("/".join(["a"] * 64)) and is_valid_pattern("x" * 512)
            and m("a/b", ["a\\b"]) and m("a/b", [" ./a//b "])),
        ("overlap", "pos", lambda: path_overlaps("src/auth", "src/auth/token.ts")
            and path_overlaps("src/**/tests", "src/auth.ts") and path_overlaps("docs/*.md", "**/*.md")
            and set_overlaps(["x/y", "src/**"], ["q", "src/a"]) == [("src/**", "src/a")]),
        ("overlap", "neg", lambda: not path_overlaps("src/*.ts", "src/a.ts/deep.py")
            and not path_overlaps("*.md", "docs/*.md") and not path_overlaps("a/[0-9]x", "a/[!0-9]x")
            and not path_overlaps("a/.*", "a/..") and not path_overlaps("/a", "/a")
            and set_overlaps(["a/*"], ["b/**"]) == []),
    ]
    ok_all = True
    for rule, sign, fn in cases:
        try:
            ok = bool(fn())
        except Exception as exc:  # a crash is a failure, never a pass
            print("  crash in %s %s: %r" % (rule, sign, exc), file=sys.stderr)
            ok = False
        ok_all &= ok
        print("case %s %s %s" % (rule, sign, "ok" if ok else "FAIL"))
    # Brute force: over paths of depth <= 4 drawn from names {a, b, ab}, two patterns overlap iff some path is
    # matched by both. Pattern segments are chosen so every shared name is witnessable inside that alphabet.
    names = ["a", "b", "ab"]
    paths = ["/".join(t) for d in range(1, 5) for t in itertools.product(names, repeat=d)]
    segs = ["a", "b", "ab", "*", "?", "a*", "*b", "[ab]", "**"]
    pats = ["/".join(t) + tail for d in (1, 2) for t in itertools.product(segs, repeat=d) for tail in ("", "/")]
    hits = {p: frozenset(x for x in paths if m(x, [p])) for p in pats}
    bad = [(p, q) for p, q in itertools.combinations_with_replacement(pats, 2)
           if bool(hits[p] & hits[q]) != path_overlaps(p, q)]
    for rule_sign, ok in (("pos", not bad and any(hits[p] & hits[q] for p, q in [("a/**", "*/b")])),
                          ("neg", not bad and not (hits["a/*"] & hits["b"]))):
        ok_all &= ok
        print("case overlap %s %s" % (rule_sign, "ok" if ok else "FAIL"))
    if bad:
        print("  brute-force mismatches (first 5): %r" % (bad[:5],), file=sys.stderr)
    print("frame_match self-test: brute force checked %d pattern pairs over %d paths" %
          (len(pats) * (len(pats) + 1) // 2, len(paths)), file=sys.stderr)
    return 0 if ok_all else 1


def main(argv: List[str]) -> int:
    if argv == ["--self-test"]:
        return _self_test()
    if len(argv) == 2 and argv[0] == "overlap":
        return cmd_overlap(argv[1])
    print("usage: frame_match.py overlap <graph.json> | --self-test", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
