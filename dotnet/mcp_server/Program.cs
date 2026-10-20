using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

if (args.Contains("--help"))
{
    Console.WriteLine("Usage: dotnet run --project dotnet/mcp_server -- [--stdio]");
    return;
}

var configurationBuilder = new ConfigurationBuilder()
    .SetBasePath(AppContext.BaseDirectory)
    .AddJsonFile("appsettings.json", optional: true);
if (string.Equals(Environment.GetEnvironmentVariable("DOTNET_ENVIRONMENT"),
    "Development", StringComparison.OrdinalIgnoreCase))
{
    configurationBuilder.AddJsonFile("appsettings.development.json", optional: true);
    configurationBuilder.AddUserSecrets<PolicyTools>();
}
using var configuration = (ConfigurationRoot)configurationBuilder.AddEnvironmentVariables().Build();
var publicHost = (configuration["MCP_PUBLIC_HOST"] ?? "").Trim();
if (publicHost.IndexOfAny(['/', '@', '*', ' ']) >= 0)
{
    throw new InvalidOperationException("MCP_PUBLIC_HOST must be a hostname with an optional port.");
}

if (args.Contains("--stdio"))
{
    var builder = Host.CreateApplicationBuilder();
    ConfigureLogging(builder.Logging);
    builder.Services.AddMcpServer(options => options.ServerInfo = ServerInfo())
        .WithStdioServerTransport()
        .WithTools<PolicyTools>();
    await builder.Build().RunAsync();
    return;
}

var host = configuration["MCP_HOST"] ?? "127.0.0.1";
var port = int.Parse(configuration["PORT"] ?? "8000");
var token = configuration["MCP_AUTH_TOKEN"] ?? "";
if ((host is not ("localhost" or "127.0.0.1" or "::1") || publicHost.Length > 0) && token.Length == 0)
{
    throw new InvalidOperationException("Set MCP_AUTH_TOKEN before exposing the server beyond loopback.");
}

var webBuilder = WebApplication.CreateBuilder();
ConfigureLogging(webBuilder.Logging);
webBuilder.WebHost.UseUrls(new UriBuilder("http", host, port).Uri.AbsoluteUri);
webBuilder.Services.AddMcpServer(options => options.ServerInfo = ServerInfo())
    .WithHttpTransport(options => options.Stateless = true)
    .WithTools<PolicyTools>();
var app = webBuilder.Build();
var expectedAuthorization = Encoding.UTF8.GetBytes($"Bearer {token}");
var requestLogger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("PolicyMcp.Requests");
app.Use(async (context, next) =>
{
    if (context.Request.Path == "/healthz")
    {
        await context.Response.WriteAsJsonAsync(new { status = "ok" }, context.RequestAborted);
        return;
    }

    if (token.Length > 0 && !CryptographicOperations.FixedTimeEquals(
        Encoding.UTF8.GetBytes(context.Request.Headers.Authorization.ToString()), expectedAuthorization))
    {
        context.Response.StatusCode = StatusCodes.Status401Unauthorized;
        context.Response.Headers.WWWAuthenticate = "Bearer";
        await context.Response.WriteAsJsonAsync(new { error = "Unauthorized" }, context.RequestAborted);
        return;
    }

    var requestHost = context.Request.Headers.Host.ToString();
    if (!IsLocalHost(requestHost) && (publicHost.Length == 0 || requestHost != publicHost))
    {
        context.Response.StatusCode = StatusCodes.Status421MisdirectedRequest;
        await context.Response.WriteAsync("Invalid Host header", context.RequestAborted);
        return;
    }

    if (context.Request.Headers.TryGetValue("Origin", out var origin))
    {
        var value = origin.ToString();
        if (!MatchesPort(value, "http://localhost") && !MatchesPort(value, "http://127.0.0.1") &&
            (publicHost.Length == 0 || value != $"https://{publicHost}"))
        {
            context.Response.StatusCode = StatusCodes.Status403Forbidden;
            await context.Response.WriteAsync("Invalid Origin header", context.RequestAborted);
            return;
        }
    }

    if (HttpMethods.IsPost(context.Request.Method) && context.Request.Path == "/mcp")
    {
        // Logs JSON-RPC method names only (never params or results), then rewinds the body for the MCP handler.
        context.Request.EnableBuffering();
        requestLogger.LogInformation("MCP request: method={Methods}", await RpcMethodsAsync(context.Request.Body, context.RequestAborted));
        context.Request.Body.Position = 0;
    }

    await next(context);
});
app.MapMcp("/mcp");
await app.RunAsync();

static async Task<string> RpcMethodsAsync(Stream body, CancellationToken cancellationToken)
{
    try
    {
        using var document = await JsonDocument.ParseAsync(body, cancellationToken: cancellationToken);
        var items = document.RootElement.ValueKind == JsonValueKind.Array
            ? document.RootElement.EnumerateArray().ToArray()
            : [document.RootElement];
        // A JSON-RPC message without "method" is a client response (for example, to a server request).
        return string.Join(",", items.Select(item =>
            item.ValueKind != JsonValueKind.Object ? "invalid"
            : item.TryGetProperty("method", out var method) ? Sanitize(method.ToString())
            : "response"));
    }
    catch (JsonException)
    {
        return "invalid-json";
    }

    static string Sanitize(string name) =>
        new string(name.Take(64).Select(c => char.IsLetterOrDigit(c) || c is '_' or '/' or '.' or '-' ? c : '?').ToArray());
}

static Implementation ServerInfo() => new() { Name = "Who Runs the Loop - Policy KB", Version = "1.0.0" };

static bool MatchesPort(string value, string host) =>
    value == host || value.StartsWith(host + ":", StringComparison.Ordinal);

static bool IsLocalHost(string host) =>
    MatchesPort(host, "localhost") || MatchesPort(host, "127.0.0.1") || MatchesPort(host, "[::1]");

static void ConfigureLogging(ILoggingBuilder logging)
{
    logging.ClearProviders();
    logging.AddConsole(options => options.LogToStandardErrorThreshold = LogLevel.Trace);
    logging.SetMinimumLevel(LogLevel.Warning);
    logging.AddFilter("PolicyTools", LogLevel.Information);
    logging.AddFilter("PolicyMcp.Requests", LogLevel.Information);
    logging.AddFilter("Microsoft.Hosting.Lifetime", LogLevel.Information);
}