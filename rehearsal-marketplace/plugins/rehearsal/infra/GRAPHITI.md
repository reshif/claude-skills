# Optional: Graphiti knowledge graph

The plugin works without this. Its own fact store in `.rehearsal/world/` is the source of truth the CLI validates against. Graphiti adds semantic and graph search over your source documents, so seed-world finds related facts you'd miss.

## Run it locally (Docker)

Use the official compose from Zep's Graphiti repo, which runs FalkorDB and the Graphiti MCP server together:

```bash
git clone https://github.com/getzep/graphiti.git
cd graphiti/mcp_server
cp .env.example .env      # set the LLM key it uses for extraction
docker compose up -d      # see the repo's README for the FalkorDB variant
```

The MCP endpoint is then `http://localhost:8000/mcp/`.

## Connect it to Claude Code

Merge `mcp.graphiti.example.json` into your project's `.mcp.json`, or run:

```bash
claude mcp add --transport http graphiti http://localhost:8000/mcp/
```

Restart Claude Code. seed-world will see the Graphiti tools (`add_episode`, search) and mirror every source document into the graph, using the repo name as the group id.

## Notes

- Graphiti calls an LLM to extract entities. Check that its key and model match your company's vendor rules.
- Keep the container on your machine or your Docker network, because the graph holds ticket and incident text.
