#!/home/Aaditya/venvs/graphify/bin/python
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
from networkx.readwrite import json_graph

from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.cluster import cluster, score_all
from graphify.export import to_html, to_json
from graphify.report import generate
from graphify.wiki import to_wiki


@dataclass(frozen=True)
class NodeSpec:
    node_id: str
    label: str
    file_type: str
    source_file: str
    source_location: str = "L1"


def _line_for_text(path: Path, needle: str) -> str:
    try:
        for index, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            if needle in line:
                return f"L{index}"
    except OSError:
        pass
    return "L1"


def _make_edge(
    source: str,
    target: str,
    relation: str,
    source_file: str,
    source_location: str = "L1",
) -> tuple[str, str, str, str, str]:
    return (source, target, relation, source_file, source_location)


def _add_node(G, spec: NodeSpec) -> None:
    if spec.node_id in G:
        return
    G.add_node(
        spec.node_id,
        label=spec.label,
        file_type=spec.file_type,
        source_file=spec.source_file,
        source_location=spec.source_location,
    )


def _add_edge(
    G, source: str, target: str, relation: str, source_file: str, source_location: str
) -> None:
    existing = G.get_edge_data(source, target)
    if existing and existing.get("relation") == relation:
        return
    G.add_edge(
        source,
        target,
        relation=relation,
        confidence="EXTRACTED",
        source_file=source_file,
        source_location=source_location,
        weight=1.0,
        _src=source,
        _tgt=target,
    )


