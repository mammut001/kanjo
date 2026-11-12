using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 订阅行（SubscriptionSettingsRow）：展示 / 空 / 编辑三种形态。
/// 展示：档位 · 月费、Renews on day N 步进、Apply / Reset / Edit、来源、billing 链接。
/// 编辑：档位下拉（来自 `config plans --json`）+ 自定义文本、月费、续费日、Apply / Cancel / Remove。
///
/// 步进箭头是 32×32 的可点图标；指针停在上面时滚轮滚页面（<see cref="WheelPolicy"/> 会拦下来），
/// 不会像以前那样「滚一下就悄悄改了续费日」。
/// </summary>
public sealed class SubscriptionSettingsRow : StackPanel
{
    private readonly AppServices _services;
    private readonly string _agent;
    private readonly string _label;
    private readonly string _currency;
    private bool _editing;
    private bool _saving;
    private string? _error;
    private int _day;
    private string _planKey;
    private string _customPlan;
    private string _price;

    public SubscriptionSettingsRow(AppServices services, string agent, string label, Subscription? sub,
        string currency, bool initiallyEditing)
    {
        _services = services;
        _agent = agent;
        _label = label;
        _currency = currency;
        _editing = initiallyEditing;
        _day = Math.Clamp(sub?.AnchorDay ?? 1, 1, 28);

        var plans = KnownPlans;
        var (key, custom) = initiallyEditing
            ? SubscriptionPlanForm.InitialSelection(sub, plans)
            : SubscriptionPlanForm.SyncSelection(sub, plans);
        _planKey = key;
        _customPlan = custom;
        _price = sub?.MonthlyPriceUsd is { } priceText
            ? SubscriptionPlanForm.FormatPrice(priceText)
            : (initiallyEditing && plans.Count > 0 && plans[0].MonthlyPriceUsd is { } list
                ? SubscriptionPlanForm.FormatPrice(list)
                : "");

        Orientation = Orientation.Vertical;
        Spacing = 4;
        Build(sub);
    }

    /// <summary>
    /// 档位表在后台预热完成后调用：重建这一行，让编辑表单用上真实的档位列表
    /// （之前用的是内置兜底表）。不阻塞打开设置的那一帧。
    /// </summary>
    public void PlansLoaded() => Rebuild();

    private IReadOnlyList<KnownPlan>? LoadedPlans => _services.Config.CachedPlans?.GetValueOrDefault(_agent);

    private IReadOnlyList<KnownPlan> KnownPlans =>
        LoadedPlans ?? KnownPlan.FallbackPlans.GetValueOrDefault(_agent) ?? [];

    private bool HasKnownPlans => KnownPlans.Count > 0;

    private bool CanEdit => _services.CanEditSubscriptions && !_saving && !_services.IsLoading;

    private Subscription? Current => _services.Report?.Subscriptions?.GetValueOrDefault(_agent);

