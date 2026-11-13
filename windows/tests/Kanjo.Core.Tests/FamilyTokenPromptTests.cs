using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 家庭上报令牌提示框（Settings → Family usage → 上报令牌 → 设置…）的回归测试。
///
/// 真机上用户报告的 bug：粘贴令牌后「保存」一直是灰的、点不动。原因是启用态在**建控件时**按
/// 当时的（空）文本算了一次：保存按钮是个静态的禁用外观，点击闭包捕获的 `trimmed` 也是空串。
/// 这里的用例走完整链路 —— 点「Set…」、往 TextBox 里写文本、点保存 —— 并断言令牌真的落进了
/// 存储（用 <see cref="InMemoryFamilyTokenStorage"/> 这个假实现，绝不碰真实凭据）。
/// </summary>
public sealed class FamilyTokenPromptTests : KanjoTestCase
{
    private static (AppServices Services, InMemoryFamilyTokenStorage Tokens) NewServices()
    {
        var settings = AppSettings.InMemory();
        settings.Set(SettingsKeys.AppLanguage, "en");
        // 家庭一节只有开关打开时才显示令牌行。
        settings.Set(SettingsKeys.FamilyReportEnabled, true);
        settings.Set(SettingsKeys.FamilyReportMode, "join");
        settings.Set(SettingsKeys.FamilyReportUrl, "https://usage.example.com");
        L10n.Store = settings;
        L10n.ResetCache();
        var tokens = new InMemoryFamilyTokenStorage();
        var services = new AppServices(settings, ["--snapshot", "--data", FixturePath], TempDir(),
            familyTokens: tokens);
        services.LoadQuietly();
        return (services, tokens);
    }

    private static Window Show(Control page, double height = Metrics.PanelHeight)
    {
        var window = new Window { Width = Metrics.PanelWidth, Height = height, Content = page };
        window.Show();
        LayOut(window);
        return window;
    }

    private static void LayOut(Window window)
    {
        window.UpdateLayout();
        Dispatcher.UIThread.RunJobs();
        if (window.Content is Control content) content.UpdateLayout();
        Dispatcher.UIThread.RunJobs();
    }

    /// <summary>按文字找按钮（启用的真 Button 和禁用的静态外观都算）。</summary>
    private static Control? FindButton(Visual root, string label) => root.GetVisualDescendants().OfType<Control>()
        .FirstOrDefault(c =>
            (c is ContentControl cc && Equals(cc.Content, label)) ||
            (c is Border { Child: TextBlock tb } && tb.Text == label));

    /// <summary>令牌提示框里的密码输入框（只有这一个 TextBox 带 PasswordChar）。</summary>
    private static TextBox FindTokenBox(Visual root) =>
        root.GetVisualDescendants().OfType<TextBox>().Single(t => t.PasswordChar != '\0');

    /// <summary>按占位说明找输入框（<see cref="Ui.TextField"/> 不设 Watermark，而是自己画一层提示文字）。</summary>
    private static TextBox FindFieldByPlaceholder(Visual root, string placeholder)
    {
        var hint = root.GetVisualDescendants().OfType<TextBlock>().First(t => t.Text == placeholder);
        return hint.GetVisualParent()!.GetVisualDescendants().OfType<TextBox>().First();
    }

    private static bool HasTokenBox(Visual root) =>
        root.GetVisualDescendants().OfType<TextBox>().Any(t => t.PasswordChar != '\0');

    private static void Click(Control button)
    {
        switch (button)
        {
            case Button real:
                real.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                break;
            case Border { Child: TextBlock }:
                // 禁用外观（StateButton 的禁用态）没有点击语义，点到就是错。
                Assert.Fail("button is disabled, so it cannot be clicked");
                break;
            default:
                Assert.Fail($"unexpected button control {button.GetType().Name}");
                break;
        }
    }

    private static bool IsEnabled(Control button) =>
        button is Button { IsEnabled: true } && button.IsEffectivelyEnabled;

    private static void SendKey(TextBox box, Key key) =>
        box.RaiseEvent(new KeyEventArgs
        {
            RoutedEvent = InputElement.KeyDownEvent,
            Key = key,
        });

    [Fact]
    public void TestSaveStaysDisabledUntilTokenIsTyped()
    {
        OnUi(() =>
        {
            var (services, tokens) = NewServices();
            var page = new SettingsPage(services, null, null, snapshot: false, onBack: () => { });
            var window = Show(page);

            Click(FindButton(page, L10n.Tr("settings.family.token.set"))!);
            LayOut(window);

            var box = FindTokenBox(page);
            Assert.Equal("", box.Text);

            var save = FindButton(page, L10n.Tr("settings.family.token.save"));
            Assert.NotNull(save);
            Assert.False(IsEnabled(save!), "Save must start disabled while the box is empty");

            box.Text = "family-token";
            LayOut(window);

            save = FindButton(page, L10n.Tr("settings.family.token.save"));
            Assert.True(IsEnabled(save!), "typing a token must enable Save");
            Assert.False(tokens.HasToken());

            // 只输入空白不算内容。
            box.Text = "   ";
            LayOut(window);
            save = FindButton(page, L10n.Tr("settings.family.token.save"));
            Assert.False(IsEnabled(save!), "whitespace alone must not enable Save");

            window.Close();
        });
    }

