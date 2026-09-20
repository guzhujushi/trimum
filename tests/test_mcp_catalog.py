"""Tests for ``trimum_core.mcp_catalog`` — the M3 curation importer + `trm mcp catalog`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trimum_core import mcp_catalog as catalog  # noqa: E402
from trimum_core.cli import main  # noqa: E402
from trimum_core.mcp_registry import NAME_PATTERN  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "awesome-mcp-sample.md"
SNAPSHOT = catalog.DEFAULT_SOURCE

PY, TS, GO, RUST = "\U0001F40D", "\U0001F4C7", "\U0001F3CE\ufe0f", "\U0001F980"
JAVA, CSHARP = "\u2615", "#\ufe0f\u20e3"
CLOUD, LOCAL, EMBEDDED = "\u2601\ufe0f", "\U0001F3E0", "\U0001F4DF"
MAC, WIN, LINUX = "\U0001F34E", "\U0001FA9F", "\U0001F427"
OFFICIAL = "\U0001F396\ufe0f"

BADGE = (
    "[![{repo} MCP server](https://glama.ai/mcp/servers/{repo}/badges/score.svg)]"
    "(https://glama.ai/mcp/servers/{repo})"
)


def entry_line(
    repo: str,
    markers: str,
    description: str = "",
    *,
    badge: bool = True,
    url: str = "",
) -> str:
    """Build one README entry line the way the upstream list writes them."""
    target = url or f"https://github.com/{repo}"
    head = f"- [{repo}]({target})"
    if badge:
        head += " " + BADGE.format(repo=repo)
    return f"{head} {markers} - {description}" if description else f"{head} {markers}"


def parse_line(line: str):
    """Parse a line as if it sat inside the Server Implementations section."""
    return catalog.parse_entry(
        line, section=catalog.SERVER_SECTION, category="files", category_label="Files"
    )


def parse_fixture() -> list:
    return catalog.parse_readme(FIXTURE.read_text(encoding="utf-8"))


def selected_fixture(**overrides):
    """Return ``(selection, entries)`` for the fixture with the given options."""
    options = catalog.SelectOptions(**overrides) if overrides else None
    return catalog.import_catalog(FIXTURE, options=options)


def selected_snapshot():
    """Return ``(selection, entries)`` for the real (gitignored) README snapshot."""
    return catalog.import_catalog(SNAPSHOT)



# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_full_line_is_classified():
    line = entry_line(
        "acme/filesystem-mcp",
        f"{OFFICIAL} {PY} {LOCAL} {MAC} {WIN} {LINUX}",
        "Local filesystem access. Install: `uvx mcp-server-filesystem /work`.",
    )
    entry = parse_line(line)

    assert entry.repo == "acme/filesystem-mcp"
    assert entry.url == "https://github.com/acme/filesystem-mcp"
    assert entry.lang == "python"
    assert entry.scope == "local"
    assert entry.systems == ("macos", "windows", "linux")
    assert entry.official is True
    assert entry.trust == "local"
    assert entry.risk == "low"
    assert entry.dist == "uvx"
    assert entry.install_hint == "uvx mcp-server-filesystem"
    assert entry.flags == ()
    assert entry.description.startswith("Local filesystem access")


def test_badge_is_optional():
    with_badge = parse_line(entry_line("acme/x", f"{PY} {LOCAL}", "Desc. `pip install x`"))
    without = parse_line(
        entry_line("acme/x", f"{PY} {LOCAL}", "Desc. `pip install x`", badge=False)
    )
    assert with_badge.dist == without.dist == "pip"
    assert with_badge.description == without.description


def test_badge_variants_are_stripped_before_marker_scan():
    line = (
        f"- [acme/y](https://github.com/acme/y) {BADGE.format(repo='acme/y')}"
        f" [![acme/y](https://img.shields.io/badge/x-y)](https://example.com) {TS} {CLOUD}"
        " - Two badges in a row. `npx -y y`"
    )
    entry = parse_line(line)
    assert entry.lang == "ts"
    assert entry.scope == "cloud"
    assert entry.dist == "npx"


def test_multi_language_keeps_first_as_primary():
    entry = parse_line(entry_line("acme/mixed", f"{TS} {PY} {LOCAL}", "Mixed. `pip install m`"))
    assert entry.lang == "ts"
    assert entry.langs == ("ts", "python")
    assert "multi-language" in entry.flags


def test_cloud_scope_maps_to_cloud_trust_and_medium_risk():
    entry = parse_line(entry_line("acme/c", f"{PY} {CLOUD}", "Cloud. `pip install c`"))
    assert entry.scope == "cloud"
    assert entry.trust == "cloud"
    assert entry.risk == "medium"


def test_missing_scope_is_flagged_and_treated_as_cloud():
    entry = parse_line(entry_line("acme/n", PY, "No scope marker. `pip install n`"))
    assert entry.scope == "unknown"
    assert entry.trust == "cloud"
    assert "unknown-scope" in entry.flags


def test_embedded_scope_is_flagged():
    entry = parse_line(entry_line("acme/e", f"{PY} {EMBEDDED}", "Embedded. `uvx e`"))
    assert entry.scope == "embedded"
    assert "embedded" in entry.flags


def test_missing_linux_marker_is_flagged():
    entry = parse_line(entry_line("acme/m", f"{PY} {LOCAL} {MAC}", "macOS only. `pip install m`"))
    assert "no-linux" in entry.flags


def test_distribution_priority_prefers_uvx_over_npx():
    entry = parse_line(
        entry_line("acme/b", f"{PY} {LOCAL}", "Prefer `uvx b` over `npx -y b`.")
    )
    assert entry.dist == "uvx"
    assert entry.dists == ("uvx", "npx")
    assert entry.install_hint == "uvx b"


def test_pip_hint_skips_flags():
    entry = parse_line(
        entry_line("acme/p", f"{PY} {CLOUD}", "Supports `pip install -U acme-p`.")
    )
    assert entry.install_hint == "pip install acme-p"


def test_uvx_hint_skips_value_flags():
    entry = parse_line(
        entry_line(
            "acme/u",
            f"{PY} {LOCAL}",
            "From git: `uvx --from git+https://github.com/acme/u@main u`",
        )
    )
    assert entry.dist == "uvx"
    assert entry.install_hint == "uvx u"


def test_go_and_cargo_hints_keep_the_package_path():
    go_entry = parse_line(
        entry_line("acme/g", f"{GO} {LOCAL} {LINUX}", "`go install github.com/acme/g@latest`")
    )
    cargo_entry = parse_line(
        entry_line("acme/r", f"{RUST} {LOCAL} {LINUX}", "`cargo install r-cli`")
    )
    assert go_entry.install_hint == "go install github.com/acme/g@latest"
    assert cargo_entry.install_hint == "cargo install r-cli"


def test_docker_hint_uses_the_image_name():
    entry = parse_line(
        entry_line("acme/d", f"{PY} {LOCAL} {LINUX}", "`docker run --rm -i acme/d:1.0`")
    )
    assert entry.dist == "docker"
    assert entry.install_hint == "docker run acme/d:1.0"


def test_node_only_entry_is_detected_as_npx():
    entry = parse_line(entry_line("acme/t", f"{TS} {CLOUD}", "`npx -y t`"))
    assert entry.dist == "npx"
    assert entry.install_hint == "npx"


def test_entry_without_description_has_no_install_hint():
    entry = parse_line(entry_line("acme/nod", f"{PY} {LOCAL}"))
    assert entry.description == ""
    assert entry.dist == "unknown"
    assert "no-install-hint" in entry.flags


def test_non_github_url_falls_back_to_the_label():
    entry = parse_line(
        entry_line("Acme Weird", f"{PY} {CLOUD}", "Non-GitHub. `pip install w`", badge=False,
                   url="https://example.com/acme/weird")
    )
    assert entry.repo == "Acme Weird"
    assert entry.url == "https://example.com/acme/weird"


@pytest.mark.parametrize(
    "line",
    [
        "* [What is MCP?](#what-is-mcp)",
        "Servers for accessing many apps.",
        "- plain bullet without a link",
        "",
    ],
)
def test_non_entry_lines_are_ignored(line: str):
    assert parse_line(line) is None


def test_readme_tracks_sections_and_categories():
    text = "\n".join(
        [
            "## Frameworks",
            entry_line("acme/framework", f"{PY} {LOCAL}", "`pip install f`"),
            "## Server Implementations",
            f"### {'\U0001F310'} <a name=\"browser-automation\"></a>Browser Automation",
            entry_line("acme/browser", f"{PY} {LOCAL}", "`uvx b`"),
            "### Other Tools and Integrations",
            entry_line("acme/other", f"{PY} {LOCAL}", "`uvx o`", badge=False),
        ]
    )
    entries = {entry.repo: entry for entry in catalog.parse_readme(text)}

    assert entries["acme/framework"].section == "Frameworks"
    assert entries["acme/browser"].section == catalog.SERVER_SECTION
    assert entries["acme/browser"].category == "browser-automation"
    assert entries["acme/browser"].category_label == "Browser Automation"
    assert entries["acme/other"].category == "other-tools-and-integrations"


# ---------------------------------------------------------------------------
# Selection (the red line)
# ---------------------------------------------------------------------------


def test_default_selection_applies_the_red_line():
    selection, entries = selected_fixture()
    repos = {entry.repo for entry in entries}
    reasons = selection.excluded

    assert "acme/ts-server" not in repos
    assert "acme/mixed-lang" not in repos
    assert "acme/java-thing" not in repos
    assert "acme/csharp-thing" not in repos
    assert "acme/brew-thing" not in repos
    assert "acme/no-hint" not in repos
    assert "acme/framework" not in repos

    assert reasons["language:ts"] == 2
    assert reasons["dist:npx"] == 1
    assert reasons["dist:unknown"] == 2
    assert reasons["dist:brew"] == 1
    assert reasons["section:other"] == 3


def test_exclusion_counts_account_for_every_parsed_entry():
    selection, entries = selected_fixture()
    assert selection.parsed == len(entries) + sum(selection.excluded.values())


def test_include_npx_and_all_languages_widen_the_selection():
    _, entries = selected_fixture(
        languages=catalog.ALL_LANGUAGES,
        distributions=catalog.ALL_DISTRIBUTIONS,
    )
    repos = {entry.repo for entry in entries}
    assert {"acme/ts-server", "acme/java-thing", "acme/no-hint"} <= repos


def test_include_unknown_dist_keeps_hintless_entries():
    _, entries = selected_fixture(
        distributions=tuple(catalog.ALLOWED_DISTRIBUTIONS) + ("unknown",)
    )
    assert "acme/no-hint" in {entry.repo for entry in entries}


def test_category_filters_narrow_the_selection():
    _, only_browser = selected_fixture(categories=("browser-automation",))
    assert {entry.category for entry in only_browser} == {"browser-automation"}

    _, without_browser = selected_fixture(exclude_categories=("Browser Automation",))
    assert "browser-automation" not in {entry.category for entry in without_browser}


def test_limit_truncates_and_reports_it():
    selection, entries = selected_fixture(limit=3)
    assert len(entries) == 3
    assert selection.excluded["limit:truncated"] == len(selected_fixture()[1]) - 3


def test_ranking_puts_official_and_local_first():
    _, entries = selected_fixture()
    assert entries[0].official is True
    local_indexes = [i for i, entry in enumerate(entries) if entry.trust == "local"]
    cloud_indexes = [i for i, entry in enumerate(entries) if entry.trust == "cloud"]
    assert local_indexes and cloud_indexes
    assert max(local_indexes) < min(cloud_indexes)


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def test_candidate_names_are_unique_and_usable_as_definitions():
    _, entries = selected_fixture()
    names = [entry.name for entry in entries]
    assert len(set(names)) == len(names)
    assert all(NAME_PATTERN.match(name) for name in names)
    assert all(catalog.NAME_PATTERN.match(name) for name in names)


def test_duplicate_repo_names_get_the_owner_prefix():
    _, entries = selected_fixture()
    names = {entry.repo: entry.name for entry in entries}
    assert names["acme/mcp-server"] == "mcp-server"
    assert names["other/mcp-server"] == "other-mcp-server"


def test_names_are_derived_from_the_repo_name():
    entry = catalog.parse_entry(entry_line("acme/x", f"{PY} {LOCAL}"))
    assert catalog.with_names([entry])[0].name == "x"


def test_preferred_name_is_kept_when_free():
    entry = catalog.parse_entry(entry_line("acme/x", f"{PY} {LOCAL}"))
    preferred = catalog.CatalogEntry(**{**entry.__dict__, "name": "my-choice"})
    assert catalog.with_names([preferred])[0].name == "my-choice"


def test_conflicting_preferred_names_are_reassigned():
    first = catalog.with_names(
        [catalog.parse_entry(entry_line("acme/a", f"{PY} {LOCAL}"))]
    )[0]
    second = catalog.with_names(
        [catalog.parse_entry(entry_line("acme/b", f"{PY} {LOCAL}"))]
    )[0]
    clash = [
        catalog.CatalogEntry(**{**first.__dict__, "name": "same"}),
        catalog.CatalogEntry(**{**second.__dict__, "name": "same"}),
    ]
    named = catalog.with_names(clash)
    assert [entry.name for entry in named] == ["same", "b"]


# ---------------------------------------------------------------------------
# Rendering, writing and carry-over
# ---------------------------------------------------------------------------


def loaded_document(entries=None, **overrides) -> catalog.CatalogDocument:
    payload = {"repo": "acme/x", "name": "x", "reviewed": False}
    payload.update(overrides)
    return catalog.CatalogDocument(
        path=Path("/tmp/catalog.yaml"), exists=True, entries=tuple(entries or (payload,))
    )


def test_render_is_deterministic():
    selection, entries = selected_fixture()
    kwargs = {"source": FIXTURE, "selection": selection, "options": catalog.SelectOptions()}
    first = catalog.render_catalog(entries, **kwargs)
    second = catalog.render_catalog(selected_fixture()[1], **kwargs)
    assert first == second


def test_render_documents_the_candidate_contract():
    selection, entries = selected_fixture()
    text = catalog.render_catalog(entries, source=FIXTURE, selection=selection)
    body = yaml.safe_load(text)

    assert "reviewed: false" in text
    assert body["version"] == catalog.CATALOG_VERSION
    assert body["candidates"] == len(entries)
    assert body["red_line"]["languages"] == list(catalog.ALLOWED_LANGUAGES)
    assert body["excluded"]["language:ts"] == 2
    assert all(group["entries"] for group in body["categories"])
    assert all(
        entry["reviewed"] is False
        for group in body["categories"]
        for entry in group["entries"]
    )


def test_write_catalog_refuses_to_clobber_without_force(tmp_path: Path):
    target = tmp_path / "mcp-catalog.yaml"
    catalog.write_catalog(target, "version: 1\n")

    with pytest.raises(catalog.CatalogExistsError):
        catalog.write_catalog(target, "version: 2\n")

    catalog.write_catalog(target, "version: 2\n", force=True)
    assert target.read_text(encoding="utf-8").startswith("version: 2")


def test_write_catalog_uses_lf_line_endings(tmp_path: Path):
    target = tmp_path / "mcp-catalog.yaml"
    catalog.write_catalog(target, "version: 1\ncandidates: 0\n")
    assert b"\r\n" not in target.read_bytes()


def test_load_catalog_round_trip(tmp_path: Path):
    selection, entries = selected_fixture()
    target = tmp_path / "mcp-catalog.yaml"
    catalog.write_catalog(
        target,
        catalog.render_catalog(entries, source=FIXTURE, selection=selection),
    )

    document = catalog.load_catalog(target)
    assert document.exists is True
    assert document.version == catalog.CATALOG_VERSION
    assert len(document.entries) == len(entries)
    assert document.unreviewed == len(entries)
    assert document.excluded["language:ts"] == 2
    assert document.review_state()["acme/filesystem-mcp"]["reviewed"] is False


def test_load_catalog_of_missing_file_is_not_an_error(tmp_path: Path):
    document = catalog.load_catalog(tmp_path / "nope.yaml")
    assert document.exists is False
    assert document.entries == ()
    assert document.to_dict()["entries"] == 0


def test_import_carries_reviewed_name_and_note_over():
    previous = loaded_document(
        [{"repo": "acme/filesystem-mcp", "name": "fs", "reviewed": True, "note": "checked"}]
    )
    _, entries = catalog.import_catalog(FIXTURE, previous=previous)
    entry = {item.repo: item for item in entries}["acme/filesystem-mcp"]

    assert entry.reviewed is True
    assert entry.note == "checked"
    assert entry.name == "fs"


def test_merge_review_state_only_touches_known_repos():
    entry = parse_line(entry_line("acme/x", f"{PY} {LOCAL}"))
    merged = catalog.merge_review_state([entry], {"other/repo": {"reviewed": True}})
    assert merged[0].reviewed is False
    assert merged[0].name == ""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_catalog_help(capsys: pytest.CaptureFixture):
    assert main(["mcp", "catalog"]) == 0
    assert "import,list" in capsys.readouterr().out


def test_cli_import_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture):
    target = tmp_path / "mcp-catalog.yaml"
    code = main(
        ["--json", "mcp", "catalog", "import", "--source", str(FIXTURE),
         "--catalog", str(target), "--dry-run"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["written"] is False
    assert payload["candidates"] == len(selected_fixture()[1])
    assert target.exists() is False


def test_cli_import_writes_and_can_be_listed(tmp_path: Path, capsys: pytest.CaptureFixture):
    target = tmp_path / "mcp-catalog.yaml"
    assert main(
        ["--json", "mcp", "catalog", "import", "--source", str(FIXTURE), "--catalog", str(target)]
    ) == 0
    capsys.readouterr()

    assert main(["--json", "mcp", "catalog", "list", "--catalog", str(target)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == len(selected_fixture()[1])
    assert payload["shown"] == payload["total"]
    assert payload["reviewed"] == 0


def test_cli_import_refuses_to_overwrite_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    target = tmp_path / "mcp-catalog.yaml"
    args = ["mcp", "catalog", "import", "--source", str(FIXTURE), "--catalog", str(target)]
    assert main(args) == 0
    capsys.readouterr()

    assert main(args) == 1
    assert "--force" in capsys.readouterr().err


def test_cli_import_force_keeps_human_review(tmp_path: Path, capsys: pytest.CaptureFixture):
    target = tmp_path / "mcp-catalog.yaml"
    args = ["mcp", "catalog", "import", "--source", str(FIXTURE), "--catalog", str(target)]
    assert main(args) == 0
    capsys.readouterr()

    body = yaml.safe_load(target.read_text(encoding="utf-8"))
    for group in body["categories"]:
        for entry in group["entries"]:
            if entry["repo"] == "acme/filesystem-mcp":
                entry["reviewed"] = True
                entry["note"] = "hand-checked"
    target.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")

    assert main([*args, "--force"]) == 0
    capsys.readouterr()

    reviewed = [
        entry
        for group in yaml.safe_load(target.read_text(encoding="utf-8"))["categories"]
        for entry in group["entries"]
        if entry.get("reviewed")
    ]
    assert [entry["repo"] for entry in reviewed] == ["acme/filesystem-mcp"]
    assert reviewed[0]["note"] == "hand-checked"


def test_cli_list_filters(tmp_path: Path, capsys: pytest.CaptureFixture):
    target = tmp_path / "mcp-catalog.yaml"
    assert main(
        ["mcp", "catalog", "import", "--source", str(FIXTURE), "--catalog", str(target)]
    ) == 0
    capsys.readouterr()

    assert main(
        ["--json", "mcp", "catalog", "list", "--catalog", str(target), "--dist", "uvx",
         "--category", "file-systems"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["shown"] >= 1
    assert {entry["dist"] for entry in payload["entries"]} == {"uvx"}

    assert main(
        ["--json", "mcp", "catalog", "list", "--catalog", str(target), "--unreviewed", "--limit", "3"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["shown"] == 3


def test_cli_list_without_catalog_fails(tmp_path: Path, capsys: pytest.CaptureFixture):
    assert main(["--json", "mcp", "catalog", "list", "--catalog", str(tmp_path / "no.yaml")]) == 1
    assert "not found" in capsys.readouterr().err


def test_cli_import_without_source_fails(tmp_path: Path, capsys: pytest.CaptureFixture):
    code = main(
        ["mcp", "catalog", "import", "--source", str(tmp_path / "no.md"),
         "--catalog", str(tmp_path / "out.yaml")]
    )
    assert code == 1
    assert "README snapshot not found" in capsys.readouterr().err


def test_cli_catalog_commands_are_documented(capsys: pytest.CaptureFixture):
    assert main(["--json", "commands"]) == 0
    routes = {item["route"] for item in json.loads(capsys.readouterr().out)["commands"]}
    assert {"trm mcp catalog", "trm mcp catalog import", "trm mcp catalog list"} <= routes


# ---------------------------------------------------------------------------
# The real snapshot (skipped when the gitignored snapshot is absent)
# ---------------------------------------------------------------------------

needs_snapshot = pytest.mark.skipif(
    not SNAPSHOT.is_file(), reason="tmp/research/awesome-README.md snapshot is not present"
)


@needs_snapshot
def test_real_snapshot_selection_respects_the_red_line():
    selection, entries = selected_snapshot()

    assert selection.parsed > 3000
    assert 100 < len(entries) < 1000
    assert selection.parsed == len(entries) + sum(selection.excluded.values())
    assert {entry.lang for entry in entries} <= set(catalog.ALLOWED_LANGUAGES)
    assert {entry.dist for entry in entries} <= set(catalog.ALLOWED_DISTRIBUTIONS)
    assert all(entry.section == catalog.SERVER_SECTION for entry in entries)
    assert len({entry.name for entry in entries}) == len(entries)
    assert all(catalog.NAME_PATTERN.match(entry.name) for entry in entries)


@needs_snapshot
def test_real_snapshot_is_node_heavy_which_is_why_the_line_exists():
    reasons = selected_snapshot()[0].excluded
    assert reasons["language:ts"] > 1000
    assert reasons["dist:unknown"] > 500