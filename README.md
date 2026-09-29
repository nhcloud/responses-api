# responses-api
Migrating from Chat Completions to the Responses API using Azure OpenAI models deployed in Microsoft Foundry, with Microsoft Agent Framework. Runnable C# and Python companions to [Who Runs the Loop?](docs/WhoRunsTheLoop.pdf).

## What The Samples Show

One fictional travel-policy KB, one publicly hosted MCP server, and the same two questions in both languages. Start either sample without arguments to select a demo. Each selection uses an Agent Framework agent and a fresh session, not a hand-written OpenAI tool loop.

| Menu | Model endpoint | Who calls MCP? | Conversation state |
| --- | --- | --- | --- |
| **1 - Chat Completions** | Chat Completions | Agent Framework in your application | Local history replay |
| **2 - Responses** | Responses with provider-hosted MCP | Azure OpenAI | Service-managed response chaining |
| **3 - Exit** | None | Neither | Ends the application |

Both demos use the same `MCP_SERVER_URL` and `search_policy` tool. **The MCP server is publicly hosted in both; only option 2 uses the provider-hosted MCP integration.** Option 1 receives function calls and executes them through Agent Framework in our application. Option 2 sends an MCP server declaration, allow-list, and authentication header to Azure OpenAI; our application does not connect to MCP at all. Approval requests may still return to our application, but approving a call does not execute the tool locally.

Responses also supports client-side tools: merely changing API endpoints does not move tool execution to the provider. The menu deliberately selects provider-hosted MCP for Responses to make this comparison explicit.

The server exposes only `search_policy`. Its data is explicitly fictional, deterministic, and read-only. It has no model credentials, filesystem tools, or external data access.

## Versions And Files

Verified against package registries on September 28, 2026:

- .NET 10; `Microsoft.Agents.AI.OpenAI` **1.22.0**, as requested.
- Python 3.11+; `agent-framework-core` **1.19.0**, the latest framework release checked.
- Python `agent-framework-openai` **1.14.4**. This integration has its own version sequence and requires core 1.19.0 or newer.
- Official MCP SDK: Python **1.30.0**, C# **2.2.0**. Python stays on the supported 1.x line because Agent Framework's MCP integration requires `<2`.

| File | Purpose |
| --- | --- |
| [dotnet/LoopDemo/Program.cs](dotnet/LoopDemo/Program.cs) | C# menu, agents, sessions, streaming, approvals |
| [python/loop_demo.py](python/loop_demo.py) | Equivalent Python agent |
| [mcp_server/server.py](mcp_server/server.py) | One shared MCP server, HTTP or local stdio |
| [tests/test_samples.py](tests/test_samples.py) | Offline, cross-language integration tests |
| [mcp_server/Dockerfile](mcp_server/Dockerfile) | Non-root container for public hosting |

The important SDK names from slides 20-25 are preserved: `.GetResponsesClient().AsAIAgent(model: ...)`, `AgentSession`, Python `Agent`, and synchronous `agent.create_session()`. Python **`OpenAIChatClient` is the Responses client**; `OpenAIChatCompletionClient` is Chat Completions.

## Local Setup

From the repository root, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
dotnet build dotnet/LoopDemo
```

On macOS/Linux, use `.venv/bin/python` instead. You need an existing Azure OpenAI model deployment in Microsoft Foundry for live calls. These local samples do not provision resources or require `azd` or a Foundry hosted-agent service.

### Configuration Files

For Python, copy [.env.example](.env.example) to `.env` at the repository root and fill in your Azure endpoint, deployment name, and API key. Both the Python client and MCP server load that file automatically, regardless of the working directory. Existing environment variables take precedence. `.env` is ignored by Git; do not commit credentials.

For .NET, configure [dotnet/LoopDemo/appsettings.json](dotnet/LoopDemo/appsettings.json). With `DOTNET_ENVIRONMENT=Development`, [dotnet/LoopDemo/appsettings.development.json](dotnet/LoopDemo/appsettings.development.json) overrides the base file, followed by .NET user secrets. Environment variables override all of these sources. The keys match [.env.example](.env.example), but .NET does not load `.env`.

Keep secrets out of both JSON files. For local .NET development, set the key with `dotnet user-secrets set AZURE_OPENAI_API_KEY "<your-key>" --project dotnet/LoopDemo`, then select Development:

```powershell
$env:DOTNET_ENVIRONMENT = "Development"
```

User secrets are outside the repository but are not encrypted. Environment variables are also supported. Set `MCP_AUTH_TOKEN` the same way when using an authenticated MCP server; it must match the Python server's token. Settings files are copied to the .NET build/publish output; rebuild after editing them if you run the DLL directly.

For the complete comparison, host the MCP server using the [public hosting instructions](#public-mcp-hosting), then set `MCP_SERVER_URL` to the same public HTTPS `/mcp` URL in both samples' configuration. Configure the matching token. Neither menu selection changes that URL.

For Chat-only local testing, you can instead start MCP in one terminal:

```powershell
.\.venv\Scripts\python.exe mcp_server/server.py
```

The local endpoint is `http://localhost:8000/mcp`; health is `http://localhost:8000/healthz`. Default binding is loopback. Unauthenticated access is allowed only for this local demo. To test authentication locally, set the same `MCP_AUTH_TOKEN` in both server and client terminals before starting them. Menu option 2 rejects localhost and returns to the menu; it requires a public HTTPS endpoint.

