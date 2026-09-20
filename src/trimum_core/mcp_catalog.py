"""MCP curation importer — awesome-mcp-servers README → ``config/mcp-catalog.yaml``.

This is posture B of ``docs/MCP-INTEGRATION-PLAN.md`` §5: the upstream list is *not*
mirrored into trimum.  A local README snapshot is parsed, the entries matching the
project's red line are ranked into a **candidate list**, and a human decides which of
them become ``~/.trimum/mcp/<name>.json5`` definitions.

Four invariants, in the same spirit as ``env_toolchain.py``:

* **offline** — only a local file is read; nothing is fetched and no server is contacted;
* **candidate ≠ enabled** — entries are emitted with ``reviewed: false`` and nothing is
  written to ``~/.trimum/mcp/``; enabling stays a deliberate, file-level act;
* **the red line is accounted for** — every dropped entry is counted under a reason
  (``language:ts``, ``dist:npx``, ``dist:unknown`` ...) in the generated summary, so the
  size of what was cut never hides;
* **deterministic** — same README in, same bytes out (stable sort, no timestamps), so
  re-imports diff cleanly and human ``reviewed`` marks survive through carry-over.

Red line (``docs/MCP-INTEGRATION-PLAN.md`` §3): TypeScript/Node is the majority of the
upstream list, so keeping it out is the whole point — accepted languages are
``python`` / ``go`` / ``rust``, accepted distributions ``uvx`` / ``uv`` / ``pip`` /
``go install`` / ``cargo install`` / ``docker``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

#: Repository root — the importer reads the snapshot and writes the catalog inside it.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Local snapshot of the upstream list (never fetched, see the module docstring).
DEFAULT_SOURCE = REPO_ROOT / "tmp" / "research" / "awesome-README.md"

#: Generated candidate list; tracked so review happens in a pull request.
DEFAULT_CATALOG = REPO_ROOT / "config" / "mcp-catalog.yaml"

CATALOG_VERSION = 1

#: Only entries below this README section are server implementations.
SERVER_SECTION = "Server Implementations"

#: Legend markers (``docs/MCP-INTEGRATION-PLAN.md`` §3).  Order is the legend order and
#: only breaks ties when two markers share a position, which cannot happen.
LANGUAGE_MARKERS: dict[str, str] = {
    "\U0001F40D": "python",
    "\U0001F4C7": "ts",
    "\U0001F3CE\ufe0f": "go",
    "\U0001F980": "rust",
    "#\ufe0f\u20e3": "csharp",
    "\u2615": "java",
    "\U0001F30A": "c_cpp",
    "\U0001F48E": "ruby",
}
SCOPE_MARKERS: dict[str, str] = {
    "\u2601\ufe0f": "cloud",
    "\U0001F3E0": "local",
    "\U0001F4DF": "embedded",
}
SYSTEM_MARKERS: dict[str, str] = {
    "\U0001F34E": "macos",
    "\U0001FA9F": "windows",
    "\U0001F427": "linux",
}
OFFICIAL_MARKER = "\U0001F396\ufe0f"

ALL_LANGUAGES: tuple[str, ...] = tuple(dict.fromkeys(LANGUAGE_MARKERS.values()))
ALL_DISTRIBUTIONS: tuple[str, ...] = (
    "uvx", "uv", "pip", "go", "cargo", "docker", "npx", "npm", "pnpm", "yarn",
    "bun", "deno", "brew", "gem", "dotnet", "unknown",
)

#: Languages trimum is willing to run (the Node faction is excluded on purpose).
ALLOWED_LANGUAGES: tuple[str, ...] = ("python", "go", "rust")

#: Distributions that do not drag the Node toolchain in.
ALLOWED_DISTRIBUTIONS: tuple[str, ...] = ("uvx", "uv", "pip", "go", "cargo", "docker")

#: Node/TypeScript-adjacent distributions — dropped unless explicitly re-enabled.
NODE_DISTRIBUTIONS: tuple[str, ...] = ("npx", "npm", "pnpm", "yarn", "bun", "deno")

#: Distribution probes, in priority order (first match wins, so a line offering both
#: ``uvx`` and ``npx`` is filed under ``uvx``).  ``tail`` is the rest of the command,
#: from which the package name is picked by :func:`_package_token`.
DISTRIBUTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("uvx", r"\buvx\s+(?P<tail>[^\n`\"']+)"),
        ("uv", r"\buv\s+(?:tool\s+run|run)\s+(?P<tail>[^\n`\"']+)"),
        ("pip", r"\bpip(?:x|3)?\s+install\s+(?P<tail>[^\n`\"']+)"),
        ("go", r"\bgo\s+install\s+(?P<tail>[^\n`\"']+)"),
        ("cargo", r"\bcargo\s+(?:install|run)\s+(?P<tail>[^\n`\"']+)"),
        ("docker", r"\bdocker\s+(?P<sub>run|pull|compose)\b\s*(?P<tail>[^\n`\"']*)"),
        ("npx", r"\bnpx\b"),
        ("npm", r"\bnpm\s+(?:i|install|exec|create|add)\b"),
        ("pnpm", r"\bpnpm\b"),
        ("yarn", r"\byarn\b"),
        ("bun", r"\bbun\b"),
        ("deno", r"\bdeno\s+(?:run|install|x)\b"),
        ("brew", r"\bbrew\s+install\b"),
        ("gem", r"\bgem\s+install\b"),
        ("dotnet", r"\bdotnet\s+(?:tool|run)\b"),
    )
)

#: Flags that consume the following token, so the package name is one token further.
VALUE_FLAGS: dict[str, frozenset[str]] = {
    "uvx": frozenset(
        {"--from", "--with", "--python", "-p", "--index", "--extra", "--default-index",
         "--env-file", "--directory", "--project", "--constraints", "--overrides",
         "--python-preference"}
    ),
    "uv": frozenset(
        {"--from", "--with", "--python", "-p", "--index", "--extra", "--env-file",
         "--directory", "--project", "--constraints", "--overrides"}
    ),
    "pip": frozenset(
        {"-r", "--requirement", "-c", "--constraint", "-i", "--index-url", "-f",
         "--find-links", "-t", "--target", "--extra-index-url", "--upgrade-strategy",
         "--python", "--prefix", "--src", "--cache-dir"}
    ),
    "cargo": frozenset(
        {"--version", "--git", "--branch", "--tag", "--rev", "--path", "--features",
         "--target", "--index", "--registry", "--root", "--locked"}
    ),
    "docker": frozenset(
        {"-e", "--env", "-v", "--volume", "-p", "--publish", "--name", "-w", "--workdir",
         "--network", "--entrypoint", "-u", "--user", "--mount", "--label", "--add-host",
         "--env-file", "--platform", "--restart", "--memory", "-m", "--entrypoint"}
    ),
}

#: ``- [owner/repo](url) ...`` — the entry form used by the upstream README.
ENTRY_RE = re.compile(r"^[-*] \[(?P<label>[^\]]+)\]\((?P<url>https?://[^)\s]+)\)")
SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
ANCHOR_RE = re.compile(r"<a name=\"(?P<anchor>[^\"]+)\"></a>")
GITHUB_RE = re.compile(r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/#?\s]+)")
BADGE_RE = re.compile(
    r"^\s*(?:\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)|\[!\[[^\]]*\]\([^)]*\)\])\s*"
)
DESCRIPTION_SEPARATOR_RE = re.compile(r"\s+[-\u2014]\s+")

#: A candidate name must be usable as ``~/.trimum/mcp/<name>.json5``.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawEntry:
    """One README line, split but not yet interpreted."""

    label: str
    url: str
    repo: str
    markers: str
    description: str


@dataclass(frozen=True)
class CatalogEntry:
    """One candidate MCP server, classified and ready for review."""

    repo: str
    url: str
    label: str
    section: str
    category: str
    category_label: str
    lang: str
    langs: tuple[str, ...]
    dist: str
    dists: tuple[str, ...]
    install_hint: str
    scope: str
    systems: tuple[str, ...]
    official: bool
    description: str
    name: str = ""
    trust: str = "cloud"
    risk: str = "medium"
    flags: tuple[str, ...] = ()
    reviewed: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the YAML-facing mapping (empty optional fields are omitted)."""
        data: dict[str, Any] = {
            "repo": self.repo,
            "name": self.name,
            "url": self.url,
            "lang": self.lang,
        }
        if len(self.langs) > 1:
            data["langs"] = list(self.langs)
        data["dist"] = self.dist
        if self.install_hint:
            data["install_hint"] = self.install_hint
        data["scope"] = self.scope
        if self.systems:
            data["systems"] = list(self.systems)
        if self.official:
            data["official"] = True
        data["trust"] = self.trust
        data["risk"] = self.risk
        if self.flags:
            data["flags"] = list(self.flags)
        if self.description:
            data["description"] = self.description
        data["reviewed"] = self.reviewed
        if self.note:
            data["note"] = self.note
        return data


