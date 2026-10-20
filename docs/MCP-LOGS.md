# Watching the MCP Traffic

The demo's menu claims to change *who* calls the MCP server. The MCP server's own log proves it. Both servers ([.NET](../dotnet/mcp_server/Program.cs) and [Python](../python/mcp_server/server.py)) log one line per JSON-RPC request, naming the method and the caller, plus one line per tool execution:

```text
MCP request: method=initialize client_info="openai-mcp (Responses API)/1.0.0" user_agent="openai-mcp/1.0.0 (Responses API)"
MCP request: method=tools/call user_agent="openai-mcp/1.0.0 (Responses API)"
Executed search_policy; matches=4
```

- `user_agent` is the HTTP `User-Agent` header, on every request.
- `client_info` is the name and version the client reports in MCP's `initialize` request.

Only method names and caller identity are logged, never tool arguments or results, so user questions stay out of the log. Requests rejected by bearer authentication are not logged.

## Who is calling

| Caller | `user_agent` | `client_info` |
| --- | --- | --- |
| Azure OpenAI, hosted MCP (menu options 3 and 4) | `openai-mcp/1.0.0 (Responses API)` | `openai-mcp (Responses API)/1.0.0` |
| The .NET demo app (menu options 1 and 2) | `who-runs-the-loop-app/1.0 (.NET)` | `LoopDemo/1.0.0.0` |
| The Python demo app (menu options 1 and 2) | `who-runs-the-loop-app/1.0 (Python)` | `mcp/0.1.0` (the MCP SDK default) |

The demo apps set their `User-Agent` explicitly so they are easy to tell apart. Azure OpenAI's values were observed on the Azure deployment in October 2026 and may change.

## What to look for

The method sequence differs depending on who runs the MCP client. These sequences were observed with this repository's servers:

| Caller | Once per conversation | Every tool call |
| --- | --- | --- |
| Your app (menu options 1 and 2) | `initialize`, `notifications/initialized`, `tools/list` (.NET also sends `server/discover`; Python also sends `ping`) | `tools/call` |
| Azure OpenAI, hosted MCP (menu options 3 and 4) | `initialize`, `initialize`, `notifications/initialized`, `tools/list` | `initialize`, `tools/call` |

- **Your app** connects once and reuses the connection, so each tool call is a single request.
- **Azure OpenAI** discovers the tools once per conversation. The result is stored as an `mcp_list_tools` item, and later turns chained with `previous_response_id` reuse it instead of calling `tools/list` again. Start a new conversation, or drop `previous_response_id`, and discovery happens again.
- **Azure OpenAI** sends a fresh `initialize` before every `tools/call`, about 150 ms apart in our runs. Over 8 tool calls that is roughly 20 MCP requests from Azure versus 10 from your app, but zero from your app. Both servers run MCP in stateless mode; a server that keeps sessions may see different behavior.

## Locally

Run a server as described in the [README](../README.md#choose-an-mcp-server) and the lines appear in that server's terminal:

- **Python:** `INFO:policy_mcp:MCP request: method=tools/call user_agent="..."`
- **.NET:** `info: PolicyMcp.Requests[0]` on one line, then `MCP request: method=tools/call user_agent="..."` on the next

Hosted MCP (menu options 3 and 4) needs a public HTTPS server, so to see Azure OpenAI's sequence, use the Azure deployment below.

## In Azure Container Apps

[deploy/deploy-mcp.ps1](../deploy/deploy-mcp.ps1) creates a Log Analytics workspace with the Container Apps environment. Each container's console output lands in the **`ContainerAppConsoleLogs_CL`** table. This is Log Analytics, not Application Insights.

- **Live, during a demo:** in the Azure portal, open the Container App (`policy-mcp-dotnet` or `policy-mcp-python`) and choose **Monitoring → Log stream**.
- **Queries:** open the Container App and choose **Monitoring → Logs**, or open the Log Analytics workspace in `rg-who-runs-the-loop` and choose **Logs**. Switch to KQL mode. New lines arrive after about 1–2 minutes.
- **CLI, recent lines:** `az containerapp logs show -n policy-mcp-python -g rg-who-runs-the-loop --tail 50 --format text`

The names above are the deploy script's defaults; use yours if you changed them.

### Sample queries

Add `| where ContainerAppName_s == "policy-mcp-dotnet"` (or `"policy-mcp-python"`) to any query to focus on one server.

**MCP requests in order, with the caller:**

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(30m)
| where Log_s has "MCP request"
| extend Method = extract(@"method=(\S+)", 1, Log_s), UserAgent = extract(@'user_agent="([^"]*)"', 1, Log_s)
| extend Caller = case(UserAgent startswith "openai-mcp", "Azure OpenAI (hosted MCP)",
                       UserAgent startswith "who-runs-the-loop-app", "Our app",
                       UserAgent)
| project TimeGenerated, Server = ContainerAppName_s, Caller, Method
| order by TimeGenerated asc
```

**Request count per caller and method:**

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(30m)
| where Log_s has "MCP request"
| extend Method = extract(@"method=(\S+)", 1, Log_s), UserAgent = extract(@'user_agent="([^"]*)"', 1, Log_s)
| extend Caller = case(UserAgent startswith "openai-mcp", "Azure OpenAI (hosted MCP)",
                       UserAgent startswith "who-runs-the-loop-app", "Our app",
                       UserAgent)
| summarize Requests = count() by Caller, Method
| order by Caller asc, Requests desc
```

**Handshake time before each hosted tool call** (one server at a time, because `prev()` compares neighboring rows):

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(30m)
| where ContainerAppName_s == "policy-mcp-python"
| where Log_s has "MCP request"
| extend Method = extract(@"method=(\S+)", 1, Log_s)
| order by TimeGenerated asc
| extend PreviousMethod = prev(Method), GapMs = datetime_diff("millisecond", TimeGenerated, prev(TimeGenerated))
| where Method == "tools/call" and PreviousMethod == "initialize"
| project TimeGenerated, GapMs
```

**Tool executions with result counts:**

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(30m)
| where Log_s has "Executed search_policy"
| extend Matches = toint(extract(@"matches=(\d+)", 1, Log_s))
| project TimeGenerated, App = ContainerAppName_s, Matches
```

**MCP traffic per minute, as a chart:**

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(1h)
| where Log_s has "MCP request"
| extend Method = extract(@"method=(\S+)", 1, Log_s)
| summarize Requests = count() by bin(TimeGenerated, 1m), Method
| render timechart
```

## Try it

1. Point `MCP_SERVER_URL` at your deployed server and run menu option **1** (Chat Completions, your app calls MCP).
2. Run menu option **4** (Responses, Azure OpenAI calls MCP, auto-approved).
3. Wait a couple of minutes, then run the "MCP requests in order, with the caller" query.

You should see **Our app** send one handshake followed by single `tools/call` requests for option 1, and **Azure OpenAI (hosted MCP)** send `initialize` + `tools/call` pairs for option 4. The loop's own `[turn]` line shows the other side: option 1 counts the MCP requests your app made, and option 4 shows `app MCP HTTP requests=0`.
