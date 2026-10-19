# Sample conventions

These samples accompany docs/WhoRunsTheLoop.pdf. Keep Chat Completions, Responses with client-side MCP, and Responses with provider-hosted MCP distinct. All agent runs use Microsoft Agent Framework.

- .NET targets net10.0 and Microsoft.Agents.AI.OpenAI 1.25.0.
- Python uses agent-framework-core 1.22.0 and the independently versioned agent-framework-openai 1.17.0.
- MCP uses the official Python SDK's supported 1.x line for compatibility with Agent Framework.
- SDK references: https://github.com/microsoft/agent-framework and https://py.sdk.modelcontextprotocol.io/v1/ and https://github.com/modelcontextprotocol/csharp-sdk.
- Never log authorization headers, API keys, or raw model request bodies. The policy catalog is intentionally fictional and read-only.
- Keep each language self-contained: `dotnet/loop`, `dotnet/mcp_server`, `python/loop`, and `python/mcp_server`. Both MCP servers must expose equivalent policy tools and security behavior.
- Python dependencies and dotenv configuration live under `python/`; shared integration tests remain at the root.
- Validate with `dotnet build dotnet/loop` and `dotnet build dotnet/mcp_server`, followed by `python -m pytest tests -q` in the configured virtual environment.