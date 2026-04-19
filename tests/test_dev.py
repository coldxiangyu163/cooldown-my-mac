"""Unit tests for `cooldown.collectors.dev`."""
from __future__ import annotations

import time
from pathlib import Path

from cooldown.collectors import dev as dev_mod
from cooldown.collectors.ancestry import Launcher
from cooldown.collectors.dev import DevProc
from cooldown.collectors.project import Project


def _mk(
    pid: int,
    *,
    lang: str = "node",
    rss: int = 100,
    cpu: float = 0.0,
    ppid: int = 100,
    framework: str | None = None,
    project: Project | None = None,
    launcher: Launcher | None = None,
    is_orphan: bool = False,
    idle: float | None = None,
) -> DevProc:
    return DevProc(
        pid=pid,
        ppid=ppid,
        lang=lang,
        framework=framework,
        name=lang,
        cmdline=f"{lang} --run",
        rss=rss,
        cpu_percent=cpu,
        age=0.0,
        cwd=None,
        project=project,
        launcher=launcher or Launcher(kind="unknown", label="unknown", pid=None),
        is_orphan=is_orphan,
        user="me",
        idle_seconds=idle,
    )


def test_collect_returns_list_no_crash():
    # Minimal smoke test — we only assert it returns a list and no raised
    # exceptions. On CI the list may be empty.
    result = dev_mod.collect(sample_interval=0.05)
    assert isinstance(result, list)
    for d in result:
        assert isinstance(d, DevProc)
        assert d.lang in {
            "node", "python", "ruby", "go", "rust", "java", "php", "deno", "bun", "dotnet",
        }


def test_group_by_project_sorts_by_rss(tmp_path: Path):
    proj_a = Project(root=tmp_path / "a", name="alpha", markers=["package.json"])
    proj_b = Project(root=tmp_path / "b", name="beta", markers=["pyproject.toml"])
    devs = [
        _mk(1, rss=100, project=proj_a),
        _mk(2, rss=500, project=proj_b),
        _mk(3, rss=400, project=proj_b),
        _mk(4, rss=50, project=None),
    ]
    groups = dev_mod.group_by(devs, "project")
    order = list(groups.keys())
    # beta has 900 total, alpha 100, unattributed 50 → beta first.
    assert order[0] == "beta"
    # Project=None falls through to the "(background: ...)" bucket rather
    # than "(cwd unknown)" to guarantee the Top Projects panel has no
    # anonymous row.
    assert order[-1].startswith("(background:")
    # Inside beta, order by -rss
    assert [d.pid for d in groups["beta"]] == [2, 3]


def test_group_by_lang():
    devs = [
        _mk(1, lang="node", rss=100),
        _mk(2, lang="python", rss=500),
        _mk(3, lang="python", rss=100),
    ]
    groups = dev_mod.group_by(devs, "lang")
    order = list(groups.keys())
    assert order[0] == "python"
    assert order[1] == "node"


def test_group_by_launcher_framework():
    launcher = Launcher(kind="tmux", label="tmux", pid=10)
    devs = [
        _mk(1, lang="node", framework="vite", launcher=launcher, rss=300),
        _mk(2, lang="python", framework=None, launcher=launcher, rss=200),
    ]
    by_launcher = dev_mod.group_by(devs, "launcher")
    assert list(by_launcher.keys()) == ["tmux"]

    by_fw = dev_mod.group_by(devs, "framework")
    assert "vite" in by_fw
    assert "(none)" in by_fw


def test_stale_requires_orphan_or_old_project(tmp_path: Path):
    # Make a fresh project root. mtime is recent, so project alone
    # shouldn't qualify.
    root = tmp_path / "fresh"
    root.mkdir()
    fresh_proj = Project(root=root, name="fresh", markers=["package.json"])
    fresh_dev = _mk(1, project=fresh_proj, cpu=0.0, idle=3600)
    assert dev_mod.stale([fresh_dev]) == []

    # Orphan + low cpu + high idle → stale.
    orphan = _mk(2, ppid=1, is_orphan=True, cpu=0.0, idle=3600)
    assert dev_mod.stale([orphan]) == [orphan]

    # Orphan but busy → not stale.
    busy = _mk(3, ppid=1, is_orphan=True, cpu=5.0, idle=3600)
    assert dev_mod.stale([busy]) == []

    # Orphan + low cpu + low idle → not stale.
    active = _mk(4, ppid=1, is_orphan=True, cpu=0.0, idle=60)
    assert dev_mod.stale([active]) == []


def test_stale_old_project_counts_as_aged(tmp_path: Path, mocker):
    root = tmp_path / "old"
    root.mkdir()
    # Force the project root to look ancient.
    ancient = time.time() - 30 * 86400
    mocker.patch("pathlib.Path.stat", return_value=type("S", (), {"st_mtime": ancient})())
    proj = Project(root=root, name="old", markers=["package.json"])
    dev = _mk(1, project=proj, ppid=200, is_orphan=False, cpu=0.0, idle=3600)
    assert dev_mod.stale([dev]) == [dev]