@dataclass(frozen=True)
class SelectOptions:
    """Which entries survive the red line and the reviewer's narrowing."""

    languages: tuple[str, ...] = ALLOWED_LANGUAGES
    distributions: tuple[str, ...] = ALLOWED_DISTRIBUTIONS
    categories: tuple[str, ...] = ()
    exclude_categories: tuple[str, ...] = ()
    limit: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "languages": list(self.languages),
            "distributions": list(self.distributions),
            "categories": list(self.categories),
            "exclude_categories": list(self.exclude_categories),
            "limit": self.limit,
        }


@dataclass(frozen=True)
class Selection:
    """What survived selection, plus why the rest did not."""

    entries: tuple[CatalogEntry, ...]
    parsed: int
    excluded: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parsed": self.parsed,
            "candidates": len(self.entries),
            "excluded": dict(self.excluded),
        }


@dataclass(frozen=True)
class CatalogDocument:
    """A generated (or human-reviewed) catalog file, read back from disk."""

    path: Path
    exists: bool
    version: int = 0
    generated_from: str = ""
    entries: tuple[dict[str, Any], ...] = ()
    excluded: dict[str, int] = field(default_factory=dict)

    @property
    def reviewed(self) -> int:
        return sum(1 for entry in self.entries if entry.get("reviewed"))

    @property
    def unreviewed(self) -> int:
        return len(self.entries) - self.reviewed

    def review_state(self) -> dict[str, dict[str, Any]]:
        """Return ``{repo: {"reviewed", "name", "note"}}`` for carry-over on re-import."""
        state: dict[str, dict[str, Any]] = {}
        for entry in self.entries:
            repo = str(entry.get("repo") or "")
            if not repo:
                continue
            state[repo] = {
                "reviewed": bool(entry.get("reviewed", False)),
                "name": str(entry.get("name") or ""),
                "note": str(entry.get("note") or ""),
            }
        return state

    def summary(self) -> dict[str, Any]:
        """Return the counts a reviewer wants first."""
        by_category: Counter[str] = Counter()
        by_trust: Counter[str] = Counter()
        by_dist: Counter[str] = Counter()
        for entry in self.entries:
            by_category[str(entry.get("category_label") or entry.get("category") or "?")] += 1
            by_trust[str(entry.get("trust") or "?")] += 1
            by_dist[str(entry.get("dist") or "?")] += 1
        return {
            "entries": len(self.entries),
            "reviewed": self.reviewed,
            "unreviewed": self.unreviewed,
            "by_category": dict(by_category),
            "by_trust": dict(by_trust),
            "by_dist": dict(by_dist),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "exists": self.exists,
            "version": self.version,
            "generated_from": self.generated_from,
            **self.summary(),
        }


