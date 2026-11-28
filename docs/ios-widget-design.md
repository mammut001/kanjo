# Kanjo iOS 小组件：设计草案（待确认）

状态：草案，未开工。确认后再写代码。

## 1. 目标

不用打开 App 就能在主屏和锁屏上看到两件事：**今天花了多少**、**额度还剩多少**。
另外这也是应对审核指南 4.2（最低功能）的主要理由：iPhone 版不只是“Mac 数据查看器”。

不在首版里做：可交互小组件（按钮刷新）、灵动岛 / 实时活动、Apple Watch。

## 2. 小组件清单

| # | 名称 | 尺寸 | 内容 |
|---|---|---|---|
| W1 | 今天 | 主屏小 | 今天花费（大字）+ 对比昨天 ↑↓ + 最近 14 天热力条（沿用 App 的 HeatStrip 配色，作为记忆点） |
| W2 | 额度 | 主屏小 / 中 | 小：一个 agent 的 5 小时 + 每周两条进度条和重置倒计时；中：左边今天花费，右边两个 agent 的额度 |
| W3 | 额度圆环 | 锁屏圆形 | 一个 agent 的每周已用 %（圆环 Gauge），中间显示数字 |
| W4 | 今天 + 5 小时 | 锁屏矩形 | 第一行今天花费，第二行 “Claude 5h 62% · 1h20m 后重置” |
| W5 | 一行 | 锁屏时钟上方 | “今天 $12.40” |

- W2 / W3 / W4 可在编辑小组件时选 agent（AppIntent 配置）。默认选“额度数据最新的那个 agent”，通常是 Claude。
- 只显示有额度数据的 agent；选中的 agent 没有额度时显示“无额度数据”。
- **锁屏和主屏都不显示项目名**。锁屏别人看得到，而且不显示项目名就不用再加隐私开关。

## 3. 数据怎么到小组件

```
App 每次加载成功 ─┐
                  ├→ App Group 缓存（瘦身 JSON，只含小组件要用的字段）→ 小组件读取
小组件定时刷新 ──┘    （小组件自己也会去 iCloud 拉一次，失败就用缓存）
```

- 新增 App Group `group.com.lanshuagent.kanjo`，App 和小组件扩展都加这个权限。
- 缓存文件 `widget-snapshot.json` 只放：`generatedAt`、`deviceName`、`timezone`、`currency`、
  按天的总花费（最近 15 天）、`quota_windows`。几 KB 大小，不含项目信息。
- 小组件的时间线：
  - 每 30 分钟请求一次刷新（系统有预算，实际可能更久）。刷新时先读 KVS / CloudKit（复用现有 `CloudKitSnapshotSource` 的拉取逻辑，挪进共享代码），8 秒超时，超时就用缓存。
  - 额度重置的时刻额外加一条时间线：一到重置点，进度条自动变成“已重置”，不会继续显示旧百分比。
  - 倒计时用系统的 `Text(date, style: .relative)`，不用为了倒计时频繁刷新。
- App 侧：加载成功后写缓存并调用 `WidgetCenter.reloadAllTimelines()`；注册后台刷新（BGAppRefreshTask），在后台也能更新缓存。
- 示例数据模式：**不写**缓存，避免示例数据跑到真实小组件上。小组件库里的预览图用内置示例数据。

## 4. 过期和异常状态

| 情况 | 显示 |
|---|---|
| 正常 | 角落小字“10:42 更新” |
| 快照超过 2 小时 | 数字变灰，角落显示“3 小时前”（Mac 可能休眠了） |
| 跨天了但还没有新快照 | 今天花费显示 “—”，不拿昨天的数冒充今天 |
| 从没同步过 | “打开 Kanjo 设置同步”，点击打开 App |
| 额度窗口已过重置点 | “已重置”，不显示旧百分比 |

点击任意小组件 → 打开 App 总览页。

## 5. 工程改动

- `ios/project.yml`：新增 target `KanjoWidget`（app-extension，bundle id `com.lanshuagent.kanjo.ios.widget`），
  依赖 KanjoCore；主 App 内嵌它。两边 entitlements 都加 App Group；小组件也加 iCloud（CloudKit + KVS）权限，否则拉不到数据。
- 新建 `ios/Shared/`：缓存模型 `WidgetSnapshot` + 读写、从 `UsageReport` 生成的函数、拉取逻辑。App 和小组件都编译这份代码。
- 今天花费的计算放进 KanjoCore（按 timezone 汇总 `projects[].by_day`），配单元测试：跨时区、跨天、缺数据。
- 本地化：中英法三语，key 放在现有 L10n 里。
- `PrivacyInfo.xcprivacy`：小组件扩展也要一份（UserDefaults / App Group 读写）。

## 6. 需要你在开发者后台做的

Xcode 自动签名会自动建 App Group 和新的 App ID，一般不用手动操作。如果自动签名报错：
1. Identifiers → 新建 App Group `group.com.lanshuagent.kanjo`；
2. 给 `com.lanshuagent.kanjo.ios` 和 `com.lanshuagent.kanjo.ios.widget` 都勾上 App Groups 和 iCloud（同一个容器）。

## 7. 验收

- 单元测试：今天花费的计算、缓存写读、过期判断、重置点判断。
- 模拟器截图：5 个小组件 × 浅色 / 深色 × 正常 / 过期 / 无数据，我先看一遍再给你。
- 真机：Mac 刷新后 30 分钟内小组件更新（受系统预算影响，只能大致验证）。

## 8. 已确认（2026-11-28）

1. 5 个小组件全做。
2. 热力条：小尺寸显示最近 7 天，中尺寸显示 14 天。
3. 小组件里的金额不标“估算”，只在 App 里标。
