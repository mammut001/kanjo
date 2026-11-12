using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 设置页，版式照 Windows 11「设置」：一列分组，每个分组标题下是若干张卡片，
/// 每张卡片是一行设置（左边标题 + 一行说明，右边右对齐的控件）。
///
/// 内容与 Mac 版逐条对应，顺序也保持：Language / Data source / Refresh / iCloud sync（Windows 只留说明）/
/// Publish / Family usage / Projects / Quota reset / Subscriptions / Apply &amp; Refresh。
/// 所有写配置的动作仍然走 CLI（ConfigDataSource），文件 / 目录选择走 Avalonia StorageProvider。
///
/// 订阅一节只在需要时展开：有订阅信息的 agent 直接列，没有的折叠在「Show N more」后面
/// （和 Mac 总览的订阅价值卡同一个模式），这样 29 个 agent 也不会把页面撑得太长。
/// </summary>
public sealed class SettingsPage : ScrollPage
{
    private readonly AppServices _services;
    private readonly string? _anchor;
    private readonly string? _editingAgent;
    private readonly bool _snapshot;
    private readonly Action _onBack;

    private readonly StackPanel _root = new()
    {
        Orientation = Orientation.Vertical,
        Spacing = Metrics.SectionSpacing,
    };

    private bool _gitMissingError;
    private bool _tokenPromptOpen;
    private string _tokenInput = "";
    private bool _familyAdvanced;
    private bool _showAllSubscriptions;

    public SettingsPage(AppServices services, string? anchor, string? editingAgent, bool snapshot, Action onBack)
        : base(snapshot)
    {
        _services = services;
        _anchor = anchor;
        _editingAgent = editingAgent;
        _snapshot = snapshot;
        _onBack = onBack;
        // 正在编辑某个 agent 时默认把它露出来，不然「编辑」按钮点了没反应。
        _showAllSubscriptions = editingAgent is not null;

        Content = _root;
        Rebuild();
        // 已知档位表要起 CLI（几十到几百毫秒），放后台预热，回来后重建订阅行让编辑表单用上真实档位。
        // 截图 / 测试模式不起进程。
        if (!_services.SnapshotMode)
        {
            _services.Config.BeginLoadKnownPlans(() =>
            {
                foreach (var row in _subscriptionRows.Values.OfType<SubscriptionSettingsRow>()) row.PlansLoaded();
            });
        }
        _services.Family.Activity.Changed += OnExternalChange;
        _services.Publish.Activity.Changed += OnExternalChange;
        DetachedFromVisualTree += (_, _) =>
        {
            _services.Family.Activity.Changed -= OnExternalChange;
            _services.Publish.Activity.Changed -= OnExternalChange;
        };

        if (snapshot) ScrollToAnchor(anchor);
    }

    private void ScrollToAnchor(string? anchor)
    {
        Avalonia.Threading.Dispatcher.UIThread.Post(() =>
        {
            UpdateLayout();
            if (anchor is null) return;
            if (anchor == RouteAnchors.SettingsBottom)
            {
                ScrollTo(Math.Max(0, Extent.Height - Viewport.Height));
            }
            else if (SubscriptionSettingsRoute.Parse(anchor)?.Agent is { } agent &&
                     _subscriptionRows.TryGetValue(agent, out var row))
            {
                UpdateLayout();
                if (row.TranslatePoint(new Point(0, 0), _root) is { } p)
                {
                    ScrollTo(Math.Min(p.Y - 12, Extent.Height - Viewport.Height));
                }
            }
        }, Avalonia.Threading.DispatcherPriority.Loaded);
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
        var keepOffset = !_snapshot ? VerticalOffset : 0;
        _root.Children.Clear();
        _subscriptionRows.Clear();

        _root.Children.Add(Header());

        if (_services.DataOverride is { } overridePath)
        {
            // WinUI 的 InfoBar：只有一条说明，不再重复页面标题当标题。
            var bar = new InfoBar(
                L10n.TrL(null, "settings.data_override", overridePath),
                InfoBar.Level.Warning)
            {
                Margin = new Thickness(Metrics.PagePadding - 2, 12, Metrics.PagePadding - 2, 0),
            };
            _root.Children.Add(bar);
        }

        _root.Children.Add(LanguageSection());
        _root.Children.Add(AppearanceSection());
        _root.Children.Add(DataSourceSection());
        _root.Children.Add(RefreshSection());
        _root.Children.Add(ICloudSection());
        _root.Children.Add(PublishSection());
        _root.Children.Add(FamilySection());
        _root.Children.Add(ProjectsSection());
        _root.Children.Add(QuotaSection());
        _root.Children.Add(SubscriptionsSection());
        _root.Children.Add(ApplySection());

        _root.Margin = new Thickness(Metrics.PagePadding, 4, Metrics.PagePadding, 16);
        if (keepOffset > 0) RestoreOffsetLater(keepOffset);
    }

