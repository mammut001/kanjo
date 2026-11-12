using Avalonia;
using Avalonia.Animation;
using Avalonia.Animation.Easings;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Styling;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 页面切换 / 面板弹出的动效。
///
/// 规则：
/// - 页面切换 ≈150ms 淡入 + 8px 上滑（Fluent 的 PageSlide 节奏），只做一次、不改变布局尺寸，
///   所以不会有跳动；切换期间旧内容先被替换，动画只作用在新内容上。
/// - 面板从托盘弹出时淡入 + 12px 上滑（Windows 11 flyout 的手感）。
/// - 「减少动画」：系统关掉动画（<see cref="AnimationsEnabled"/> 为 false）或 `--snapshot` 时一律不动。
/// </summary>
public static class Motion
{
    /// <summary>
    /// 是否允许动画。截图模式（可复现）和系统「关闭动画」都为 false。
    /// Windows 上读 <c>UISettings.AnimationsEnabled</c>；其它平台 / headless 默认允许。
    /// </summary>
    public static bool AnimationsEnabled
    {
        get
        {
            if (Snapshot) return false;
            if (_override is { } forced) return forced;
            return PlatformAnimationsEnabled();
        }
    }

    private static bool? _override;

    /// <summary>测试 / 预览用：强制打开或关闭动画。</summary>
    public static void Override(bool? enabled) => _override = enabled;

    /// <summary>`--snapshot` 模式：动画一律关掉，截图才是确定的。</summary>
    public static bool Snapshot { get; set; }

    private static bool PlatformAnimationsEnabled()
    {
        // Windows 的「辅助功能 → 视觉效果 → 动画效果」会写进 UISettings.AnimationsEnabled。
        // Avalonia 11 没有把它暴露到 IPlatformSettings，所以直接读 WinRT 的 UISettings（best effort）。
        if (!OperatingSystem.IsWindows()) return true;
        try
        {
            var type = System.Type.GetType("Windows.UI.ViewManagement.UISettings, Microsoft.Windows.SDK.NET");
            if (type?.GetProperty("AnimationsEnabled")?.GetValue(
                    Activator.CreateInstance(type)) is bool value) return value;
        }
        catch (Exception)
        {
            // 拿不到就用系统默认（有动画）。
        }
        return true;
    }

    private const double TransitionMilliseconds = 150;

    /// <summary>把新内容装进宿主，并做一次「淡入 + 上滑」。不改变宿主的测量尺寸。</summary>
    public static void SwapContent(Border host, Control content)
    {
        host.Child = content;
        if (!AnimationsEnabled)
        {
            content.Opacity = 1;
            content.RenderTransform = null;
            return;
        }
        AnimateIn(content, Metrics.PageTransitionOffset, TransitionMilliseconds);
    }

    /// <summary>面板整体弹出（淡入 + 上滑）。</summary>
    public static void AnimatePanelIn(Control panel)
    {
        if (!AnimationsEnabled)
        {
            panel.Opacity = 1;
            panel.RenderTransform = null;
            return;
        }
        AnimateIn(panel, Metrics.PanelTransitionOffset, TransitionMilliseconds);
    }

    /// <summary>淡入 + 竖直位移（正数 = 从下方滑上来）。</summary>
    private static void AnimateIn(Control target, double offset, double milliseconds)
    {
        var transform = new TranslateTransform { Y = offset };
        target.RenderTransform = transform;

        var duration = TimeSpan.FromMilliseconds(milliseconds);
        var easing = new CubicEaseOut();

        target.Opacity = 0;
        target.Transitions = new Transitions
        {
            new DoubleTransition { Property = Visual.OpacityProperty, Duration = duration, Easing = easing },
            new DoubleTransition
            {
                Property = TranslateTransform.YProperty,
                Duration = duration,
                Easing = easing,
            },
        };
        // 下一帧再赋终值，过渡才会跑起来。
        Avalonia.Threading.Dispatcher.UIThread.Post(() =>
        {
            target.Opacity = 1;
            transform.Y = 0;
        }, Avalonia.Threading.DispatcherPriority.Render);
    }
}
