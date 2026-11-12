namespace Kanjo.Core;

/// <summary>
/// 模型聚合工具：纯函数，负责聚合报告或项目中的模型用量。
/// - All 范围：直接从各项目的 by_model 汇总（精确值）；
/// - 非 All 范围：仅从范围内的会话（SessionsDetail，已按范围过滤）汇总。
/// </summary>
public static class ModelAggregation
{
    public static IReadOnlyList<ModelCost> Aggregate(FilteredReport report)
    {
        var map = new Dictionary<string, ModelCost>(StringComparer.Ordinal);

        if (report.Spec.IsAll)
        {
            foreach (var fp in report.Projects)
            {
                foreach (var m in fp.Project.ByModel)
                {
                    if (map.TryGetValue(m.Id, out var existing))
                    {
                        map[m.Id] = existing with
                        {
                            Cost = existing.Cost + m.Cost,
                            Tokens = existing.Tokens + m.Tokens,
                            Estimated = existing.Estimated || m.Estimated,
                        };
                    }
                    else
                    {
                        map[m.Id] = m;
                    }
                }
            }
        }
        else
        {
            void ProcessGroup(IReadOnlyList<Session> sessions, double targetCost, long targetTokens)
            {
                if (sessions.Count == 0) return;
                if (!(targetCost > 0) && targetTokens <= 0) return;

                var rawCosts = new List<double>(sessions.Count);
                var rawTokens = new List<double>(sessions.Count);
                foreach (var s in sessions)
                {
                    var (c, t) = report.Spec.InRangeCostAndTokens(s);
                    rawCosts.Add(c);
                    rawTokens.Add(t);
                }

                var sumRawCosts = rawCosts.Sum();
                List<double> sessionCosts;
                if (sumRawCosts > 0)
                {
                    sessionCosts = rawCosts.Select(c => targetCost * (c / sumRawCosts)).ToList();
                }
                else
                {
                    var eq = targetCost / sessions.Count;
                    sessionCosts = Enumerable.Repeat(eq, sessions.Count).ToList();
                }

                var sessionTokenTotals = Apportion(targetTokens, rawTokens);

                for (var idx = 0; idx < sessions.Count; idx++)
                {
                    var s = sessions[idx];
                    if (s.Models.Count == 0) continue;
                    var sCost = sessionCosts[idx];
                    var sTotalTokens = sessionTokenTotals[idx];
                    if (!(sCost > 0) && sTotalTokens <= 0) continue;

                    var origInp = (double)s.Tokens.Input;
                    var origOut = (double)s.Tokens.Output;
                    var origCr = (double)s.Tokens.CacheRead;
                    var origCw = (double)s.Tokens.CacheWrite;
                    var origSum = origInp + origOut + origCr + origCw;

                    var splitFields = origSum > 0
                        ? Apportion(sTotalTokens, [origInp, origOut, origCr, origCw])
                        : new List<long> { 0, 0, 0, 0 };

                    long scaledThinking = s.Tokens.Total > 0
                        ? (long)Math.Round(s.Tokens.Thinking * ((double)sTotalTokens / s.Tokens.Total), MidpointRounding.AwayFromZero)
                        : 0;

                    var sScaledTokens = new Tokens(
                        splitFields[0], splitFields[1], splitFields[2], splitFields[3],
                        scaledThinking, sTotalTokens);

                    var count = s.Models.Count;
                    if (count == 1)
                    {
                        var model = s.Models[0];
                        var key = $"{s.Agent}/{model}";
                        if (map.TryGetValue(key, out var existing))
                        {
                            map[key] = existing with
                            {
                                Cost = existing.Cost + sCost,
                                Tokens = existing.Tokens + sScaledTokens,
                            };
                        }
                        else
                        {
                            map[key] = new ModelCost(model, s.Agent, sCost, sScaledTokens, false);
                        }
                    }
                    else
                    {
                        var shareCost = sCost / count;
                        for (var i = 0; i < s.Models.Count; i++)
                        {
                            var model = s.Models[i];

                            long SplitField(long value)
                            {
                                var b = value / count;
                                var rem = value % count;
                                return i == 0 ? b + rem : b;
                            }

                            var splitInp = SplitField(sScaledTokens.Input);
                            var splitOut = SplitField(sScaledTokens.Output);
                            var splitCr = SplitField(sScaledTokens.CacheRead);
                            var splitCw = SplitField(sScaledTokens.CacheWrite);
                            var splitTh = SplitField(sScaledTokens.Thinking);
                            long splitTotal;
                            if (sScaledTokens.Input + sScaledTokens.Output + sScaledTokens.CacheRead + sScaledTokens.CacheWrite > 0)
                            {
                                splitTotal = splitInp + splitOut + splitCr + splitCw;
                            }
                            else
                            {
                                splitTotal = SplitField(sScaledTokens.Total);
                            }

                            var shareTokens = new Tokens(splitInp, splitOut, splitCr, splitCw, splitTh, splitTotal);
                            var key = $"{s.Agent}/{model}";
                            if (map.TryGetValue(key, out var existing))
                            {
                                map[key] = existing with
                                {
                                    Cost = existing.Cost + shareCost,
                                    Tokens = existing.Tokens + shareTokens,
                                    Estimated = true,
                                };
                            }
                            else
                            {
                                map[key] = new ModelCost(model, s.Agent, shareCost, shareTokens, true);
                            }
                        }
                    }
                }
            }

            foreach (var fp in report.Projects) ProcessGroup(fp.SessionsDetail, fp.Cost, fp.Tokens);
            ProcessGroup(report.Unattributed.SessionsDetail, report.Unattributed.Cost, report.Unattributed.Tokens);
            ProcessGroup(report.Excluded.SessionsDetail, report.Excluded.Cost, report.Excluded.Tokens);
        }

        // 按总 token 数降序排列；相等时按花费降序，再按模型名称升序。
        return map.Values
            .Where(m => m.Tokens.Total > 0 || m.Cost > 0)
            .OrderByDescending(m => m.Tokens.Total)
            .ThenByDescending(m => m.Cost)
            .ThenBy(m => m.Model, StringComparer.Ordinal)
            .ToList();
    }

    /// <summary>
    /// 最大余额法（Hamilton-Hare）按比例分配整数 token，保证分配后之和严格等于 total。
    /// </summary>
    public static List<long> Apportion(long total, IReadOnlyList<double> weights)
    {
        if (weights.Count == 0) return [];
        if (total <= 0) return Enumerable.Repeat(0L, weights.Count).ToList();

        var sumW = weights.Sum();
        List<double> normalized;
        if (sumW > 0)
        {
            normalized = weights.Select(w => w / sumW).ToList();
        }
        else
        {
            var eq = 1.0 / weights.Count;
            normalized = Enumerable.Repeat(eq, weights.Count).ToList();
        }

        var quotas = normalized.Select(w => total * w).ToList();
        var integers = quotas.Select(q => (long)Math.Floor(q)).ToList();
        var remainders = quotas.Select((q, index) => (Index: index, Remainder: q - integers[index])).ToList();
        var currentSum = integers.Sum();
        var leftover = total - currentSum;

        remainders.Sort((a, b) =>
        {
            if (Math.Abs(a.Remainder - b.Remainder) > 1e-9) return b.Remainder.CompareTo(a.Remainder);
            return a.Index.CompareTo(b.Index);
        });

        for (var i = 0; i < Math.Min(leftover, remainders.Count); i++)
        {
            integers[remainders[i].Index] += 1;
        }
        return integers;
    }
}
