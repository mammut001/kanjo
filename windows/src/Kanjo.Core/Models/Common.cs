using System.Globalization;

namespace Kanjo.Core;

public static class Contract
{
    /// <summary>UI 能完整理解的最高 schema 版本。</summary>
    public const int SupportedSchemaVersion = 1;
}

public static class ReportDates
{
    /// <summary>
    /// ISO 8601 时间戳 → <see cref="DateTimeOffset"/>。
    /// 接受带时区的完整时间，包括 Mac ISO8601 回退支持的无冒号偏移
    /// <c>YYYY-MM-DDTHH:MM:SS[.fff…]Z</c> 或 <c>±HH:MM</c>。
    /// 纯日期、缺时区、空格分隔、没有冒号的偏移都拒绝。小数秒全部保留。
    /// </summary>
    public static DateTimeOffset? ParseTimestamp(string? s)
    {
        if (string.IsNullOrEmpty(s) || !HasMacTimestampShape(s)) return null;
        if (DateTimeOffset.TryParse(s, CultureInfo.InvariantCulture,
                DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out var dto))
        {
            return dto;
        }
        return null;
    }

    /// <summary>Mac <c>ReportDates.parseTimestamp</c> 接受的常见形状。不合形状的字符串直接拒绝，不再交给 TryParse。</summary>
    private static bool HasMacTimestampShape(string s)
    {
        if (s.Length < 20) return false;
        if (s[0] is < '0' or > '9' || s[1] is < '0' or > '9' || s[2] is < '0' or > '9' || s[3] is < '0' or > '9'
            || s[5] is < '0' or > '9' || s[6] is < '0' or > '9' || s[8] is < '0' or > '9' || s[9] is < '0' or > '9'
            || s[11] is < '0' or > '9' || s[12] is < '0' or > '9' || s[14] is < '0' or > '9' || s[15] is < '0' or > '9'
            || s[17] is < '0' or > '9' || s[18] is < '0' or > '9')
        {
            return false;
        }
        if (s[4] != '-' || s[7] != '-' || s[10] != 'T' || s[13] != ':' || s[16] != ':') return false;

        var pos = 19;
        if (s[pos] == '.')
        {
            pos++;
            var digits = 0;
            while (pos < s.Length && s[pos] is >= '0' and <= '9')
            {
                digits++;
                pos++;
            }
            if (digits == 0) return false;
        }
        if (pos >= s.Length) return false;
        if (s[pos] == 'Z') return pos + 1 == s.Length;
        if (s[pos] is not ('+' or '-')) return false;
        if (pos + 5 == s.Length)
        {
            return s[pos + 1] is >= '0' and <= '9'
                && s[pos + 2] is >= '0' and <= '9'
                && s[pos + 3] is >= '0' and <= '9'
                && s[pos + 4] is >= '0' and <= '9';
        }
        if (pos + 6 != s.Length || s[pos + 3] != ':') return false;
        return s[pos + 1] is >= '0' and <= '9'
            && s[pos + 2] is >= '0' and <= '9'
            && s[pos + 4] is >= '0' and <= '9'
            && s[pos + 5] is >= '0' and <= '9';
    }

    /// <summary>"YYYY-MM-DD"（契约里的本地日期）→ 本地零点。</summary>
    public static DateOnly? ParseDay(string? s)
    {
        if (string.IsNullOrEmpty(s)) return null;
        if (s.Length < 10) return null;
        return DateOnly.TryParseExact(s.AsSpan(0, 10), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var d)
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
    long Sessions,
    long? UniqueSessions,
    string? FirstActive,
    string? LastActive)
{
    public static Aggregate Decode(System.Text.Json.JsonElement e, string path) => new(
        J.Number(e, "cost", path),
        Tokens.Decode(J.RequiredObject(e, "tokens", path), J.Child(path, "tokens")),
        J.Long(e, "sessions", path),
        J.LongOrNull(e, "unique_sessions", path),
        J.StringOrNull(e, "first_active", path),
        J.StringOrNull(e, "last_active", path));
}

public sealed record SessionBucket(
    double Cost,
    Tokens Tokens,
    long Sessions,
    string? FirstActive,
    string? LastActive,
    RoList<Session> SessionsDetail)
{
    public static SessionBucket Decode(System.Text.Json.JsonElement e, string path) => new(
        J.Number(e, "cost", path),
        Tokens.Decode(J.RequiredObject(e, "tokens", path), J.Child(path, "tokens")),
        J.Long(e, "sessions", path),
        J.StringOrNull(e, "first_active", path),
        J.StringOrNull(e, "last_active", path),
        J.List(J.ArrayOrNull(e, "sessions_detail", path), J.Child(path, "sessions_detail"), Session.Decode));
}

public sealed record ParseFailedBucket(long Sessions, RoList<string> Files)
{
    public static ParseFailedBucket Decode(System.Text.Json.JsonElement e, string path) => new(
        J.Long(e, "sessions", path),
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
