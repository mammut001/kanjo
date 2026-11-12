namespace Kanjo.App;

/// <summary>
/// 面板窗口的「是活动窗口」状态。macOS 的 `.borderedProminent`（默认按钮）只有在窗口是 key window
/// 时才画强调色，非活动窗口里就是一个普通灰白按钮 —— Mac 的截图正是非活动状态，所以参考图里
/// 「Apply」「Apply &amp; Refresh」都是白底描边。这里复刻同一条规则：<see cref="PanelWindow"/>
/// 在激活 / 失活时改这里并重建页面，截图模式固定为非活动。
/// </summary>
public static class WindowActivation
{
    private static volatile bool _isActive;

    /// <summary>面板窗口当前是否是活动窗口（截图 / 无窗口时为 false，和 Mac 的非 key 窗口一致）。</summary>
    public static bool IsActive => _isActive;

    public static void SetActive(bool active) => _isActive = active;

    /// <summary>没有窗口时（截图 / 单元测试）也要能重置。</summary>
    public static void Reset() => _isActive = false;
}