    [Fact]
    public void TestClickingSaveStoresTheTypedToken()
    {
        OnUi(() =>
        {
            var (services, tokens) = NewServices();
            var page = new SettingsPage(services, null, null, snapshot: false, onBack: () => { });
            var window = Show(page);

            Click(FindButton(page, L10n.Tr("settings.family.token.set"))!);
            LayOut(window);

            FindTokenBox(page).Text = "  pasted-token\n";
            LayOut(window);

            Click(FindButton(page, L10n.Tr("settings.family.token.save"))!);
            LayOut(window);

            // 落库的是去掉首尾空白后的令牌；提示框关闭、状态行变成「已配置」。
            Assert.Equal("pasted-token", tokens.LoadToken());
            Assert.True(services.Family.HasToken);
            Assert.False(HasTokenBox(page), "the prompt closes after a successful save");
            Assert.Contains(page.GetVisualDescendants().OfType<TextBlock>(),
                t => t.Text == L10n.Tr("settings.family.token.configured"));

            window.Close();
        });
    }

    [Fact]
    public void TestEnterSavesAndEscapeCancels()
    {
        OnUi(() =>
        {
            var (services, tokens) = NewServices();
            var page = new SettingsPage(services, null, null, snapshot: false, onBack: () => { });
            var window = Show(page);

            // Escape：关掉提示框，什么都不存。
            Click(FindButton(page, L10n.Tr("settings.family.token.set"))!);
            LayOut(window);
            var box = FindTokenBox(page);
            box.Text = "escaped-token";
            LayOut(window);
            SendKey(box, Key.Escape);
            LayOut(window);
            Assert.False(tokens.HasToken(), "Escape must not save");
            Assert.DoesNotContain(page.GetVisualDescendants().OfType<TextBox>(), t => t.PasswordChar != '\0');

            // Enter：等同于点保存。
            Click(FindButton(page, L10n.Tr("settings.family.token.set"))!);
            LayOut(window);
            box = FindTokenBox(page);
            box.Text = "entered-token";
            LayOut(window);
            SendKey(box, Key.Enter);
            LayOut(window);
            Assert.Equal("entered-token", tokens.LoadToken());
            Assert.DoesNotContain(page.GetVisualDescendants().OfType<TextBox>(), t => t.PasswordChar != '\0');

            // 空白时按 Enter 不应该关闭提示框。
            Click(FindButton(page, L10n.Tr("settings.family.token.change"))!);
            LayOut(window);
            box = FindTokenBox(page);
            box.Text = "   ";
            LayOut(window);
            SendKey(box, Key.Enter);
            LayOut(window);
            Assert.Equal("entered-token", tokens.LoadToken());
            Assert.True(HasTokenBox(page), "an empty token must leave the prompt open");

            window.Close();
        });
    }

    /// <summary>
    /// 同一类问题的另一处：「Report now」的启用态同时看令牌和服务器 URL，而 URL 输入框只在失焦时提交。
    /// 填完地址后按钮必须立刻亮起来，不用先点别处。
    /// </summary>
    [Fact]
    public void TestReportNowFollowsTheServerUrlField()
    {
        OnUi(() =>
        {
            var (services, tokens) = NewServices();
            tokens.SaveToken("token");
            services.Settings.Set(SettingsKeys.FamilyReportUrl, "");
            // 点「Report now」会真的发起上报：换成假运行器，测试不起进程。
            services.UseReportRunner(new FakeReportRunner());

            var page = new SettingsPage(services, null, null, snapshot: false, onBack: () => { });
            var window = Show(page);

            var urlBox = FindFieldByPlaceholder(page, "https://usage.example.com");
            Assert.Equal("", urlBox.Text);
            Assert.False(IsEnabled(FindButton(page, L10n.Tr("settings.family.now"))!),
                "Report now needs a valid URL");

            urlBox.Text = "https://usage.example.com";
            LayOut(window);
            Assert.True(IsEnabled(FindButton(page, L10n.Tr("settings.family.now"))!),
                "a valid URL must enable Report now");

            urlBox.Text = "not a url";
            LayOut(window);
            Assert.False(IsEnabled(FindButton(page, L10n.Tr("settings.family.now"))!));

            // 按钮按输入框里的地址亮起来，点下去就得报给这个地址（不用先失焦提交）。
            urlBox.Text = "https://family.example.com";
            LayOut(window);
            Click(FindButton(page, L10n.Tr("settings.family.now"))!);
            Assert.Equal("https://family.example.com",
                services.Settings.Str(SettingsKeys.FamilyReportUrl, ""));

            window.Close();
        });
    }

    /// <summary>切换启用态的按钮：禁用外观和 <see cref="Ui.DisabledButton"/> 完全一致，启用后是真 Button。</summary>
    [Fact]
    public void TestStateButtonSwitchesBetweenDisabledAndAccentLooks()
    {
        OnUi(() =>
        {
            var clicked = 0;
            var button = new StateButton("Save", () => clicked++, enabled: false);
            Assert.IsType<Border>(button.Child);

            button.SetEnabled(true);
            var real = Assert.IsType<Button>(button.Child);
            Assert.True(real.IsEnabled);
            Assert.Equal(Palette.AccentFillColor, ((Avalonia.Media.ISolidColorBrush)real.Background!).Color);
            real.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Assert.Equal(1, clicked);

            button.SetEnabled(false);
            Assert.IsType<Border>(button.Child);
            Assert.False(button.IsEnabled);
        });
    }
}
