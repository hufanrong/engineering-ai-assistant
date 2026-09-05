const SILENCE_THRESHOLD = 0.004;
const PRE_ROLL_SEC = 0.15;
const POST_ROLL_SEC = 0.25;
const TARGET_SAMPLE_RATE = 16000;

interface TrimRange {
  startIdx: number;
  endIdx: number;
}

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let i = 0; i < text.length; i += 1) {
    view.setUint8(offset + i, text.charCodeAt(i));
  }
}

function encodeWav(buffer: AudioBuffer): Blob {
  const channels = buffer.numberOfChannels;
  const sampleRate = buffer.sampleRate;
  const samples = buffer.getChannelData(0);
  const dataSize = samples.length * 2;
  const arrayBuffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(arrayBuffer);
  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeAscii(view, 8, 'WAVE');
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * channels * 2, true);
  view.setUint16(32, channels * 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, 'data');
  view.setUint32(40, dataSize, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }
  return new Blob([arrayBuffer], { type: 'audio/wav' });
}

function findTrimRange(samples: Float32Array): TrimRange | null {
  let startIdx = 0;
  let endIdx = samples.length - 1;
  while (startIdx < samples.length && Math.abs(samples[startIdx]) < SILENCE_THRESHOLD) {
    startIdx += 1;
  }
  while (endIdx > startIdx && Math.abs(samples[endIdx]) < SILENCE_THRESHOLD) {
    endIdx -= 1;
  }
  if (startIdx >= endIdx) {
    return null;
  }
  return { startIdx, endIdx };
}

export interface VoiceWavResult {
  blob: Blob;
  durationSec: number;
}

export async function voiceBlobToWav(blob: Blob): Promise<VoiceWavResult | null> {
  try {
    const audioCtx = new AudioContext();
    const decoded = await audioCtx.decodeAudioData(await blob.arrayBuffer());
    void audioCtx.close();
    const samples = decoded.getChannelData(0);
    const trim = findTrimRange(samples);
    if (!trim) {
      return null;
    }
    const sampleRate = decoded.sampleRate;
    const startIdx = Math.max(0, trim.startIdx - Math.floor(PRE_ROLL_SEC * sampleRate));
    const endIdx = Math.min(
      samples.length - 1,
      trim.endIdx + Math.floor(POST_ROLL_SEC * sampleRate),
    );
    const durationSec = (endIdx - startIdx + 1) / sampleRate;
    const frames = Math.max(1, Math.ceil(durationSec * TARGET_SAMPLE_RATE));
    const offline = new OfflineAudioContext(1, frames, TARGET_SAMPLE_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start(0, startIdx / sampleRate, durationSec);
    const rendered = await offline.startRendering();
    return { blob: encodeWav(rendered), durationSec };
  } catch {
    return null;
  }
}