In a second terminal, after configuring the files above (and selecting Development for .NET user secrets), run either sample. You can still override file settings with environment variables:

```powershell
dotnet run --project dotnet/LoopDemo

.\.venv\Scripts\python.exe python/loop_demo.py
```

Choose `1` or `2` to run the two-question demo with streaming enabled. After it completes or encounters a handled error, the menu appears again. Choose `3` to exit. Each selection starts a fresh session; the two questions within that selection share context. Invalid selections are retried; end-of-input exits.

Use an Azure OpenAI deployment that supports the selected API and tools. `AZURE_OPENAI_DEPLOYMENT_NAME` is your **deployment name**, which may differ from its underlying model ID. Both samples require Azure configuration and do not fall back to OpenAI.com or the old `OPENAI_*` settings.

`AZURE_OPENAI_ENDPOINT` accepts the resource root (for example `https://YOUR-RESOURCE.openai.azure.com/` or `https://YOUR-RESOURCE.services.ai.azure.com/`) or its full `/openai/v1/` API root. Both are normalized to `/openai/v1/`. Do not use a Foundry project URL containing `/api/projects/...`, a deployment-specific URL, or a URL with an `api-version` query. The v1 API does not require an API-version setting.

The clients intentionally still use the `OpenAIClient` / `AsyncOpenAI` SDKs: Azure OpenAI v1 supports these clients for both Chat Completions and Responses. All agent execution remains in Microsoft Agent Framework. This is direct Azure OpenAI model inference, not the Foundry Agent Service. Authentication remains API-key based for the demo; managed identity is not implemented. For production, prefer Microsoft Entra ID. Model, region, and resource support for Responses, stored state, and hosted MCP must be verified for your deployment.

Each demo asks about hotel/meal limits and then asks about exceptions using the same session. Menu runs stream text and underlying provider event types, with explicit approval for provider-hosted MCP. Turns have a two-minute timeout and support Ctrl+C cancellation.

Python loads the repository-root `.env`; .NET loads its project JSON files and, in Development, user secrets. Both retain environment-variable overrides. Never commit credentials.

### Optional Command-Line Modes

The existing one-shot modes remain available for automation and deeper comparisons, but are not required for the menu:

| CLI mode | Behavior |
| --- | --- |
| `chat` | Chat Completions with application-side MCP, like menu option 1 |
| `hosted-mcp` | Responses with provider-hosted MCP, like menu option 2 |
| `responses` | Additional Responses comparison with application-side MCP; not menu option 2 |

For example, `dotnet run --project dotnet/LoopDemo -- hosted-mcp --stream` or `python python/loop_demo.py hosted-mcp --stream`. One-shot modes accept `--stream`, `--interactive` (free-form chat, `/exit` quits), and `--auto-approve` (provider-hosted read-only tool only). Menu runs always stream the two fixed prompts and require hosted-tool approval.

## Public MCP Hosting

Hosted MCP requires an **internet-reachable HTTPS URL** with a valid certificate. `localhost`, private-only DNS, and a local stdio server cannot be reached by the provider. The URL must point to `/mcp`, not `/healthz` or an HTML login page.

Start Docker Desktop's Linux engine (or another Linux Docker daemon), then build the server-only image with its own directory as the build context:

```powershell
docker build -t who-runs-the-loop-mcp ./mcp_server
```

Set `MCP_AUTH_TOKEN` to a long randomly generated secret through your host's secret manager. Set `MCP_PUBLIC_HOST` to the exact public hostname, such as `policy.example.com`, without a scheme or path. Then run behind your HTTPS ingress/reverse proxy:

```powershell
$env:MCP_PUBLIC_HOST = "policy.example.com"
docker run --rm -p 127.0.0.1:8000:8000 `
	-e MCP_AUTH_TOKEN -e MCP_PUBLIC_HOST who-runs-the-loop-mcp