class CatalogExistsError(FileExistsError):
    """Raised when writing would destroy an existing (possibly reviewed) catalog."""


# ---------------------------------------------------------------------------
# Reading the README
# ---------------------------------------------------------------------------


def _clean_text(value: str) -> str:
    """Collapse whitespace and drop leading decoration such as ``🔗 ``."""
    text = re.sub(r"\s+", " ", value or "").strip()
    return re.sub(r"^[^0-9A-Za-z]+", "", text).strip()


def _slug(value: str) -> str:
    """Return a filesystem- and CLI-friendly identifier."""
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:64]


def _strip_badges(text: str) -> str:
    """Remove leading ``[![badge](url)](url)`` decorations."""
    while True:
        stripped = BADGE_RE.sub("", text, count=1)
        if stripped == text:
            return text
        text = stripped


def _repo_from(url: str, label: str) -> str:
    """Return ``owner/repo`` for a GitHub URL, else the entry label."""
    match = GITHUB_RE.match(url or "")
    if match:
        return f"{match.group('owner')}/{match.group('repo').removesuffix('.git')}"
    return (label or "").strip().lstrip("@")


def _marker_values(text: str, markers: dict[str, str]) -> tuple[str, ...]:
    """Return the marker ids present in *text*, ordered by position of appearance."""
    found = [
        (text.find(marker), value)
        for marker, value in markers.items()
        if marker in text
    ]
    if not found:
        return ()
    return tuple(value for _, value in sorted(found, key=lambda item: item[0]))