def _community_labels(G, communities: dict[int, list[str]]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for cid, nodes in communities.items():
        picks: list[str] = []
        for node_id in sorted(nodes, key=lambda item: G.degree(item), reverse=True):
            label = G.nodes[node_id].get("label", node_id)
            for prefix in (
                "MCP: ",
                "Command: /",
                "Agent: ",
                "Skill: ",
                "Doc: ",
                "Rules: ",
                "Config: ",
                "Plugin: ",
                "Script: ",
                "Artifact: ",
            ):
                label = label.replace(prefix, "")
            label = label.replace("graphify-out/", "")
            label = label.strip()
            if not label or label in picks:
                continue
            picks.append(label)
            if len(picks) == 2:
                break
        labels[cid] = " / ".join(picks) if picks else f"Community {cid}"
    return labels


def _word_count(paths: set[str]) -> int:
    total = 0
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.exists() or "graphify-out" in path.parts:
            continue
        try:
            total += len(path.read_text(encoding="utf-8", errors="ignore").split())
        except OSError:
            continue
    return total


def _prune_questions(questions: list[dict], *, apply_repo_overlay: bool) -> list[dict]:
    pruned: list[dict] = []
    for question in questions:
        qtext = question.get("question") or ""
        qtype = question.get("type")

        if qtype == "no_signal":
            continue

        if not apply_repo_overlay and qtype == "low_cohesion":
            continue

        if len(qtext) > 220:
            continue

        if "Should `" in qtext and "be split into smaller" in qtext:
            continue

        pruned.append(question)

    return pruned[:5]


def _prune_communities(
    G, communities: dict[int, list[str]], labels: dict[int, str]
) -> tuple[dict[int, list[str]], dict[int, str]]:
    filtered: dict[int, list[str]] = {}
    filtered_labels: dict[int, str] = {}
    next_id = 0

    for cid, nodes in communities.items():
        real_nodes = []
        for node_id in nodes:
            data = G.nodes[node_id]
            label = data.get("label", node_id)
            source_file = data.get("source_file", "")

            is_file_hub = False
            if source_file:
                try:
                    is_file_hub = Path(source_file).name == label
                except Exception:
                    is_file_hub = False

            if is_file_hub:
                continue
            if label.startswith(".") and label.endswith("()"):
                continue

            real_nodes.append(node_id)

        if not real_nodes:
            continue

        filtered[next_id] = nodes
        filtered_labels[next_id] = labels.get(cid, f"Community {cid}")
        next_id += 1

    return filtered, filtered_labels


def _is_view_noise_label(label: str) -> bool:
    if not label:
        return False

    # Graphify can emit truncated prose/docstring nodes that dominate reports
    # without adding useful navigation value.
    if "     " in label:
        return True

    if len(label) > 80 and not re.search(r"[/.][A-Za-z0-9]+$|\(\)$", label):
        return True

    return False


def _build_view_graph(G: nx.Graph):
    H = G.copy()
    noisy_nodes = [
        node_id
        for node_id, data in H.nodes(data=True)
        if _is_view_noise_label(data.get("label", node_id))
    ]
    if noisy_nodes:
        H.remove_nodes_from(noisy_nodes)

    return H


def _main(repo_root: Path) -> None:
    graph_path = repo_root / "graphify-out" / "graph.json"
    seeded_graph = not graph_path.exists()
    if graph_path.exists():
        raw = json.loads(graph_path.read_text(encoding="utf-8"))
        try:
            G = json_graph.node_link_graph(raw, edges="links")
        except TypeError:
            G = json_graph.node_link_graph(raw)
    else:
        G = nx.DiGraph()

    apply_repo_overlay = (
        seeded_graph or G.number_of_nodes() == 0 or repo_root.name == "ai-stack"
    )

    docs_dir = repo_root / "docs" / "opencode"
    commands_dir = repo_root / ".opencode" / "commands"
    agents_dir = repo_root / ".opencode" / "agents"
    skills_dir = repo_root / ".opencode" / "skills"
    scripts_dir = repo_root / ".opencode" / "scripts"
    plugins_dir = repo_root / ".opencode" / "plugins"

    specs = [
        NodeSpec(
            "artifact_graph_json",
            "Artifact: graphify-out/graph.json",
            "document",
            str(repo_root / "graphify-out" / "graph.json"),
        ),
        NodeSpec(
            "artifact_graph_report",
            "Artifact: graphify-out/GRAPH_REPORT.md",
            "document",
            str(repo_root / "graphify-out" / "GRAPH_REPORT.md"),
        ),
        NodeSpec(
            "artifact_graph_html",
            "Artifact: graphify-out/graph.html",
            "document",
            str(repo_root / "graphify-out" / "graph.html"),
        ),
        NodeSpec(
            "artifact_graph_wiki",
            "Artifact: graphify-out/wiki/index.md",
            "document",
            str(repo_root / "graphify-out" / "wiki" / "index.md"),
        ),
        NodeSpec(
            "repo_agents_md",
            "Rules: AGENTS.md",
            "document",
            str(repo_root / "AGENTS.md"),
        ),
        NodeSpec(
            "repo_opencode_json",
            "Config: opencode.json",
            "document",
            str(repo_root / "opencode.json"),
        ),
        NodeSpec(
            "repo_doc_workflows",
            "Doc: mcp-workflows.md",
            "document",
            str(docs_dir / "mcp-workflows.md"),
        ),
        NodeSpec(
            "repo_doc_runtime",
            "Doc: runtime-notes.md",
            "document",
            str(docs_dir / "runtime-notes.md"),
        ),
        NodeSpec(
            "repo_doc_profiles",
            "Doc: LOCAL_AI_PROFILES.md",
            "document",
            str(repo_root / "LOCAL_AI_PROFILES.md"),
        ),
        NodeSpec(
            "repo_doc_plan",
            "Doc: GRAPH_MEMORY_STACK_PLAN.md",
            "document",
            str(repo_root / "GRAPH_MEMORY_STACK_PLAN.md"),
        ),
        NodeSpec(
            "plugin_graphify",
            "Plugin: graphify.js",
            "code",
            str(plugins_dir / "graphify.js"),
        ),
        NodeSpec(
            "script_build_graphify",
            "Script: build-graphify",
            "code",
            str(scripts_dir / "build-graphify"),
        ),
        NodeSpec(
            "script_audit_opencode",
            "Script: audit-opencode",
            "code",
            str(scripts_dir / "audit-opencode"),
        ),
        NodeSpec(
            "script_graphify_overlay",
            "Script: graphify_repo_overlay.py",
            "code",
            str(scripts_dir / "graphify_repo_overlay.py"),
        ),
        NodeSpec(
            "command_refresh_graph",
            "Command: /refresh-graph",
            "document",
            str(commands_dir / "refresh-graph.md"),
        ),
        NodeSpec(
            "command_mcp_audit",
            "Command: /mcp-audit",
            "document",
            str(commands_dir / "mcp-audit.md"),
        ),
        NodeSpec(
            "command_repo_research",
            "Command: /repo-research",
            "document",
            str(commands_dir / "repo-research.md"),
        ),
        NodeSpec(
            "command_graph_report",
            "Command: /graph-report",
            "document",
            str(commands_dir / "graph-report.md"),
        ),
        NodeSpec(
            "command_graph_query",
            "Command: /graph-query",
            "document",
            str(commands_dir / "graph-query.md"),
        ),
        NodeSpec(
            "command_graph_path",
            "Command: /graph-path",
            "document",
            str(commands_dir / "graph-path.md"),
        ),
        NodeSpec(
            "agent_mcp_orchestrator",
            "Agent: mcp-orchestrator",
            "rationale",
            str(agents_dir / "mcp-orchestrator.md"),
        ),
        NodeSpec(
            "agent_mcp_researcher",
            "Agent: mcp-researcher",
            "rationale",
            str(agents_dir / "mcp-researcher.md"),
        ),
        NodeSpec(
            "agent_repo_surgeon",
            "Agent: repo-surgeon",
            "rationale",
            str(agents_dir / "repo-surgeon.md"),
        ),
        NodeSpec(
            "skill_mcp_research",
            "Skill: mcp-research",
            "rationale",
            str(skills_dir / "mcp-research" / "SKILL.md"),
        ),
        NodeSpec(
            "skill_repo_triage",
            "Skill: repo-triage",
            "rationale",
            str(skills_dir / "repo-triage" / "SKILL.md"),
        ),
        NodeSpec(
            "mcp_graphify_local",
            "MCP: graphify-local",
            "rationale",
            str(repo_root / "opencode.json"),
        ),
        NodeSpec(
            "mcp_searxng_local",
            "MCP: searxng-local",
            "rationale",
            str(repo_root / "AGENTS.md"),
        ),
        NodeSpec(
            "mcp_firecrawl_local",
            "MCP: firecrawl-local",
            "rationale",
            str(repo_root / "AGENTS.md"),
        ),
        NodeSpec(
            "mcp_neo4j_memory_local",
            "MCP: neo4j-memory-local",
            "rationale",
            str(repo_root / "AGENTS.md"),
        ),
    ]

    if apply_repo_overlay:
        for spec in specs:
            _add_node(G, spec)

    opencode_json = repo_root / "opencode.json"
    config = (
        json.loads(opencode_json.read_text(encoding="utf-8"))
        if opencode_json.exists()
        else {}
    )
    edges = set()

    manual_edges = []
    if apply_repo_overlay:
        for item in config.get("instructions", []):
            if item.endswith("mcp-workflows.md"):
                edges.add(
                    _make_edge(
                        "repo_opencode_json",
                        "repo_doc_workflows",
                        "loads_instruction",
                        str(opencode_json),
                        _line_for_text(opencode_json, item),
                    )
                )
            if item.endswith("runtime-notes.md"):
                edges.add(
                    _make_edge(
                        "repo_opencode_json",
                        "repo_doc_runtime",
                        "loads_instruction",
                        str(opencode_json),
                        _line_for_text(opencode_json, item),
                    )
                )

        if "graphify-local" in config.get("mcp", {}):
            edges.add(
                _make_edge(
                    "repo_opencode_json",
                    "mcp_graphify_local",
                    "configures_mcp",
                    str(opencode_json),
                    _line_for_text(opencode_json, '"graphify-local"'),
                )
            )

        if ".opencode/plugins/graphify.js" in config.get("plugin", []):
            edges.add(
                _make_edge(
                    "repo_opencode_json",
                    "plugin_graphify",
                    "registers_plugin",
                    str(opencode_json),
                    _line_for_text(opencode_json, ".opencode/plugins/graphify.js"),
                )
            )

        manual_edges = [
            _make_edge(
                "repo_agents_md",
                "mcp_graphify_local",
                "defines_policy",
                str(repo_root / "AGENTS.md"),
                _line_for_text(repo_root / "AGENTS.md", "graphify-local"),
            ),
            _make_edge(
                "repo_agents_md",
                "mcp_searxng_local",
                "defines_policy",
                str(repo_root / "AGENTS.md"),
                _line_for_text(repo_root / "AGENTS.md", "searxng-local"),
            ),
            _make_edge(
                "repo_agents_md",
                "mcp_firecrawl_local",
                "defines_policy",
                str(repo_root / "AGENTS.md"),
                _line_for_text(repo_root / "AGENTS.md", "firecrawl-local"),
            ),
            _make_edge(
                "repo_agents_md",
                "mcp_neo4j_memory_local",
                "defines_policy",
                str(repo_root / "AGENTS.md"),
                _line_for_text(repo_root / "AGENTS.md", "neo4j-memory-local"),
            ),
            _make_edge(
                "repo_doc_workflows",
                "mcp_graphify_local",
                "documents",
                str(docs_dir / "mcp-workflows.md"),
                _line_for_text(docs_dir / "mcp-workflows.md", "graphify-local"),
            ),
            _make_edge(
                "repo_doc_workflows",
                "mcp_searxng_local",
                "documents",
                str(docs_dir / "mcp-workflows.md"),
                _line_for_text(docs_dir / "mcp-workflows.md", "searxng-local"),
            ),
            _make_edge(
                "repo_doc_workflows",
                "mcp_firecrawl_local",
                "documents",
                str(docs_dir / "mcp-workflows.md"),
                _line_for_text(docs_dir / "mcp-workflows.md", "firecrawl-local"),
            ),
            _make_edge(
                "repo_doc_workflows",
                "mcp_neo4j_memory_local",
                "documents",
                str(docs_dir / "mcp-workflows.md"),
                _line_for_text(docs_dir / "mcp-workflows.md", "neo4j-memory-local"),
            ),
            _make_edge(
                "repo_doc_runtime",
                "artifact_graph_json",
                "documents",
                str(docs_dir / "runtime-notes.md"),
                _line_for_text(
                    docs_dir / "runtime-notes.md", "graphify-out/graph.json"
                ),
            ),
            _make_edge(
                "repo_doc_runtime",
                "mcp_graphify_local",
                "documents",
                str(docs_dir / "runtime-notes.md"),
                _line_for_text(docs_dir / "runtime-notes.md", "graphify-local"),
            ),
            _make_edge(
                "repo_doc_profiles",
                "repo_doc_runtime",
                "references",
                str(repo_root / "LOCAL_AI_PROFILES.md"),
                _line_for_text(
                    repo_root / "LOCAL_AI_PROFILES.md", "local-reasoner.service"
                ),
            ),
            _make_edge(
                "command_refresh_graph",
                "script_build_graphify",
                "runs",
                str(commands_dir / "refresh-graph.md"),
                _line_for_text(commands_dir / "refresh-graph.md", "build-graphify"),
            ),
            _make_edge(
                "command_refresh_graph",
                "artifact_graph_json",
                "refreshes",
                str(commands_dir / "refresh-graph.md"),
                _line_for_text(
                    commands_dir / "refresh-graph.md", "graphify-out/graph.json"
                ),
            ),
            _make_edge(
                "command_refresh_graph",
                "artifact_graph_report",
                "refreshes",
                str(commands_dir / "refresh-graph.md"),
                _line_for_text(
                    commands_dir / "refresh-graph.md", "graphify-out/GRAPH_REPORT.md"
                ),
            ),
            _make_edge(
                "command_refresh_graph",
                "artifact_graph_html",
                "refreshes",
                str(commands_dir / "refresh-graph.md"),
                _line_for_text(
                    commands_dir / "refresh-graph.md", "graphify-out/graph.html"
                ),
            ),
            _make_edge(
                "command_refresh_graph",
                "artifact_graph_wiki",
                "refreshes",
                str(commands_dir / "refresh-graph.md"),
                _line_for_text(
                    commands_dir / "refresh-graph.md", "graphify-out/wiki/index.md"
                ),
            ),
            _make_edge(
                "command_mcp_audit",
                "script_audit_opencode",
                "runs",
                str(commands_dir / "mcp-audit.md"),
                _line_for_text(commands_dir / "mcp-audit.md", "audit-opencode"),
            ),
            _make_edge(
                "command_repo_research",
                "agent_mcp_researcher",
                "dispatches_agent",
                str(commands_dir / "repo-research.md"),
                _line_for_text(
                    commands_dir / "repo-research.md", "agent: mcp-researcher"
                ),
            ),
            _make_edge(
                "command_graph_report",
                "artifact_graph_report",
                "reads",
                str(commands_dir / "graph-report.md"),
                _line_for_text(
                    commands_dir / "graph-report.md", "graphify-out/GRAPH_REPORT.md"
                ),
            ),
            _make_edge(
                "command_graph_query",
                "mcp_graphify_local",
                "queries",
                str(commands_dir / "graph-query.md"),
                _line_for_text(
                    commands_dir / "graph-query.md", "graphify-local_query_graph"
                ),
            ),
            _make_edge(
                "command_graph_query",
                "command_graph_report",
                "follows_up_with",
                str(commands_dir / "graph-query.md"),
                _line_for_text(commands_dir / "graph-query.md", "get_node"),
            ),
            _make_edge(
                "command_graph_path",
                "mcp_graphify_local",
                "queries",
                str(commands_dir / "graph-path.md"),
                _line_for_text(
                    commands_dir / "graph-path.md", "graphify-local_shortest_path"
                ),
            ),
            _make_edge(
                "agent_mcp_orchestrator",
                "mcp_graphify_local",
                "routes_to",
                str(agents_dir / "mcp-orchestrator.md"),
                _line_for_text(
                    agents_dir / "mcp-orchestrator.md", "graphify-local_query_graph"
                ),
            ),
            _make_edge(
                "agent_mcp_researcher",
                "mcp_graphify_local",
                "routes_to",
                str(agents_dir / "mcp-researcher.md"),
                _line_for_text(
                    agents_dir / "mcp-researcher.md", "graphify-local_query_graph"
                ),
            ),
            _make_edge(
                "agent_mcp_researcher",
                "artifact_graph_report",
                "uses_orientation",
                str(agents_dir / "mcp-researcher.md"),
                _line_for_text(agents_dir / "mcp-researcher.md", "GRAPH_REPORT.md"),
            ),
            _make_edge(
                "agent_repo_surgeon",
                "artifact_graph_report",
                "uses_orientation",
                str(agents_dir / "repo-surgeon.md"),
                _line_for_text(agents_dir / "repo-surgeon.md", "Graphify report"),
            ),
            _make_edge(
                "skill_mcp_research",
                "mcp_graphify_local",
                "teaches_usage",
                str(skills_dir / "mcp-research" / "SKILL.md"),
                _line_for_text(
                    skills_dir / "mcp-research" / "SKILL.md",
                    "graphify-local_query_graph",
                ),
            ),
            _make_edge(
                "skill_repo_triage",
                "mcp_graphify_local",
                "teaches_usage",
                str(skills_dir / "repo-triage" / "SKILL.md"),
                _line_for_text(
                    skills_dir / "repo-triage" / "SKILL.md",
                    "graphify-local_query_graph",
                ),
            ),
            _make_edge(
                "plugin_graphify",
                "artifact_graph_report",
                "reminds_about",
                str(plugins_dir / "graphify.js"),
                _line_for_text(plugins_dir / "graphify.js", "GRAPH_REPORT.md"),
            ),
            _make_edge(
                "plugin_graphify",
                "artifact_graph_wiki",
                "reminds_about",
                str(plugins_dir / "graphify.js"),
                _line_for_text(plugins_dir / "graphify.js", "wiki/index.md"),
            ),
            _make_edge(
                "script_build_graphify",
                "script_graphify_overlay",
                "calls",
                str(scripts_dir / "build-graphify"),
                _line_for_text(
                    scripts_dir / "build-graphify", "graphify_repo_overlay.py"
                ),
            ),
            _make_edge(
                "script_build_graphify",
                "artifact_graph_json",
                "updates",
                str(scripts_dir / "build-graphify"),
                _line_for_text(
                    scripts_dir / "build-graphify", "graphify-out/graph.json"
                ),
            ),
            _make_edge(
                "script_build_graphify",
                "artifact_graph_report",
                "updates",
                str(scripts_dir / "build-graphify"),
                _line_for_text(scripts_dir / "build-graphify", "GRAPH_REPORT.md"),
            ),
            _make_edge(
                "script_build_graphify",
                "repo_opencode_json",
                "updates",
                str(scripts_dir / "build-graphify"),
                _line_for_text(scripts_dir / "build-graphify", "opencode.json"),
            ),
            _make_edge(
                "script_build_graphify",
                "mcp_graphify_local",
                "configures_mcp",
                str(scripts_dir / "build-graphify"),
                _line_for_text(scripts_dir / "build-graphify", "graphify-local"),
            ),
            _make_edge(
                "script_audit_opencode",
                "plugin_graphify",
                "checks",
                str(scripts_dir / "audit-opencode"),
                _line_for_text(
                    scripts_dir / "audit-opencode", ".opencode/plugins/graphify.js"
                ),
            ),
            _make_edge(
                "script_audit_opencode",
                "command_graph_report",
                "checks",
                str(scripts_dir / "audit-opencode"),
                _line_for_text(
                    scripts_dir / "audit-opencode", ".opencode/commands/graph-report.md"
                ),
            ),
            _make_edge(
                "script_audit_opencode",
                "command_graph_query",
                "checks",
                str(scripts_dir / "audit-opencode"),
                _line_for_text(
                    scripts_dir / "audit-opencode", ".opencode/commands/graph-query.md"
                ),
            ),
            _make_edge(
                "script_audit_opencode",
                "command_graph_path",
                "checks",
                str(scripts_dir / "audit-opencode"),
                _line_for_text(
                    scripts_dir / "audit-opencode", ".opencode/commands/graph-path.md"
                ),
            ),
            _make_edge(
                "mcp_graphify_local",
                "artifact_graph_json",
                "serves",
                str(opencode_json),
                _line_for_text(opencode_json, "graphify-out/graph.json"),
            ),
            _make_edge(
                "artifact_graph_report",
                "artifact_graph_json",
                "derived_from",
                str(scripts_dir / "graphify_repo_overlay.py"),
                _line_for_text(
                    scripts_dir / "graphify_repo_overlay.py", "GRAPH_REPORT.md"
                ),
            ),
            _make_edge(
                "artifact_graph_html",
                "artifact_graph_json",
                "derived_from",
                str(scripts_dir / "graphify_repo_overlay.py"),
                _line_for_text(scripts_dir / "graphify_repo_overlay.py", "graph.html"),
            ),
            _make_edge(
                "artifact_graph_wiki",
                "artifact_graph_json",
                "derived_from",
                str(scripts_dir / "graphify_repo_overlay.py"),
                _line_for_text(scripts_dir / "graphify_repo_overlay.py", "wiki"),
            ),
        ]
        edges.update(manual_edges)

    for source, target, relation, source_file, source_location in sorted(edges):
        _add_edge(G, source, target, relation, source_file, source_location)

    H = _build_view_graph(G)
    communities = cluster(H)
    labels = _community_labels(H, communities)
    communities, labels = _prune_communities(H, communities, labels)
    cohesion = score_all(H, communities)
    gods = god_nodes(H)
    surprises = surprising_connections(H, communities)
    questions = _prune_questions(
        suggest_questions(H, communities, labels),
        apply_repo_overlay=apply_repo_overlay,
    )

    source_files = {
        data.get("source_file", "")
        for _, data in G.nodes(data=True)
        if data.get("source_file")
    }
    detection = {
        "files": {},
        "total_files": len(source_files),
        "total_words": _word_count(source_files),
        "warning": None,
    }

    out_dir = repo_root / "graphify-out"
    out_dir.mkdir(exist_ok=True)
    report = generate(
        H,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        detection,
        {"input": 0, "output": 0},
        str(repo_root),
        suggested_questions=questions,
    )
    (out_dir / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    to_json(G, communities, str(out_dir / "graph.json"))
    try:
        to_html(H, communities, str(out_dir / "graph.html"), labels)
        html_status = "refreshed"
    except ValueError as exc:
        html_status = f"skipped ({exc})"
    to_wiki(H, communities, out_dir / "wiki", labels, cohesion, gods)

    print(
        f"[graphify overlay] merged graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {len(communities)} communities"
    )
    print(f"[graphify overlay] refreshed {out_dir / 'graph.json'}")
    print(f"[graphify overlay] refreshed {out_dir / 'GRAPH_REPORT.md'}")
    print(f"[graphify overlay] graph.html {html_status}")
    print(f"[graphify overlay] refreshed {out_dir / 'wiki' / 'index.md'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: graphify_repo_overlay.py <repo-root>")
    _main(Path(sys.argv[1]).resolve())
