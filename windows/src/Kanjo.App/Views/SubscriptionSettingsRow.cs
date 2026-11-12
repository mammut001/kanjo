using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 订阅行（SubscriptionSettingsRow）：展示 / 空 / 编辑三种形态。
/// 展示：档位 · 月费、Renews on day N 步进、Apply / Reset / Edit、来源、billing 链接。
/// 编辑：档位菜单（来自 `config plans --json`）+ 自定义文本、月费、续费日、Apply / Cancel / Remove。
/// 所有写入都走 CLI（ConfigDataSource），和 Mac 版逐条一致。
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
        _services.Config.KnownPlans();
    }

    private IReadOnlyList<KnownPlan>? LoadedPlans => _services.Config.CachedPlans?.GetValueOrDefault(_agent);

    private IReadOnlyList<KnownPlan> KnownPlans =>
        LoadedPlans ?? KnownPlan.FallbackPlans.GetValueOrDefault(_agent) ?? [];

    private bool HasKnownPlans => KnownPlans.Count > 0;

    private bool CanEdit => _services.CanEditSubscriptions && !_saving && !_services.IsLoading;

    private Subscription? Current => _services.Report?.Subscriptions?.GetValueOrDefault(_agent);

    private void Build(Subscription? sub)
    {
        Children.Clear();
        var header = Ui.H(5);
        header.Children.Add(Ui.Dot(_agent, 6));
        header.Children.Add(Ui.Text(_label, 11.5, maxLines: 1));
        Children.Add(header);

        if (_editing) Children.Add(EditingForm(sub));
        else if (sub is not null) Children.Add(DisplayForm(sub));
        else Children.Add(EmptyForm());

        if (_error is { } error)
        {
            Children.Add(Widgets.StatusBlock(true,
            [
                Ui.Text(error, 10.5, null, Palette.Bad, wrap: true),
            ]));
        }
    }

    private Control DisplayForm(Subscription sub)
    {
        var box = Ui.V(4);
        var plan = Ui.Text($"{sub.PlanLabel} · {Fmt.PerMonth(sub.MonthlyPriceUsd, _currency)}", 10, null,
            Palette.Secondary);
        plan.Margin = new Thickness(11, 0, 0, 0);
        box.Children.Add(plan);

        // Mac 的 Stepper 只画 label + 一对箭头（数字就在 label 里），没有单独的数值框。
        var stepper = Stepper(CanEdit, "settings.renews_on_day", _day);
        stepper.Margin = new Thickness(11, 0, 0, 0);
        ToolTip.SetTip(stepper, CanEdit
            ? L10n.Tr("settings.renews_day_help")
            : L10n.Tr("settings.renews_day_disabled_help"));
        if (!CanEdit) stepper.Opacity = 0.6;
        box.Children.Add(stepper);

        var actions = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto,Auto") };
        actions.Margin = new Thickness(11, 0, 0, 0);
        var apply = Ui.BorderedButton(L10n.Tr("common.apply"), () => SaveAnchor(_day), enabled: CanEdit);
        var reset = Ui.BorderedButton(L10n.Tr("common.reset"), ResetAll, enabled: CanEdit);
        var edit = Ui.BorderedButton(L10n.Tr("settings.edit"), () =>
        {
            SyncInputs(sub);
            _editing = true;
            Rebuild();
        }, enabled: CanEdit);
        reset.Margin = new Thickness(6, 0, 0, 0);
        edit.Margin = new Thickness(6, 0, 0, 0);
        Grid.SetColumn(apply, 1);
        Grid.SetColumn(reset, 2);
        Grid.SetColumn(edit, 3);
        actions.Children.Add(apply);
        actions.Children.Add(reset);
        actions.Children.Add(edit);
        box.Children.Add(actions);

        var source = Ui.Text(_saving ? L10n.Tr("settings.saving") : SubscriptionValue.AnchorSource(sub),
            10, null, Palette.Secondary);
        source.Margin = new Thickness(11, 0, 0, 0);
        box.Children.Add(source);

        if (SubscriptionValue.BillingPage(_agent) is { } url)
        {
            var link = Ui.SmallLink(L10n.Tr("settings.open_billing_page"), () => ProjectActions.OpenUrl(url));
            link.Margin = new Thickness(11, 0, 0, 0);
            box.Children.Add(link);
            var hint = Ui.Text(L10n.Tr("settings.billing_page_hint"), 10, null, Palette.Secondary, wrap: true);
            hint.Margin = new Thickness(11, 0, 0, 0);
            box.Children.Add(hint);
        }
        return box;
    }

    private Control EmptyForm()
    {
        var box = Ui.V(4);
        var row = Ui.H(8);
        row.Margin = new Thickness(11, 0, 0, 0);
        row.Children.Add(Ui.Text(L10n.Tr("settings.no_subscription_info"), 10, null, Palette.Tertiary));
        row.Children.Add(Ui.BorderedButton(L10n.Tr("settings.add_subscription"), () =>
        {
            SyncInputs(null);
            _editing = true;
            Rebuild();
        }, enabled: CanEdit));
        box.Children.Add(row);
        if (SubscriptionValue.BillingPage(_agent) is { } url)
        {
            var link = Ui.SmallLink(L10n.Tr("settings.open_billing_page"), () => ProjectActions.OpenUrl(url));
            link.Margin = new Thickness(11, 0, 0, 0);
            box.Children.Add(link);
        }
        return box;
    }

    private Control EditingForm(Subscription? sub)
    {
        var box = Ui.V(6);
        box.Margin = new Thickness(11, 0, 0, 0);

        var plans = KnownPlans;
        if (plans.Count > 0)
        {
            var options = plans.Select(p => SubscriptionPlanForm.MenuLabel(p, _currency)).ToList();
            options.Add(L10n.Tr("settings.plan_other"));
            var index = plans.ToList().FindIndex(p => p.Key == _planKey);
            var dropdown = new DropdownControl(options[Math.Max(index, 0)], options, i =>
            {
                _planKey = i < plans.Count ? plans[i].Key : SubscriptionPlanForm.OtherPlanTag;
                if (_planKey != SubscriptionPlanForm.OtherPlanTag) _customPlan = "";
                _price = SubscriptionPlanForm.PriceForSelection(_planKey, sub, plans);
                Rebuild();
            })
            {
                HorizontalAlignment = HorizontalAlignment.Stretch,
            };
            box.Children.Add(dropdown);

            if (_planKey == SubscriptionPlanForm.OtherPlanTag)
            {
                box.Children.Add(SmallField(L10n.Tr("settings.plan"), _customPlan, value => _customPlan = value));
            }
        }
        else
        {
            box.Children.Add(SmallField(L10n.Tr("settings.plan"), _customPlan, value => _customPlan = value));
        }

        var priceRow = Ui.H(8);
        var priceField = new TextBox
        {
            Text = _price,
            Watermark = L10n.Tr("settings.monthly_price_usd"),
            Width = 85,
            FontSize = 11,
            MinHeight = 24,
            Padding = new Thickness(6, 2, 6, 2),
            FontFamily = Type.Mono,
            CornerRadius = new CornerRadius(6),
            Background = Palette.CardBackground,
            BorderBrush = Palette.CardBorder,
            BorderThickness = new Thickness(0.5),
        };
        priceField.TextChanged += (_, _) => _price = priceField.Text ?? "";
        ToolTip.SetTip(priceField, L10n.Tr("settings.monthly_price_usd"));
        priceRow.Children.Add(priceField);
        // 价格框后面是「Renews on day N」+ 步进箭头，顺序和 Mac 一样。
        priceRow.Children.Add(Stepper(!_saving, "settings.renews_on_day", _day));
        box.Children.Add(priceRow);

        var actions = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto,Auto") };
        // Mac：Apply 是 borderedProminent，但禁用时看起来和普通 bordered 一样（快照里就是灰白）。
        var applyButton = _saving
            ? Ui.BorderedButton(L10n.Tr("common.apply"), ApplyManual, enabled: false)
            : Ui.ProminentButton(L10n.Tr("common.apply"), ApplyManual);
        var cancelButton = Ui.BorderedButton(L10n.Tr("common.cancel"), () =>
        {
            _editing = false;
            _error = null;
            SyncInputs(Current);
            Rebuild();
        }, enabled: !_saving);
        cancelButton.Margin = new Thickness(6, 0, 0, 0);
        Grid.SetColumn(applyButton, 1);
        Grid.SetColumn(cancelButton, 2);
        actions.Children.Add(applyButton);
        actions.Children.Add(cancelButton);
        if (sub is not null)
        {
            var remove = Ui.BorderedButton(L10n.Tr("settings.remove_subscription"), RemoveManual, enabled: !_saving);
            remove.Margin = new Thickness(6, 0, 0, 0);
            Grid.SetColumn(remove, 3);
            actions.Children.Add(remove);
        }
        box.Children.Add(actions);
        if (_saving) box.Opacity = 0.7;
        return box;
    }

    private Control SmallField(string label, string value, Action<string> onChange)
    {
        var box = Ui.V(3);
        box.Children.Add(Ui.Text(label, 10.5, null, Palette.Secondary));
        var text = new TextBox
        {
            Text = value,
            FontSize = 11,
            MinHeight = 24,
            Padding = new Thickness(6, 2, 6, 2),
            CornerRadius = new CornerRadius(6),
            Background = Palette.CardBackground,
            BorderBrush = Palette.CardBorder,
            BorderThickness = new Thickness(0.5),
        };
        text.TextChanged += (_, _) => onChange(text.Text ?? "");
        box.Children.Add(text);
        return box;
    }

    /// <summary>
    /// 步进控件（SwiftUI 的 `Stepper(label, value:in:)`）：label 里已经含数字（「Renews on day N」），
    /// 右边只有上下两个小箭头，不额外画数值框。点箭头改 day 后整行重建。
    /// </summary>
    private Control Stepper(bool enabled, string labelKey, int day)
    {
        var row = Ui.H(6);
        row.Children.Add(Ui.Text(L10n.TrL(null, labelKey, day), 11));
        var arrows = Ui.V(0);
        arrows.Children.Add(new Clickable(Icons.ChevronUp(7, Palette.Secondary), () =>
        {
            _day = _day >= 28 ? 1 : _day + 1;
            Rebuild();
        }, radius: 2));
        arrows.Children.Add(new Clickable(Icons.ChevronDown(7, Palette.Secondary), () =>
        {
            _day = _day <= 1 ? 28 : _day - 1;
            Rebuild();
        }, radius: 2));
        if (!enabled)
        {
            arrows.Opacity = 0.55;
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
