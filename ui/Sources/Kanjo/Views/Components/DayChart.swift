import Charts
import SwiftUI
import KanjoCore

/// by_day 时间线：每个活跃日一根柱，x 轴是真实时间（空白日自然留空）。
/// 鼠标悬停显示当天金额与 token；悬停时其他柱子变淡。
struct DayChart: View {
    struct Point: Identifiable {
        let day: String
        let date: Date
        let cost: Double
        let tokens: Int
        var id: String { day }
    }

    let days: [DayCost]
    let currency: String
    /// 柱子颜色：该项目主力 agent 的颜色；悬停的柱子满色，其余略淡。
    var color: Color = AgentPalette.chartBar
    @State private var hovered: Point?

    private var points: [Point] {
        days.compactMap { d in
            ReportDates.parseDay(d.day).map { Point(day: d.day, date: $0, cost: d.cost, tokens: d.tokens) }
        }
        .sorted { $0.date < $1.date }
    }

    var body: some View {
        let pts = points
        VStack(alignment: .leading, spacing: 6) {
            Group {
                if let h = hovered {
                    Text("\(Fmt.day(h.day)) · ")
                        + Text(Fmt.money(h.cost, currency: currency)).fontWeight(.semibold)
                        + Text(" · \(Fmt.tokens(h.tokens)) tokens")
                } else {
                    Text("\(pts.count) active day\(pts.count == 1 ? "" : "s") · hover a bar for daily cost")
                        .foregroundColor(.secondary)
                }
            }
            .font(.system(size: 10.5))
            .monospacedDigit()

            if pts.isEmpty {
                Text("No daily data.").font(.system(size: 11)).foregroundStyle(.secondary)
            } else {
                chart(pts)
                    .frame(height: 110)
            }
        }
    }

    private func chart(_ pts: [Point]) -> some View {
        let cal = Calendar.current
        let lo = cal.date(byAdding: .day, value: -1, to: pts.first!.date)!
        let hi = cal.date(byAdding: .day, value: 1, to: pts.last!.date)!
        return Chart {
            ForEach(pts) { p in
                BarMark(x: .value("Day", p.date, unit: .day),
                        y: .value("Cost", p.cost))
                    .foregroundStyle(color.opacity(hovered == nil || hovered?.day == p.day ? 0.9 : 0.45))
                    .cornerRadius(1.5)
            }
            if let h = hovered {
                RuleMark(x: .value("Day", h.date, unit: .day))
                    .foregroundStyle(Color.primary.opacity(0.22))
                    .lineStyle(StrokeStyle(lineWidth: 1))
            }
        }
        .chartXScale(domain: lo...hi)
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 4)) { _ in
                AxisGridLine().foregroundStyle(Color.primary.opacity(0.06))
                // 显式用 secondaryLabelColor：层级样式 .secondary 在图表里会继承柱子的蓝色，玻璃上发暗。
                AxisValueLabel(format: .dateTime.month(.abbreviated).day(), centered: false)
                    .font(.system(size: 9).monospacedDigit())
                    .foregroundStyle(Color(nsColor: .secondaryLabelColor))
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) { v in
                AxisGridLine().foregroundStyle(Color.primary.opacity(0.08))
                AxisValueLabel {
                    if let d = v.as(Double.self) {
                        Text(axisMoney(d)).font(.system(size: 9).monospacedDigit())
                            .foregroundStyle(Color(nsColor: .secondaryLabelColor))
                    }
                }
            }
        }
        .chartOverlay { proxy in
            GeometryReader { geo in
                Rectangle().fill(Color.clear).contentShape(Rectangle())
                    .onContinuousHover { phase in
                        switch phase {
                        case .active(let loc):
                            let origin = geo[proxy.plotAreaFrame].origin
                            guard let date: Date = proxy.value(atX: loc.x - origin.x) else { hovered = nil; return }
                            hovered = nearest(to: date, in: pts)
                        case .ended:
                            hovered = nil
                        }
                    }
            }
        }
    }

    /// 只在鼠标落在某根柱所在的那一天（±半天）时选中，空白日不选。
    private func nearest(to date: Date, in pts: [Point]) -> Point? {
        let best = pts.min { abs($0.date.addingTimeInterval(43_200).timeIntervalSince(date))
                           < abs($1.date.addingTimeInterval(43_200).timeIntervalSince(date)) }
        guard let b = best, abs(b.date.addingTimeInterval(43_200).timeIntervalSince(date)) <= 43_200 * 1.2 else { return nil }
        return b
    }

    private func axisMoney(_ v: Double) -> String {
        if v == v.rounded() { return "$" + String(Int(v)) }
        return String(format: "$%.1f", v)
    }
}
