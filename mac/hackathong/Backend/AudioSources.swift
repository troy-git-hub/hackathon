//
//  AudioSources.swift
//  Echo - 课程音频来源（对应 Python echo/backend/sources.py）
//    system : ScreenCaptureKit 抓电脑正在播放的声音（腾讯会议 / Zoom / B站 / 录播课，戴耳机也行）→ Apple 语音识别
//    mic    : 麦克风 → Apple 语音识别
//    demo   : 回放 DemoLesson 讲稿（离线兜底）
//

import AVFoundation
import Foundation
import ScreenCaptureKit
import Speech

protocol AudioSource: AnyObject {
    /// 课程总时长（秒）；实时课程为 0
    var totalSeconds: Double { get }
    func start()
    func stop()
}

// MARK: - demo

/// 读取 `时间码 文本` 格式的讲稿，# 开头为注释。
func loadScript(_ text: String = DemoLesson.script) -> [(t: Double, text: String)] {
    var lines: [(t: Double, text: String)] = []
    for raw in text.split(separator: "\n") {
        let raw = raw.trimmingCharacters(in: .whitespaces)
        if raw.isEmpty || raw.hasPrefix("#") { continue }
        let parts = raw.split(separator: " ", maxSplits: 1)
        if let t = parseTC(String(parts[0])), parts.count == 2 {
            lines.append((t, parts[1].trimmingCharacters(in: .whitespaces)))
        } else {
            lines.append(((lines.last?.t ?? -10) + 10, raw))
        }
    }
    return lines
}

final class DemoSource: AudioSource {
    private weak var engine: EchoEngine?
    private let lines = loadScript()
    private var task: Task<Void, Never>?
    private let lesson: Int

    var totalSeconds: Double { lines.last?.t ?? 0 }

    init(engine: EchoEngine) {
        self.engine = engine
        lesson = engine.lesson
    }

    func start() {
        task = Task { [weak self] in
            guard let self else { return }
            for (t, text) in lines {
                try? await Task.sleep(for: .seconds(EchoConfig.demoLineInterval))
                if Task.isCancelled { return }
                engine?.addTranscript(text, t: t, lesson: lesson)
                // demo 没有真实音频：读一句时给声纹一个起伏
                for v in [0.55, 0.8, 0.4, 0.65, 0.2, 0.0] {
                    engine?.setLevel(v, lesson: lesson)
                    try? await Task.sleep(for: .milliseconds(80))
                }
            }
        }
    }

    func stop() { task?.cancel() }
}

// MARK: - 实时语音（系统声音 / 麦克风）

final class LiveSpeechSource: AudioSource {
    enum Capture { case system, mic }

    private weak var engine: EchoEngine?
    private let capture: Capture
    private var pipe: SpeechPipe?
    private var mic: AVAudioEngine?
    private var system: SystemAudioCapture?
    private var hotWordTask: Task<Void, Never>?
    private var meterTask: Task<Void, Never>?
    private let meter = LevelMeter()
    private let lesson: Int
    private var stopped = false

    let totalSeconds: Double = 0

    init(engine: EchoEngine, capture: Capture) {
        self.engine = engine
        self.capture = capture
        lesson = engine.lesson
    }

    func start() {
        Task { [weak self] in
            guard let self else { return }
            do {
                try await self.run()
            } catch {
                print("[echo.asr] 音频采集失败: \(error)")
                self.engine?.reportError("音频采集失败：\(error.localizedDescription)", lesson: self.lesson)
            }
        }
    }