def _package_token(tail: str, dist: str) -> str:
    """Return the first non-flag token of an install command tail."""
    value_flags = VALUE_FLAGS.get(dist, frozenset())
    tokens = (tail or "").split()
    index = 0
    while index < len(tokens):
        token = tokens[index].strip("`'\",.;:")
        if not token:
            index += 1
            continue
        if token.startswith("-"):
            index += 2 if token in value_flags else 1
            continue
        return token
    return ""


def _render_install_hint(dist: str, match: re.Match[str] | None) -> str:
    """Build a copy-pasteable hint such as ``uvx mcp-server-filesystem``."""
    if match is None:
        return ""
    groups = match.groupdict()
    token = _package_token(groups.get("tail") or "", dist)
    if dist == "pip":
        return f"pip install {token}".strip()
    if dist == "uv":
        return f"uv tool run {token}".strip()
    if dist == "go":
        return f"go install {token}".strip()
    if dist == "cargo":
        return f"cargo install {token}".strip()
    if dist == "docker":
        sub = groups.get("sub") or "run"
        return f"docker {sub} {token}".strip()
    return f"{dist} {token}".strip()


def _detect_distribution(text: str) -> tuple[str, str, tuple[str, ...]]:
    """Return ``(primary, install_hint, all_matches)`` for the distribution probes."""
    matches: list[tuple[str, re.Match[str]]] = []
    for name, pattern in DISTRIBUTION_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            matches.append((name, match))
    if not matches:
        return "unknown", "", ()
    primary, match = matches[0]
    return primary, _render_install_hint(primary, match), tuple(name for name, _ in matches)


def _flags(
    langs: tuple[str, ...],
    scopes: tuple[str, ...],
    systems: tuple[str, ...],
    dist: str,
) -> tuple[str, ...]:
    """Return the things a reviewer should look at before enabling an entry."""
    flags: list[str] = []
    if not scopes:
        flags.append("unknown-scope")
    elif len(scopes) > 1:
        flags.append("scope-mixed")
    if len(langs) > 1:
        flags.append("multi-language")
    if dist == "unknown":
        flags.append("no-install-hint")
    if "embedded" in scopes:
        flags.append("embedded")
    if systems and "linux" not in systems:
        flags.append("no-linux")
    return tuple(flags)


def _classify(raw: RawEntry, section: str, category: str, category_label: str) -> CatalogEntry:
    """Turn one raw README line into a classified candidate."""
    langs = _marker_values(raw.markers, LANGUAGE_MARKERS)
    scopes = _marker_values(raw.markers, SCOPE_MARKERS)
    systems = _marker_values(raw.markers, SYSTEM_MARKERS)
    dist, install_hint, dists = _detect_distribution(f"{raw.markers}\n{raw.description}")

    lang = langs[0] if langs else "unknown"
    scope = scopes[0] if scopes else "unknown"
    trust = "local" if scope == "local" else "cloud"
    return CatalogEntry(
        repo=raw.repo,
        url=raw.url,
        label=_clean_text(raw.label),
        section=section,
        category=category,
        category_label=category_label,
        lang=lang,
        langs=langs,
        dist=dist,
        dists=dists,
        install_hint=install_hint,
        scope=scope,
        systems=systems,
        official=OFFICIAL_MARKER in raw.markers,
        description=_clean_text(raw.description),
        trust=trust,
        risk="low" if trust == "local" else "medium",
        flags=_flags(langs, scopes, systems, dist),
    )


