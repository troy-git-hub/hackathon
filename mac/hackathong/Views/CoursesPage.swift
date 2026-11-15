//
//  CoursesPage.swift
//  Echo — 课程管理（对应 floating_window 的 COURSES 页）
//  搜索 / 全选 / 批量删除 / 批量重命名 / 看回顾
//

import SwiftUI

struct CourseRowVM: Identifiable, Equatable {
    let id: Double            // 开课时间戳，作为课程 ID
    var name: String
    var date: String
    var points: Int
    var minutes: Int
    var review: Int

    var detail: String {
        var bits = [date]
        if points > 0 { bits.append(tr("\(points) 个知识点", "\(points) concepts")) }
        if minutes > 0 { bits.append(tr("\(minutes) 分钟", "\(minutes) min")) }
        if review > 0 { bits.append(tr("\(review) 个待复习", "\(review) to review")) }
        return bits.joined(separator: " · ")
    }
}

struct CoursesPage: View {
    var rows: [CourseRowVM]
    var onOpen: (Double) -> Void
    var onRename: (Double, String) -> Void
    var onDelete: ([Double]) -> Void

    @State private var query = ""
    @State private var checked: Set<Double> = []
    @State private var renaming: CourseRowVM?
    @State private var renameText = ""
    @State private var confirmDelete = false
    @State private var notice: String?

    private var filtered: [CourseRowVM] {
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return rows }
        return rows.filter { $0.name.lowercased().contains(q) || $0.date.contains(q) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 2) {
                Text(tr("课程管理", "Course manager")).pageTitle()
                Text(subtitle).caption().wrap()
            }
            TextField(tr("搜索课程名或日期，例如「数学」或「10-02」…", "Search by lesson name or date, e.g. \"Math\" or \"10-02\"…"),
                      text: $query)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .padding(.horizontal, 10).padding(.vertical, 7)
                .background(Palette.surface.opacity(0.7), in: .rect(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Palette.border))

            HStack(spacing: Spacing.sm) {
                Button(checked.count == filtered.count && !filtered.isEmpty
                       ? tr("取消全选", "Clear selection") : tr("全选", "Select all")) {
                    if checked.count == filtered.count { checked.removeAll() }
                    else { checked = Set(filtered.map(\.id)) }
                }
                .buttonStyle(QuietButtonStyle(expand: false))
                Button(tr("批量删除", "Delete selected")) {
                    if checked.isEmpty { notice = tr("先勾选要删除的课程。", "Check the lessons you want to delete first.") }
                    else { confirmDelete = true }
                }
                .buttonStyle(QuietButtonStyle(expand: false))
                .help(tr("删除勾选的课程（不可恢复）", "Delete the checked lessons (cannot be undone)"))
                Button(tr("批量重命名", "Rename selected")) {
                    guard !checked.isEmpty else {
                        notice = tr("先勾选要重命名的课程。", "Check the lessons you want to rename first.")
                        return
                    }
                    if checked.count == 1, let only = rows.first(where: { checked.contains($0.id) }) {
                        startRename(only)
                    } else {
                        notice = tr("请逐个重命名，或先只勾选一节。", "Rename one at a time, or check a single lesson.")
                    }
                }
                .buttonStyle(QuietButtonStyle(expand: false))
                .help(tr("给勾选的课程统一改名", "Rename the checked lessons"))
            }

            if filtered.isEmpty {
                Text(tr("还没有上过课。", "No lessons yet."))
                    .font(.system(size: 13)).foregroundStyle(Palette.textSecondary)
            }
            ForEach(filtered) { row in
                card(row)
            }
        }
        .alert(tr("批量删除", "Delete selected"), isPresented: $confirmDelete) {
            Button(tr("取消", "Cancel"), role: .cancel) {}
            Button(tr("删除", "Delete"), role: .destructive) {
                onDelete(Array(checked))
                checked.removeAll()
            }
        } message: {
            Text(tr("确定删除选中的 \(checked.count) 节课吗？删除后不可恢复。",
                    "Delete the \(checked.count) selected lessons? This cannot be undone."))
        }
        .alert(tr("重命名", "Rename"), isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField(tr("新的课程名：", "New lesson name:"), text: $renameText)
            Button(tr("取消", "Cancel"), role: .cancel) { renaming = nil }
            Button(tr("确定", "OK")) {
                if let r = renaming, !renameText.trimmingCharacters(in: .whitespaces).isEmpty {
                    onRename(r.id, renameText.trimmingCharacters(in: .whitespaces))
                }
                renaming = nil
            }
        }
        .alert(notice ?? "", isPresented: Binding(get: { notice != nil }, set: { if !$0 { notice = nil } })) {
            Button(tr("好", "OK"), role: .cancel) { notice = nil }
        }
    }

    private var subtitle: String {
        var s = tr("共 \(rows.count) 节课", "\(rows.count) lessons")
        if !query.isEmpty { s += tr(" · 匹配 \(filtered.count) 节", " · \(filtered.count) matched") }
        return s
    }

    private func startRename(_ row: CourseRowVM) {
        renameText = row.name
        renaming = row
    }

    private func card(_ row: CourseRowVM) -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Toggle("", isOn: Binding(
                get: { checked.contains(row.id) },
                set: { on in
                    if on { checked.insert(row.id) } else { checked.remove(row.id) }
                }))
                .labelsHidden()
                .toggleStyle(.checkbox)
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 2) {
                Text(row.name).font(.system(size: 13, weight: .bold)).foregroundStyle(Palette.textPrimary).wrap()
                Text(row.detail).font(.system(size: 11)).foregroundStyle(Palette.textSecondary).wrap()
            }
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 4) {
                Button(tr("重命名", "Rename")) { startRename(row) }.buttonStyle(LinkButtonStyle())
                Button(tr("看回顾", "Review")) { onOpen(row.id) }.buttonStyle(QuietButtonStyle(expand: false))
            }
        }
        .card()
    }
}
