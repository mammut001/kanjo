using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 设置页（SettingsView.swift），按 Mac 的顺序：
/// Language / Data source / Refresh / iCloud sync（Windows 只留说明）/ Publish / Family usage /
/// Projects / Quota reset / Subscriptions / Apply & Refresh。
/// 所有写配置的动作都走 CLI（ConfigDataSource），文件 / 目录选择走 Avalonia StorageProvider。
/// </summary>
public sealed class SettingsPage : ScrollViewer, ISnapshotPage
{
    /// <summary>截图模式：交出内容本身（不含滚动容器），由面板按整页高度渲染。</summary>
    public Control SnapshotBody
    {
        get
        {
            var content = Content as Control ?? new Panel();
            Content = null;
            return content;
        }
    }

    private readonly AppServices _services;
    private readonly string? _anchor;
    private readonly string? _editingAgent;
    private readonly bool _snapshot;
    private readonly Action _onBack;

    private readonly StackPanel _root = Ui.V(Metrics.SectionSpacing);
    private bool _gitMissingError;
    private bool _tokenPromptOpen;
    private string _tokenInput = "";
    private bool _familyAdvanced;

    public SettingsPage(AppServices services, string? anchor, string? editingAgent, bool snapshot, Action onBack)
    {
        _services = services;
        _anchor = anchor;
        _editingAgent = editingAgent;
        _snapshot = snapshot;
        _onBack = onBack;

        HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled;
        VerticalScrollBarVisibility = snapshot
            ? Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled
            : Avalonia.Controls.Primitives.ScrollBarVisibility.Auto;
        Background = Brushes.Transparent;
        Content = _root;
        Rebuild();
        _services.Family.Activity.Changed += OnExternalChange;
        _services.Publish.Activity.Changed += OnExternalChange;
        DetachedFromVisualTree += (_, _) =>
        {
            _services.Family.Activity.Changed -= OnExternalChange;
            _services.Publish.Activity.Changed -= OnExternalChange;
        };

        if (snapshot)
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(() =>
            {
                UpdateLayout();
                if (anchor is null) return;
                if (anchor == RouteAnchors.SettingsBottom)
                {
                    Offset = new Vector(0, Math.Max(0, Extent.Height - Viewport.Height));
                }
                else if (SubscriptionSettingsRoute.Parse(anchor)?.Agent is { } agent &&
                         _subscriptionRows.TryGetValue(agent, out var row))
                {
                    // 滚到该 agent 的订阅行（布局完成后按实际位置算）。
                    UpdateLayout();
                    if (row.TranslatePoint(new Point(0, 0), _root) is { } p)
                    {
                        Offset = new Vector(0, Math.Max(0,
                            Math.Min(p.Y - 12, Extent.Height - Viewport.Height)));
                    }
                }
            }, Avalonia.Threading.DispatcherPriority.Loaded);
        }
    }

    private readonly Dictionary<string, Control> _subscriptionRows = new(StringComparer.Ordinal);

    private void OnExternalChange()
    {
        if (!Avalonia.Threading.Dispatcher.UIThread.CheckAccess())
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(Rebuild);
            return;
        }
        Rebuild();
    }

    private AppSettings S => _services.Settings;

    private void Set(string key, string value)
    {
        S.Set(key, value);
        _services.NotifyChanged();
    }

    private void Set(string key, bool value)
    {
        S.Set(key, value);
        _services.NotifyChanged();
    }

    private void Set(string key, int value)
    {
        S.Set(key, value);
        _services.NotifyChanged();
    }

    public void Rebuild()
    {
        _root.Children.Clear();
        _subscriptionRows.Clear();

        var header = Ui.V(8);
        var back = Widgets.BackButton(L10n.Tr("common.done"), _onBack);
        back.Margin = new Thickness(Metrics.BackInset - Metrics.RowInset, 0, 0, 0);
        header.Children.Add(back);
        header.Children.Add(Ui.Text(L10n.Tr("settings.title"), 15, FontWeight.SemiBold));
        header.Margin = new Thickness(Metrics.RowInset, 0, 0, 0);
        _root.Children.Add(header);

        if (_services.DataOverride is { } overridePath)
        {
            _root.Children.Add(Widgets.StatusBlock(false,
            [
                Ui.Text(L10n.TrL(null, "settings.data_override", overridePath), 10.5, FontWeight.Medium,
                    Palette.WarnInk, wrap: true),
            ]));
        }

        _root.Children.Add(LanguageSection());
        _root.Children.Add(DataSourceSection());
        _root.Children.Add(RefreshSection());
        _root.Children.Add(ICloudSection());
        _root.Children.Add(PublishSection());
        _root.Children.Add(FamilySection());
        _root.Children.Add(ProjectsSection());
        _root.Children.Add(QuotaSection());
        _root.Children.Add(SubscriptionsSection());
        _root.Children.Add(ApplySection());

        _root.Margin = new Thickness(Metrics.PagePadding, 12, Metrics.PagePadding, 10);
    }

    // MARK: - Language

    private Control LanguageSection()
    {
        var current = AppLanguages.Parse(S.Str(SettingsKeys.AppLanguage, SettingsDefaults.AppLanguage))
                      ?? AppLanguage.System;
        var options = AppLanguages.All.Select(l => l.DisplayName()).ToList();
        var dropdown = new DropdownControl(options[(int)current], options, index =>
        {
            Set(SettingsKeys.AppLanguage, AppLanguages.All[index].RawValue());
            Rebuild();
        });
        return Chrome.Section(L10n.Tr("settings.section.language"), Row(L10n.Tr("settings.language"), dropdown),
            padding: Metrics.RowInset);
    }

    private static Control Row(string label, Control control)
    {
        // Mac：标签固定宽度，picker 铺满剩下的整行宽度（不是右对齐的小控件）。
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
        var text = Ui.Text(label, 12);
        text.VerticalAlignment = VerticalAlignment.Center;
        text.Margin = new Thickness(0, 0, 8, 0);
        Grid.SetColumn(text, 0);
        grid.Children.Add(text);
        control.HorizontalAlignment = HorizontalAlignment.Stretch;
        Grid.SetColumn(control, 1);
        grid.Children.Add(control);
        return grid;
    }

    // MARK: - Data source

    private Control DataSourceSection()
    {
        var kind = SourceResolution.Resolve(S.GetString(SettingsKeys.SourceKind));
        var segmented = new SegmentedControl(
            SourceKinds.All.Select(k => k.Label()).ToList(),
            kind == SourceKind.File ? 0 : 1,
            index =>
            {
                Set(SettingsKeys.SourceKind, index == 0 ? "file" : "cli");
                // Mac：`onChange(of: sourceKind) { store.applySettings() }`（会重建数据源 / 监听 / 定时器）。
                _services.ApplySettings();
                Rebuild();
            })
        {
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };

        var content = Ui.V(8);
        content.Children.Add(segmented);

        if (kind == SourceKind.Cli)
        {
            content.Children.Add(Ui.Text(CliDescription(), 10.5, null, Palette.Secondary, wrap: true));
            content.Children.Add(Field(L10n.Tr("settings.command"), SettingsKeys.CliCommand,
                DefaultPaths.DefaultCliCommand, mono: true));

            var dirRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            var dirField = Field(L10n.Tr("settings.working_directory"), SettingsKeys.CliWorkingDirectory,
                DefaultPaths.ResolvedCliDirectory() ?? L10n.Tr("settings.inherit"), mono: true);
            Grid.SetColumn(dirField, 0);
            dirRow.Children.Add(dirField);
            var choose = Ui.BorderedButton(L10n.Tr("settings.choose"), ChooseDirectory);
            choose.Margin = new Thickness(6, 0, 0, 0);
            choose.VerticalAlignment = VerticalAlignment.Bottom;
            Grid.SetColumn(choose, 1);
            dirRow.Children.Add(choose);
            content.Children.Add(dirRow);

            content.Children.Add(Ui.Text(WindowsL10n.Tr("settings.cli_note"), 10.5, null, Palette.Secondary,
                wrap: true));
            var diskCommand = DiskCommand.Report(EffectiveCliCommand, false, null);
            var diskText = Ui.Text(L10n.TrL(null, "settings.disk_command", diskCommand), 10.5, null,
                Palette.Secondary, wrap: true, mono: true);
            ToolTip.SetTip(diskText, WindowsL10n.Tr("settings.disk_command_help"));
            content.Children.Add(diskText);
        }
        else
        {
            var fileRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            var fileField = Field(L10n.Tr("settings.json_file"), SettingsKeys.FilePath,
                DefaultPaths.SampleFixture);
            Grid.SetColumn(fileField, 0);
            fileRow.Children.Add(fileField);
            var choose = Ui.BorderedButton(L10n.Tr("settings.choose"), ChooseFile);
            choose.Margin = new Thickness(6, 0, 0, 0);
            choose.VerticalAlignment = VerticalAlignment.Bottom;
            Grid.SetColumn(choose, 1);
            fileRow.Children.Add(choose);
            content.Children.Add(fileRow);
            content.Children.Add(Ui.Text(L10n.Tr("settings.file_note"), 10.5, null, Palette.Secondary, wrap: true));
        }

        return Chrome.Section(L10n.Tr("settings.section.data_source"), content, padding: Metrics.RowInset);
    }

    private string EffectiveCliCommand
    {
        get
        {
            var command = S.Str(SettingsKeys.CliCommand, "").Trim();
            return command.Length == 0 ? DefaultPaths.DefaultCliCommand : command;
        }
    }

    /// <summary>
    /// 和 Mac 的 <c>DefaultPaths.cliDescription(customDirectory:customCommand:)</c> 一一对应：
    /// 自定义过就是「Custom」，否则按解析出来的 CLI 目录说「Bundled CLI &lt;version&gt;」/「Repository cli/」/ 实际路径。
    /// 版本从内置 CLI 目录里的 <c>VERSION</c> 读（打包脚本会把仓库的 VERSION 拷进 cli\，和 Mac 的 .app 一样）。
    /// </summary>
    private string CliDescription()
    {
        var command = S.Str(SettingsKeys.CliCommand, "");
        if (S.Str(SettingsKeys.CliWorkingDirectory, "").Trim().Length > 0 ||
            (command.Length > 0 && command != DefaultPaths.DefaultCliCommand))
        {
            return L10n.Tr("settings.cli_source.custom");
        }

        var resolved = DefaultPaths.ResolvedCliDirectory();
        if (resolved is null) return L10n.Tr("settings.cli_source.unavailable");

        if (DefaultPaths.BundledCliDirectory is { } bundled && AppPaths.SameDirectory(resolved, bundled))
        {
            return L10n.TrL(null, "settings.cli_source.bundled", BundledCliVersion(bundled));
        }
        if (DefaultPaths.RepoCliDirectory is { } repo && AppPaths.SameDirectory(resolved, repo))
        {
            return L10n.Tr("settings.cli_source.repo");
        }
        return resolved;
    }

    /// <summary>内置 CLI 的版本：读 cli\VERSION（和 Mac 的 .app 一样）；读不到就说 unknown。</summary>
    private static string BundledCliVersion(string cliDirectory)
    {
        try
        {
            var file = Path.Combine(cliDirectory, "VERSION");
            if (File.Exists(file))
            {
                var text = File.ReadAllText(file).Trim();
                if (text.Length > 0) return text;
            }
        }
        catch (Exception)
        {
            // 读不到就用 unknown。
        }
        // 兜底：CLI 的 __init__.py 里也有 __version__（VERSION 文件漏拷时还能显示对）。
        try
        {
            var init = Path.Combine(cliDirectory, "kanjo", "__init__.py");
            if (File.Exists(init))
            {
                var match = System.Text.RegularExpressions.Regex.Match(
                    File.ReadAllText(init), "__version__\\s*=\\s*\"([^\"]+)\"");
                if (match.Success) return match.Groups[1].Value;
            }
        }
        catch (Exception)
        {
            // 同上。
        }
        return "unknown";
    }

    /// <summary>带标签的文本框（label 在上，输入框在下；回车应用并刷新）。Mac 这几个框都用等宽字体。</summary>
    private Control Field(string label, string key, string? placeholder, bool mono = true)
    {
        var box = Ui.V(3);
        box.Children.Add(Ui.Text(label, 10.5, null, Palette.Secondary));
        var field = Ui.TextField(S.Str(key, ""), placeholder, mono: mono);
        var text = field.Box;
        text.LostFocus += (_, _) => S.Set(key, text.Text ?? "");
        text.KeyDown += (_, e) =>
        {
            if (e.Key is Avalonia.Input.Key.Enter or Avalonia.Input.Key.Return)
            {
                S.Set(key, text.Text ?? "");
                _services.ApplySettings();
            }
        };
        box.Children.Add(field.Root);
        return box;
    }

    private async void ChooseFile()
    {
        try
        {
            if (TopLevel.GetTopLevel(this) is not { } top) return;
            var files = await top.StorageProvider.OpenFilePickerAsync(new Avalonia.Platform.Storage.FilePickerOpenOptions
            {
                Title = L10n.Tr("settings.json_file"),
                AllowMultiple = false,
                FileTypeFilter =
                [
                    new Avalonia.Platform.Storage.FilePickerFileType("JSON")
                    {
                        Patterns = ["*.json", "*.JSON"],
                    },
                ],
            });
            if (files.Count > 0) Set(SettingsKeys.FilePath, files[0].Path.LocalPath);
        }
        catch (Exception)
        {
            // 没有 StorageProvider（headless）时忽略。
        }
    }

    private async void ChooseDirectory()
    {
        try
        {
            if (TopLevel.GetTopLevel(this) is not { } top) return;
            var folders = await top.StorageProvider.OpenFolderPickerAsync(
                new Avalonia.Platform.Storage.FolderPickerOpenOptions
                {
                    Title = L10n.Tr("settings.working_directory"),
                    AllowMultiple = false,
                });
            if (folders.Count > 0) Set(SettingsKeys.CliWorkingDirectory, folders[0].Path.LocalPath);
        }
        catch (Exception)
        {
            // 同上。
        }
    }

    // MARK: - Refresh

    private Control RefreshSection()
    {
        var content = Ui.V(8);
        var minutes = S.Int(SettingsKeys.RefreshMinutes, SettingsDefaults.RefreshMinutes);
        var intervals = new[] { 0, 15, 30, 60 };
        var labels = intervals
            .Select(m => m == 0 ? L10n.Tr("settings.refresh_off") : L10n.TrL(null, "settings.refresh_minutes", m))
            .ToList();
        var index = Math.Max(0, Array.IndexOf(intervals, minutes));
        content.Children.Add(Row(L10n.Tr("settings.auto_refresh"),
            new DropdownControl(labels[index], labels, i =>
            {
                Set(SettingsKeys.RefreshMinutes, intervals[i]);
                // Mac：`onChange(of: refreshMinutes) { store.restartTimer() }` —— 改了就重排兜底定时器。
                _services.RestartFallbackTimer();
                Rebuild();
            })));
        content.Children.Add(Ui.Text(L10n.Tr("settings.refresh_note"), 10.5, null, Palette.Secondary, wrap: true));

        var mode = MenuBarModes.Parse(S.Str(SettingsKeys.MenuBarMode, SettingsDefaults.MenuBarMode))
                   ?? MenuBarMode.Cost;
        var modeOptions = MenuBarModes.All.Select(m => m.Label()).ToList();
        content.Children.Add(Row(L10n.Tr("settings.menu_bar_shows"),
            new DropdownControl(modeOptions[(int)mode], modeOptions, i =>
            {
                Set(SettingsKeys.MenuBarMode, MenuBarModes.All[i].RawValue());
                Rebuild();
            })));

        content.Children.Add(CheckRow(L10n.Tr("settings.show_menu_bar_cost"),
            S.Bool(SettingsKeys.ShowAmountInMenuBar, SettingsDefaults.ShowAmountInMenuBar),
            value => Set(SettingsKeys.ShowAmountInMenuBar, value)));
        return Chrome.Section(L10n.Tr("settings.section.refresh"), content, padding: Metrics.RowInset);
    }

    private Control CheckRow(string label, bool value, Action<bool> onChange)
    {
        var row = Ui.H(7);
        row.Children.Add(new CheckBoxControl(value, false, () => onChange(!value)));
        row.Children.Add(Ui.Text(label, 12));
        return new Clickable(row, () => onChange(!value), radius: 4)
        {
            HorizontalAlignment = HorizontalAlignment.Left,
            Padding = new Thickness(0),
        };
    }

    // MARK: - iCloud（Mac 专属）

    private Control ICloudSection()
    {
        var content = Ui.V(6);
        content.Children.Add(Ui.Text(WindowsL10n.Tr("settings.icloud.windows_only"), 10.5, null,
            Palette.Secondary, wrap: true));
        return Chrome.Section(L10n.Tr("settings.section.icloud"), content, padding: Metrics.RowInset);
    }

    // MARK: - Publish

    private Control PublishSection()
    {
        var enabled = S.Bool(SettingsKeys.PublishEnabled, SettingsDefaults.PublishEnabled);
        var content = Ui.V(8);
        content.Children.Add(CheckRow(L10n.Tr("settings.publish.enable"), enabled,
            value => Set(SettingsKeys.PublishEnabled, value)));

        if (enabled)
        {
            var frequency = PublishFrequencies.Parse(S.GetString(SettingsKeys.PublishFrequency))
                            ?? PublishFrequency.Weekly;
            var freqOptions = PublishFrequencies.All.Select(f => f.Label()).ToList();
            content.Children.Add(Row(L10n.Tr("settings.publish.frequency"),
                new DropdownControl(freqOptions[PublishFrequencies.All.ToList().IndexOf(frequency)], freqOptions, i =>
                {
                    Set(SettingsKeys.PublishFrequency, PublishFrequencies.All[i].RawValue());
                    Rebuild();
                })));

            var repo = S.Str(SettingsKeys.PublishRepoPath, SettingsDefaults.PublishRepoPath);
            var repoRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            var repoText = Ui.Text(repo.Length == 0 ? "—" : repo, 11, null,
                repo.Length == 0 ? Palette.Secondary : Palette.Foreground, maxLines: 1);
            repoText.TextTrimming = TextTrimming.CharacterEllipsis;
            Grid.SetColumn(repoText, 0);
            repoRow.Children.Add(repoText);
            var choose = Ui.BorderedButton(L10n.Tr("settings.publish.choose_repo"), ChooseRepo);
            choose.Margin = new Thickness(8, 0, 0, 0);
            Grid.SetColumn(choose, 1);
            repoRow.Children.Add(choose);
            var repoBlock = Ui.V(4);
            repoBlock.Children.Add(Ui.Text(L10n.Tr("settings.publish.repo_path"), 11, null, Palette.Secondary));
            repoBlock.Children.Add(repoRow);
            if (_gitMissingError)
            {
                repoBlock.Children.Add(Ui.Text(L10n.Tr("settings.publish.git_missing"), 10.5, null, Palette.Bad,
                    wrap: true));
            }
            content.Children.Add(repoBlock);

            content.Children.Add(LabeledField(L10n.Tr("settings.publish.file_path"),
                SettingsKeys.PublishFilePath, SettingsDefaults.PublishFilePath));
            content.Children.Add(LabeledField(L10n.Tr("settings.publish.branch"),
                SettingsKeys.PublishBranch, SettingsDefaults.PublishBranch));

            var (statusText, statusError, statusWarn) = _services.Publish.StatusText();
            var statusRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            var status = Ui.Text(statusText, 10.5, null,
                statusError ? Palette.Bad : statusWarn ? Palette.QuotaWarn : Palette.Secondary, wrap: true);
            Grid.SetColumn(status, 0);
            statusRow.Children.Add(status);
            var repoTrim = repo.Trim();
            var publishNow = Ui.BorderedButton(L10n.Tr("settings.publish.now"), () =>
            {
                Task.Run(() =>
                {
                    try
                    {
                        _services.Publish.PublishNow();
                    }
                    catch (Exception)
                    {
                        // 状态已经记下来了。
                    }
                    _services.NotifyChanged();
                });
            }, enabled: repoTrim.Length > 0 && !_services.Publish.Activity.IsBusy);
            Grid.SetColumn(publishNow, 1);
            statusRow.Children.Add(publishNow);
            content.Children.Add(statusRow);
        }

        content.Children.Add(Ui.Text(L10n.Tr("settings.publish.note"), 10.5, null, Palette.Secondary, wrap: true));
        return Chrome.Section(L10n.Tr("settings.section.publish"), content, padding: Metrics.RowInset);
    }

    private Control LabeledField(string label, string key, string placeholder)
    {
        var box = Ui.V(4);
        box.Children.Add(Ui.Text(label, 11, null, Palette.Secondary));
        var field = Ui.TextField(S.Str(key, ""), placeholder);
        var text = field.Box;
        text.LostFocus += (_, _) => S.Set(key, text.Text ?? "");
        box.Children.Add(field.Root);
        return box;
    }

    private async void ChooseRepo()
    {
        try
        {
            if (TopLevel.GetTopLevel(this) is not { } top) return;
            var folders = await top.StorageProvider.OpenFolderPickerAsync(
                new Avalonia.Platform.Storage.FolderPickerOpenOptions
                {
                    Title = L10n.Tr("settings.publish.repo_path"),
                    AllowMultiple = false,
                });
            if (folders.Count == 0) return;
            var path = folders[0].Path.LocalPath;
            if (Directory.Exists(Path.Combine(path, ".git")))
            {
                S.Set(SettingsKeys.PublishRepoPath, path);
            }
            else
            {
                _gitMissingError = true;
            }
            Rebuild();
        }
        catch (Exception)
        {
            // 没有 StorageProvider 时忽略。
        }
    }

    // MARK: - Family

    private Control FamilySection()
    {
        var enabled = S.Bool(SettingsKeys.FamilyReportEnabled, SettingsDefaults.FamilyReportEnabled);
        var content = Ui.V(8);
        content.Children.Add(CheckRow(L10n.Tr("settings.family.enable"), enabled,
            value => Set(SettingsKeys.FamilyReportEnabled, value)));

        if (enabled)
        {
            var mode = S.Str(SettingsKeys.FamilyReportMode, SettingsDefaults.FamilyReportMode);
            var modes = new List<string> { L10n.Tr("settings.family.mode.join"), L10n.Tr("settings.family.mode.manager") };
            content.Children.Add(new SegmentedControl(modes, mode == "manager" ? 1 : 0, index =>
            {
                Set(SettingsKeys.FamilyReportMode, index == 1 ? "manager" : "join");
                Rebuild();
            })
            {
                HorizontalAlignment = HorizontalAlignment.Stretch,
            });

            if (mode == "manager")
            {
                var manager = Ui.V(8);
                manager.Children.Add(Ui.Text(WindowsL10n.Tr("settings.family.manager.desc"), 11, null,
                    Palette.Secondary, wrap: true));
                manager.Children.Add(Ui.BorderedButton(L10n.Tr("settings.family.manager.view_guide"),
                    () => ProjectActions.OpenUrl("https://github.com/mammut001/kanjo/blob/main/family-server/DEPLOY.md")));
                manager.Margin = new Thickness(0, 4, 0, 4);
                content.Children.Add(manager);
            }
            else
            {
                content.Children.Add(LabeledField(L10n.Tr("settings.family.url"), SettingsKeys.FamilyReportUrl,
                    "https://usage.example.com"));
                content.Children.Add(TokenRow());
                content.Children.Add(LabeledField(L10n.Tr("settings.family.member_label"),
                    SettingsKeys.FamilyReportMemberLabel, L10n.Tr("settings.family.member_label_placeholder")));
                content.Children.Add(ScopeSection());
                content.Children.Add(FamilyStatusRow());
            }

            content.Children.Add(Ui.Text(L10n.Tr("settings.family.note"), 10.5, null, Palette.Secondary, wrap: true));
        }
        else
        {
            content.Children.Add(Ui.Text(L10n.Tr("settings.family.off_note"), 10.5, null, Palette.Secondary,
                wrap: true));
        }
        return Chrome.Section(L10n.Tr("settings.section.family"), content, padding: Metrics.RowInset);
    }

    private Control TokenRow()
    {
        var block = Ui.V(4);
        block.Children.Add(Ui.Text(L10n.Tr("settings.family.token"), 11, null, Palette.Secondary));
        var row = Ui.H(8);
        var hasToken = _services.Family.HasToken;
        row.Children.Add(Ui.Text(hasToken
            ? L10n.Tr("settings.family.token.configured")
            : L10n.Tr("settings.family.token.not_configured"), 11, null,
            hasToken ? Palette.Foreground : Palette.Secondary));
        if (hasToken)
        {
            row.Children.Add(Ui.BorderedButton(L10n.Tr("settings.family.token.change"), () =>
            {
                _tokenInput = "";
                _tokenPromptOpen = true;
                Rebuild();
            }));
            row.Children.Add(Ui.BorderedButton(L10n.Tr("settings.family.token.clear"), () =>
            {
                _services.Family.ClearToken();
                Rebuild();
            }));
        }
        else
        {
            row.Children.Add(Ui.BorderedButton(L10n.Tr("settings.family.token.set"), () =>
            {
                _tokenInput = "";
                _tokenPromptOpen = true;
                Rebuild();
            }));
        }
        block.Children.Add(row);

        if (_tokenPromptOpen)
        {
            var prompt = Ui.V(8);
            prompt.Children.Add(Ui.Text(L10n.Tr("settings.family.token.prompt_title"), 12, FontWeight.SemiBold));
            prompt.Children.Add(Ui.Text(WindowsL10n.Tr("settings.family.token.prompt_message"), 10.5, null,
                Palette.Secondary, wrap: true));
            var input = new TextBox
            {
                Text = _tokenInput,
                Watermark = L10n.Tr("settings.family.token.placeholder"),
                PasswordChar = '•',
                FontSize = 11,
                MinHeight = 24,
                Padding = new Thickness(6, 2, 6, 2),
                CornerRadius = new CornerRadius(6),
                Background = Palette.CardBackground,
                BorderBrush = Palette.CardBorder,
                BorderThickness = new Thickness(0.5),
            };
            input.TextChanged += (_, _) => _tokenInput = input.Text ?? "";
            prompt.Children.Add(input);
            var actions = Ui.H(8);
            var spacer = new Panel { HorizontalAlignment = HorizontalAlignment.Stretch };
            actions.Children.Add(spacer);
            actions.Children.Add(Ui.BorderedButton(L10n.Tr("settings.family.token.cancel"), () =>
            {
                _tokenInput = "";
                _tokenPromptOpen = false;
                Rebuild();
            }));
            var trimmed = _tokenInput.Trim();
            actions.Children.Add(Ui.BorderedButton(L10n.Tr("settings.family.token.save"), () =>
            {
                if (trimmed.Length > 0) _services.Family.SetToken(trimmed);
                _tokenInput = "";
                _tokenPromptOpen = false;
                Rebuild();
            }, enabled: trimmed.Length > 0));
            prompt.Children.Add(actions);
            var card = Chrome.HoverCardChrome(prompt);
            card.Margin = new Thickness(0, 4, 0, 0);
            block.Children.Add(card);
        }
        return block;
    }

    private Control ScopeSection()
    {
        var config = _services.Report?.Config.Family;
        var block = Ui.V(6);
        block.Children.Add(Ui.Text(L10n.TrL(null, "settings.family.scope.label",
            FamilyScopeText.Make(config)), 11, null, Palette.Secondary, wrap: true));

        var agents = config?.Agents?.ToList() ?? ["antigravity"];
        var isAll = agents.Count > 0 && (agents[0] == "all" || agents.Contains("all"));
        var options = new List<string>
        {
            L10n.Tr("settings.family.scope.agents_antigravity"),
            L10n.Tr("settings.family.scope.agents_all"),
        };
        var agentsRow = Row(L10n.Tr("settings.family.scope.agents_choice"),
            new DropdownControl(options[isAll ? 1 : 0], options, index =>
            {
                RunConfig(() =>
                {
                    if (index == 1) _services.Config.SetFamilyAgents("all");
                    else _services.Config.SetFamilyAgents(null);
                });
            }, enabled: _services.CanEditSubscriptions));
        if (!_services.CanEditSubscriptions) agentsRow.Opacity = 0.6;
        block.Children.Add(agentsRow);

        var advanced = Ui.V(6);
        var header = Ui.H(3);
        header.Children.Add(Icons.Chevron(_familyAdvanced, 8, Palette.Secondary));
        header.Children.Add(Ui.Text(L10n.Tr("settings.family.scope.advanced"), 11));
        block.Children.Add(new Clickable(header, () =>
        {
            _familyAdvanced = !_familyAdvanced;
            Rebuild();
        }, radius: 4)
        {
            HorizontalAlignment = HorizontalAlignment.Left,
        });

        if (_familyAdvanced)
        {
            var dateRow = Ui.H(8);
            var since = config?.Since;
            var dateBox = new TextBox
            {
                Text = since is { Length: >= 10 } ? since[..10] : "",
                Watermark = "yyyy-MM-dd",
                FontSize = 11,
                MinHeight = 24,
                Width = 110,
                Padding = new Thickness(6, 2, 6, 2),
                FontFamily = Type.Mono,
                CornerRadius = new CornerRadius(6),
                Background = Palette.CardBackground,
                BorderBrush = Palette.CardBorder,
                BorderThickness = new Thickness(0.5),
                IsEnabled = _services.CanEditSubscriptions,
            };
            dateBox.LostFocus += (_, _) =>
            {
                var value = (dateBox.Text ?? "").Trim();
                if (value == (since is { Length: >= 10 } ? since[..10] : "")) return;
                RunConfig(() => _services.Config.SetFamilySince(value.Length == 0 ? null : value));
            };
            dateRow.Children.Add(dateBox);
            if (!string.IsNullOrEmpty(since))
            {
                dateRow.Children.Add(Ui.BorderedButton(L10n.Tr("settings.family.scope.clear_date"),
                    () => RunConfig(() => _services.Config.SetFamilySince(null)),
                    enabled: _services.CanEditSubscriptions));
            }
            var dateBlock = Ui.V(4);
            dateBlock.Children.Add(Ui.Text(L10n.Tr("settings.family.scope.start_date"), 11, null,
                Palette.Secondary));
            dateBlock.Children.Add(dateRow);
            dateBlock.Margin = new Thickness(0, 4, 0, 0);
            advanced.Children.Add(dateBlock);
            advanced.Children.Add(Ui.Text(L10n.Tr("settings.family.scope.advanced_note"), 10.5, null,
                Palette.Secondary, wrap: true));
            block.Children.Add(advanced);
        }
        return block;
    }

    private Control FamilyStatusRow()
    {
        var (text, kind) = _services.Family.StatusText();
        var color = kind switch
        {
            FamilyReportStatusStateKind.NoNetwork => Palette.QuotaWarn,
            FamilyReportStatusStateKind.Failed => Palette.Bad,
            _ => Palette.Secondary,
        };
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        var status = Ui.Text(text, 10.5, null, color, wrap: true);
        Grid.SetColumn(status, 0);
        row.Children.Add(status);
        var reportNow = Ui.BorderedButton(L10n.Tr("settings.family.now"), () =>
        {
            Task.Run(() =>
            {
                try
                {
                    _services.Family.ReportNow();
                }
                catch (Exception)
                {
                    // 状态已经记下来了。
                }
                _services.NotifyChanged();
            });
        }, enabled: _services.Family.CanReportNow);
        Grid.SetColumn(reportNow, 1);
        row.Children.Add(reportNow);
        return row;
    }

    /// <summary>配置写入放后台（会起 CLI 进程），完成后重读报告。</summary>
    private void RunConfig(Action action)
    {
        Task.Run(() =>
        {
            try
            {
                action();
                _services.Refresh();
            }
            catch (Exception)
            {
                // 设置页的状态文字 / 报告错误会体现出来。
            }
            _services.NotifyChanged();
        });
    }

    // MARK: - Projects

    private Control ProjectsSection()
    {
        var hidden = ProjectPrefs.Parse(S.Str(SettingsKeys.HiddenProjects, ""));
        var content = Ui.V(8);
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        row.Children.Add(Ui.Text(L10n.TrL(null, "settings.hidden_projects_count", hidden.Count), 12));
        var unhide = Ui.BorderedButton(L10n.Tr("settings.unhide_all"), () =>
        {
            Set(SettingsKeys.HiddenProjects, "");
        }, enabled: hidden.Count > 0);
        Grid.SetColumn(unhide, 1);
        row.Children.Add(unhide);
        content.Children.Add(row);
        content.Children.Add(Ui.Text(L10n.Tr("settings.projects_note"), 10.5, null, Palette.Secondary, wrap: true));
        return Chrome.Section(L10n.Tr("settings.section.projects"), content, padding: Metrics.RowInset);
    }

    // MARK: - Quota reset

    private Control QuotaSection()
    {
        var content = Ui.V(10);
        if (_services.Report is { } report)
        {
            var agents = SettingsAgentList.QuotaAgents(report);
            if (agents.Count == 0)
            {
                content.Children.Add(Ui.Text(L10n.Tr("settings.no_reset_info"), 11, null, Palette.Tertiary));
            }
            foreach (var agent in agents)
            {
                content.Children.Add(new QuotaResetRow(_services, agent, report));
            }
        }
        else
        {
            content.Children.Add(Ui.Text(L10n.Tr("settings.no_data_loaded"), 10.5, null, Palette.Secondary));
        }
        content.Children.Add(Ui.Text(L10n.Tr("settings.quota_note"), 10.5, null, Palette.Secondary, wrap: true));
        return Chrome.Section(L10n.Tr("settings.section.quota_reset"), content, padding: Metrics.RowInset);
    }

    // MARK: - Subscriptions

    private Control SubscriptionsSection()
    {
        var content = Ui.V(8);
        if (_services.Report is { } report)
        {
            var agents = SettingsAgentList.SubscriptionAgents(report, _editingAgent);
            foreach (var agent in agents)
            {
                var label = report.AgentLabels().GetValueOrDefault(agent)
                            ?? AgentColors.DefaultLabels.GetValueOrDefault(agent, agent);
                var row = new SubscriptionSettingsRow(_services, agent, label,
                    report.Subscriptions?.TryGetValue(agent, out var sub) == true ? sub : null,
                    report.Currency, _editingAgent == agent);
                _subscriptionRows[agent] = row;
                content.Children.Add(row);
            }
        }
        else
        {
            content.Children.Add(Ui.Text(L10n.Tr("settings.no_data_loaded"), 10.5, null, Palette.Secondary));
        }
        content.Children.Add(Ui.Text(L10n.Tr("settings.subscriptions_note"), 10.5, null, Palette.Secondary,
            wrap: true));
        return Chrome.Section(L10n.Tr("settings.section.subscriptions"), content, padding: Metrics.RowInset);
    }

    // MARK: - Apply

    private Control ApplySection()
    {
        var box = Ui.V(8);
        var apply = Ui.ProminentButton(L10n.Tr("settings.apply_refresh"), () =>
        {
            _services.ApplySettings();
            _services.NotifyChanged();
        });
        apply.HorizontalAlignment = HorizontalAlignment.Right;
        box.Children.Add(apply);
        var source = Ui.Text(L10n.TrL(null, "settings.current_source", _services.DescribeSource()), 10.5,
            null, Palette.Secondary, wrap: true);
        box.Children.Add(source);
        box.Margin = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 0);
        return box;
    }
}