    /// <summary>页头：标题（Title 28）+ 副标题 + 返回链接。Windows 11 设置的页头节奏。</summary>
    private Control Header()
    {
        var box = Ui.V(2);
        box.Margin = new Thickness(2, 8, 2, 0);

        var back = Widgets.BackButton(L10n.Tr("common.done"), _onBack);
        back.Margin = new Thickness(-2, 0, 0, 4);
        box.Children.Add(back);
        box.Children.Add(Ui.Title(L10n.Tr("settings.title")));
        return box;
    }

    /// <summary>
    /// 一行设置：[标题 + 说明] …… [控件]。
    /// Windows 11 设置页在窗口够宽时是左右排；窗口窄（我们这个面板只有 360px）时把控件落到下一行右对齐，
    /// 免得标题被挤成「Fallback refre」这种截断。
    /// </summary>
    private static Control RowControl(string label, string? description, Control control)
    {
        var left = Ui.V(2);
        var title = Ui.Text(label, Type.BodySize, wrap: true);
        left.Children.Add(title);
        if (!string.IsNullOrEmpty(description))
        {
            left.Children.Add(Ui.Text(description!, Type.CaptionSize, null, Palette.Secondary, wrap: true));
        }
        left.VerticalAlignment = VerticalAlignment.Center;

        control.VerticalAlignment = VerticalAlignment.Center;

        // 一行可用宽度：面板宽 - 页面留白 - 卡片描边 - 卡片内边距。
        const double available = Metrics.RowContentWidth;
        // 控件自己想要的宽度：开关这类窄控件给 0（和标题同排），下拉 / 输入给 200。
        var controlWidth = control.MinWidth > 0 ? control.MinWidth : 0;
        const double minLabelWidth = 130;
        var fitsBeside = controlWidth == 0 || controlWidth + minLabelWidth + 14 <= available;

        Control body;
        if (fitsBeside)
        {
            // 窄控件（开关）：标题 + 说明在左，控件右对齐同排。
            control.HorizontalAlignment = HorizontalAlignment.Right;
            var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            left.Margin = new Thickness(0, 0, 14, 0);
            Grid.SetColumn(left, 0);
            grid.Children.Add(left);
            Grid.SetColumn(control, 1);
            grid.Children.Add(control);
            body = grid;
        }
        else
        {
            // 宽控件（下拉 / 输入框）：360px 的面板放不下「标题 + 200px 控件」，
            // 按 Windows 11 设置页的窄窗做法把控件落到下一行并右对齐。
            control.HorizontalAlignment = HorizontalAlignment.Right;
            var stack = new StackPanel { Orientation = Orientation.Vertical, Spacing = 8 };
            stack.Children.Add(left);
            stack.Children.Add(control);
            body = stack;
        }

        return new Border
        {
            Child = body,
            MinHeight = Metrics.SettingRowMinHeight,
            Padding = new Thickness(Metrics.RowInset, 10, Metrics.RowInset, 10),
        };
    }

    private static Control SimpleRow(string label, string? description, Control control) =>
        RowControl(label, description, control);

    // MARK: - Language

    private Control LanguageSection()
    {
        var current = AppLanguages.Parse(S.Str(SettingsKeys.AppLanguage, SettingsDefaults.AppLanguage))
                      ?? AppLanguage.System;
        var options = AppLanguages.All.Select(l => l.DisplayName()).ToList();
        var picker = Picker.Make(options, (int)current, index =>
        {
            Set(SettingsKeys.AppLanguage, AppLanguages.All[index].RawValue());
            Rebuild();
        });
        return Section(L10n.Tr("settings.section.language"),
            [SimpleRow(L10n.Tr("settings.language"), null, picker)]);
    }

    // MARK: - Appearance（Windows 专有：Mac 版永远跟随系统）

