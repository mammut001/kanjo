using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Media.TextFormatting;
using Avalonia.Platform;
using Avalonia.Skia;
using Avalonia.Threading;
using Kanjo.App.Views;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>一张渲染好的分享图：PNG 字节，以及自上而下的 BGRA8888（给剪贴板的 CF_DIB）。</summary>
public sealed record ShareRender(byte[] Png, byte[] Bgra, int Width, int Height);

/// <summary>
/// 把 <see cref="ShareImageView"/> 画成 2 倍 PNG。
/// 卡片必须挂进一个窗口（TopLevel）再画，文字才会有字形；窗口放在屏幕外，避免挡住正在看的面板。
/// <c>--share-image</c> 走 headless，和 <see cref="SnapshotRunner"/> 一样。
/// </summary>
public static class ShareImageRunner
{
    public const double Scale = 2;

    /// <summary>在 UI 线程上调用。失败返回 null，不抛给界面。</summary>
    public static ShareRender? Render(ShareSummary summary)
    {
        Window? window = null;
        try
        {
            // 单测会话的绘图桩 Save 不写 PNG。命令行 --share-image 用的是 Skia，所以那边是好的。
            EnsurePaintable();

            var view = new ShareImageView(summary);
            window = new Window
            {
                SystemDecorations = SystemDecorations.None,
                ShowActivated = false,
                ShowInTaskbar = false,
                Background = Brushes.Transparent,
                Width = ShareImageView.CardWidth,
                Height = 800,
                Content = view,
                Position = new PixelPoint(-100000, -100000),
                WindowStartupLocation = WindowStartupLocation.Manual,
            };
            window.Show();
            Dispatcher.UIThread.RunJobs();

            view.Measure(new Size(ShareImageView.CardWidth, double.PositiveInfinity));
            var height = view.DesiredSize.Height;
            if (!double.IsFinite(height) || height < 40)
            {
                Trace.WriteLine($"kanjo: share image measured {height}");
                return null;
            }

            window.Width = ShareImageView.CardWidth;
            window.Height = height;
            view.Height = height;
            window.UpdateLayout();
            view.Measure(new Size(ShareImageView.CardWidth, height));
            view.Arrange(new Rect(0, 0, ShareImageView.CardWidth, height));
            window.UpdateLayout();
            Dispatcher.UIThread.RunJobs();

            var pixelW = (int)Math.Round(ShareImageView.CardWidth * Scale);
            var pixelH = (int)Math.Round(height * Scale);
            using var bitmap = new RenderTargetBitmap(new PixelSize(pixelW, pixelH), new Vector(96 * Scale, 96 * Scale));
            bitmap.Render(view);

            using var stream = new MemoryStream();
            bitmap.Save(stream);
            var png = stream.ToArray();
            if (png.Length < 32)
            {
                Trace.WriteLine($"kanjo: share image png {png.Length} bytes");
                return null;
            }

            var bgra = ReadBgra(bitmap, pixelW, pixelH);
            if (!bgra.Any(b => b != 0))
            {
                Trace.WriteLine("kanjo: share image blank");
                return null;
            }
            return new ShareRender(png, bgra, pixelW, pixelH);
        }
        catch (Exception e)
        {
            Trace.WriteLine($"kanjo: share render failed: {e}");
            return null;
        }
        finally
        {
            if (window is not null)
            {
                window.Content = null;
                window.Close();
            }
        }
    }

    /// <summary>
    /// <c>--share-image &lt;out.png&gt; --data &lt;json&gt; [--share-range &lt;raw&gt;]</c>。
    /// 语言用启动时已经选好的设置（和 <c>--snapshot</c> 同一个 <c>kanjo-preview</c>）。
    /// 「现在」钉在报告的 <c>generated_at</c>，这样同一份数据每次出的图一致。命令行不套隐藏项目。
    /// </summary>
    public static int Run(string outputPath, string[] args)
    {
        var dataPath = DefaultPaths.FlagValue("--data", args);
        if (string.IsNullOrEmpty(dataPath))
        {
            Console.Error.WriteLine("Error: --data <file> required");
            return 1;
        }

        UsageReport report;
        try
        {
            report = ReportDecoder.Decode(File.ReadAllBytes(dataPath));
        }
        catch (Exception e)
        {
            Trace.WriteLine($"kanjo: share data failed: {e.Message}");
            Console.Error.WriteLine("Error: Failed to load data");
            return 1;
        }

        var previousRoot = L10n.ResourcesRoot;
        try
        {
            AppSetup.ConfigureHeadless("dark");
            L10n.ResetCache();

            var range = DefaultPaths.FlagValue("--share-range", args);
            if (string.IsNullOrEmpty(range))
            {
                range = (L10n.Store as AppSettings)?.Str(SettingsKeys.TimeRange, SettingsDefaults.TimeRange)
                    ?? SettingsDefaults.TimeRange;
            }

            var now = ReportDates.ParseTimestamp(report.GeneratedAt) ?? DateTimeOffset.UtcNow;
            var summary = ShareSummary.Build(report, range, now);
            var image = Render(summary);
            if (image is null)
            {
                Console.Error.WriteLine("Error: Failed to render image");
                return 1;
            }

            var dir = Path.GetDirectoryName(Path.GetFullPath(outputPath));
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            File.WriteAllBytes(outputPath, image.Png);
            Console.WriteLine($"Rendered to {outputPath}");
            return 0;
        }
        catch (Exception e)
        {
            Trace.WriteLine($"kanjo: share image failed: {e.Message}");
            Console.Error.WriteLine("Error: Failed to render image");
            return 1;
        }
        finally
        {
            L10n.ResourcesRoot = previousRoot;
        }
    }

