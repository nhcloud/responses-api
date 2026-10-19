# responses-api
Migrating from Chat Completions to the Responses API using Azure OpenAI models deployed in Microsoft Foundry, with Microsoft Agent Framework. Runnable C# and Python companions to [Who Runs the Loop?](docs/WhoRunsTheLoop.pdf).

## What The Samples Show

One fictional travel-policy KB, equivalent MCP servers in .NET and Python, and the same two questions in both languages. Choose either server to host; either client can use it. Start either loop sample without arguments to select a demo. Each selection uses an Agent Framework agent and a fresh session, not a hand-written OpenAI tool loop.

| Menu | Model endpoint | Who calls MCP? | Conversation state |
| --- | --- | --- | --- |
| **1 - Chat Completions** | Chat Completions | Agent Framework in your application | Local history replay |
| **2 - Responses (confirm)** | Responses with provider-hosted MCP | Azure OpenAI, after you approve each call | Service-managed response chaining |
| **3 - Responses (auto-approve)** | Responses with provider-hosted MCP | Azure OpenAI, without asking | Service-managed response chaining |
| **4 - Exit** | None | Neither | Ends the application |

Both demos use the same `MCP_SERVER_URL` and `search_policy` tool. **The MCP server is publicly hosted in both; only options 2 and 3 use the provider-hosted MCP integration.** Option 1 receives function calls and executes them through Agent Framework in our application. Options 2 and 3 send an MCP server declaration, allow-list, and authentication header to Azure OpenAI; our application does not connect to MCP at all. Approval requests may still return to our application, but approving a call does not execute the tool locally.

Responses also supports client-side tools: merely changing API endpoints does not move tool execution to the provider. The menu deliberately selects provider-hosted MCP for Responses to make this comparison explicit.

### Hosted MCP approval

With hosted MCP, the tool declaration sent to Azure OpenAI carries `require_approval`. Option 2 sends `always`: before each call, the service stops and returns an `mcp_approval_request` with the proposed arguments. The demo asks `Allow search_policy ...? [y/N]` and sends the answer back in a **second Responses request**. That extra round trip and your typing time are why option 2 takes longer, and both count in `[timing]`. Option 3 sends `never`: Azure OpenAI calls the MCP server and finishes the turn in a single request. The startup line shows `MCP approval: prompt (always_require)` or `MCP approval: auto (never_require)`.

To skip confirmation, choose menu option 3, or pass `--auto-approve` to the one-shot `hosted-mcp` mode. In code, this is `HostedMcpServerToolApprovalMode.NeverRequire` in .NET and `approval_mode="never_require"` in Python. Skip approval only for tools you trust with whatever the model sends them. Here `search_policy` is read-only and allow-listed. For tools that change data or receive sensitive input, keep `always`, or require approval only for specific tools (`HostedMcpServerToolApprovalMode.RequireSpecific` / `{"always_require_approval": [...]}`).

The server exposes only `search_policy`. Its data is explicitly fictional, deterministic, and read-only. It has no model credentials, filesystem tools, or external data access.

## Versions And Files

Verified against package registries on September 28, 2026:

- .NET 10; `Microsoft.Agents.AI.OpenAI` **1.25.0** (latest .NET release).
- Python 3.11+; `agent-framework-core` **1.22.0**, the latest Python release (Python and .NET packages are versioned independently; there is no Python 1.25).
- Python `agent-framework-openai` **1.17.0**. This integration has its own version sequence and requires core 1.22.0 or newer.
- Official MCP SDK: Python **1.30.0**, C# **2.2.0**. Python stays on the supported 1.x line because Agent Framework's MCP integration requires `<2`.