    /// <summary>
    /// 外观卡片：Dark（默认）/ Light / System。
    /// 选择立即生效（<see cref="App.Appearance.Choose"/>），不重启；System 等于跟随 Windows。
    /// </summary>
    private Control AppearanceSection()
    {
        // 显示的是**设置里的值**（不是截图的显式覆盖）：--snapshot-appearance 只决定这张图用哪套
        // 颜色，不代表用户选了那个外观，所以截图里这一格应始终显示设置本身（缺省 Dark）。
        var current = Appearance.FromSettings(S);
        var options = AppearanceChoices.All.Select(c => c.Label()).ToList();
        var picker = Picker.Make(options, AppearanceChoices.All.ToList().IndexOf(current), index =>
        {
            Appearance.Choose(S, AppearanceChoices.All[index]);
            // 外观一变整页都会重建一次（PanelView 订阅了 Appearance），这里不用再手动 Rebuild。
        });
        return Section(WindowsL10n.Tr("settings.section.appearance"),
            [SimpleRow(WindowsL10n.Tr("settings.appearance"), WindowsL10n.Tr("settings.appearance.note"), picker)]);
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
                _services.ApplySettings();
                Rebuild();
            });

        var rows = new List<Control>
        {
            RowControl(L10n.Tr("settings.section.data_source"), null, segmented),
        };

        if (kind == SourceKind.Cli)
        {
            rows.Add(InfoRow(Ui.Text(CliDescription(), Type.CaptionSize, null, Palette.Secondary, wrap: true)));
            rows.Add(FieldRow(L10n.Tr("settings.command"), null, SettingsKeys.CliCommand,
                DefaultPaths.DefaultCliCommand, mono: true));
            rows.Add(FieldWithButtonRow(L10n.Tr("settings.working_directory"), SettingsKeys.CliWorkingDirectory,
                DefaultPaths.ResolvedCliDirectory() ?? L10n.Tr("settings.inherit"), L10n.Tr("settings.choose"),
                ChooseDirectory, mono: true));
            rows.Add(InfoRow(Ui.Text(WindowsL10n.Tr("settings.cli_note"), Type.CaptionSize, null, Palette.Secondary,
                wrap: true)));
            var diskCommand = DiskCommand.Report(EffectiveCliCommand, false, null);
            var diskText = Ui.Text(L10n.TrL(null, "settings.disk_command", diskCommand), Type.CaptionSize, null,
                Palette.Secondary, wrap: true, mono: true);
            ToolTip.SetTip(diskText, WindowsL10n.Tr("settings.disk_command_help"));
            rows.Add(InfoRow(diskText));
        }
        else
        {
            rows.Add(FieldWithButtonRow(L10n.Tr("settings.json_file"), SettingsKeys.FilePath,
                DefaultPaths.SampleFixture, L10n.Tr("settings.choose"), ChooseFile));
            rows.Add(InfoRow(Ui.Text(L10n.Tr("settings.file_note"), Type.CaptionSize, null, Palette.Secondary,
                wrap: true)));
        }

        return GroupedSection(L10n.Tr("settings.section.data_source"), rows);
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
    /// 和 Mac 的 <c>DefaultPaths.cliDescription(customDirectory:customCommand:)</c> 一一对应。
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

    /// <summary>内置 CLI 的版本：读 cli\VERSION；读不到就说 unknown。</summary>
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

    /// <summary>只有说明文字的一行（卡片内的灰色脚注）。</summary>
    private static Control InfoRow(Control content) => new Border
    {
        Child = content,
        Padding = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 10),
    };

    /// <summary>标签 + 输入框的行（回车应用并刷新）。</summary>
    private Control FieldRow(string label, string? description, string key, string? placeholder, bool mono = true)
    {
        var box = Ui.V(4);
        box.Children.Add(Ui.Text(label, Type.CaptionSize, FontWeight.SemiBold, Palette.Secondary));
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
        return new Border
        {
            Child = box,
            Padding = new Thickness(Metrics.RowInset, 8, Metrics.RowInset, 10),
        };
    }

    /// <summary>标签 + 输入框 + 右侧「Choose…」按钮。</summary>
    private Control FieldWithButtonRow(string label, string key, string? placeholder, string buttonText,
        Action onClick, bool mono = true)
    {
        var box = Ui.V(4);
        box.Children.Add(Ui.Text(label, Type.CaptionSize, FontWeight.SemiBold, Palette.Secondary));
        var field = Ui.TextField(S.Str(key, ""), placeholder, mono: mono);
        var text = field.Box;
        text.LostFocus += (_, _) => S.Set(key, text.Text ?? "");
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        Grid.SetColumn(field.Root, 0);
        row.Children.Add(field.Root);
        var choose = Ui.StandardButton(buttonText, onClick);
        choose.Margin = new Thickness(8, 0, 0, 0);
        Grid.SetColumn(choose, 1);
        row.Children.Add(choose);
        box.Children.Add(row);
        return new Border
        {
            Child = box,
            Padding = new Thickness(Metrics.RowInset, 8, Metrics.RowInset, 10),
        };
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
        var rows = new List<Control>();
        var minutes = S.Int(SettingsKeys.RefreshMinutes, SettingsDefaults.RefreshMinutes);
        var intervals = new[] { 0, 15, 30, 60 };
        var labels = intervals
            .Select(m => m == 0 ? L10n.Tr("settings.refresh_off") : L10n.TrL(null, "settings.refresh_minutes", m))
            .ToList();
        var index = Math.Max(0, Array.IndexOf(intervals, minutes));
        rows.Add(RowControl(L10n.Tr("settings.auto_refresh"), L10n.Tr("settings.refresh_note"),
            Picker.Make(labels, index, i =>
            {
                Set(SettingsKeys.RefreshMinutes, intervals[i]);
                _services.RestartFallbackTimer();
                Rebuild();
            })));

        var mode = MenuBarModes.Parse(S.Str(SettingsKeys.MenuBarMode, SettingsDefaults.MenuBarMode))
                   ?? MenuBarMode.Cost;
        var modeOptions = MenuBarModes.All.Select(m => m.Label()).ToList();
        rows.Add(RowControl(L10n.Tr("settings.menu_bar_shows"), null,
            Picker.Make(modeOptions, (int)mode, i =>
            {
                Set(SettingsKeys.MenuBarMode, MenuBarModes.All[i].RawValue());
                Rebuild();
            })));

        rows.Add(ToggleRow(L10n.Tr("settings.show_menu_bar_cost"), null,
            S.Bool(SettingsKeys.ShowAmountInMenuBar, SettingsDefaults.ShowAmountInMenuBar),
            value => Set(SettingsKeys.ShowAmountInMenuBar, value)));

        return GroupedSection(L10n.Tr("settings.section.refresh"), rows);
    }

    /// <summary>开关行（[标题 + 说明] …… ToggleSwitch）。</summary>
    private static Control ToggleRow(string label, string? description, bool value, Action<bool> onChange) =>
        RowControl(label, description, Toggle.Make(value, onChange));

    // MARK: - iCloud（Mac 专属）

    private Control ICloudSection() =>
        GroupedSection(L10n.Tr("settings.section.icloud"),
        [
            InfoRow(Ui.Text(WindowsL10n.Tr("settings.icloud.windows_only"), Type.CaptionSize, null,
                Palette.Secondary, wrap: true)),
        ]);

    // MARK: - Publish

    private Control PublishSection()
    {
        var enabled = S.Bool(SettingsKeys.PublishEnabled, SettingsDefaults.PublishEnabled);
        var rows = new List<Control>
        {
            ToggleRow(L10n.Tr("settings.publish.enable"), L10n.Tr("settings.publish.note"), enabled,
                value => Set(SettingsKeys.PublishEnabled, value)),
        };

        if (enabled)
        {
            var frequency = PublishFrequencies.Parse(S.GetString(SettingsKeys.PublishFrequency))
                            ?? PublishFrequency.Weekly;
            var freqOptions = PublishFrequencies.All.Select(f => f.Label()).ToList();
            rows.Add(RowControl(L10n.Tr("settings.publish.frequency"), null,
                Picker.Make(freqOptions, PublishFrequencies.All.ToList().IndexOf(frequency), i =>
                {
                    Set(SettingsKeys.PublishFrequency, PublishFrequencies.All[i].RawValue());
                    Rebuild();
                })));

            var repo = S.Str(SettingsKeys.PublishRepoPath, SettingsDefaults.PublishRepoPath);
            var repoBlock = Ui.V(4);
            repoBlock.Children.Add(Ui.Text(L10n.Tr("settings.publish.repo_path"), Type.CaptionSize,
                FontWeight.SemiBold, Palette.Secondary));
            var repoRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            var repoText = Ui.Text(repo.Length == 0 ? "—" : repo, Type.CaptionSize, null,
                repo.Length == 0 ? Palette.Secondary : Palette.Foreground, maxLines: 1);
            repoText.TextTrimming = TextTrimming.CharacterEllipsis;
            Grid.SetColumn(repoText, 0);
            repoRow.Children.Add(repoText);
            var choose = Ui.StandardButton(L10n.Tr("settings.publish.choose_repo"), ChooseRepo);
            choose.Margin = new Thickness(8, 0, 0, 0);
            Grid.SetColumn(choose, 1);
            repoRow.Children.Add(choose);
            repoBlock.Children.Add(repoRow);
            if (_gitMissingError)
            {
                repoBlock.Children.Add(Ui.Text(L10n.Tr("settings.publish.git_missing"), Type.CaptionSize, null,
                    Palette.Bad, wrap: true));
            }
            rows.Add(new Border
            {
                Child = repoBlock,
                Padding = new Thickness(Metrics.RowInset, 8, Metrics.RowInset, 10),
            });

            rows.Add(FieldRow(L10n.Tr("settings.publish.file_path"), null, SettingsKeys.PublishFilePath,
                SettingsDefaults.PublishFilePath, mono: false));
            rows.Add(FieldRow(L10n.Tr("settings.publish.branch"), null, SettingsKeys.PublishBranch,
                SettingsDefaults.PublishBranch, mono: false));

            var (statusText, statusError, statusWarn) = _services.Publish.StatusText();
            var statusRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            var status = Ui.Text(statusText, Type.CaptionSize, null,
                statusError ? Palette.Bad : statusWarn ? Palette.WarnInk : Palette.Secondary, wrap: true);
            status.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(status, 0);
            statusRow.Children.Add(status);
            var repoTrim = repo.Trim();
            var publishNow = Ui.AccentButton(L10n.Tr("settings.publish.now"), () =>
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
            rows.Add(new Border
            {
                Child = statusRow,
                Padding = new Thickness(Metrics.RowInset, 8, Metrics.RowInset, 10),
            });
        }

        return GroupedSection(L10n.Tr("settings.section.publish"), rows);
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
        var rows = new List<Control>
        {
            ToggleRow(L10n.Tr("settings.family.enable"),
                enabled ? null : L10n.Tr("settings.family.off_note"), enabled,
                value => Set(SettingsKeys.FamilyReportEnabled, value)),
        };

        if (enabled)
        {
            var mode = S.Str(SettingsKeys.FamilyReportMode, SettingsDefaults.FamilyReportMode);
            var modes = new List<string>
            {
                L10n.Tr("settings.family.mode.join"), L10n.Tr("settings.family.mode.manager"),
            };
            rows.Add(RowControl(L10n.Tr("settings.family.mode"), null,
                new SegmentedControl(modes, mode == "manager" ? 1 : 0, index =>
                {
                    Set(SettingsKeys.FamilyReportMode, index == 1 ? "manager" : "join");
                    Rebuild();
                }, stretch: false)
                {
                    MinWidth = Metrics.ControlMinWidth,
                }));

            if (mode == "manager")
            {
                rows.Add(new Border
                {
                    Child = Ui.V(6).Also(box =>
                    {
                        box.Children.Add(Ui.Text(WindowsL10n.Tr("settings.family.manager.desc"), Type.CaptionSize,
                            null, Palette.Secondary, wrap: true));
                        box.Children.Add(Ui.StandardButton(L10n.Tr("settings.family.manager.view_guide"),
                            () => ProjectActions.OpenUrl(
                                "https://github.com/mammut001/kanjo/blob/main/family-server/DEPLOY.md")));
                    }),
                    Padding = new Thickness(Metrics.RowInset, 8, Metrics.RowInset, 10),
                });
            }
            else
            {
                rows.Add(FieldRow(L10n.Tr("settings.family.url"), null, SettingsKeys.FamilyReportUrl,
                    "https://usage.example.com", mono: false));
                rows.Add(TokenRow());
                rows.Add(FieldRow(L10n.Tr("settings.family.member_label"), null,
                    SettingsKeys.FamilyReportMemberLabel, L10n.Tr("settings.family.member_label_placeholder"),
                    mono: false));
                rows.AddRange(ScopeRows());
                rows.Add(FamilyStatusRow());
                rows.Add(InfoRow(Ui.Text(L10n.Tr("settings.family.note"), Type.CaptionSize, null,
                    Palette.Secondary, wrap: true)));
            }
        }

        return GroupedSection(L10n.Tr("settings.section.family"), rows);
    }

    private Control TokenRow()
    {
        var block = Ui.V(6);
        block.Children.Add(Ui.Text(L10n.Tr("settings.family.token"), Type.CaptionSize, FontWeight.SemiBold,
            Palette.Secondary));
        var hasToken = _services.Family.HasToken;
        var row = Ui.H(8);
        row.Children.Add(Ui.Text(hasToken
            ? L10n.Tr("settings.family.token.configured")
            : L10n.Tr("settings.family.token.not_configured"), Type.CaptionSize, null,
            hasToken ? Palette.Foreground : Palette.Secondary));
        if (hasToken)
        {
            row.Children.Add(Ui.StandardButton(L10n.Tr("settings.family.token.change"), () =>
            {
                _tokenInput = "";
                _tokenPromptOpen = true;
                Rebuild();
            }));
            row.Children.Add(Ui.StandardButton(L10n.Tr("settings.family.token.clear"), () =>
            {
                _services.Family.ClearToken();
                Rebuild();
            }));
        }
        else
        {
            row.Children.Add(Ui.StandardButton(L10n.Tr("settings.family.token.set"), () =>
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
            prompt.Children.Add(Ui.Text(L10n.Tr("settings.family.token.prompt_title"), Type.BodyStrongSize,
                FontWeight.SemiBold));
            prompt.Children.Add(Ui.Text(WindowsL10n.Tr("settings.family.token.prompt_message"), Type.CaptionSize,
                null, Palette.Secondary, wrap: true));
            var input = new TextBox
            {
                Text = _tokenInput,
                Watermark = L10n.Tr("settings.family.token.placeholder"),
                PasswordChar = '•',
                FontSize = Type.CaptionSize,
                MinHeight = 32,
                Padding = new Thickness(10, 5, 10, 5),
                CornerRadius = new CornerRadius(4),
                Background = Palette.ControlFill,
                BorderBrush = new SolidColorBrush(Palette.CardStrokeColor),
                BorderThickness = new Thickness(1),
            };
            input.TextChanged += (_, _) => _tokenInput = input.Text ?? "";
            prompt.Children.Add(input);
            var actions = Ui.H(8);
            var spacer = new Panel { HorizontalAlignment = HorizontalAlignment.Stretch };
            actions.Children.Add(spacer);
            actions.Children.Add(Ui.StandardButton(L10n.Tr("settings.family.token.cancel"), () =>
            {
                _tokenInput = "";
                _tokenPromptOpen = false;
                Rebuild();
            }));
            var trimmed = _tokenInput.Trim();
            actions.Children.Add(Ui.AccentButton(L10n.Tr("settings.family.token.save"), () =>
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
        return new Border
        {
            Child = block,
            Padding = new Thickness(Metrics.RowInset, 8, Metrics.RowInset, 10),
        };
    }

    private IEnumerable<Control> ScopeRows()
    {
        var config = _services.Report?.Config.Family;
        var rows = new List<Control>
        {
            InfoRow(Ui.Text(L10n.TrL(null, "settings.family.scope.label", FamilyScopeText.Make(config)),
                Type.CaptionSize, null, Palette.Secondary, wrap: true)),
        };

        var agents = config?.Agents?.ToList() ?? ["antigravity"];
        var isAll = agents.Count > 0 && (agents[0] == "all" || agents.Contains("all"));
        var options = new List<string>
        {
            L10n.Tr("settings.family.scope.agents_antigravity"),
            L10n.Tr("settings.family.scope.agents_all"),
        };
        var picker = Picker.Make(options, isAll ? 1 : 0, index =>
        {
            RunConfig(() =>
            {
                if (index == 1) _services.Config.SetFamilyAgents("all");
                else _services.Config.SetFamilyAgents(null);
            });
        }, enabled: _services.CanEditSubscriptions);
        rows.Add(RowControl(L10n.Tr("settings.family.scope.agents_choice"), null, picker));

        var header = Ui.H(6);
        header.Children.Add(Icons.Chevron(_familyAdvanced, 10, Palette.Secondary));
        header.Children.Add(Ui.Text(L10n.Tr("settings.family.scope.advanced"),
            Type.CaptionSize, null, Palette.Link));
        rows.Add(new Border
        {
            Child = new Clickable(header, () =>
            {
                _familyAdvanced = !_familyAdvanced;
                Rebuild();
            }, radius: 4, hand: true)
            {
                HorizontalAlignment = HorizontalAlignment.Left,
            },
            Padding = new Thickness(Metrics.RowInset, 2, Metrics.RowInset, 10),
        });

        if (_familyAdvanced)
        {
            var advanced = Ui.V(6);
            var since = config?.Since;
            var dateBox = new TextBox
            {
                Text = since is { Length: >= 10 } ? since[..10] : "",
                Watermark = "yyyy-MM-dd",
                FontSize = Type.CaptionSize,
                MinHeight = 32,
                Width = 130,
                Padding = new Thickness(10, 5, 10, 5),
                FontFamily = Type.Mono,
                CornerRadius = new CornerRadius(4),
                Background = Palette.ControlFill,
                BorderBrush = new SolidColorBrush(Palette.CardStrokeColor),
                BorderThickness = new Thickness(1),
                IsEnabled = _services.CanEditSubscriptions,
            };
            dateBox.LostFocus += (_, _) =>
            {
                var value = (dateBox.Text ?? "").Trim();
                if (value == (since is { Length: >= 10 } ? since[..10] : "")) return;
                RunConfig(() => _services.Config.SetFamilySince(value.Length == 0 ? null : value));
            };
            var dateRow = Ui.H(8);
            dateRow.Children.Add(dateBox);
            if (!string.IsNullOrEmpty(since))
            {
                dateRow.Children.Add(Ui.StandardButton(L10n.Tr("settings.family.scope.clear_date"),
                    () => RunConfig(() => _services.Config.SetFamilySince(null)),
                    enabled: _services.CanEditSubscriptions));
            }
            var dateBlock = Ui.V(4);
            dateBlock.Children.Add(Ui.Text(L10n.Tr("settings.family.scope.start_date"), Type.CaptionSize,
                FontWeight.SemiBold, Palette.Secondary));
            dateBlock.Children.Add(dateRow);
            advanced.Children.Add(dateBlock);
            advanced.Children.Add(Ui.Text(L10n.Tr("settings.family.scope.advanced_note"), Type.CaptionSize, null,
                Palette.Secondary, wrap: true));
            rows.Add(new Border
            {
                Child = advanced,
                Padding = new Thickness(Metrics.RowInset, 4, Metrics.RowInset, 12),
            });
        }
        return rows;
    }

    private Control FamilyStatusRow()
    {
        var (text, kind) = _services.Family.StatusText();
        var color = kind switch
        {
            FamilyReportStatusStateKind.NoNetwork => Palette.WarnInk,
            FamilyReportStatusStateKind.Failed => Palette.Bad,
            _ => Palette.Secondary,
        };
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        var status = Ui.Text(text, Type.CaptionSize, null, color, wrap: true);
        status.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(status, 0);
        row.Children.Add(status);
        var reportNow = Ui.AccentButton(L10n.Tr("settings.family.now"), () =>
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
        return new Border
        {
            Child = row,
            Padding = new Thickness(Metrics.RowInset, 8, Metrics.RowInset, 10),
        };
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
        var unhide = Ui.StandardButton(L10n.Tr("settings.unhide_all"), () =>
        {
            Set(SettingsKeys.HiddenProjects, "");
        }, enabled: hidden.Count > 0);
        return GroupedSection(L10n.Tr("settings.section.projects"),
        [
            RowControl(L10n.TrL(null, "settings.hidden_projects_count", hidden.Count),
                L10n.Tr("settings.projects_note"), unhide),
        ]);
    }

    // MARK: - Quota reset

    private Control QuotaSection()
    {
        var rows = new List<Control>();
        if (_services.Report is { } report)
        {
            var agents = SettingsAgentList.QuotaAgents(report);
            if (agents.Count == 0)
            {
                rows.Add(InfoRow(Ui.Text(L10n.Tr("settings.no_reset_info"), Type.CaptionSize, null,
                    Palette.Secondary)));
            }
            // 每个 agent 一张独立卡片（Windows 11 设置页里一项一卡）。
            foreach (var agent in agents) rows.Add(new QuotaResetRow(_services, agent, report));
        }
        else
        {
            rows.Add(InfoRow(Ui.Text(L10n.Tr("settings.no_data_loaded"), Type.CaptionSize, null,
                Palette.Secondary)));
        }
        rows.Add(InfoRow(Ui.Text(L10n.Tr("settings.quota_note"), Type.CaptionSize, null, Palette.Secondary,
            wrap: true)));
        return GroupedSection(L10n.Tr("settings.section.quota_reset"), rows);
    }

    // MARK: - Subscriptions

    private Control SubscriptionsSection()
    {
        var rows = new List<Control>();
        if (_services.Report is { } report)
        {
            var agents = SettingsAgentList.SubscriptionAgents(report, _editingAgent);
            // 有订阅信息的直接列；没有的折叠在「Show N more」后面（29 个 agent 时页面才不会失控）。
            var withInfo = new List<string>();
            var withoutInfo = new List<string>();
            foreach (var agent in agents)
            {
                var has = report.Subscriptions?.ContainsKey(agent) == true || agent == _editingAgent;
                (has ? withInfo : withoutInfo).Add(agent);
            }

            void AddRow(string agent)
            {
                var label = report.AgentLabels().GetValueOrDefault(agent)
                            ?? AgentColors.DefaultLabels.GetValueOrDefault(agent, agent);
                var row = new SubscriptionSettingsRow(_services, agent, label,
                    report.Subscriptions?.TryGetValue(agent, out var sub) == true ? sub : null,
                    report.Currency, _editingAgent == agent);
                _subscriptionRows[agent] = row;
                rows.Add(row);
            }

            foreach (var agent in withInfo) AddRow(agent);

            if (withoutInfo.Count > 0)
            {
                if (_showAllSubscriptions)
                {
                    foreach (var agent in withoutInfo) AddRow(agent);
                    rows.Add(MoreLink(L10n.Tr("common.show_fewer"), () =>
                    {
                        _showAllSubscriptions = false;
                        Rebuild();
                    }));
                }
                else
                {
                    rows.Add(MoreLink(
                        L10n.TrL(null, "overview.subscription_value.show_more", withoutInfo.Count),
                        () =>
                        {
                            _showAllSubscriptions = true;
                            Rebuild();
                        }));
                }
            }
        }
        else
        {
            rows.Add(InfoRow(Ui.Text(L10n.Tr("settings.no_data_loaded"), Type.CaptionSize, null,
                Palette.Secondary)));
        }
        rows.Add(InfoRow(Ui.Text(L10n.Tr("settings.subscriptions_note"), Type.CaptionSize, null,
            Palette.Secondary, wrap: true)));
        return GroupedSection(L10n.Tr("settings.section.subscriptions"), rows);
    }

    private static Control MoreLink(string text, Action onClick)
    {
        var link = Ui.LinkButton(text, onClick, Type.CaptionSize);
        link.HorizontalAlignment = HorizontalAlignment.Left;
        return new Border
        {
            Child = link,
            Padding = new Thickness(Metrics.RowInset, 6, Metrics.RowInset, 8),
        };
    }

    // MARK: - Apply

    private Control ApplySection()
    {
        var box = Ui.V(8);
        var source = Ui.Text(L10n.TrL(null, "settings.current_source", _services.DescribeSource()),
            Type.CaptionSize, null, Palette.Secondary, wrap: true);
        box.Children.Add(source);

        var apply = Ui.AccentButton(L10n.Tr("settings.apply_refresh"), () =>
        {
            _services.ApplySettings();
            _services.NotifyChanged();
        });
        apply.HorizontalAlignment = HorizontalAlignment.Right;
        box.Children.Add(apply);

        return new Border
        {
            Child = box,
            Padding = new Thickness(2, 0, 2, 8),
        };
    }

    // MARK: - 卡片的组织方式

    /// <summary>一个分组：标题 + 一列卡片（每行一张卡片，行间 4px）。</summary>
    private static Control Section(string title, IEnumerable<Control> rows) =>
        GroupedSection(title, rows);

    /// <summary>把一个分组的若干行做成「一列独立卡片」。</summary>
    private static Control GroupedSection(string title, IEnumerable<Control> rows)
    {
        var column = new StackPanel { Orientation = Orientation.Vertical, Spacing = Metrics.CardGap };
        foreach (var row in rows)
        {
            column.Children.Add(new Border
            {
                Child = row,
                Background = Palette.CardBackground,
                BorderBrush = Palette.CardBorder,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(Metrics.GroupRadius),
                ClipToBounds = true,
            });
        }

        var box = new StackPanel { Orientation = Orientation.Vertical };
        var label = Ui.SectionTitle(title);
        label.Margin = new Thickness(2, 0, 2, 8);
        box.Children.Add(label);
        box.Children.Add(column);
        return box;
    }
}

/// <summary>让对象初始化的写法短一点（只在设置页内部用）。</summary>
internal static class ControlExtensions
{
    public static T Also<T>(this T value, Action<T> action)
    {
        action(value);
        return value;
    }
}
