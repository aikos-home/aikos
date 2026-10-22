// Audio for talking to the door (A5): the microphone down to 16 kHz 16-bit frames of 20 ms for the app's WebSocket, and the
// door's 16 kHz frames up to the phone's rate. A separate file: the page's security rules allow scripts only from here.

const RATE = 16000;
const FRAME = 320; // 20 ms

class MicCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / RATE;
    this.pos = 0;
    this.sum = 0;
    this.count = 0;
    this.frame = new Int16Array(FRAME);
    this.n = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.sum += ch[i];
      this.count += 1;
      this.pos += 1;
      if (this.pos >= this.ratio) {   // average over each 16 kHz step (a simple low-pass for the decimation)
        this.pos -= this.ratio;
        const v = this.sum / this.count;
        this.sum = 0;
        this.count = 0;
        this.frame[this.n++] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)));
        if (this.n === FRAME) {
          this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
          this.frame = new Int16Array(FRAME);
          this.n = 0;
        }
      }
    }
    return true;
  }
}

class DoorPlay extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = [];
    this.cur = null;
    this.idx = 0;
    this.step = RATE / sampleRate;
    this.frac = 0;
    this.waiting = true;           // after running dry: wait for 3 frames (60 ms) against network jitter
    this.port.onmessage = (e) => {
      if (e.data === "clear") {
        this.queue = [];
        this.cur = null;
        this.waiting = true;
        return;
      }
      if (this.queue.length < 50) this.queue.push(new Int16Array(e.data));
    };
  }

  sample(k) {
    if (this.cur && k < this.cur.length) return this.cur[k] / 32768;
    const next = this.queue[0];
    return next && k - (this.cur ? this.cur.length : 0) < next.length ? next[k - (this.cur ? this.cur.length : 0)] / 32768 : 0;
  }

  process(_inputs, outputs) {
    const out = outputs[0][0];
    if (this.waiting && this.queue.length >= 3) this.waiting = false;
    for (let i = 0; i < out.length; i++) {
      if (this.waiting) {
        out[i] = 0;
        continue;
      }
      if (!this.cur || this.idx >= this.cur.length) {
        this.idx -= this.cur ? this.cur.length : 0;
        this.cur = this.queue.shift() || null;
        if (!this.cur) {
          this.waiting = true;
          this.idx = 0;
          out[i] = 0;
          continue;
        }
      }
      const a = this.sample(this.idx);
      const b = this.sample(this.idx + 1);
      out[i] = a + (b - a) * this.frac;   // linear interpolation up to the phone's rate
      this.frac += this.step;
      while (this.frac >= 1) {
        this.frac -= 1;
        this.idx += 1;
      }
    }
    return true;
  }
}

registerProcessor("mic-capture", MicCapture);
registerProcessor("door-play", DoorPlay);
