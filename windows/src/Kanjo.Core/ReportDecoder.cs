using System.Text.Json;

namespace Kanjo.Core;

/// <summary>契约 JSON 解码入口。错误信息尽量指出出错的字段路径（与 Swift 版相同）。</summary>
public static class ReportDecoder
{
    public static UsageReport Decode(byte[] data)
    {
        using var doc = ParseDocument(data, "Input");
        return DecodeRoot(doc.RootElement, "Report");
    }

    public static UsageReport Decode(string json) => Decode(System.Text.Encoding.UTF8.GetBytes(json));

    internal static JsonDocument ParseDocument(byte[] data, string emptyWhat)
    {
        if (IsBlank(data)) throw DataSourceError.EmptyInput(emptyWhat);
        JsonDocument doc;
        try
        {
            doc = JsonDocument.Parse(data);
        }
        catch (JsonException e)
        {
            throw DataSourceError.InvalidJson(e.Message);
        }
        return doc;
    }

    internal static bool IsBlank(byte[] data)
    {
        foreach (var b in data)
        {
            if (b is not (0x20 or 0x0A or 0x0D or 0x09)) return false;
        }
        return true;
    }

    private static UsageReport DecodeRoot(JsonElement root, string emptyWhat)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw DataSourceError.ContractMismatch("top level must be a JSON object", null);
        }
        int? version = root.TryGetProperty("schema_version", out var v) && v.ValueKind == JsonValueKind.Number
            ? (int)v.GetDouble()
            : null;
        try
        {
            return UsageReport.Decode(root);
        }
        catch (DecodeError e)
        {
            throw DataSourceError.ContractMismatch(e.Message, version);
        }
    }

    /// <summary>`kanjo paths --json` → agent → 路径列表。</summary>
    public static IReadOnlyDictionary<string, IReadOnlyList<string>> DecodePathsJson(byte[] data)
    {
        using var doc = ReportDecoder.ParseDocument(data, "Paths output");
        var root = doc.RootElement;
        var result = new Dictionary<string, IReadOnlyList<string>>(StringComparer.Ordinal);
        if (root.ValueKind != JsonValueKind.Object) return result;
        foreach (var (key, value) in J.Properties(root, string.Empty))
        {
            result[key] = J.List(value, key, (item, p) => J.ToString(item, p));
        }
        return result;
    }

    /// <summary>`kanjo config plans --json` → agent → 已知档位。</summary>
    public static IReadOnlyDictionary<string, IReadOnlyList<KnownPlan>> DecodeKnownPlans(byte[] data)
    {
        using var doc = ReportDecoder.ParseDocument(data, "Plans output");
        var root = doc.RootElement;
        var result = new Dictionary<string, IReadOnlyList<KnownPlan>>(StringComparer.Ordinal);
        if (root.ValueKind != JsonValueKind.Object) return result;
        foreach (var (key, value) in J.Properties(root, string.Empty))
        {
            result[key] = J.List(value, key, KnownPlan.Decode);
        }
        return result;
    }

    /// <summary>把字段级错误描述成 `<c>missing field projects[1].by_day</c>` 这样的文本。</summary>
    public static string Describe(Exception e) => e.Message;
}

/// <summary>`kanjo disk --json` / `disk clean` 的解码入口。</summary>
public static class DiskDecoder
{
    public static DiskReport Decode(byte[] data)
    {
        using var doc = ReportDecoder.ParseDocument(data, "Disk report");
        return DecodeElement<DiskReport>(doc.RootElement, DiskReport.Decode);
    }

    public static DiskReport Decode(string json) => Decode(System.Text.Encoding.UTF8.GetBytes(json));

    public static CleanResult DecodeClean(byte[] data)
    {
        using var doc = ReportDecoder.ParseDocument(data, "Clean result");
        return DecodeElement<CleanResult>(doc.RootElement, CleanResult.Decode);
    }

    public static CleanResult DecodeClean(string json) => DecodeClean(System.Text.Encoding.UTF8.GetBytes(json));

    private static T DecodeElement<T>(JsonElement root, Func<JsonElement, string, T> decode)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw DataSourceError.ContractMismatch("top level must be a JSON object", null);
        }
        int? version = root.TryGetProperty("schema_version", out var v) && v.ValueKind == JsonValueKind.Number
            ? (int)v.GetDouble()
            : null;
        try
        {
            return decode(root, string.Empty);
        }
        catch (DecodeError e)
        {
            throw DataSourceError.ContractMismatch(e.Message, version);
        }
    }
}