def test_enrich_idle_sets_value():
    devs = [_mk(1, rss=100)]
    devs[0].age = 120.0
    dev_mod.enrich_idle(devs)
    assert devs[0].idle_seconds is not None
    assert devs[0].idle_seconds >= 0


def test_classify_lang_and_framework():
    assert dev_mod._classify_lang("node", "/usr/bin/node vite") == "node"
    assert dev_mod._classify_lang("python3", "/usr/bin/python3 -m uvicorn app:app") == "python"
    # Only python gets uvicorn attribution.
    assert dev_mod._classify_framework("python", "uvicorn app:app") == "uvicorn"
    assert dev_mod._classify_framework("node", "uvicorn app:app") is None
    assert dev_mod._classify_framework("node", "/path/to/next-server main") == "next"


# ---------------------------------------------------------------------------
# Regression: 2026-04-19 — "(cwd unknown)" dominated `cool watch` because the
# language classifier used raw substring match, so "--bundle-id=..." matched
# "bun" and "*.node" native extensions matched "node". Make sure those
# false positives stay dead and that the real boundaries still work.
# ---------------------------------------------------------------------------

def test_classify_lang_rejects_bundle_id_substring():
    # WeChatAppEx real-world cmdline: "--bundle-id=com.tencent.xinwechat".
    # The bare token "bun" must *not* match inside "bundle-id".
    assert dev_mod._classify_lang(
        "WeChatAppEx",
        "/Applications/WeChat.app/... --bundle-id=5a4re8sf68.com.tencent.xinwechat",
    ) is None


def test_classify_lang_rejects_dot_node_loadables():
    # Creative Cloud and plenty of other macOS native extensions expose
    # loadable files ending in ".node". These are not Node.js processes.
    assert dev_mod._classify_lang(
        "Creative Cloud Content Manager.node", "/path/to/Creative Cloud Content Manager.node"
    ) is None


def test_classify_lang_still_catches_real_node_invocations():
    # argv0 basename match.
    assert dev_mod._classify_lang(
        "node", "/opt/homebrew/Cellar/node/23.11.0/bin/node server.js"
    ) == "node"
    # Name = "bun" exactly.
    assert dev_mod._classify_lang("bun", "/usr/local/bin/bun run dev") == "bun"
    # Whole-word match in cmdline.
    assert dev_mod._classify_lang(
        "some-wrapper", "exec node /path/to/script.js"
    ) == "node"
    # Tool-needle substring match still works.
    assert dev_mod._classify_lang("x", "pytest -q") == "python"


def test_synthesize_app_project_for_app_path():
    proj = dev_mod._synthesize_app_project(
        "WeChatAppEx",
        "/Applications/WeChat.app/Contents/MacOS/WeChatAppEx.app/... --bundle-id=...",
        cwd="/Applications/WeChat.app/Contents/MacOS",
    )
    assert proj is not None
    assert proj.name == "(app: WeChat)"
    assert str(proj.root).endswith("/WeChat.app")


def test_synthesize_app_project_for_named_helper_without_bundle_path():
    proj = dev_mod._synthesize_app_project(
        "Obsidian Helper (Renderer)", "", cwd="/"
    )
    assert proj is not None
    assert proj.name == "(app: Obsidian)"


def test_synthesize_app_project_returns_none_for_regular_dev_proc():
    assert dev_mod._synthesize_app_project(
        "node", "/usr/bin/node server.js", cwd="/Users/me/my-project"
    ) is None


def test_bucket_orphan_for_launchd_orphan_at_root():
    proj = dev_mod._bucket_orphan_project(cwd="/", is_orphan=True)
    assert proj is not None
    assert proj.name == "(orphan)"

    # Non-orphan → None even at root.
    assert dev_mod._bucket_orphan_project(cwd="/", is_orphan=False) is None
    # Orphan but with real cwd → leave for the regular project lookup.
    assert dev_mod._bucket_orphan_project(
        cwd="/Users/me/project", is_orphan=True
    ) is None


def test_is_self_excludes_cool_cli():
    assert dev_mod._is_self("python3", "python3 -m cooldown.cli dev")
    assert dev_mod._is_self("cool", "/Users/x/.venv/bin/cool dev")
    assert not dev_mod._is_self("node", "node server.js")


# ---------------------------------------------------------------------------
# Regression: 2026-04-19 part 2 — "(cwd unknown)" was not fully eliminated
# after the first pass: npx cache / VS Code extensions / stale-cwd ghosts
# still fell through. These fixtures pin every fallback synthesizer and the
# "(cwd unknown)" → never-emitted invariant.
# ---------------------------------------------------------------------------

def test_synthesize_npx_from_cache_path():
    proj = dev_mod._synthesize_npx_project(
        "/opt/homebrew/Cellar/node/23.11.0/bin/node "
        "/Users/me/.npm/_npx/15c61037b1978c83/node_modules/chrome-devtools-mcp/dist/index.js"
    )
    assert proj is not None
    assert proj.name == "(npx: chrome-devtools-mcp)"


