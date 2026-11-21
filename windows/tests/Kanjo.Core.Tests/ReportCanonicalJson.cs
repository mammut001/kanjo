using System.Globalization;
using System.Text;
using System.Text.Json;

namespace Kanjo.Core.Tests;

/// <summary>解码结果的规范化 JSON，供测试比较（字段顺序与数值格式固定）。</summary>
internal static class ReportCanonicalJson
{
    public static string Serialize(UsageReport report)
    {
        var compact = SerializeCompact(report);
        using var doc = JsonDocument.Parse(compact);
        var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions
        {
            Indented = true,
            IndentCharacter = ' ',
            IndentSize = 2,
        }))
        {
            WriteSorted(writer, doc.RootElement);
        }
        return Encoding.UTF8.GetString(stream.ToArray());
    }

    private static string SerializeCompact(UsageReport report)
    {
        var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = false }))
        {
            WriteReport(writer, report);
        }
        return Encoding.UTF8.GetString(stream.ToArray());
    }

    private static void WriteSorted(Utf8JsonWriter w, JsonElement el)
    {
        switch (el.ValueKind)
        {
            case JsonValueKind.Object:
                w.WriteStartObject();
                foreach (var prop in el.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal))
                {
                    w.WritePropertyName(prop.Name);
                    WriteSorted(w, prop.Value);
                }
                w.WriteEndObject();
                break;
            case JsonValueKind.Array:
                w.WriteStartArray();
                foreach (var item in el.EnumerateArray()) WriteSorted(w, item);
                w.WriteEndArray();
                break;
            case JsonValueKind.String:
                w.WriteStringValue(el.GetString());
                break;
            case JsonValueKind.Number:
                w.WriteRawValue(el.GetRawText());
                break;
            case JsonValueKind.True:
                w.WriteBooleanValue(true);
                break;
            case JsonValueKind.False:
                w.WriteBooleanValue(false);
                break;
            case JsonValueKind.Null:
                w.WriteNullValue();
                break;
            default:
                throw new JsonException($"unexpected JSON value kind {el.ValueKind}");
        }
    }

    private static void WriteReport(Utf8JsonWriter w, UsageReport r)
    {
        w.WriteStartObject();
        WriteProp(w, "schema_version", r.SchemaVersion);
        WriteProp(w, "generated_at", r.GeneratedAt);
        WriteProp(w, "generated_by", r.GeneratedBy);
        WriteProp(w, "timezone", r.Timezone);
        WriteProp(w, "currency", r.Currency);
        WriteProp(w, "cost_note", r.CostNote);
        WriteConfig(w, r.Config);
        WriteQuotaWindows(w, r.QuotaWindows);
        WriteSubscriptions(w, r.Subscriptions);
        WriteAggregate(w, "totals", r.Totals);
        WriteProjects(w, r.Projects);
        WriteBuckets(w, r.Buckets);
        w.WriteEndObject();
    }

    private static void WriteConfig(Utf8JsonWriter w, ReportConfig c)
    {
        w.WritePropertyName("config");
        w.WriteStartObject();
        WriteProp(w, "dominant_threshold", c.DominantThreshold);
        if (c.NoNetwork is { } nn) WriteProp(w, "no_network", nn);
        if (c.Family is { } fam)
        {
            w.WritePropertyName("family");
            w.WriteStartObject();
            WriteProp(w, "since", fam.Since);
            if (fam.Agents is { } agents) WriteStringList(w, "agents", agents);
            w.WriteEndObject();
        }
        w.WriteEndObject();
    }

    private static void WriteQuotaWindows(Utf8JsonWriter w, RoDict<QuotaWindow>? q)
    {
        if (q is null) return;
        w.WritePropertyName("quota_windows");
        w.WriteStartObject();
        foreach (var (k, v) in q.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            w.WritePropertyName(k);
            WriteQuotaWindow(w, v);
        }
        w.WriteEndObject();
    }

    private static void WriteQuotaWindow(Utf8JsonWriter w, QuotaWindow q)
    {
        w.WriteStartObject();
        WriteProp(w, "weekly_resets_at", q.WeeklyResetsAt);
        WriteProp(w, "weekly_window_hours", q.WeeklyWindowHours);
        if (q.WeeklyUsedPercent is { } wu) WriteProp(w, "weekly_used_percent", wu);
        WriteProp(w, "five_hour_resets_at", q.FiveHourResetsAt);
        if (q.FiveHourWindowHours is { } fw) WriteProp(w, "five_hour_window_hours", fw);
        if (q.FiveHourUsedPercent is { } fu) WriteProp(w, "five_hour_used_percent", fu);
        WriteProp(w, "source", q.Source);
        if (q.ExtraWindows is { } extras && extras.Count > 0)
        {
            w.WritePropertyName("extra_windows");
            w.WriteStartArray();
            foreach (var e in extras) WriteExtraWindow(w, e);
            w.WriteEndArray();
        }
        w.WriteEndObject();
    }

    private static void WriteExtraWindow(Utf8JsonWriter w, ExtraQuotaWindow e)
    {
        w.WriteStartObject();
        WriteProp(w, "id", e.Id);
        WriteProp(w, "title", e.Title);
        if (e.UsedPercent is { } u) WriteProp(w, "used_percent", u);
        WriteProp(w, "resets_at", e.ResetsAt);
        if (e.WindowHours is { } h) WriteProp(w, "window_hours", h);
        w.WriteEndObject();
    }

    private static void WriteSubscriptions(Utf8JsonWriter w, RoDict<Subscription>? subs)
    {
        if (subs is null) return;
        w.WritePropertyName("subscriptions");
        w.WriteStartObject();
        foreach (var (k, s) in subs.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            w.WritePropertyName(k);
            WriteSubscription(w, s);
        }
        w.WriteEndObject();
    }

    private static void WriteSubscription(Utf8JsonWriter w, Subscription s)
    {
        w.WriteStartObject();
        WriteProp(w, "plan", s.Plan);
        WriteProp(w, "plan_label", s.PlanLabel);
        if (s.MonthlyPriceUsd is { } m) WriteProp(w, "monthly_price_usd", m);
        WriteProp(w, "cycle_start", s.CycleStart);
        WriteProp(w, "cycle_end", s.CycleEnd);
        if (s.AnchorDay is { } a) WriteProp(w, "anchor_day", a);
        WriteProp(w, "cycle_source", s.CycleSource);
        WriteProp(w, "extra_usage_enabled", s.ExtraUsageEnabled);
        WriteProp(w, "source", s.Source);
        if (s.Account is { } ac)
        {
            w.WritePropertyName("account");
            w.WriteStartObject();
            WriteProp(w, "email", ac.Email);
            WriteProp(w, "name", ac.Name);
            w.WriteEndObject();
        }
        w.WriteEndObject();
    }

    private static void WriteProjects(Utf8JsonWriter w, RoList<Project> projects)
    {
        w.WritePropertyName("projects");
        w.WriteStartArray();
        foreach (var p in projects) WriteProject(w, p);
        w.WriteEndArray();
    }

    private static void WriteProject(Utf8JsonWriter w, Project p)
    {
        w.WriteStartObject();
        WriteProp(w, "id", p.Id);
        WriteProp(w, "name", p.Name);
        WriteProp(w, "remote", p.Remote);
        WriteStringList(w, "paths", p.Paths);
        WriteProp(w, "path_missing", p.PathMissing);
        WriteProp(w, "cost", p.Cost);
        WriteTokens(w, "tokens", p.Tokens);
        WriteProp(w, "sessions", p.Sessions);
        WriteProp(w, "first_active", p.FirstActive);
        WriteProp(w, "last_active", p.LastActive);
        WriteAgentCosts(w, p.ByAgent);
        WriteModelCosts(w, p.ByModel);
        WriteDayCosts(w, "by_day", p.ByDay);
        WriteBranchCosts(w, p.ByBranch);
        WriteSessions(w, p.SessionsDetail);
        w.WriteEndObject();
    }

    private static void WriteAgentCosts(Utf8JsonWriter w, RoList<AgentCost> list)
    {
        w.WritePropertyName("by_agent");
        w.WriteStartArray();
        foreach (var a in list)
        {
            w.WriteStartObject();
            WriteProp(w, "agent", a.Agent);
            WriteProp(w, "label", a.Label);
            WriteProp(w, "cost", a.Cost);
            WriteTokens(w, "tokens", a.Tokens);
            WriteProp(w, "sessions", a.Sessions);
            w.WriteEndObject();
        }
        w.WriteEndArray();
    }

    private static void WriteModelCosts(Utf8JsonWriter w, RoList<ModelCost> list)
    {
        w.WritePropertyName("by_model");
        w.WriteStartArray();
        foreach (var m in list)
        {
            w.WriteStartObject();
            WriteProp(w, "model", m.Model);
            WriteProp(w, "agent", m.Agent);
            WriteProp(w, "cost", m.Cost);
            WriteTokens(w, "tokens", m.Tokens);
            WriteProp(w, "estimated", m.Estimated);
            w.WriteEndObject();
        }
        w.WriteEndArray();
    }

    private static void WriteDayCosts(Utf8JsonWriter w, string name, RoList<DayCost> list)
    {
        w.WritePropertyName(name);
        w.WriteStartArray();
        foreach (var d in list) WriteDayCost(w, d);
        w.WriteEndArray();
    }

    private static void WriteDayCost(Utf8JsonWriter w, DayCost d)
    {
        w.WriteStartObject();
        WriteProp(w, "day", d.Day);
        WriteProp(w, "cost", d.Cost);
        WriteProp(w, "tokens", d.Tokens);
        if (d.ByAgent is { } ba) WriteNumberDict(w, "by_agent", ba);
        if (d.ByAgentTokens is { } bt) WriteLongDict(w, "by_agent_tokens", bt);
        w.WriteEndObject();
    }

    private static void WriteBranchCosts(Utf8JsonWriter w, RoList<BranchCost> list)
    {
        if (list.Count == 0) return;
        w.WritePropertyName("by_branch");
        w.WriteStartArray();
        foreach (var b in list)
        {
            w.WriteStartObject();
            WriteProp(w, "branch", b.Branch);
            WriteProp(w, "cost", b.Cost);
            WriteProp(w, "sessions", b.Sessions);
            w.WriteEndObject();
        }
        w.WriteEndArray();
    }

    private static void WriteSessions(Utf8JsonWriter w, RoList<Session> list)
    {
        if (list.Count == 0) return;
        w.WritePropertyName("sessions_detail");
        w.WriteStartArray();
        foreach (var s in list) WriteSession(w, s);
        w.WriteEndArray();
    }

    private static void WriteSession(Utf8JsonWriter w, Session s)
    {
        w.WriteStartObject();
        WriteProp(w, "id", s.Id);
        WriteProp(w, "agent", s.Agent);
        WriteProp(w, "label", s.Label);
        WriteProp(w, "started", s.Started);
        WriteProp(w, "ended", s.Ended);
        WriteProp(w, "cwd", s.Cwd);
        WriteProp(w, "branch", s.Branch);
        WriteStringList(w, "models", s.Models);
        WriteProp(w, "cost", s.Cost);
        WriteTokens(w, "tokens", s.Tokens);
        WriteProp(w, "share", s.Share);
        WriteProp(w, "attribution", s.Attribution);
        WriteProp(w, "subagents", s.Subagents);
        WriteProp(w, "title", s.Title);
        if (s.ByDay is { } days && days.Count > 0) WriteDayCosts(w, "by_day", days);
        w.WriteEndObject();
    }

    private static void WriteBuckets(Utf8JsonWriter w, Buckets b)
    {
        w.WritePropertyName("buckets");
        w.WriteStartObject();
        WriteSessionBucket(w, "unattributed", b.Unattributed);
        WriteSessionBucket(w, "excluded", b.Excluded);
        w.WritePropertyName("parse_failed");
        w.WriteStartObject();
        WriteProp(w, "sessions", b.ParseFailed.Sessions);
        WriteStringList(w, "files", b.ParseFailed.Files);
        w.WriteEndObject();
        w.WriteEndObject();
    }

    private static void WriteSessionBucket(Utf8JsonWriter w, string name, SessionBucket b)
    {
        w.WritePropertyName(name);
        w.WriteStartObject();
        WriteProp(w, "cost", b.Cost);
        WriteTokens(w, "tokens", b.Tokens);
        WriteProp(w, "sessions", b.Sessions);
        WriteProp(w, "first_active", b.FirstActive);
        WriteProp(w, "last_active", b.LastActive);
        WriteSessions(w, b.SessionsDetail);
        w.WriteEndObject();
    }

    private static void WriteAggregate(Utf8JsonWriter w, string name, Aggregate a)
    {
        w.WritePropertyName(name);
        w.WriteStartObject();
        WriteProp(w, "cost", a.Cost);
        WriteTokens(w, "tokens", a.Tokens);
        WriteProp(w, "sessions", a.Sessions);
        if (a.UniqueSessions is { } u) WriteProp(w, "unique_sessions", u);
        WriteProp(w, "first_active", a.FirstActive);
        WriteProp(w, "last_active", a.LastActive);
        w.WriteEndObject();
    }

    private static void WriteTokens(Utf8JsonWriter w, string name, Tokens t)
    {
        w.WritePropertyName(name);
        w.WriteStartObject();
        WriteProp(w, "input", t.Input);
        WriteProp(w, "output", t.Output);
        WriteProp(w, "cache_read", t.CacheRead);
        WriteProp(w, "cache_write", t.CacheWrite);
        WriteProp(w, "thinking", t.Thinking);
        WriteProp(w, "total", t.Total);
        w.WriteEndObject();
    }

    private static void WriteStringList(Utf8JsonWriter w, string name, IReadOnlyList<string> list)
    {
        w.WritePropertyName(name);
        w.WriteStartArray();
        foreach (var s in list) w.WriteStringValue(s);
        w.WriteEndArray();
    }

    private static void WriteNumberDict(Utf8JsonWriter w, string name, IReadOnlyDictionary<string, double> dict)
    {
        w.WritePropertyName(name);
        w.WriteStartObject();
        foreach (var (k, v) in dict.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            WriteProp(w, k, v);
        }
        w.WriteEndObject();
    }

    private static void WriteLongDict(Utf8JsonWriter w, string name, IReadOnlyDictionary<string, long> dict)
    {
        w.WritePropertyName(name);
        w.WriteStartObject();
        foreach (var (k, v) in dict.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            w.WritePropertyName(k);
            w.WriteNumberValue(v);
        }
        w.WriteEndObject();
    }

    private static void WriteProp(Utf8JsonWriter w, string name, string? value)
    {
        w.WritePropertyName(name);
        if (value is null) w.WriteNullValue();
        else w.WriteStringValue(value);
    }

    private static void WriteProp(Utf8JsonWriter w, string name, int value)
    {
        w.WritePropertyName(name);
        w.WriteNumberValue(value);
    }

    private static void WriteProp(Utf8JsonWriter w, string name, long value)
    {
        w.WritePropertyName(name);
        w.WriteNumberValue(value);
    }

    private static void WriteProp(Utf8JsonWriter w, string name, double value)
    {
        w.WritePropertyName(name);
        w.WriteRawValue(value.ToString("R", CultureInfo.InvariantCulture));
    }

    private static void WriteProp(Utf8JsonWriter w, string name, bool value)
    {
        w.WritePropertyName(name);
        w.WriteBooleanValue(value);
    }
}