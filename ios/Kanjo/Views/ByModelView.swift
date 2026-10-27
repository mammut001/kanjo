import KanjoCore
import SwiftUI

struct ByModelView: View {
    let report: UsageReport
    let range: TimeRange

    private var models: [ModelCost] {
        let spec = RangeEngine.spec(range, report: report)
        let filtered = RangeEngine.filtered(report, range: spec, fallbackAgentFor: OverviewView.fallbackAgent)
        return ModelAggregation.aggregate(in: filtered)
    }

    var body: some View {
        List {
            if models.isEmpty {
                Text(L10n.tr("overview.models.no_usage_range"))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                Section {
                    ForEach(models) { model in
                        ModelRowView(model: model, currency: report.currency)
                            .listRowInsets(EdgeInsets())
                    }
                } header: {
                    Text(range.longLabel)
                } footer: {
                    Text(L10n.tr("ios.updated", Fmt.timestamp(report.generatedAt)))
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(L10n.tr("ios.all_models"))
        .navigationBarTitleDisplayMode(.inline)
    }
}
