import AppKit
import SwiftUI
import AICostCore

struct SettingsView: View {
    @EnvironmentObject var store: ReportStore
    let onBack: () -> Void

    @AppStorage(SettingsKeys.sourceKind) private var sourceKind =
        (DefaultPaths.cliDirectoryExists ? SourceKind.cli : SourceKind.file).rawValue
    @AppStorage(SettingsKeys.filePath) private var filePath = ""
    @AppStorage(SettingsKeys.cliCommand) private var cliCommand = CLIDataSource.defaultCommand
    @AppStorage(SettingsKeys.cliWorkingDirectory) private var cliWorkingDirectory = ""
    @AppStorage(SettingsKeys.refreshMinutes) private var refreshMinutes = 5
    @AppStorage(SettingsKeys.showAmountInMenuBar) private var showAmount = true

    private let intervals = [0, 1, 5, 15, 30, 60]

    var body: some View {
        ScrollView {
            GlassGroup(spacing: 6) {
                VStack(alignment: .leading, spacing: 12) {
                    BackButton(title: "Done", action: onBack)
                    Text("Settings").font(.system(size: 17, weight: .bold))

                    if let o = store.dataOverride {
                        Text("Launched with --data / AICOST_DATA: \(o.path). This overrides the data source below until the app is restarted without it.")
                            .font(.system(size: 10.5, weight: .medium)).foregroundStyle(AgentPalette.warnInk)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .glassSurface(cornerRadius: 12, tint: AgentPalette.warnTint, fallbackFill: AgentPalette.warnFill)
                    }

                    SectionCard("Data source") {
                        Picker("Source", selection: $sourceKind) {
                            ForEach(SourceKind.allCases) { Text($0.label).tag($0.rawValue) }
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()

                        if sourceKind == SourceKind.cli.rawValue {
                            field("Command", text: $cliCommand, placeholder: CLIDataSource.defaultCommand)
                            HStack(alignment: .bottom) {
                                field("Working directory (cli/ path)", text: $cliWorkingDirectory,
                                      placeholder: DefaultPaths.cliDirectoryExists ? DefaultPaths.cliDirectory.path : "Inherit")
                                Button("Choose…") { if let p = chooseFolder() { cliWorkingDirectory = p } }.glassButtonStyle()
                            }
                            note("Runs via /bin/zsh -l -c and reads aicost export JSON from stdout.")
                        } else {
                            HStack(alignment: .bottom) {
                                field("JSON file", text: $filePath, placeholder: DefaultPaths.sampleFixture.path)
                                Button("Choose…") { if let p = chooseFile() { filePath = p } }.glassButtonStyle()
                            }
                            note("Leave empty to use the bundled sample: fixtures/sample.json.")
                        }
                    }

                    SectionCard("Refresh") {
                        Picker("Auto refresh", selection: $refreshMinutes) {
                            ForEach(intervals, id: \.self) { m in
                                Text(m == 0 ? "Off" : "Every \(m) min").tag(m)
                            }
                        }
                        .font(.system(size: 11.5))
                        Toggle("Show total cost in menu bar", isOn: $showAmount)
                            .font(.system(size: 11.5))
                    }

                    HStack {
                        Spacer()
                        Button("Apply & Refresh") { store.applySettings() }
                            .keyboardShortcut(.defaultAction)
                            .glassButtonStyle(prominent: true)
                    }
                    Text("Current source — \(store.sourceDescription)")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(10)
            }
        }
        .onChange(of: refreshMinutes) { _ in store.restartTimer() }
        .onChange(of: sourceKind) { _ in store.applySettings() }
    }

    private func field(_ label: String, text: Binding<String>, placeholder: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.system(size: 10.5)).foregroundStyle(.secondary)
            TextField(placeholder, text: text)
                .textFieldStyle(.roundedBorder)
                .font(.system(size: 11, design: .monospaced))
                .onSubmit { store.applySettings() }
        }
    }

    private func note(_ s: String) -> some View {
        Text(s).font(.system(size: 10)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }

    private func chooseFile() -> String? {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.json]
        p.canChooseDirectories = false
        p.allowsMultipleSelection = false
        NSApp.activate(ignoringOtherApps: true)
        return p.runModal() == .OK ? p.url?.path : nil
    }

    private func chooseFolder() -> String? {
        let p = NSOpenPanel()
        p.canChooseFiles = false
        p.canChooseDirectories = true
        p.allowsMultipleSelection = false
        NSApp.activate(ignoringOtherApps: true)
        return p.runModal() == .OK ? p.url?.path : nil
    }
}