    private void Build(Subscription? sub)
    {
        Children.Clear();
        var header = Ui.H(8);
        header.Children.Add(Ui.Dot(_agent, 8));
        header.Children.Add(Ui.Text(_label, Type.BodySize, FontWeight.SemiBold, maxLines: 1));
        if (sub is not null)
        {
            header.Children.Add(Ui.Text(
                $"{L10n.Tr("settings.subscriptions.price")}: {Fmt.PerMonth(sub.MonthlyPriceUsd, _currency)}",
                Type.CaptionSize, null, Palette.Secondary, maxLines: 1));
        }
        Children.Add(new Border
        {
            Child = header,
            Padding = new Thickness(Metrics.RowInset, 10, Metrics.RowInset, sub is null ? 2 : 4),
        });

        if (_editing) Children.Add(EditingForm(sub));
        else if (sub is not null) Children.Add(DisplayForm(sub));
        else Children.Add(EmptyForm());

        if (_error is { } error)
        {
            var block = Widgets.StatusBlock(true,
            [
                Ui.Text(error, Type.CaptionSize, null, Palette.Bad, wrap: true),
            ]);
            block.Margin = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 10);
            Children.Add(block);
        }
        else
        {
            Children.Add(new Border { Height = 6 });
        }
    }

    private Control DisplayForm(Subscription sub)
    {
        var box = Ui.V(8);

        var stepper = Stepper(CanEdit);
        ToolTip.SetTip(stepper, CanEdit
            ? L10n.Tr("settings.renews_day_help")
            : L10n.Tr("settings.renews_day_disabled_help"));
        box.Children.Add(stepper);

        // 三个按钮（Apply / Reset / Edit）右对齐。
        // 用 Grid 的 `*,Auto` 列来右推，而不是靠 HorizontalAlignment.Right ——
        // 后者会让 StackPanel 先按内容定宽、再溢出可用宽度。
        // 左右 12px 内边距**只由外层 Border 提供一次**：这里再包一层 Padding 会变成 24，
        // 按钮就会比同一行的文字窄进半格（review 里「右侧留白不均」的来源）。
        var actions = Ui.H(8);
        var apply = Ui.AccentButton(L10n.Tr("common.apply"), () => SaveAnchor(_day), enabled: CanEdit);
        var reset = Ui.StandardButton(L10n.Tr("common.reset"), ResetAll, enabled: CanEdit, compact: true);
        var edit = Ui.StandardButton(L10n.Tr("settings.edit"), () =>
        {
            SyncInputs(sub);
            _editing = true;
            Rebuild();
        }, enabled: CanEdit, compact: true);
        actions.Children.Add(apply);
        actions.Children.Add(reset);
        actions.Children.Add(edit);
        var actionRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        Grid.SetColumn(actions, 1);
        actionRow.Children.Add(actions);
        box.Children.Add(actionRow);

        var source = Ui.Text(_saving
                ? L10n.Tr("settings.saving")
                : SubscriptionValue.AnchorSource(sub), Type.CaptionSize, null, Palette.Secondary);
        box.Children.Add(source);

        if (SubscriptionValue.BillingPage(_agent) is { } url)
        {
            var link = Ui.SmallLink(L10n.Tr("settings.open_billing_page"), () => ProjectActions.OpenUrl(url));
            box.Children.Add(link);
            box.Children.Add(Ui.Text(L10n.Tr("settings.billing_page_hint"), Type.CaptionSize, null,
                Palette.Secondary, wrap: true));
        }

        return new Border
        {
            Child = box,
            Padding = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 10),
        };
    }

    private Control EmptyForm()
    {
        var box = Ui.V(8);
        // 说明和按钮不再挤在同一行（360px 里 "No subscription info" + "Add subscription"
        // 会超出卡片）：说明一行、按钮右对齐一行，和 Mac 的窄窗表现一致。
        box.Children.Add(Ui.Text(L10n.Tr("settings.no_subscription_info"), Type.CaptionSize, null,
            Palette.Secondary, wrap: true));
        var addButton = Ui.StandardButton(L10n.Tr("settings.add_subscription"), () =>
        {
            SyncInputs(null);
            _editing = true;
            Rebuild();
        }, enabled: CanEdit);
        var actionRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        Grid.SetColumn(addButton, 1);
        actionRow.Children.Add(addButton);
        box.Children.Add(actionRow);
        if (SubscriptionValue.BillingPage(_agent) is { } url)
        {
            box.Children.Add(Ui.SmallLink(L10n.Tr("settings.open_billing_page"), () => ProjectActions.OpenUrl(url)));
        }
        return new Border
        {
            Child = box,
            Padding = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 10),
        };
    }

    private Control EditingForm(Subscription? sub)
    {
        var box = Ui.V(10);

        var plans = KnownPlans;
        if (plans.Count > 0)
        {
            var options = plans.Select(p => SubscriptionPlanForm.MenuLabel(p, _currency)).ToList();
            options.Add(L10n.Tr("settings.plan_other"));
            var index = plans.ToList().FindIndex(p => p.Key == _planKey);
            var picker = Ui.V(4);
            picker.Children.Add(Ui.Text(L10n.Tr("settings.plan"), Type.CaptionSize, FontWeight.SemiBold,
                Palette.Secondary));
            picker.Children.Add(Picker.Make(options, Math.Max(index, 0), i =>
            {
                _planKey = i < plans.Count ? plans[i].Key : SubscriptionPlanForm.OtherPlanTag;
                if (_planKey != SubscriptionPlanForm.OtherPlanTag) _customPlan = "";
                _price = SubscriptionPlanForm.PriceForSelection(_planKey, sub, plans);
                Rebuild();
            }, minWidth: 220));
            box.Children.Add(picker);

            if (_planKey == SubscriptionPlanForm.OtherPlanTag)
            {
                box.Children.Add(SmallField(L10n.Tr("settings.plan"), _customPlan, value => _customPlan = value));
            }
        }
        else
        {
            box.Children.Add(SmallField(L10n.Tr("settings.plan"), _customPlan, value => _customPlan = value));
        }

        var priceBlock = Ui.V(4);
        priceBlock.Children.Add(Ui.Text(L10n.Tr("settings.monthly_price_usd"), Type.CaptionSize,
            FontWeight.SemiBold, Palette.Secondary));
        var priceRow = Ui.H(10);
        var price = Ui.TextField(_price, L10n.Tr("settings.monthly_price_usd"), mono: true, width: 110);
        var priceField = price.Box;
        priceField.TextChanged += (_, _) => _price = priceField.Text ?? "";
        ToolTip.SetTip(priceField, L10n.Tr("settings.monthly_price_usd"));
        priceRow.Children.Add(price.Root);
        priceRow.Children.Add(Stepper(!_saving));
        priceBlock.Children.Add(priceRow);
        box.Children.Add(priceBlock);

        var actions = Ui.H(8);
        var applyEnabled = !_saving && !_services.IsLoading;
        var applyButton = Ui.AccentButton(L10n.Tr("common.apply"), ApplyManual, enabled: applyEnabled);
        var cancelButton = Ui.StandardButton(L10n.Tr("common.cancel"), () =>
        {
            _editing = false;
            _error = null;
            SyncInputs(Current);
            Rebuild();
        }, enabled: !_saving);
        actions.Children.Add(applyButton);
        actions.Children.Add(cancelButton);
        if (sub is not null)
        {
            actions.Children.Add(Ui.StandardButton(L10n.Tr("settings.remove_subscription"), RemoveManual,
                enabled: !_saving));
        }
        var actionRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        Grid.SetColumn(actions, 1);
        // box 由外层 Border 统一提供左右内边距，这里不要再加一层（否则 12+12 双内缩）。
        actionRow.Children.Add(actions);
        box.Children.Add(actionRow);
        if (_saving) box.Opacity = 0.7;

        return new Border
        {
            Child = box,
            Padding = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 12),
        };
    }

    private Control SmallField(string label, string value, Action<string> onChange)
    {
        var box = Ui.V(4);
        box.Children.Add(Ui.Text(label, Type.CaptionSize, FontWeight.SemiBold, Palette.Secondary));
        var text = new TextBox
        {
            Text = value,
            FontSize = Type.CaptionSize,
            MinHeight = 32,
            Padding = new Thickness(10, 5, 10, 5),
            CornerRadius = new CornerRadius(4),
            Background = Palette.ControlFill,
            BorderBrush = new SolidColorBrush(Palette.CardStrokeColor),
            BorderThickness = new Thickness(1),
        };
        text.TextChanged += (_, _) => onChange(text.Text ?? "");
        box.Children.Add(text);
        return box;
    }

    /// <summary>
    /// 步进控件（SwiftUI 的 `Stepper`）：左边一行「Renews on day N」，右边两个 32×32 箭头。
    /// 箭头是普通可点区域（不是 NumericUpDown），所以不会自己吞滚轮；滚轮由页面处理。
    /// </summary>
    private Control Stepper(bool enabled)
    {
        var row = Ui.H(6);
        row.Children.Add(Ui.Text(L10n.TrL(null, "settings.renews_on_day", _day), Type.CaptionSize, null,
            enabled ? Palette.Foreground : Palette.Secondary));

        var arrows = Ui.H(0);
        Control ArrowGlyph(Control glyph)
        {
            glyph.HorizontalAlignment = HorizontalAlignment.Center;
            glyph.VerticalAlignment = VerticalAlignment.Center;
            return new Grid { Width = 26, Height = 22, Children = { glyph } };
        }

        var up = new Clickable(ArrowGlyph(Icons.ChevronUp(9, enabled ? Palette.Secondary : Palette.Disabled)), () =>
        {
            _day = _day >= 28 ? 1 : _day + 1;
            Rebuild();
        }, L10n.Tr("settings.renews_day_help"), radius: 4)
        {
            Width = 26,
            Height = 22,
        };
        var down = new Clickable(ArrowGlyph(Icons.ChevronDown(9, enabled ? Palette.Secondary : Palette.Disabled)), () =>
        {
            _day = _day <= 1 ? 28 : _day - 1;
            Rebuild();
        }, L10n.Tr("settings.renews_day_help"), radius: 4)
        {
            Width = 26,
            Height = 22,
        };
        arrows.Children.Add(up);
        arrows.Children.Add(down);
        if (!enabled)
        {
            arrows.Opacity = 0.6;
            arrows.IsHitTestVisible = false;
        }
        row.Children.Add(arrows);
        return row;
    }

    private void Rebuild()
    {
        if (!Avalonia.Threading.Dispatcher.UIThread.CheckAccess())
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(() => Build(Current));
            return;
        }
        Build(Current);
    }

    private void SyncInputs(Subscription? sub)
    {
        _day = Math.Clamp(sub?.AnchorDay ?? 1, 1, 28);
        var plans = KnownPlans;
        var (key, custom) = SubscriptionPlanForm.SyncSelection(sub, plans);
        _planKey = key;
        _customPlan = custom;
        _price = sub?.MonthlyPriceUsd is { } price
            ? SubscriptionPlanForm.FormatPrice(price)
            : SubscriptionPlanForm.PriceForSelection(_planKey, sub, plans);
    }

    private void SaveAnchor(int? day)
    {
        if (!CanEdit) return;
        _saving = true;
        _error = null;
        Rebuild();
        Task.Run(() =>
        {
            try
            {
                _services.Config.SetAnchorDay(_agent, day);
                _services.Refresh();
            }
            catch (Exception e)
            {
                _error = e.Message;
            }
            _saving = false;
            _services.NotifyChanged();
        });
    }

    private void ApplyManual()
    {
        var (fields, error) = SubscriptionPlanForm.Validate(_planKey, _customPlan, _price, HasKnownPlans,
            KnownPlans, _day);
        if (error is not null)
        {
            _error = error;
            Rebuild();
            return;
        }
        if (fields is null) return;
        _saving = true;
        _error = null;
        Rebuild();
        Task.Run(() =>
        {
            try
            {
                _services.Config.SetSubscription(_agent, fields.Plan, fields.MonthlyPriceUsd, fields.AnchorDay);
                _editing = false;
                _services.Refresh();
            }
            catch (Exception e)
            {
                _error = e.Message;
            }
            _saving = false;
            _services.NotifyChanged();
        });
    }

    private void RemoveManual()
    {
        _saving = true;
        _error = null;
        Rebuild();
        Task.Run(() =>
        {
            try
            {
                _services.Config.RemoveSubscription(_agent);
                _editing = false;
                _services.Refresh();
            }
            catch (Exception e)
            {
                _error = e.Message;
            }
            _saving = false;
            _services.NotifyChanged();
        });
    }

    /// <summary>source 是 manual 时 Reset 等于移除覆盖，否则是清掉续费日。</summary>
    private void ResetAll()
    {
        if (Current?.Source == "manual") RemoveManual();
        else SaveAnchor(null);
    }
}