    /// <summary>
    /// Headless 单元测试默认 <c>UseHeadlessDrawing</c>：位图 Save 是空操作，字形也不是 Skia 的。
    /// 这种宿主里改换成 Skia，并换掉已经缓存的 FontManager / TextShaper，否则画文字会抛异常然后被吞掉。
    /// 正式界面和 <c>--share-image</c> 本来就能写出 PNG，探测成功就什么都不做。
    /// </summary>
    private static void EnsurePaintable()
    {
        if (ProbeEncodesPng()) return;

        Trace.WriteLine("kanjo: share render switching to skia");
        SkiaPlatform.Initialize();
        Rebind(new FontManager(Resolve<IFontManagerImpl>()));
        Rebind(new TextShaper(Resolve<ITextShaperImpl>()));
    }

    private static bool ProbeEncodesPng()
    {
        try
        {
            using var bitmap = new RenderTargetBitmap(new PixelSize(1, 1));
            using var stream = new MemoryStream();
            bitmap.Save(stream);
            return stream.Length >= 32;
        }
        catch (Exception e)
        {
            Trace.WriteLine($"kanjo: share render probe failed: {e.Message}");
            return false;
        }
    }

    private static T Resolve<T>() where T : class
    {
        var current = LocatorMember("Current");
        var get = current.GetType().GetMethod("GetService", new[] { typeof(System.Type) })
            ?? throw new MissingMethodException("GetService");
        return (T)(get.Invoke(current, new object[] { typeof(T) })
            ?? throw new InvalidOperationException($"Missing {typeof(T).FullName}"));
    }

    private static void Rebind<T>(T instance) where T : class
    {
        var mutable = LocatorMember("CurrentMutable");
        var bind = mutable.GetType().GetMethod("Bind") ?? throw new MissingMethodException("Bind");
        var helper = bind.MakeGenericMethod(typeof(T)).Invoke(mutable, null)
            ?? throw new InvalidOperationException("Bind");
        var toConstant = helper.GetType().GetMethod("ToConstant") ?? throw new MissingMethodException("ToConstant");
        toConstant.MakeGenericMethod(typeof(T)).Invoke(helper, new object[] { instance });
    }

    /// <summary>AvaloniaLocator 在引用程序集里是内部 API，运行时仍然在。</summary>
    private static object LocatorMember(string name)
    {
        var type = System.Type.GetType("Avalonia.AvaloniaLocator, Avalonia.Base")
            ?? throw new InvalidOperationException("AvaloniaLocator");
        return type.GetProperty(name, BindingFlags.Public | BindingFlags.Static)?.GetValue(null)
            ?? throw new InvalidOperationException(name);
    }

    /// <summary>自上而下的 BGRA8888。渲染目标读不出来时，把 PNG 再解码一次。</summary>
    private static byte[] ReadBgra(Bitmap bitmap, int width, int height)
    {
        var direct = TryCopy(bitmap, width, height);
        if (direct.Any(b => b != 0)) return direct;

        try
        {
            using var stream = new MemoryStream();
            bitmap.Save(stream);
            stream.Position = 0;
            using var decoded = WriteableBitmap.Decode(stream);
            if (decoded.PixelSize.Width != width || decoded.PixelSize.Height != height) return direct;
            var decodedPixels = TryCopy(decoded, width, height);
            return decodedPixels.Any(b => b != 0) ? decodedPixels : direct;
        }
        catch (Exception e)
        {
            Trace.WriteLine($"kanjo: share pixels failed: {e.Message}");
            return direct;
        }
    }

    private static byte[] TryCopy(Bitmap bitmap, int width, int height)
    {
        if (width <= 0 || height <= 0) return [];
        var stride = width * 4;
        var bgra = new byte[stride * height];
        var handle = GCHandle.Alloc(bgra, GCHandleType.Pinned);
        try
        {
            bitmap.CopyPixels(new PixelRect(0, 0, width, height), handle.AddrOfPinnedObject(), bgra.Length, stride);
            return bgra;
        }
        catch (Exception e)
        {
            Trace.WriteLine($"kanjo: share pixels failed: {e.Message}");
            return [];
        }
        finally
        {
            handle.Free();
        }
    }
}