def _subsection_heading(line: str) -> tuple[str, str] | None:
    """Return ``(anchor, label)`` for a ``### <a name="..."></a>Label`` heading."""
    if not line.startswith("### "):
        return None
    rest = line[4:].strip()
    anchor_match = ANCHOR_RE.search(rest)
    if anchor_match is None:
        label = _clean_text(rest)
        return _slug(label), label
    return anchor_match.group("anchor"), _clean_text(rest[anchor_match.end():])


def parse_entry(
    line: str,
    *,
    section: str = "",
    category: str = "",
    category_label: str = "",
) -> CatalogEntry | None:
    """Parse one README line; return ``None`` when it is not an entry."""
    match = ENTRY_RE.match(line)
    if match is None:
        return None
    rest = _strip_badges(line[match.end():])
    separator = DESCRIPTION_SEPARATOR_RE.search(rest)
    if separator:
        markers, description = rest[: separator.start()], rest[separator.end():]
    else:
        markers, description = rest, ""
    raw = RawEntry(
        label=match.group("label"),
        url=match.group("url"),
        repo=_repo_from(match.group("url"), match.group("label")),
        markers=markers,
        description=description,
    )
    return _classify(raw, section, category, category_label)


def parse_readme(text: str) -> list[CatalogEntry]:
    """Parse a README snapshot into classified entries, in source order.

    Entries outside the ``Server Implementations`` section are kept as well (marked with
    their own section) so the caller can report how many were dropped for that reason.
    """
    entries: list[CatalogEntry] = []
    section = ""
    category = ""
    category_label = ""
    for line in (text or "").splitlines():
        heading = SECTION_RE.match(line)
        if heading:
            section = _clean_text(heading.group("title"))
            if section != SERVER_SECTION:
                category, category_label = "", ""
            continue
        subheading = _subsection_heading(line)
        if subheading is not None:
            if section == SERVER_SECTION:
                category, category_label = subheading
            continue
        entry = parse_entry(
            line, section=section, category=category, category_label=category_label
        )
        if entry is not None:
            entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Selecting candidates
# ---------------------------------------------------------------------------


def _matches_category(entry: CatalogEntry, wanted: tuple[str, ...]) -> bool:
    """Return whether *entry* is in one of the wanted categories (id or label)."""
    haystack = {entry.category.lower(), entry.category_label.lower()}
    for value in wanted:
        needle = (value or "").strip().lower()
        if needle and needle in haystack:
            return True
    return False


def _reject(entry: CatalogEntry, options: SelectOptions) -> str:
    """Return the reason to drop *entry*, or an empty string to keep it."""
    if entry.section != SERVER_SECTION:
        return "section:other"
    if entry.lang not in options.languages:
        return f"language:{entry.lang}"
    if entry.dist not in options.distributions:
        return f"dist:{entry.dist}"
    if options.categories and not _matches_category(entry, options.categories):
        return "category:not-selected"
    if options.exclude_categories and _matches_category(entry, options.exclude_categories):
        return "category:excluded"
    return ""


def _rank(entry: CatalogEntry) -> tuple[Any, ...]:
    """Order entries the way a reviewer wants to read them."""
    return (not entry.official, entry.trust != "local", entry.category_label, entry.repo)


def select_candidates(
    entries: Iterable[CatalogEntry],
    options: SelectOptions | None = None,
) -> Selection:
    """Apply the red line (and any narrowing) to *entries*; rank what survives.

    The returned ``excluded`` counts every dropped entry exactly once, so
    ``parsed == len(entries) + sum(excluded.values())`` always holds for a
    :func:`parse_readme` result.
    """
    options = options or SelectOptions()
    counted = list(entries)
    excluded: Counter[str] = Counter()
    kept: list[CatalogEntry] = []
    for entry in counted:
        reason = _reject(entry, options)
        if reason:
            excluded[reason] += 1
        else:
            kept.append(entry)

    kept.sort(key=_rank)
    if options.limit and len(kept) > options.limit:
        excluded["limit:truncated"] += len(kept) - options.limit
        kept = kept[: options.limit]
    return Selection(entries=tuple(kept), parsed=len(counted), excluded=dict(excluded))


