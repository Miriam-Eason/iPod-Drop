import AppKit
import SwiftUI
import UniformTypeIdentifiers
import Combine

struct Request: Encodable, Sendable {
    var action: String
    var root: String? = nil
    var paths: [String]? = nil
    var pids: [String]? = nil
}
struct Song: Decodable, Identifiable, Sendable {
    var pid: String
    var title: String
    var artist: String
    var album: String
    var ms: Int
    var size: Int64
    var path: String
    var id: String { pid }
}
struct Reply: Decodable, Sendable {
    var ok: Bool
    var error: String?
    var root: String?
    var name: String?
    var count: Int?
    var free: Int64?
    var total: Int64?
    var message: String?
    var backup: String?
    var added: Int?
    var deleted: Int?
    var songs: [Song]?
}
enum EngineError: LocalizedError {
    case detail(String)
    var errorDescription: String? {
        switch self { case .detail(let message): return message }
    }
}
enum Engine {
    @concurrent static func perform(_ request: Request) async throws -> Reply {
        guard let resources = Bundle.main.resourceURL else { throw EngineError.detail("应用文件不完整。") }
        let process = Process()
        process.executableURL = resources.appending(path: "Engine/ipod-engine")
        let input = Pipe(), output = Pipe()
        process.standardInput = input
        process.standardOutput = output
        // Errors go to a file so neither pipe can block a long import.
        let log = FileManager.default.temporaryDirectory.appending(path: "ipod-drop-\(UUID()).log")
        FileManager.default.createFile(atPath: log.path, contents: nil)
        let errorFile = try FileHandle(forWritingTo: log)
        process.standardError = errorFile
        defer { try? errorFile.close(); try? FileManager.default.removeItem(at: log) }
        try process.run()
        try input.fileHandleForWriting.write(contentsOf: JSONEncoder().encode(request))
        try input.fileHandleForWriting.close()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let details = (try? String(contentsOf: log, encoding: .utf8)) ?? ""
            throw EngineError.detail("导入引擎未能运行。\n" + details.suffix(2000))
        }
        let reply = try JSONDecoder().decode(Reply.self, from: data)
        guard reply.ok else { throw EngineError.detail(reply.error ?? "操作未完成。") }
        return reply
    }
}

@MainActor final class ImportModel: ObservableObject {
    @Published var device: Reply?
    @Published var pending: [URL] = []
    @Published var busy = false
    @Published var status = "正在查找 iPod…"
    @Published var problem = false
    @Published var backup: String?
    @Published var automatic = true
    @Published var refreshing = false
    @Published var detail = ""
    @Published var songs: [Song] = []
    @Published var selection = Set<String>()
    @Published var libraryOpen = false
    @Published var loadingSongs = false
    func refresh() async {
        guard !busy && !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            device = try await Engine.perform(Request(action: "status"))
            if status == "正在查找 iPod…" || problem { status = "可以导入，原有歌曲会保留。"; problem = false }
        } catch {
            device = nil
            if !busy { status = error.localizedDescription; problem = true }
        }
    }
    func add(_ urls: [URL]) {
        guard !busy else { return }
        for url in urls where !pending.contains(url) { pending.append(url) }
        if automatic && device != nil { Task { await start() } }
    }
    func choose() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.mp3, .folder]
        panel.canChooseDirectories = true
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = true
        panel.prompt = "加入导入"
        if panel.runModal() == .OK { add(panel.urls) }
    }
    func start() async {
        guard !busy, let device, !pending.isEmpty else { return }
        busy = true; problem = false; status = "正在检查重复、备份曲库并导入，请保持连接…"
        let files = pending
        do {
            let result = try await Engine.perform(Request(action: "import", root: device.root, paths: files.map(\.path)))
            status = result.message ?? "导入完成。"
            if let path = result.backup { backup = path }
            pending.removeAll(); detail = "歌曲复制与签名检查已通过。"
        } catch { status = error.localizedDescription; problem = true; detail = "请检查提示后重试，原始文件仍在电脑上。" }
        busy = false
        // Keep the import result visible while updating the device count.
        let message = status, failed = problem
        await refresh()
        status = message; problem = failed
    }
    func openLibrary() async {
        libraryOpen = true
        await loadSongs()
    }
    func loadSongs() async {
        guard let device else { songs = []; selection.removeAll(); return }
        loadingSongs = true
        defer { loadingSongs = false }
        do {
            let result = try await Engine.perform(Request(action: "songs", root: device.root))
            songs = result.songs ?? []
            let valid = Set(songs.map(\.pid))
            selection = selection.intersection(valid)
        } catch {
            status = error.localizedDescription
            problem = true
        }
    }
    func deleteSelected() async {
        guard !busy, !selection.isEmpty, let device else { return }
        busy = true; problem = false; status = "正在备份曲库并删除选中歌曲，请保持连接…"
        do {
            let result = try await Engine.perform(Request(action: "delete", root: device.root, pids: Array(selection)))
            status = result.message ?? "删除完成。"
            detail = "删除前已自动备份曲库；电脑上的原 MP3 未改动。"
            selection.removeAll()
        } catch {
            status = error.localizedDescription
            problem = true
            detail = "删除未完成，曲库已按事务记录恢复。"
        }
        busy = false
        await refresh()
        await loadSongs()
    }
    func eject() async {
        guard !busy, let root = device?.root else { return }
        busy = true
        do { let result = try await Engine.perform(Request(action: "eject", root: root)); status = result.message ?? "已弹出。"; device = nil; problem = false }
        catch { status = error.localizedDescription; problem = true }
        busy = false
    }
    func recover() async {
        guard !busy else { return }
        let panel = NSOpenPanel(); panel.directoryURL = URL(filePath: "/Volumes")
        panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.prompt = "选择 iPod 磁盘"
        guard panel.runModal() == .OK, let root = panel.url else { return }
        busy = true
        do { let result = try await Engine.perform(Request(action: "recover", root: root.path)); status = result.message ?? "恢复完成。"; problem = false }
        catch { status = error.localizedDescription; problem = true }
        busy = false; await refresh()
    }
}

