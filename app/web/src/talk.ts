// Talking to the door from the phone (A5, A48: hold to talk). One WebSocket to this app node: the door's microphone comes
// in all the time, the phone's microphone goes out only while the button is held (the node forwards it as RTP).

export type TalkState = "connecting" | "listening" | "talking" | "busy" | "off" | "error";

export class DoorTalk {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private mic: AudioWorkletNode | null = null;
  private play: AudioWorkletNode | null = null;
  private holding = false;

  constructor(private onState: (s: TalkState, detail?: string) => void) {}

  static supported(): boolean {
    return typeof AudioWorkletNode !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof WebSocket !== "undefined";
  }

  /** Must run from a tap: the phone allows sound and the microphone only then. */
  async start(): Promise<void> {
    this.onState("connecting");
    this.ctx = new AudioContext();
    await this.ctx.audioWorklet.addModule("/talk-worklet.js");
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    this.mic = new AudioWorkletNode(this.ctx, "mic-capture");
    this.ctx.createMediaStreamSource(this.stream).connect(this.mic);
    this.play = new AudioWorkletNode(this.ctx, "door-play", { outputChannelCount: [1] });
    this.play.connect(this.ctx.destination);
    this.mic.port.onmessage = (e) => {
      if (this.holding && this.ws?.readyState === WebSocket.OPEN) this.ws.send(e.data as ArrayBuffer);
    };
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    this.ws = new WebSocket(`${proto}//${location.host}/api/v1/door/talk`);
    this.ws.binaryType = "arraybuffer";
    this.ws.onmessage = (e) => {
      if (typeof e.data === "string") {
        try {
          const s = JSON.parse(e.data).state as TalkState;
          if (s) this.onState(s);
        } catch {
          /* not for us */
        }
      } else {
        this.play?.port.postMessage(e.data, [e.data]);
      }
    };
    this.ws.onclose = () => {
      this.cleanup();
      this.onState("off");
    };
    this.ws.onerror = () => this.onState("error", "Keine Verbindung zur Tür.");
  }

  hold(on: boolean): void {
    if (on === this.holding || this.ws?.readyState !== WebSocket.OPEN) return;
    this.holding = on;
    if (on) this.play?.port.postMessage("clear");
    this.ws.send(JSON.stringify({ hold: on }));
  }

  stop(): void {
    this.holding = false;
    this.ws?.close();
    this.cleanup();
  }

  private cleanup(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.mic?.disconnect();
    this.play?.disconnect();
    this.mic = this.play = null;
    this.ctx?.close().catch(() => {});
    this.ctx = null;
    this.ws = null;
  }
}