    private func run() async throws {
        let lesson = lesson
        engine?.setStatus(.loadingASR)
        guard await SpeechPipe.authorize() else {
            throw LLMError(message: "没有语音识别权限，请在 系统设置 → 隐私与安全性 → 语音识别 里允许 Echo")
        }
        let pipe = try SpeechPipe(pause: EchoConfig.asrPause, maxSentence: EchoConfig.asrMaxSentence) { [weak self] text, t0 in
            Task { @MainActor in self?.engine?.addTranscript(text, t: t0, lesson: lesson) }
        }
        // 句子起点用课堂时钟
        let clockStart = Date().addingTimeInterval(-(engine?.elapsed() ?? 0))
        pipe.clock = { Date().timeIntervalSince(clockStart) }
        self.pipe = pipe

        guard !stopped else { return }   // 等权限期间已经停课
        let meter = meter
        let feed: (AVAudioPCMBuffer) -> Void = { buffer in
            meter.feed(buffer)
            pipe.append(buffer)
        }
        switch capture {
        case .mic: try startMic(feed)
        case .system: try await startSystem(feed)
        }
        pipe.start()
        if engine?.lesson == lesson { engine?.setStatus(.listening) }

        // 真实声纹：约 20Hz 把响度交给 UI
        meterTask = Task { [weak self] in
            while !Task.isCancelled {
                if let self { self.engine?.setLevel(self.meter.read(), lesson: lesson) }
                try? await Task.sleep(for: .milliseconds(50))
            }
        }

        // 用时间轴上已识别出的知识点当热词，减少同音错字（如「备叶思」→「贝叶斯」）
        hotWordTask = Task { [weak self] in
            while !Task.isCancelled {
                if let words = self?.engine?.hotWords() { self?.pipe?.setHotWords(words) }
                try? await Task.sleep(for: .seconds(10))
            }
        }
    }

    private func startMic(_ feed: @escaping (AVAudioPCMBuffer) -> Void) throws {
        let engine = AVAudioEngine()
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in
            feed(buffer)
        }
        engine.prepare()
        try engine.start()
        mic = engine
    }

    private func startSystem(_ feed: @escaping (AVAudioPCMBuffer) -> Void) async throws {
        let cap = SystemAudioCapture(onBuffer: feed)
        try await cap.start()
        system = cap
    }

    func stop() {
        stopped = true
        hotWordTask?.cancel()
        meterTask?.cancel()
        mic?.inputNode.removeTap(onBus: 0)
        mic?.stop()
        mic = nil
        if let system { Task { await system.stop() } }
        system = nil
        pipe?.stop()
        pipe = nil
    }
}

// MARK: - 声纹响度

/// 音频线程写、主线程读的响度表：取最近一段的 RMS 峰值，读完清零（没声音就自然回落到 0）。
nonisolated final class LevelMeter: @unchecked Sendable {
    private let lock = NSLock()
    private var peak: Float = 0

    func feed(_ buffer: AVAudioPCMBuffer) {
        guard let data = buffer.floatChannelData, buffer.frameLength > 0 else { return }
        let n = Int(buffer.frameLength)
        var sum: Float = 0
        for i in 0..<n { let v = data[0][i]; sum += v * v }
        let rms = (sum / Float(n)).squareRoot()
        lock.withLock { peak = max(peak, rms) }
    }

    func read() -> Double {
        lock.withLock {
            defer { peak = 0 }
            return min(1, Double(peak) * 6)
        }
    }
}

// MARK: - 系统声音：ScreenCaptureKit

/// 抓整台电脑正在播放的声音（不经过麦克风，耳机也能用）。需要「屏幕与系统录音」权限。
nonisolated final class SystemAudioCapture: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    private let onBuffer: (AVAudioPCMBuffer) -> Void
    private let queue = DispatchQueue(label: "echo.system-audio")
    private var stream: SCStream?

    init(onBuffer: @escaping (AVAudioPCMBuffer) -> Void) {
        self.onBuffer = onBuffer
    }

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else {
            throw LLMError(message: "找不到显示器，无法抓取系统声音")
        }
        let filter = SCContentFilter(display: display, excludingWindows: [])
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 48_000
        config.channelCount = 1
        // 只要声音：画面压到最小、最低帧率
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        config.queueDepth = 3

        let stream = SCStream(filter: filter, configuration: config, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
        try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
        try await stream.startCapture()
        self.stream = stream
    }

    func stop() async {
        try? await stream?.stopCapture()
        stream = nil
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sampleBuffer.isValid, let pcm = sampleBuffer.copyToPCMBuffer() else { return }
        onBuffer(pcm)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        print("[echo.asr] 系统音频流停止: \(error)")
    }
}

private nonisolated extension CMSampleBuffer {
    /// 把 ScreenCaptureKit 的音频帧拷成独立的 AVAudioPCMBuffer（原始内存在回调结束后失效）
    func copyToPCMBuffer() -> AVAudioPCMBuffer? {
        guard var asbd = formatDescription?.audioStreamBasicDescription,
              let format = AVAudioFormat(streamDescription: &asbd) else { return nil }
        let frames = AVAudioFrameCount(numSamples)
        guard frames > 0, let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else { return nil }
        out.frameLength = frames
        let status = CMSampleBufferCopyPCMDataIntoAudioBufferList(
            self, at: 0, frameCount: Int32(frames), into: out.mutableAudioBufferList)
        return status == noErr ? out : nil
    }
}

