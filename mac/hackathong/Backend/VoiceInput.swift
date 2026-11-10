//
//  VoiceInput.swift
//  Echo - 语音转文字（按一下说话）（对应 Python echo/backend/voice_input.py）
//
//  「讲给 Echo 听」：按下开始录音，再按一下结束，转成文字填进输入框——不自动发送。
//  Mac 上不用 Whisper：AVAudioEngine 麦克风 + SFSpeechRecognizer（zh-CN；英文界面 en-US）。
//  单次短录音，跟上课时的实时听写（SpeechPipe）各自独立，互不影响。
//

import AVFoundation
import Foundation
import Speech

nonisolated struct VoiceInputError: LocalizedError, Sendable {
    let message: String
    var errorDescription: String? { message }
}

/// 一次性录音 + 流式识别。
///
///     guard await VoiceRecorder.authorize() else { ... }
///     let r = VoiceRecorder()
///     try r.start()
///     let text = await r.stop()
nonisolated final class VoiceRecorder: @unchecked Sendable {
    /// 封个上限：这是单轮对话用的，不是让人讲整节课
    static let MAX_SECONDS: Double = 30

    private let lock = NSLock()
    private var engine: AVAudioEngine?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var latest = ""
    private var finalWaiter: CheckedContinuation<String, Never>?
    private var finished = false
    private var framesSent: Double = 0
    private var sampleRate: Double = 0
    private var _level: Double = 0
    private var _recording = false

    /// 当前音量 0…1（给按钮做跳动动画）
    var level: Double { lock.withLock { _level } }
    var isRecording: Bool { lock.withLock { _recording } }

    /// 麦克风 + 语音识别权限（参考 SpeechPipe.authorize）。start() 前先 await 一次。
    static func authorize() async -> Bool {
        let mic: Bool
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: mic = true
        case .notDetermined:
            mic = await withCheckedContinuation { cont in
                AVCaptureDevice.requestAccess(for: .audio) { cont.resume(returning: $0) }
            }
        default: mic = false
        }
        guard mic else { return false }
        return await SpeechPipe.authorize()
    }

    /// 打开麦克风开始录（语言跟随界面：英文界面 en-US，否则 zh-CN）。
    /// 失败（没权限/没设备/识别不可用）直接抛，调用方提示学生。
    @MainActor func start() throws { try start(english: EchoConfig.english) }

    /// 同上，显式指定语言（非主线程调用时用）。
    func start(english: Bool) throws {
        _ = cancelInternal()
        guard SFSpeechRecognizer.authorizationStatus() == .authorized else {
            throw VoiceInputError(message: english
                ? "Speech recognition not allowed. Enable it in System Settings → Privacy & Security → Speech Recognition."
                : "没有语音识别权限，请在 系统设置 → 隐私与安全性 → 语音识别 里允许 Echo")
        }
        let localeID = english ? "en-US" : "zh-CN"
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeID)),
              recognizer.isAvailable else {
            throw VoiceInputError(message: english ? "Speech recognition unavailable" : "语音识别不可用")
        }

        let engine = AVAudioEngine()
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw VoiceInputError(message: english ? "No microphone found" : "找不到可用的麦克风输入设备")
        }

        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        req.addsPunctuation = true
        req.taskHint = .dictation

        lock.withLock {
            latest = ""; finished = false; finalWaiter = nil
            framesSent = 0; sampleRate = format.sampleRate; _level = 0
            request = req
        }

        let task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            guard let self else { return }
            if let result {
                self.lock.withLock { self.latest = result.bestTranscription.formattedString }
                if result.isFinal { self.finish() }
            } else if error != nil {
                self.finish()
            }
        }

        input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
            self?.handle(buffer)
        }
        engine.prepare()
        do {
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            task.cancel()
            throw VoiceInputError(message: (english ? "Microphone failed: " : "麦克风启动失败：")
                                  + error.localizedDescription)
        }
        lock.withLock { self.engine = engine; self.task = task; _recording = true }
    }

    /// 音频线程回调：算音量、喂给识别；到 MAX_SECONDS 自动停喂。
    private func handle(_ buffer: AVAudioPCMBuffer) {
        var rms: Float = 0
        if let ch = buffer.floatChannelData?[0], buffer.frameLength > 0 {
            let n = Int(buffer.frameLength)
            var sum: Float = 0
            for i in 0..<n { sum += ch[i] * ch[i] }
            rms = (sum / Float(n)).squareRoot()
        }
        let req: SFSpeechAudioBufferRecognitionRequest? = lock.withLock {
            _level = min(1, Double(rms) * 8)
            guard _recording, sampleRate > 0, framesSent / sampleRate < Self.MAX_SECONDS else { return nil }
            framesSent += Double(buffer.frameLength)
            return request
        }
        req?.append(buffer)
    }

    private func finish() {
        let w: CheckedContinuation<String, Never>? = lock.withLock {
            finished = true
            let w = finalWaiter; finalWaiter = nil
            return w
        }
        w?.resume(returning: lock.withLock { latest }.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private func stopEngine() -> SFSpeechAudioBufferRecognitionRequest? {
        let (e, r): (AVAudioEngine?, SFSpeechAudioBufferRecognitionRequest?) = lock.withLock {
            _recording = false; _level = 0
            let e = engine, r = request
            engine = nil; request = nil
            return (e, r)
        }
        e?.inputNode.removeTap(onBus: 0)
        e?.stop()
        return r
    }

    private func cancelInternal() -> Bool {
        let had = stopEngine() != nil
        lock.withLock { task }?.cancel()
        lock.withLock { task = nil }
        return had
    }

    /// 取消录音，不要结果。
    func cancel() { _ = cancelInternal() }

    /// 停止录音，等最终文字。没录到 / 太短（<0.3s，误触）/ 识别失败都返回空串。
    func stop() async -> String {
        guard let req = stopEngine() else { return "" }
        let tooShort = lock.withLock { sampleRate <= 0 || framesSent / sampleRate < 0.3 }
        if tooShort { cancel(); return "" }
        req.endAudio()
        let text: String = await withCheckedContinuation { cont in
            let done: Bool = lock.withLock {
                if finished { return true }
                finalWaiter = cont
                return false
            }
            if done { cont.resume(returning: lock.withLock { latest }.trimmingCharacters(in: .whitespacesAndNewlines)) }
            // 兜底：识别迟迟不给 final 时，用最后一次部分结果
            DispatchQueue.global().asyncAfter(deadline: .now() + 5) { [weak self] in self?.finish() }
        }
        lock.withLock { task = nil }
        return text
    }
}

/// 兼容旧接口（Views/ChatPages.swift 在用：start() async throws / stopAndTranscribe()）
nonisolated final class VoiceInputRecorder: @unchecked Sendable {
    let recorder = VoiceRecorder()
    var level: Double { recorder.level }
    var isRecording: Bool { recorder.isRecording }

    func start() async throws {
        let english = await MainActor.run { EchoConfig.english }
        guard await VoiceRecorder.authorize() else {
            throw VoiceInputError(message: english
                ? "Microphone / speech recognition not allowed. Enable them in System Settings → Privacy & Security."
                : "没有麦克风或语音识别权限，请在 系统设置 → 隐私与安全性 里允许 Echo")
        }
        try recorder.start(english: english)
    }
    func stop() { recorder.cancel() }
    func cancel() { recorder.cancel() }
    func stopAndTranscribe() async -> String { await recorder.stop() }
}