```

For a managed container host, route its ingress directly to container port 8000 instead of using this local Docker port mapping. The image binds `0.0.0.0`; `PORT` can override 8000. For non-container hosting, install [mcp_server/requirements.txt](mcp_server/requirements.txt), set `MCP_HOST=0.0.0.0`, and run the same server script.

The public ingress must preserve the `Authorization` and public `Host` headers and pass POST requests and MCP headers through. The server uses stateless Streamable HTTP with JSON responses, so no sticky sessions or legacy SSE endpoint are required. Keep it behind TLS, enforce request-size/rate limits at ingress, and check `/healthz` without authentication. An unauthorized MCP request returns 401; a disallowed Host returns 421.

This sample uses a shared bearer token, **not a complete OAuth authorization server**. Use an identity provider and scoped token validation before exposing real enterprise data. Read-only annotations are descriptive metadata; actual safety comes from the limited tool implementation, allow-list, and authentication. Do not disable Host validation to fix a proxy configuration.

In the client terminal, set the same token securely and switch only the MCP URL:

```powershell
$env:MCP_SERVER_URL = "https://policy.example.com/mcp"
dotnet run --project dotnet/LoopDemo
.\.venv\Scripts\python.exe python/loop_demo.py
```

Select `1` and `2` in turn to compare the same hosted server. Responses requires explicit approval: review the displayed arguments, then enter `y` to approve or any other response to deny. Approval IDs are sent back using the same session. Both demos allow only `search_policy`; neither grants blanket access to future server tools. In Responses, the MCP bearer header is supplied on every model request, including follow-ups and approval continuations. Your application chooses the credential, never the model.

Azure OpenAI receives the MCP credential and tool data in hosted mode. Send only data and credentials you are authorized to share with that service. The MCP server needs no Azure OpenAI key.

## What To Watch

The clients log HTTP methods and paths, not headers or request bodies. At the end of each turn they show model HTTP request counts and **application-side** MCP HTTP request counts. In Chat, expect a model tool request, a real MCP call, and another model request. In Responses with provider-hosted MCP, expect zero application-to-MCP requests even when approval requires additional model requests; the MCP server log shows the provider's tool execution instead.

Counts are observations, not fixed performance guarantees: tool choices, retries, and approvals change them. Streaming prints framework-forwarded provider events; Agent Framework does not necessarily forward every wire-level lifecycle event. Approval prompts deliberately display model-proposed query arguments, so do not record console output containing sensitive user data.

Responses sessions use stored response chaining by default. Chat sessions retain and replay local messages. Sessions here live only for the process lifetime; this sample does not implement durable session storage, Conversations API lifecycle management, or `store=false`. Service-managed context is still billed and subject to provider retention settings. Do not assume it is free or persistent forever.

## Verify And Debug

```powershell
dotnet build dotnet/LoopDemo
.\.venv\Scripts\python.exe -m pytest tests -q
```

Tests run both actual SDK clients against a scripted local Azure OpenAI v1 endpoint and a real MCP HTTP server. They cover repeated menu selections, fresh sessions, exit/EOF, invalid selections, recovery from configuration errors, file configuration and environment overrides, Azure endpoint normalization, deployment-name routing, all three underlying modes, two-turn context, streaming, approve/deny, allow-lists, token propagation, real tool results, authentication, and Host protection. They do not incur model charges. The .NET tests require the Debug build above and skip only when `dotnet` is absent.

For VS Code, select `.venv` as your Python interpreter and configure `.env` for Python and the MCP server. Configure the project JSON files and user secrets for .NET; its F5 profile sets `DOTNET_ENVIRONMENT=Development` and does not read `.env`. Press F5 for the MCP server or either agent sample. The Python/Python Debugger and C# extensions are required. [.vscode/mcp.json](.vscode/mcp.json) also exposes the same server via stdio for local MCP inspection; this does not replace the HTTP endpoint needed by the samples or provider.

Live provider execution requires your credentials, a supported model, and the public URL you host. Offline tests prove the client contracts and local tool execution, not public reachability or provider-side tool execution. The Docker image must also be built and exercised in your hosting environment.

Troubleshooting:

- Model 401/403: check `AZURE_OPENAI_API_KEY`, the matching Azure resource endpoint, and whether key-based authentication is enabled.
- Model 404: check `AZURE_OPENAI_DEPLOYMENT_NAME` matches the deployment in that resource, not just the model ID.
- MCP 401: the server and client token values must match. Restart the server after changing its token.
- MCP 421: set `MCP_PUBLIC_HOST` to the hostname actually forwarded by ingress.
- Hosted MCP connection failure: verify public DNS, trusted TLS, `/mcp`, ingress authorization forwarding, and provider network restrictions. A successful local client call is not proof of provider reachability.
- Unsupported tool or state error: use a provider/model with Responses hosted MCP and stored response support; use `chat` or `responses` with client-side MCP for compatible endpoints without hosted MCP.
- `OPENAI001`: the upstream .NET OpenAI SDK still marks Responses experimental. The project explicitly suppresses only this diagnostic, despite Agent Framework itself being GA.

## References

- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- [Azure OpenAI v1 endpoint configuration](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/switching-endpoints)
- [Hosted MCP tools](https://learn.microsoft.com/agent-framework/agents/tools/hosted-mcp-tools)
- [OpenAI remote MCP](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
- [Official Python MCP SDK 1.x](https://py.sdk.modelcontextprotocol.io/v1/)
- [Official C# MCP SDK](https://github.com/modelcontextprotocol/csharp-sdk)
