import { existsSync } from "node:fs"
import { join } from "node:path"

const reminder = [
  "Graphify knowledge graph is available in graphify-out/.",
  "Before broad repo exploration, prefer graphify-local_graph_stats, graphify-local_god_nodes, and graphify-local_query_graph.",
  "Use graphify-local_get_node or graphify-local_get_neighbors for drilldown and graphify-local_shortest_path for connection questions.",
  "Use graphify-out/GRAPH_REPORT.md or graphify-out/wiki/index.md when that is cheaper than raw file searching.",
].join(" ")

const remindedSessions = new Set()

export const GraphifyPlugin = async ({ directory }) => {
  const graphPath = join(directory, "graphify-out", "graph.json")

  return {
    "experimental.chat.system.transform": async (_input, output) => {
      if (!existsSync(graphPath)) return
      output.system.push(reminder)
    },
    "tool.execute.before": async (input, output) => {
      if (!existsSync(graphPath)) return
      if (input.tool !== "bash") return
      if (remindedSessions.has(input.sessionID)) return
      if (!output.args || typeof output.args.command !== "string") return

      output.args.command = [
        "printf '%s\\n' '[graphify] Knowledge graph available. Prefer graphify-local_* tools or graphify-out/GRAPH_REPORT.md before broad repo searching.' >&2",
        output.args.command,
      ].join(" && ")
      remindedSessions.add(input.sessionID)
    },
  }
}