| File | Purpose |
| --- | --- |
| [dotnet/loop/Program.cs](dotnet/loop/Program.cs) | C# menu, agents, sessions, streaming, approvals |
| [dotnet/mcp_server/Program.cs](dotnet/mcp_server/Program.cs) | ASP.NET Core MCP server, HTTP or local stdio |
| [dotnet/mcp_server/PolicyTools.cs](dotnet/mcp_server/PolicyTools.cs) | C# implementation of the fictional policy tool |
| [python/loop/loop_demo.py](python/loop/loop_demo.py) | Equivalent Python agent |
| [python/mcp_server/server.py](python/mcp_server/server.py) | Equivalent Python MCP server, HTTP or local stdio |
| [tests/test_samples.py](tests/test_samples.py) | Offline, cross-language integration tests |
| [dotnet/mcp_server/Dockerfile](dotnet/mcp_server/Dockerfile) | Server-only .NET container |
| [python/mcp_server/Dockerfile](python/mcp_server/Dockerfile) | Server-only Python container |
| [deploy/deploy-mcp.ps1](deploy/deploy-mcp.ps1) | Deploys both servers to one Azure Container Apps environment |

All sample code and language-specific configuration live in two folders:

```text
dotnet/
	loop/
	mcp_server/
python/
	loop/
	mcp_server/
	requirements.txt
	requirements-dev.txt
```

.NET users do not need Python; Python users do not need .NET. Only the shared cross-language integration suite requires both runtimes. The servers contain the same policy records, search rules, query validation, read-only annotations, bearer authentication, and Host/Origin checks. Neither server needs a model API key.

The important SDK names from slides 20-25 are preserved: `.GetResponsesClient().AsAIAgent(model: ...)`, `AgentSession`, Python `Agent`, and synchronous `agent.create_session()`. Python **`OpenAIChatClient` is the Responses client**; `OpenAIChatCompletionClient` is Chat Completions.

## Local Setup

Choose one language below. Commands are from the repository root in PowerShell. You need an existing Azure OpenAI model deployment in Microsoft Foundry for live agent calls. These samples do not provision resources or require `azd` or a Foundry hosted-agent service.

### .NET Setup

Install the .NET 10 SDK, then build the loop and server:

```powershell
dotnet build dotnet/loop
dotnet build dotnet/mcp_server
```

Configure the endpoint and deployment in [dotnet/loop/appsettings.json](dotnet/loop/appsettings.json), and server settings in [dotnet/mcp_server/appsettings.json](dotnet/mcp_server/appsettings.json). Each project loads its own JSON file from the build output. With `DOTNET_ENVIRONMENT=Development`, each also loads its optional `appsettings.development.json` and its own user-secrets store. Environment variables take precedence. Development settings are ignored by Git. .NET does not load Python's dotenv files.

Keep secrets out of tracked JSON files. For local development, set the key with `dotnet user-secrets set AZURE_OPENAI_API_KEY "<your-key>" --project dotnet/loop`, then select Development:

```powershell
$env:DOTNET_ENVIRONMENT = "Development"
```

User secrets are outside the repository but are not encrypted. For authenticated MCP, set the same `MCP_AUTH_TOKEN` in the loop and the server. They have separate secret stores: use `--project dotnet/loop` for the client and `--project dotnet/mcp_server` for the server. Alternatively, supply environment variables. Settings files are copied to build/publish output; rebuild after editing them if you run the DLL directly.

For local Chat testing, start the server in one terminal, then run the loop in another:

```powershell
dotnet run --project dotnet/mcp_server
```

```powershell
dotnet run --project dotnet/loop
```

### Python Setup

Install Python 3.11 or newer, then:

```powershell
python -m venv python/.venv
.\python\.venv\Scripts\python.exe -m pip install -r python/requirements.txt
Copy-Item python/loop/.env.example python/loop/.env
```

Fill in the Azure endpoint, deployment name, and API key in `python/loop/.env`. Like .NET, each program has its own settings with the same keys: the loop loads [python/loop/.env](python/loop/.env.example) (Azure OpenAI and `MCP_SERVER_URL`/`MCP_AUTH_TOKEN`), and the server loads an optional `python/mcp_server/.env` (`MCP_HOST`, `PORT`, `MCP_PUBLIC_HOST`, `MCP_AUTH_TOKEN`; see [the template](python/mcp_server/.env.example)). The server's defaults work for a local demo, so you only need that file to set a token or change the port. Both load their file regardless of the working directory, without overriding existing environment variables. `.env` files are ignored by Git; do not commit credentials.

