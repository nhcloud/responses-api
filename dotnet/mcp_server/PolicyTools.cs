using System.ComponentModel;
using System.Text.Json.Serialization;

[McpServerToolType]
public sealed class PolicyTools(ILogger<PolicyTools> logger)
{
    private static readonly Policy[] Policies =
    [
        new("TRAVEL-001", "Booking and approval",
            "Book economy flights at least 14 days before departure. Manager approval is required before booking business travel."),
        new("TRAVEL-002", "Hotel and meal limits",
            "The fictional company reimburses hotels up to USD 200 per night and meals up to USD 75 per day. Itemized receipts are required."),
        new("TRAVEL-003", "Travel exceptions",
            "Accessibility needs, documented medical needs, and destinations with no hotels under the limit qualify for exceptions. Obtain written Finance approval before booking; emergency travel may be approved retrospectively within 2 business days."),
        new("TRAVEL-004", "Expense submission",
            "Submit travel expenses with receipts within 30 days of return. Personal entertainment and companion travel are not reimbursable.")
    ];

    private static readonly HashSet<string> StopWords =
        ["the", "a", "an", "and", "or", "is", "what", "are", "for", "of", "to", "in"];

    [McpServerTool(Name = "search_policy", ReadOnly = true, Destructive = false,
        Idempotent = true, OpenWorld = false)]
    [Description("Search the fictional travel policy KB. Returns policy IDs and source text for citations. Never changes data.")]
    public PolicySearchResult SearchPolicy(string query)
    {
        if (string.IsNullOrWhiteSpace(query) || query.EnumerateRunes().Count() > 500)
        {
            throw new McpException("query must contain between 1 and 500 characters");
        }

        var words = query.ToLowerInvariant().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)
            .Where(word => !StopWords.Contains(word)).ToHashSet();
        var matches = Policies.Where(policy => words.Any(word =>
            (policy.Title + " " + policy.Text).ToLowerInvariant().Contains(word, StringComparison.Ordinal))).ToArray();
        logger.LogInformation("Executed search_policy; matches={Count}", matches.Length);
        return new PolicySearchResult(true, matches);
    }
}

public sealed record Policy(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("text")] string Text);

public sealed record PolicySearchResult(
    [property: JsonPropertyName("fictional")] bool Fictional,
    [property: JsonPropertyName("matches")] Policy[] Matches);