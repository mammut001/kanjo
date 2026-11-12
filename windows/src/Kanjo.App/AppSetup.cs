using Avalonia;
using Avalonia.Headless;
using Avalonia.Styling;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>截图（headless）用的启动引导：装样式、定外观、指向隔离设置。</summary>
public static class AppSetup
{
    public static void ConfigureHeadless(string? appearance)
    {
        if (Application.Current is null)
        {
            AppBuilder.Configure<HeadlessApplication>()
                .UseSkia()
                .UseHeadless(new AvaloniaHeadlessPlatformOptions { UseHeadlessDrawing = false })
                .SetupWithoutStarting();
        }
        ApplyAppearance(appearance);
        L10n.Store ??= AppSettings.InMemory();
        L10n.ResetCache();
    }

    public static void ApplyAppearance(string? appearance)
    {
        if (Application.Current is not { } app) return;
        if (appearance is "dark")
        {
            app.RequestedThemeVariant = ThemeVariant.Dark;
            Palette.IsDark = true;
        }
        else if (appearance is "light")
        {
            app.RequestedThemeVariant = ThemeVariant.Light;
            Palette.IsDark = false;
        }
        else
        {
            Palette.IsDark = app.ActualThemeVariant == ThemeVariant.Dark;
        }
    }
}

/// <summary>不带托盘的 Application（headless 截图与单元级渲染共用）。</summary>
public sealed class HeadlessApplication : Application
{
    public override void Initialize()
    {
        Styles.Add(new Avalonia.Themes.Fluent.FluentTheme());
        RequestedThemeVariant = ThemeVariant.Default;
        Styles.Add(new Style(x => x.OfType<Avalonia.Controls.TextBlock>())
        {
            Setters =
            {
                new Setter(Avalonia.Controls.TextBlock.FontFamilyProperty, Type.Font),
            },
        });
    }
}