// MARK: - 切句 + 转写：SFSpeechRecognizer

/// 连续语音识别。Apple 的单次识别有时长限制，所以每切出一句就重开一个识别请求：
/// 说话中停顿 ≥ pause 秒、或一句超过 maxSentence 秒，就把当前文字当作一句交出去。
nonisolated final class SpeechPipe: @unchecked Sendable {
    private let recognizer: SFSpeechRecognizer
    private let pause: Double
    private let maxSentence: Double
    private let onSentence: (String, Double) -> Void
    private let lock = NSLock()

    var clock: () -> Double = { 0 }

    // 以下状态由 lock 保护
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var generation = 0
    private var text = ""
    private var sentenceStart: Double?
    private var lastChange = Date()
    private var hotWords: [String] = []
    private var timer: DispatchSourceTimer?
    private var running = false

    init(pause: Double, maxSentence: Double, onSentence: @escaping (String, Double) -> Void) throws {
        guard let r = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN")), r.isAvailable else {
            throw LLMError(message: "中文语音识别不可用")
        }
        recognizer = r
        self.pause = pause
        self.maxSentence = maxSentence
        self.onSentence = onSentence
    }

    static func authorize() async -> Bool {
        let status = await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { cont.resume(returning: $0) }
        }
        return status == .authorized
    }

    func setHotWords(_ words: [String]) {
        lock.withLock { hotWords = words }
    }

    func start() {
        lock.withLock {
            running = true
            restartLocked()
        }
        let timer = DispatchSource.makeTimerSource(queue: .global(qos: .userInitiated))
        timer.schedule(deadline: .now() + 0.3, repeating: 0.3)
        timer.setEventHandler { [weak self] in self?.check() }
        timer.resume()
        lock.withLock { self.timer = timer }
    }

    func stop() {
        let sentence: (String, Double)? = lock.withLock {
            running = false
            timer?.cancel()
            timer = nil
            let s = takeSentenceLocked()
            task?.cancel()
            task = nil
            request = nil
            return s
        }
        if let sentence { onSentence(sentence.0, sentence.1) }
    }

    func append(_ buffer: AVAudioPCMBuffer) {
        lock.withLock { request?.append(buffer) }
    }

    private func check() {
        let sentence: (String, Double)? = lock.withLock {
            guard running, !text.isEmpty, let t0 = sentenceStart else { return nil }
            let silent = Date().timeIntervalSince(lastChange) >= pause
            let tooLong = clock() - t0 >= maxSentence
            guard silent || tooLong else { return nil }
            let s = takeSentenceLocked()
            restartLocked()
            return s
        }
        if let sentence { onSentence(sentence.0, sentence.1) }
    }

    private func takeSentenceLocked() -> (String, Double)? {
        defer { text = ""; sentenceStart = nil }
        let s = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard s.count > 1, let t0 = sentenceStart else { return nil }
        return (s, t0)
    }

    /// 结束当前识别请求并开一个新的（调用方持有 lock）
    private func restartLocked() {
        request?.endAudio()
        task?.cancel()
        generation += 1
        let gen = generation
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        req.addsPunctuation = true
        req.taskHint = .dictation
        req.contextualStrings = hotWords
        if recognizer.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = false }
        request = req
        task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            self?.handle(gen: gen, result: result, error: error)
        }
    }

    private func handle(gen: Int, result: SFSpeechRecognitionResult?, error: Error?) {
        let sentence: (String, Double)? = lock.withLock {
            guard running, gen == generation else { return nil }   // 旧请求的回调，忽略
            if let result {
                let s = result.bestTranscription.formattedString
                if s != text {
                    if sentenceStart == nil { sentenceStart = max(0, clock() - 1) }
                    text = s
                    lastChange = Date()
                }
                if result.isFinal {
                    let out = takeSentenceLocked()
                    restartLocked()
                    return out
                }
            } else if error != nil {
                // 无语音超时 / 单次时长上限等：交出已有文字，重开
                let out = takeSentenceLocked()
                restartLocked()
                return out
            }
            return nil
        }
        if let sentence { onSentence(sentence.0, sentence.1) }
    }
}