struct ContentView: View {
    @ObservedObject var model: ImportModel
    @State private var targeted = false
    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack(spacing: 13) {
                Image(systemName: "ipod").font(.system(size: 36)).foregroundStyle(.blue)
                VStack(alignment: .leading, spacing: 5) {
                    Text("iPod Drop").font(.system(size: 25, weight: .semibold, design: .rounded))
                    Text("把喜欢的歌，放回口袋。 ").foregroundStyle(.secondary)
                }
                Spacer()
                Label(model.device == nil ? "未就绪" : "已连接", systemImage: model.device == nil ? "circle" : "checkmark.circle.fill")
                    .font(.callout).foregroundStyle(model.device == nil ? Color.secondary : Color.green)
            }
            HStack {
                VStack(alignment: .leading, spacing: 6) {
                    Text(model.device?.name ?? "连接你的 iPod nano").fontWeight(.medium)
                    if let device = model.device {
                        Text("\(device.count ?? 0) 首歌曲 · 可用 \(ByteCountFormatter.string(fromByteCount: device.free ?? 0, countStyle: .file))")
                            .font(.callout).foregroundStyle(.secondary)
                    } else { Text("支持 nano 6 / 7，需显示为可读写磁盘").font(.callout).foregroundStyle(.secondary) }
                }
                Spacer()
                Button { Task { await model.openLibrary() } } label: { Label("管理歌曲", systemImage: "music.note.list") }.help("查看或删除 iPod 上的歌曲")
                    .disabled(model.busy || model.device == nil)
                Button { Task { await model.refresh() } } label: { Image(systemName: "arrow.clockwise") }.help("刷新设备")
                    .disabled(model.busy)
            }.padding(16).background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 14))
            VStack(spacing: 12) {
                Image(systemName: "music.note.list").font(.system(size: 42, weight: .light)).foregroundStyle(.blue)
                Text(targeted ? "松开，开始导入" : "把 MP3 拖到这里").font(.title2.weight(.medium))
                Text("一次拖入多首，或整个歌曲文件夹").foregroundStyle(.secondary)
                Button("选择歌曲…") { model.choose() }.controlSize(.large).disabled(model.busy)
                if !model.pending.isEmpty { Text("已加入 \(model.pending.count) 个文件或文件夹").font(.callout) }
            }
            .frame(maxWidth: .infinity, minHeight: 205)
            .background(targeted ? Color.blue.opacity(0.1) : Color.blue.opacity(0.035), in: RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(Color.blue.opacity(targeted ? 0.8 : 0.25), style: StrokeStyle(lineWidth: 1.5, dash: [7,5])))
            .dropDestination(for: URL.self) { urls, _ in
                guard !model.busy else { return false }
                model.add(urls); return true
            } isTargeted: { targeted = $0 }
            HStack {
                Toggle("拖入后自动导入", isOn: $model.automatic).toggleStyle(.checkbox).disabled(model.busy)
                Spacer()
                if !model.pending.isEmpty {
                    Button("清空") { model.pending.removeAll() }.disabled(model.busy)
                    Button("开始导入") { Task { await model.start() } }.buttonStyle(.borderedProminent).disabled(model.busy || model.device == nil)
                }
            }
            HStack(alignment: .top, spacing: 10) {
                if model.busy { ProgressView().controlSize(.small) }
                else { Image(systemName: model.problem ? "exclamationmark.circle" : "checkmark.shield").foregroundStyle(model.problem ? .orange : .green) }
                VStack(alignment: .leading, spacing: 5) {
                    Text(model.status).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    Text(model.detail.isEmpty ? "可追加或删除歌曲 · 自动备份曲库 · 相同文件自动跳过" : model.detail)
                        .font(.caption).foregroundStyle(.secondary)
                }
            }.frame(minHeight: 55, alignment: .topLeading)
            Divider()
            HStack {
                Button("查看备份") { NSWorkspace.shared.open(URL(filePath: model.backup ?? NSHomeDirectory()+"/Library/Application Support/iPod Drop/Backups")) }
                if model.problem { Button("恢复上次曲库") { Task { await model.recover() } }.disabled(model.busy) }
                Spacer()
                Button("安全弹出") { Task { await model.eject() } }.disabled(model.device == nil || model.busy)
            }
            Text("导入时请勿同时运行 Finder / 音乐中的同步。新版歌曲封面暂不写入。").font(.caption).foregroundStyle(.secondary)
        }
        .padding(28).frame(width: 590)
        .task { await model.refresh() }
        .sheet(isPresented: $model.libraryOpen) { SongManagerView(model: model) }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didMountNotification)) { _ in Task { await model.refresh() } }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didUnmountNotification)) { _ in Task { await model.refresh() } }
    }
}

