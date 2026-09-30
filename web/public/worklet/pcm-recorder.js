// AudioWorklet processor: forwards raw Float32 frames from the mic to the main thread while
// recording. Plain JS on purpose (served as a static asset, never bundled).
class PcmRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.recording = false;
    this.port.onmessage = (e) => {
      if (e.data === 'start') this.recording = true;
      else if (e.data === 'stop') this.recording = false;
    };
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && this.recording) {
      const copy = new Float32Array(ch.length);
      copy.set(ch);
      this.port.postMessage(copy, [copy.buffer]);
    }
    return true;
  }
}
registerProcessor('pcm-recorder', PcmRecorder);