def test_synthesize_npx_from_npm_exec():
    proj = dev_mod._synthesize_npx_project(
        "npm exec @modelcontextprotocol/server-sequential-thinking"
    )
    assert proj is not None
    assert proj.name == "(npx: @modelcontextprotocol/server-sequential-thinking)"


def test_synthesize_npx_ignores_regular_node_cmdline():
    assert dev_mod._synthesize_npx_project("node /Users/me/project/server.js") is None


def test_synthesize_npx_skips_dotbin_shim():
    # ~/.npm/_npx/<hash>/node_modules/.bin/<tool> is the symlink shim, not
    # the real package dir. Make sure we skip past ".bin" to the tool.
    proj = dev_mod._synthesize_npx_project(
        "node /Users/me/.npm/_npx/de2bd410102f5eda/node_modules/.bin/mcp-server-sequential-thinking"
    )
    assert proj is not None
    assert proj.name == "(npx: mcp-server-sequential-thinking)"


def test_synthesize_npx_by_process_name_after_exec():
    # When npx tools exec() over their launcher, psutil reports name='node'
    # but argv[0] is rewritten. Catch both paths.
    proj = dev_mod._synthesize_npx_project(
        "chrome-devtools-mcp  ", name="node"
    )
    assert proj is not None
    assert proj.name == "(npx: chrome-devtools-mcp)"

    # Name-only match (name was preserved).
    proj = dev_mod._synthesize_npx_project("", name="mcp-server-puppeteer")
    assert proj is not None
    assert proj.name == "(npx: mcp-server-puppeteer)"

    # Ensure plain 'node' / 'python' never masquerade as npx.
    assert dev_mod._synthesize_npx_project("node server.js", name="node") is None


def test_npx_attribution_wins_over_find_root():
    # Direct wiring check: an _npx cache path always returns a project so
    # collect()'s order of operations can skip find_root for MCP tools
    # spawned by claude / droid / cursor. (Simulates a developer whose
    # shell cwd is inside a real repo, but the tool being run is an
    # ephemeral npx binary — the tool should NOT inflate the repo's
    # memory footprint.)
    proj = dev_mod._synthesize_npx_project(
        "node /Users/me/.npm/_npx/aaaabbbbccccdddd/node_modules/some-tool/dist/index.js"
    )
    assert proj is not None
    assert proj.name == "(npx: some-tool)"


def test_synthesize_vscode_extension():
    proj = dev_mod._synthesize_vscode_ext_project(
        "/Users/me/.vscode/extensions/ms-python.vscode-python-envs-1.20.1-darwin-arm64/"
        "python-env-tools/bin/pet",
        cwd="/",
    )
    assert proj is not None
    assert "vscode" in proj.name.lower()
    assert "python-envs" in proj.name


def test_synthesize_cwd_from_deleted_monorepo_path():
    # Path does not exist on disk (stale cwd of a long-running process)
    # but we can still fold it to the workspace root from the string.
    proj = dev_mod._synthesize_cwd_project(
        "/Users/me/personal/project/music-train-ui-saas/apps/web"
    )
    assert proj is not None
    assert proj.name == "music-train-ui-saas"


def test_synthesize_cwd_folds_packages_up():
    proj = dev_mod._synthesize_cwd_project(
        "/Users/me/code/my-repo/packages/ui"
    )
    assert proj is not None
    assert proj.name == "my-repo"


def test_synthesize_cwd_hidden_tool_dir():
    proj = dev_mod._synthesize_cwd_project("/Users/me/.mcporter")
    assert proj is not None
    assert proj.name == "(tool: mcporter)"


def test_synthesize_cwd_ignores_root_and_empty():
    assert dev_mod._synthesize_cwd_project(None) is None
    assert dev_mod._synthesize_cwd_project("/") is None
    assert dev_mod._synthesize_cwd_project("") is None


def test_synthesize_cmdline_project_from_dir_flag():
    proj = dev_mod._synthesize_cmdline_project(
        "node /opt/homebrew/bin/pnpm --dir /Users/me/work/acme/pkg --filter api dev"
    )
    assert proj is not None
    # Falls back to cwd_project parser which uses the "work" anchor.
    assert proj.name == "acme"


def test_group_key_never_emits_cwd_unknown():
    # A dev proc with project=None should fall back to (background: <proc>),
    # not the old "(cwd unknown)" sentinel.
    dev = _mk(1, project=None)
    dev.cmdline = "/opt/homebrew/bin/rogue-tool --flag"
    key = dev_mod._group_key(dev, "project")
    assert "cwd unknown" not in key
    assert key.startswith("(background:")


def test_walk_past_monorepo_folds_apps_web_up(tmp_path: Path):
    # Simulate a pnpm-style monorepo: repo/.git + repo/apps/web/package.json.
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "apps" / "web").mkdir(parents=True)
    (repo / "apps" / "web" / "package.json").write_text("{}")
    # find_root from inside apps/web would find the inner package.json first.
    inner = Project(
        root=repo / "apps" / "web", name="web", markers=["package.json"]
    )
    outer = dev_mod._walk_past_monorepo(inner)
    # Must climb past the ``apps`` layer and land on the workspace root.
    assert outer.root == repo
    assert outer.name == "repo"
