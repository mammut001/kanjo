using System.Globalization;

namespace Kanjo.Core;

public static class Contract
{
    /// <summary>UI 能完整理解的最高 schema 版本。</summary>
    public const int SupportedSchemaVersion = 1;
}

public static class ReportDates
{
    /// <summary>ISO 8601 时间戳 → <see cref="DateTimeOffset"/>；带或不带小数秒都接受。</summary>
    public static DateTimeOffset? ParseTimestamp(string? s)
    {
        if (string.IsNullOrEmpty(s)) return null;
        if (DateTimeOffset.TryParse(s, CultureInfo.InvariantCulture,
                DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out var dto))
        {
            return dto;
        }
        return null;
    }

    /// <summary>"YYYY-MM-DD"（契约里的本地日期）→ 本地零点。</summary>
    public static DateOnly? ParseDay(string? s)
    {
        if (string.IsNullOrEmpty(s)) return null;
        if (s.Length < 10) return null;
        return DateOnly.TryParseExact(s[..10], "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var d)
            ? d
            : null;
    }
}

public readonly record struct Tokens(
    long Input,
    long Output,
    long CacheRead,
    long CacheWrite,
    long Thinking,
    long Total)
{
    public static readonly Tokens Zero = new(0, 0, 0, 0, 0, 0);

    public static Tokens WithTotal(long total) => new(0, 0, 0, 0, 0, total);

    public static Tokens operator +(Tokens a, Tokens b) => new(
        a.Input + b.Input, a.Output + b.Output, a.CacheRead + b.CacheRead,
        a.CacheWrite + b.CacheWrite, a.Thinking + b.Thinking, a.Total + b.Total);

    public static Tokens Decode(System.Text.Json.JsonElement e, string path)
    {
        var input = J.LongOrNull(e, "input", path) ?? 0;
        var output = J.LongOrNull(e, "output", path) ?? 0;
        var cacheRead = J.LongOrNull(e, "cache_read", path) ?? 0;
        var cacheWrite = J.LongOrNull(e, "cache_write", path) ?? 0;
        var thinking = J.LongOrNull(e, "thinking", path) ?? 0;
        var total = J.LongOrNull(e, "total", path) ?? 0;
        // 手机快照里的会话只有 {"total": N}；其余字段缺失时补 0，total 缺失时用四项之和。
        if (J.Optional(e, "total") is null)
        {
            total = input + output + cacheRead + cacheWrite;
        }
        return new Tokens(input, output, cacheRead, cacheWrite, thinking, total);
    }
}

public sealed record Aggregate(
    double Cost,
    Tokens Tokens,
    int Sessions,
    int? UniqueSessions,
    string? FirstActive,
    string? LastActive)
{
    public static Aggregate Decode(System.Text.Json.JsonElement e, string path) => new(
        J.Number(e, "cost", path),
        Tokens.Decode(J.RequiredObject(e, "tokens", path), J.Child(path, "tokens")),
        J.Int(e, "sessions", path),
        J.IntOrNull(e, "unique_sessions", path),
        J.StringOrNull(e, "first_active", path),
        J.StringOrNull(e, "last_active", path));
}

public sealed record SessionBucket(
    double Cost,
    Tokens Tokens,
    int Sessions,
    string? FirstActive,
    string? LastActive,
    RoList<Session> SessionsDetail)
{
    public static SessionBucket Decode(System.Text.Json.JsonElement e, string path) => new(
        J.Number(e, "cost", path),
        Tokens.Decode(J.RequiredObject(e, "tokens", path), J.Child(path, "tokens")),
        J.Int(e, "sessions", path),
        J.StringOrNull(e, "first_active", path),
        J.StringOrNull(e, "last_active", path),
        J.List(J.ArrayOrNull(e, "sessions_detail", path), J.Child(path, "sessions_detail"), Session.Decode));
}

public sealed record ParseFailedBucket(int Sessions, RoList<string> Files)
{
    public static ParseFailedBucket Decode(System.Text.Json.JsonElement e, string path) => new(
        J.Int(e, "sessions", path),
        J.List(J.ArrayOrNull(e, "files", path), J.Child(path, "files"),
            (item, p) => J.ToString(item, p)));
}

public sealed record Buckets(SessionBucket Unattributed, SessionBucket Excluded, ParseFailedBucket ParseFailed)
{
    public static Buckets Decode(System.Text.Json.JsonElement e, string path) => new(
        SessionBucket.Decode(J.RequiredObject(e, "unattributed", path), J.Child(path, "unattributed")),
        SessionBucket.Decode(J.RequiredObject(e, "excluded", path), J.Child(path, "excluded")),
        ParseFailedBucket.Decode(J.RequiredObject(e, "parse_failed", path), J.Child(path, "parse_failed")));
}
