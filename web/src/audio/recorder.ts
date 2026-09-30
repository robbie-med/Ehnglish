/** Lossless microphone capture through an AudioWorklet. Output: Int16 PCM at the context rate. */
import { float32ToInt16 } from './wav';

export interface MicInfo { deviceId: string; label: string; sampleRate: number }

export class PcmRecorder {
  ctx: AudioContext;
  stream: MediaStream;
  node: AudioWorkletNode;
  source: MediaStreamAudioSourceNode;
  private chunks: Float32Array[] = [];
  private capturing = false;
  onLevel: ((rmsDbfs: number) => void) | null = null;

  private constructor(ctx: AudioContext, stream: MediaStream, node: AudioWorkletNode, source: MediaStreamAudioSourceNode) {
    this.ctx = ctx;
    this.stream = stream;
    this.node = node;
    this.source = source;
  }

  static async create(deviceId?: string): Promise<PcmRecorder> {
    const audio: MediaTrackConstraints = {
      channelCount: 1,
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    };
    if (deviceId) audio.deviceId = { exact: deviceId };
    const stream = await navigator.mediaDevices.getUserMedia({ audio, video: false });
    const ctx = new AudioContext({ latencyHint: 'interactive' });
    await ctx.audioWorklet.addModule('/worklet/pcm-recorder.js');
    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, 'pcm-recorder', { numberOfInputs: 1, numberOfOutputs: 0, channelCount: 1 });
    source.connect(node);
    const rec = new PcmRecorder(ctx, stream, node, source);
    node.port.onmessage = (e: MessageEvent<Float32Array>) => rec.onFrame(e.data);
    if (ctx.state !== 'running') await ctx.resume();
    return rec;
  }

  private onFrame(frame: Float32Array): void {
    if (this.capturing) this.chunks.push(frame);
    if (this.onLevel) {
      let ss = 0;
      for (let i = 0; i < frame.length; i++) ss += frame[i] * frame[i];
      const rms = Math.sqrt(ss / frame.length);
      this.onLevel(rms > 0 ? 20 * Math.log10(rms) : -120);
    }
  }

  get info(): MicInfo {
    const track = this.stream.getAudioTracks()[0];
    const s = track?.getSettings() ?? {};
    return { deviceId: s.deviceId ?? '', label: track?.label ?? '', sampleRate: this.ctx.sampleRate };
  }

  async start(): Promise<void> {
    if (this.ctx.state !== 'running') await this.ctx.resume();
    this.chunks = [];
    this.capturing = true;
    this.node.port.postMessage('start');
  }

  /** Stops capture and returns the take as Int16 PCM. */
  async stop(): Promise<Int16Array> {
    this.node.port.postMessage('stop');
    // Let in-flight frames arrive before we close the take.
    await new Promise((r) => setTimeout(r, 60));
    this.capturing = false;
    const out = float32ToInt16(this.chunks);
    this.chunks = [];
    return out;
  }

  /** Record for a fixed number of milliseconds. */
  async recordFor(ms: number): Promise<Int16Array> {
    await this.start();
    await new Promise((r) => setTimeout(r, ms));
    return this.stop();
  }

  /** Play a test tone through the headphones while recording; returns the captured PCM. */
  async recordWithTone(ms: number, freq = 1000, gain = 0.25): Promise<Int16Array> {
    const osc = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    osc.frequency.value = freq;
    g.gain.value = gain;
    osc.connect(g).connect(this.ctx.destination);
    osc.start();
    try {
      return await this.recordFor(ms);
    } finally {
      osc.stop();
      osc.disconnect();
      g.disconnect();
    }
  }

  dispose(): void {
    this.node.port.onmessage = null;
    this.source.disconnect();
    this.node.disconnect();
    for (const t of this.stream.getTracks()) t.stop();
    void this.ctx.close();
  }
}

let current: PcmRecorder | null = null;

/** One recorder for the whole sitting. Creating it must follow a user gesture. */
export async function getRecorder(deviceId?: string): Promise<PcmRecorder> {
  if (current && (!deviceId || current.info.deviceId === deviceId) && current.ctx.state !== 'closed') return current;
  current?.dispose();
  current = await PcmRecorder.create(deviceId);
  return current;
}

export function releaseRecorder(): void {
  current?.dispose();
  current = null;
}

export async function listMics(): Promise<MediaDeviceInfo[]> {
  const devs = await navigator.mediaDevices.enumerateDevices();
  return devs.filter((d) => d.kind === 'audioinput');
}