# ---------------------------------------------------------------------------
# Naming and carry-over
# ---------------------------------------------------------------------------


def _unique_name(repo: str, used: set[str]) -> str:
    """Return a name no other candidate uses, legal as ``<name>.json5``."""
    owner, _, name = repo.partition("/")
    primary = _slug(name) or _slug(owner) or "server"
    candidates = [primary]
    if owner:
        candidates.append(f"{_slug(owner)[:32]}-{primary}"[:64].strip("-"))
    for candidate in candidates:
        if candidate and NAME_PATTERN.match(candidate) and candidate not in used:
            return candidate
    stem = (f"{_slug(owner)[:32]}-{primary}" if owner else primary)[:60].strip("-") or "server"
    index = 2
    while f"{stem}-{index}" in used:
        index += 1
    return f"{stem}-{index}"


def with_names(entries: Iterable[CatalogEntry]) -> list[CatalogEntry]:
    """Assign unique names, honouring a name a human already chose."""
    used: set[str] = set()
    named: list[CatalogEntry] = []
    for entry in entries:
        preferred = (entry.name or "").strip().lower()
        if preferred and NAME_PATTERN.match(preferred) and preferred not in used:
            used.add(preferred)
            named.append(replace(entry, name=preferred))
            continue
        name = _unique_name(entry.repo, used)
        used.add(name)
        named.append(replace(entry, name=name))
    return named


def merge_review_state(
    entries: Iterable[CatalogEntry],
    state: dict[str, dict[str, Any]],
) -> list[CatalogEntry]:
    """Carry ``reviewed`` / ``name`` / ``note`` over from a previous catalog."""
    merged: list[CatalogEntry] = []
    for entry in entries:
        previous = state.get(entry.repo) or {}
        merged.append(
            replace(
                entry,
                reviewed=bool(previous.get("reviewed", False)),
                name=str(previous.get("name") or ""),
                note=str(previous.get("note") or ""),
            )
        )
    return merged


# ---------------------------------------------------------------------------
# Rendering and writing
# ---------------------------------------------------------------------------

_HEADER = """\
# trimum MCP 策展候选清单（由 `trm mcp catalog import` 生成）
#
# 这是**候选库**，不是生效配置：
#   * `reviewed: false` 的条目一律不生效 —— 人工审核后把该条目的 `reviewed` 改成 true；
#   * 启用走文件化注册：人工把条目转成 ~/.trimum/mcp/<name>.json5 并显式 `enabled: true`
#     （deny-by-default，见 docs/MCP-INTEGRATION-PLAN.md §4.2）；
#   * 导入器只读本地 README 快照，不联网、不写 ~/.trimum、不启动任何 server；
#   * 重新导入（`--force`）会按 repo 保留已有的 `reviewed` / `name` / `note`。
#
# 红线（docs/MCP-INTEGRATION-PLAN.md §3）：语言只收 python / go / rust，分发只收
# uvx / uv / pip / go install / cargo install / docker；`npx` 等 Node 派系默认不收
# （上游 4,000+ 条里 Node 派系占大头，全收等于把 Node 引回技术栈）。
#
# flags 含义：no-install-hint（描述里没有安装方式）/ unknown-scope（缺范围标记）/
#   scope-mixed（本地+云端都标了）/ multi-language（多语言）/ embedded（嵌入式）/
#   no-linux（标记里没有 Linux）。
"""