struct SongManagerView: View {
    @ObservedObject var model: ImportModel
    @Environment(\.dismiss) private var dismiss
    @State private var search = ""
    @State private var confirmDelete = false

    private var filtered: [Song] {
        let query = search.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !query.isEmpty else { return model.songs }
        return model.songs.filter {
            $0.title.lowercased().contains(query) ||
            $0.artist.lowercased().contains(query) ||
            $0.album.lowercased().contains(query)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("iPod 曲库").font(.system(size: 23, weight: .semibold, design: .rounded))
                    Text("勾选歌曲后可从设备删除；电脑上的原文件不会被删。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("关闭") { dismiss() }
            }
            .padding(20)
            Divider()
            HStack(spacing: 9) {
                TextField("搜索歌名、歌手或专辑", text: $search)
                    .textFieldStyle(.roundedBorder)
                Button("全选可见") {
                    model.selection.formUnion(filtered.map(\.pid))
                }
                Button("取消选择") { model.selection.removeAll() }
            }
            .padding(.horizontal, 20).padding(.vertical, 12)
            Divider()

            if model.loadingSongs {
                VStack(spacing: 10) {
                    ProgressView()
                    Text("正在读取 iPod 曲库…").font(.callout).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if filtered.isEmpty {
                Text(search.isEmpty ? "曲库是空的。" : "没有匹配的歌曲。")
                    .foregroundStyle(.secondary).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(filtered) { song in
                            HStack(spacing: 12) {
                                Toggle("", isOn: selectedBinding(song.pid)).labelsHidden().toggleStyle(.checkbox)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(song.title.isEmpty ? "未命名歌曲" : song.title)
                                        .fontWeight(.medium).lineLimit(1)
                                    Text([song.artist, song.album].filter { !$0.isEmpty }.joined(separator: " · "))
                                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                }
                                Spacer(minLength: 8)
                                Text(duration(song.ms)).font(.caption).monospacedDigit().foregroundStyle(.secondary)
                            }
                            .padding(.horizontal, 20).padding(.vertical, 9)
                            if song.id != filtered.last?.id { Divider().padding(.leading, 52) }
                        }
                    }
                }
                .frame(maxHeight: .infinity)
            }

            Divider()
            HStack {
                Text("共 \(model.songs.count) 首 · 已选 \(model.selection.count) 首")
                    .font(.callout).foregroundStyle(.secondary)
                Spacer()
                Button("删除选中…") { confirmDelete = true }
                    .buttonStyle(.borderedProminent).tint(.red)
                    .disabled(model.selection.isEmpty || model.busy)
            }
            .padding(20)
            if model.busy {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(model.status).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }.padding(.horizontal, 20).padding(.bottom, 12)
            }
        }
        .frame(width: 650, height: 580)
        .confirmationDialog("从 iPod 删除 \(model.selection.count) 首歌曲？",
                            isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("删除", role: .destructive) { Task { await model.deleteSelected() } }
            Button("取消", role: .cancel) {}
        } message: {
            Text("电脑上的原 MP3 不会被删除。删除前会自动备份曲库。")
        }
    }

    private func selectedBinding(_ pid: String) -> Binding<Bool> {
        Binding(
            get: { model.selection.contains(pid) },
            set: { selected in
                if selected { model.selection.insert(pid) } else { model.selection.remove(pid) }
            }
        )
    }

    private func duration(_ ms: Int) -> String {
        let seconds = max(0, ms / 1000)
        return "\(seconds / 60):\(String(format: "%02d", seconds % 60))"
    }
}

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    var model: ImportModel?
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if model?.busy == true {
            let alert = NSAlert(); alert.messageText = "正在导入歌曲"; alert.informativeText = "请等待本次导入结束后再退出。"; alert.runModal()
            return .terminateCancel
        }
        return .terminateNow
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { model?.busy != true }
}
@main struct iPodDropApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = ImportModel()
    var body: some Scene {
        WindowGroup("iPod Drop") {
            ContentView(model: model).onAppear { delegate.model = model; NSApp.activate(ignoringOtherApps: true) }
        }.windowResizability(.contentSize).defaultPosition(.center)
    }
}
