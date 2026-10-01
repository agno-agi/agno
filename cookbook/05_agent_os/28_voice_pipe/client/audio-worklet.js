// Capture fixed PCM16 frames on the audio thread; microphone audio never plays locally.
class VoiceCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const config = options.processorOptions;
    this.frame = new Int16Array(config.frameSamples);
    this.frameIndex = 0;
    this.ratio = sampleRate / config.sampleRate;
    this.position = 0;
    this.previous = 0;
    this.level = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    let power = 0;
    for (const sample of input) power += sample * sample;
    this.level = Math.sqrt(power / input.length);

    // A fractional position is preserved between render quanta, including at 44.1 kHz.
    while (this.position < input.length - 1) {
      const index = Math.floor(this.position);
      const fraction = this.position - index;
      const left = index < 0 ? this.previous : input[index];
      const right = input[index + 1];
      const sample = Math.max(-1, Math.min(1, left + (right - left) * fraction));
      this.frame[this.frameIndex++] = Math.round(sample * (sample < 0 ? 32768 : 32767));
      this.position += this.ratio;
      if (this.frameIndex === this.frame.length) {
        // DataView makes the wire format explicitly little endian.
        const bytes = new ArrayBuffer(this.frame.length * 2);
        const view = new DataView(bytes);
        for (let i = 0; i < this.frame.length; i++) view.setInt16(i * 2, this.frame[i], true);
        this.port.postMessage({ pcm: bytes, level: this.level }, [bytes]);
        this.frameIndex = 0;
      }
    }
    this.position -= input.length;
    this.previous = input[input.length - 1];
    return true;
  }
}

registerProcessor("voice-capture", VoiceCapture);