def render_catalog(
    entries: Iterable[CatalogEntry],
    *,
    source: Path | str,
    selection: Selection | None = None,
    options: SelectOptions | None = None,
) -> str:
    """Render the catalog document (comment header + YAML body) as text."""
    import yaml

    options = options or SelectOptions()
    rows = list(entries)
    groups: dict[tuple[str, str], list[CatalogEntry]] = {}
    for entry in rows:
        groups.setdefault(
            (entry.category_label or "Uncategorised", entry.category or "uncategorised"), []
        ).append(entry)

    body: dict[str, Any] = {
        "version": CATALOG_VERSION,
        "generated_from": display_path(source),
        "source_entries": selection.parsed if selection else len(rows),
        "candidates": len(rows),
        "reviewed": sum(1 for entry in rows if entry.reviewed),
        "excluded": dict(sorted((selection.excluded if selection else {}).items())),
        "red_line": {
            "languages": list(options.languages),
            "distributions": list(options.distributions),
            "categories": list(options.categories),
            "exclude_categories": list(options.exclude_categories),
            "limit": options.limit,
            "note": "npx / npm / deno 等 Node 派系默认不收（见 docs/MCP-INTEGRATION-PLAN.md §3）",
        },
        "categories": [
            {
                "id": category,
                "label": label,
                "candidates": len(items),
                "entries": [entry.to_dict() for entry in items],
            }
            for (label, category), items in sorted(groups.items())
        ],
    }
    dumped = yaml.safe_dump(
        body,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=4096,
    )
    return f"{_HEADER}\n{dumped}"


def display_path(path: Path | str) -> str:
    """Return *path* relative to the repository root when it lives inside it."""
    target = Path(path)
    try:
        return target.resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return str(target)


def write_catalog(path: Path | str, text: str, *, force: bool = False) -> Path:
    """Write the catalog, refusing to clobber one that already exists.

    The write is LF-only on purpose: the catalog is a tracked file, and a Windows
    checkout must not turn it into CRLF.
    """
    target = Path(path)
    if target.exists() and not force:
        raise CatalogExistsError(
            f"{target} already exists — re-import with --force to overwrite it"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return target


def load_catalog(path: Path | str | None = None) -> CatalogDocument:
    """Read a catalog file back (a missing file yields ``exists=False``, no raise)."""
    target = Path(path) if path is not None else DEFAULT_CATALOG
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return CatalogDocument(path=target, exists=False)

    import yaml

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        data = {}

    entries: list[dict[str, Any]] = []
    for group in data.get("categories") or []:
        if not isinstance(group, dict):
            continue
        for entry in group.get("entries") or []:
            if not isinstance(entry, dict) or not entry.get("repo"):
                continue
            item = dict(entry)
            item["category"] = group.get("id", "")
            item["category_label"] = group.get("label", "")
            entries.append(item)

    excluded = data.get("excluded") if isinstance(data.get("excluded"), dict) else {}
    return CatalogDocument(
        path=target,
        exists=True,
        version=int(data.get("version") or 0),
        generated_from=str(data.get("generated_from") or ""),
        entries=tuple(entries),
        excluded={str(key): int(value or 0) for key, value in (excluded or {}).items()},
    )


def import_catalog(
    source: Path | str | None = None,
    *,
    options: SelectOptions | None = None,
    previous: CatalogDocument | None = None,
) -> tuple[Selection, list[CatalogEntry]]:
    """Parse *source* and return the ranked, named candidates for this run.

    ``previous`` (when given) supplies the review carry-over, so re-importing keeps the
    ``reviewed`` / ``name`` / ``note`` a human already wrote.
    """
    target = Path(source) if source is not None else DEFAULT_SOURCE
    text = target.read_text(encoding="utf-8")
    selection = select_candidates(parse_readme(text), options)
    state = previous.review_state() if previous is not None and previous.exists else {}
    return selection, with_names(merge_review_state(selection.entries, state))


__all__ = [
    "ALL_DISTRIBUTIONS",
    "ALL_LANGUAGES",
    "ALLOWED_DISTRIBUTIONS",
    "ALLOWED_LANGUAGES",
    "CATALOG_VERSION",
    "CatalogDocument",
    "CatalogEntry",
    "CatalogExistsError",
    "DEFAULT_CATALOG",
    "DEFAULT_SOURCE",
    "NODE_DISTRIBUTIONS",
    "NAME_PATTERN",
    "REPO_ROOT",
    "RawEntry",
    "SERVER_SECTION",
    "SelectOptions",
    "Selection",
    "display_path",
    "import_catalog",
    "load_catalog",
    "merge_review_state",
    "parse_entry",
    "parse_readme",
    "render_catalog",
    "select_candidates",
    "with_names",
    "write_catalog",
]