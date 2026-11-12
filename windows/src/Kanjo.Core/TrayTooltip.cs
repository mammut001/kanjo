namespace Kanjo.Core;

/// <summary>托盘状态：正常 / 出错 / 正在加载。</summary>
public enum TrayStatus
{
    Normal,
    Error,
    Loading,
}

/// <summary>
/// 托盘 tooltip 与图标状态。Windows 托盘图标不能显示文字，所以 Mac 菜单栏上的金额改成 tooltip：
/// `Kanjo · $3,057 · 30d`。
/// </summary>
public static class TrayTooltip
{
    public const string AppName = "Kanjo";

    /// <summary>工具提示里的那一段文字；不想显示金额时返回 null（只剩图标）。</summary>
    public static string? AmountText(
        bool hasReport,
        bool hasError,
        bool showAmount,
        MenuBarMode mode,
        double cost,
        long tokens,
        string currency,
        TimeRange range)
    {
        if (!hasReport && hasError)
        {
            return showAmount ? (mode == MenuBarMode.Tokens ? "—" : "$—") : null;
        }
        if (!showAmount || !hasReport) return null;
        return MenuBarText.Make(mode, cost, tokens, currency, range);
    }

    /// <summary>完整 tooltip：`Kanjo` 或 `Kanjo · $3,057 · 30d`。</summary>
    public static string Build(
        bool hasReport,
        bool hasError,
        bool showAmount,
        MenuBarMode mode,
        double cost,
        long tokens,
        string currency,
        TimeRange range)
    {
        var text = AmountText(hasReport, hasError, showAmount, mode, cost, tokens, currency, range);
        return string.IsNullOrEmpty(text) ? AppName : $"{AppName} · {text}";
    }

    public static TrayStatus Status(bool hasReport, bool hasError) =>
        hasError ? TrayStatus.Error : hasReport ? TrayStatus.Normal : TrayStatus.Loading;
}