Start the server in one terminal and the loop in another:

```powershell
.\python\.venv\Scripts\python.exe python/mcp_server/server.py
```

```powershell
.\python\.venv\Scripts\python.exe python/loop/loop_demo.py
```

On macOS/Linux, replace `.\python\.venv\Scripts\python.exe` with `python/.venv/bin/python` and use `cp` to copy the template. You can also work entirely inside the Python folder using relative paths such as `loop/loop_demo.py` and `mcp_server/server.py`.

An existing repository-root `.venv` can still be used with the new script and requirements paths; it has not been moved. If upgrading an older checkout, move the client settings from `python/.env` to `python/loop/.env`, and any server settings to `python/mcp_server/.env`.

### Choose An MCP Server

Run **one** server, in either language. Both default to `http://localhost:8000/mcp`, with health at `http://localhost:8000/healthz`. To run both simultaneously, give one a different `PORT` and point the client at that port. Default binding is loopback; unauthenticated access is allowed only for the local demo. Set the same `MCP_AUTH_TOKEN` in server and client configuration to enable local authentication.

For the complete comparison, use the [public hosting instructions](#public-mcp-hosting), then set `MCP_SERVER_URL` to that server's public HTTPS `/mcp` URL in the loop configuration. Neither menu selection changes the URL. Menu options 2 and 3 reject localhost and returns to the menu: Azure OpenAI must be able to reach the server.

### Terminal Launchers

After setup, [start.cmd](start.cmd) and [start.sh](start.sh) open the selected loop demos in interactive terminals. No selection means both:

```powershell
.\start.cmd dotnet
.\start.cmd python
.\start.cmd
```

```bash
bash start.sh dotnet
bash start.sh python
bash start.sh
```

Only the selected language's runtime is required. The scripts prefer `python/.venv`, fall back to the existing root `.venv`, work from any current directory, and default `DOTNET_ENVIRONMENT` to `Development` unless already set. Add `--check` to check prerequisites without opening windows. Git Bash delegates to the Windows launcher; Linux requires a desktop session with `gnome-terminal`, `konsole`, `xfce4-terminal`, or `xterm`; macOS uses Terminal. For headless use, run the individual commands above.

Launchers start the loop clients only, not an MCP server. Select `3` to end each demo; on Windows, close the remaining command window or type `exit`. On macOS/Linux, press Enter after the demo ends.

Choose `1`, `2`, or `3` to run the two-question demo with streaming enabled. After it completes or encounters a handled error, the menu appears again. Choose `4` to exit. Each selection starts a fresh session; the two questions within that selection share context. Invalid selections are retried; end-of-input exits.

Use an Azure OpenAI deployment that supports the selected API and tools. `AZURE_OPENAI_DEPLOYMENT_NAME` is your **deployment name**, which may differ from its underlying model ID. Both samples require Azure configuration and do not fall back to OpenAI.com or the old `OPENAI_*` settings.

`AZURE_OPENAI_ENDPOINT` accepts the resource root (for example `https://YOUR-RESOURCE.openai.azure.com/` or `https://YOUR-RESOURCE.services.ai.azure.com/`) or its full `/openai/v1/` API root. Both are normalized to `/openai/v1/`. Do not use a Foundry project URL containing `/api/projects/...`, a deployment-specific URL, or a URL with an `api-version` query. The v1 API does not require an API-version setting.

The clients intentionally still use the `OpenAIClient` / `AsyncOpenAI` SDKs: Azure OpenAI v1 supports these clients for both Chat Completions and Responses. All agent execution remains in Microsoft Agent Framework. This is direct Azure OpenAI model inference, not the Foundry Agent Service. Authentication remains API-key based for the demo; managed identity is not implemented. For production, prefer Microsoft Entra ID. Model, region, and resource support for Responses, stored state, and hosted MCP must be verified for your deployment.

Each demo asks about hotel/meal limits and then asks about exceptions using the same session. Menu runs stream text and underlying provider event types, with explicit approval for provider-hosted MCP in option 2 and none in option 3. Turns have a two-minute timeout and support Ctrl+C cancellation.

Python loads `python/loop/.env` and `python/mcp_server/.env`; .NET loads its project JSON files and, in Development, user secrets. Both retain environment-variable overrides. Never commit credentials.

### Optional Command-Line Modes

The existing one-shot modes remain available for automation and deeper comparisons, but are not required for the menu:

| CLI mode | Behavior |
| --- | --- |
| `chat` | Chat Completions with application-side MCP, like menu option 1 |
| `hosted-mcp` | Responses with provider-hosted MCP, like menu option 2 (add `--auto-approve` for option 3) |
| `responses` | Additional Responses comparison with application-side MCP; not menu option 2 or 3 |

For example, `dotnet run --project dotnet/loop -- hosted-mcp --stream` or, with the Python virtual environment activated, `python python/loop/loop_demo.py hosted-mcp --stream`. One-shot modes accept `--stream`, `--interactive` (free-form chat, `/exit` quits), `--long` (8 scripted turns; see [Is Responses faster?](#is-responses-faster)), and `--auto-approve` (provider-hosted read-only tool only). Menu runs always stream the two fixed prompts; option 2 requires hosted-tool approval and option 3 does not.

## Public MCP Hosting

Hosted MCP requires an **internet-reachable HTTPS URL** with a valid certificate. `localhost`, private-only DNS, and a local stdio server cannot be reached by the provider. The URL must point to `/mcp`, not `/healthz` or an HTML login page.

### Azure Container Apps (both servers)

[deploy/deploy-mcp.ps1](deploy/deploy-mcp.ps1) deploys **both** servers as separate apps in one Container Apps environment, each with its own HTTPS URL. Images are built in Azure Container Registry, so local Docker is not needed. Requires PowerShell 7 and the Azure CLI:

```powershell
az login
az account set --subscription "<subscription>"   # if you have more than one
./deploy/deploy-mcp.ps1                           # defaults: rg-who-runs-the-loop, eastus2
```

The script creates the resource group, a Basic registry (pulled by each app's managed identity), the environment with Log Analytics, and the apps `policy-mcp-dotnet` and `policy-mcp-python`. It sets `MCP_PUBLIC_HOST` to each app's FQDN and stores one generated `MCP_AUTH_TOKEN` as a secret shared by both apps, so a client switches servers by changing only `MCP_SERVER_URL`. It then checks `/healthz` and an authenticated MCP `initialize` on each. Re-running rebuilds the images and keeps the existing token. Add `-WriteLocalConfig` to write each URL and the token into the git-ignored client configs (.NET server → `dotnet/loop/appsettings.development.json`, Python server → `python/loop/.env`). Each app keeps one replica running (`-MinReplicas 1`, the default). A cold start can take longer than Azure OpenAI waits for a hosted MCP server, which makes the first Responses call fail. Pass `-MinReplicas 0` to scale to zero between demos at lower cost. Remove everything with `az group delete -n rg-who-runs-the-loop`.

### Other hosts

Start Docker Desktop's Linux engine (or another Linux Docker daemon), then choose **one** server-only image. Each build context contains only that language's server:

```powershell
docker build -t who-runs-the-loop-mcp ./dotnet/mcp_server
```

Or:

```powershell
docker build -t who-runs-the-loop-mcp ./python/mcp_server
```

Set `MCP_AUTH_TOKEN` to a long randomly generated secret through your host's secret manager. Set `MCP_PUBLIC_HOST` to the exact public hostname, such as `policy.example.com`, without a scheme or path. Then run behind your HTTPS ingress/reverse proxy:

```powershell
$env:MCP_PUBLIC_HOST = "policy.example.com"
docker run --rm -p 127.0.0.1:8000:8000 `
	-e MCP_AUTH_TOKEN -e MCP_PUBLIC_HOST who-runs-the-loop-mcp
```

For a managed container host, route ingress directly to container port 8000 instead of using this local Docker port mapping. Both images run as non-root and bind `0.0.0.0`; `PORT` can override 8000. Neither image includes the loop client or needs Azure model credentials. Configure the host's health probe at `/healthz`.

For non-container .NET hosting, publish with `dotnet publish dotnet/mcp_server -c Release` and run `dotnet dotnet/mcp_server/bin/Release/net10.0/publish/PolicyMcpServer.dll`. For non-container Python hosting, install [python/mcp_server/requirements.txt](python/mcp_server/requirements.txt) and run the server script. In either case, set `MCP_HOST=0.0.0.0`, `MCP_PUBLIC_HOST`, and `MCP_AUTH_TOKEN` before startup. No Python runtime is required by the .NET server, and no .NET runtime is required by the Python server.

The public ingress must preserve `Authorization` and the public `Host` header and pass POST requests and MCP headers through. Both servers use stateless Streamable HTTP; clients support JSON and streamed responses, so no sticky sessions or legacy SSE endpoint are required. Keep the server behind TLS, enforce request-size/rate limits at ingress, and check `/healthz` without authentication. An unauthorized MCP request returns 401; a disallowed Host returns 421; a disallowed Origin returns 403.

This sample uses a shared bearer token, **not a complete OAuth authorization server**. Use an identity provider and scoped token validation before exposing real enterprise data. Read-only annotations are descriptive metadata; actual safety comes from the limited tool implementation, allow-list, and authentication. Do not disable Host validation to fix a proxy configuration.

In the client terminal, set the same token securely and switch only the MCP URL:

```powershell
$env:MCP_SERVER_URL = "https://policy.example.com/mcp"
dotnet run --project dotnet/loop
.\python\.venv\Scripts\python.exe python/loop/loop_demo.py
```

Select `1` and `2` in turn to compare the same hosted server. Responses requires explicit approval: review the displayed arguments, then enter `y` to approve or any other response to deny. Approval IDs are sent back using the same session. Both demos allow only `search_policy`; neither grants blanket access to future server tools. In Responses, the MCP bearer header is supplied on every model request, including follow-ups and approval continuations. Your application chooses the credential, never the model.

Azure OpenAI receives the MCP credential and tool data in hosted mode. Send only data and credentials you are authorized to share with that service. The MCP server needs no Azure OpenAI key.

## What To Watch

Every question in Chat Completions and both Responses modes prints `[timing start]` before execution, then a `[timing]` summary with `start_utc`, `end_utc`, and `elapsed_seconds` (to three decimal places). This works for menu, streaming, and one-shot runs, including failed or cancelled turns. Elapsed time uses a monotonic clock. Timing covers the full agent turn, including model requests, tool calls, output, and any human approval wait; it excludes client setup, initial MCP discovery, and time spent entering the question. For audience comparisons, use the same prompts/model and account for approval wait: these measurements do not imply that either API is always faster. The optional `--auto-approve` mode removes human approval wait for this read-only demo.

The clients log HTTP methods and paths, not headers or request bodies. At the end of each turn they show model HTTP request counts, the total size of the request bodies sent to the model (`model request bytes`), and **application-side** MCP HTTP request counts. When a run ends, a `[summary]` table lists every turn and the totals. In a terminal, `[app -> MCP]` lines are yellow, `[timing]` elapsed-time lines are green, and `[turn]` lines are cyan. Redirected output stays plain, and setting `NO_COLOR` turns colors off. In Chat, expect a model tool request, a real MCP call, and another model request. In Responses with provider-hosted MCP, expect zero application-to-MCP requests even when approval requires additional model requests; the MCP server log shows the provider's tool execution instead.

### Is Responses faster?

Not necessarily, and the demo should not claim it is. In a warm two-turn run on the same model, Chat Completions was often slightly faster. Your application opens its MCP connection before timing starts, while hosted MCP connects from Azure OpenAI during the turn, and with a tiny local tool each saved round trip is worth very little. Responses wins on other things: who runs the loop, request size, and model capability. Use `--long` (8 scripted turns, ending with a question that depends on the whole conversation) to show request size growing:

```powershell
dotnet run --project dotnet/loop -- chat --stream --long
dotnet run --project dotnet/loop -- hosted-mcp --stream --auto-approve --long
```

A sample run with `gpt-5.6-terra` and the Container Apps MCP server:

| | Chat Completions | Responses with hosted MCP |
| --- | --- | --- |
| Model request bytes, turn 1 → turn 8 | 3,097 → 27,969 (grows every turn) | 739 → 814 (flat) |
| Total model request bytes | 129,695 | 6,453 |
| Model requests / app MCP requests | 16 / 8 | 8 / 0 |
| Total elapsed | 26.0 s | 27.8 s |

Chat re-sends the entire conversation, including tool results, on every request. Responses sends only the new input plus `previous_response_id`. Fewer bytes sent does not mean fewer billed tokens: the service still processes the stored context, though cached input is typically cheaper. Some models restrict Chat Completions: for example, `gpt-6-astra` rejects function tools on `/chat/completions` but supports them on `/responses`.

Counts are observations, not fixed performance guarantees: tool choices, retries, and approvals change them. Streaming prints framework-forwarded provider events; Agent Framework does not necessarily forward every wire-level lifecycle event. Approval prompts deliberately display model-proposed query arguments, so do not record console output containing sensitive user data.

Responses sessions use stored response chaining by default. Chat sessions retain and replay local messages. Sessions here live only for the process lifetime; this sample does not implement durable session storage, Conversations API lifecycle management, or `store=false`. Service-managed context is still billed and subject to provider retention settings. Do not assume it is free or persistent forever.

## Verify And Debug

```powershell
dotnet build dotnet/loop
dotnet build dotnet/mcp_server
.\python\.venv\Scripts\python.exe -m pip install -r python/requirements-dev.txt
.\python\.venv\Scripts\python.exe -m pytest tests -q
```

Use the existing root virtual environment instead if that is your configured interpreter. The full shared suite requires both runtimes and the Debug builds above.

Tests run both actual Agent Framework clients against a scripted local Azure OpenAI v1 endpoint and **both real MCP servers**. They cover repeated menu selections, fresh sessions, exit/EOF, invalid selections, recovery from configuration errors, file configuration and environment overrides, Azure endpoint normalization, deployment-name routing, all three underlying modes, two-turn context, streaming, approve/deny, allow-lists, token propagation, and real tool results. Shared HTTP and stdio contract tests verify the servers' policy results, query validation, discovery metadata, authentication, and Host/Origin protection. They do not incur model charges.

For VS Code, select your Python virtual environment and configure `python/loop/.env` (and optionally `python/mcp_server/.env`). Configure each project's JSON files and user secrets for .NET; both .NET F5 profiles set `DOTNET_ENVIRONMENT=Development` and do not read dotenv files. Press F5 for either MCP server or either loop sample. Install the Python/Python Debugger or C# extension for your chosen language. [.vscode/mcp.json](.vscode/mcp.json) exposes both server alternatives via stdio for local inspection; enable only the one you want and build the .NET server first. Stdio does not replace the HTTP endpoint needed by the samples or provider. You can also launch either server directly with `--stdio`.

Live provider execution requires your credentials, a supported model, and the public URL you host. Offline tests prove the client contracts and local tool execution, not public reachability or provider-side tool execution. Build and exercise your chosen Docker image in the hosting environment as well.

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
