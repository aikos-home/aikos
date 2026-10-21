// Play/pause with a progress bar. The sound comes through the app (never a Home Assistant link, rule G3).
import { useEffect, useRef, useState } from "preact/hooks";
import { duration } from "../format";
import { Icon } from "./Icon";

export function AudioPlayer({ src, seconds, onPlay }: { src: string; seconds: number | null; onPlay: () => void }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const [total, setTotal] = useState<number | null>(seconds);
  const [failed, setFailed] = useState(false);

  useEffect(() => () => audio.current?.pause(), []);

  const toggle = async () => {
    const a = audio.current!;
    if (playing) return a.pause();
    try {
      setFailed(false);
      await a.play();
      onPlay();
    } catch {
      setFailed(true);
    }
  };

  const seek = (e: MouseEvent) => {
    const a = audio.current!;
    const bar = e.currentTarget as HTMLElement;
    const part = (e.clientX - bar.getBoundingClientRect().left) / bar.clientWidth;
    if (total) a.currentTime = Math.max(0, Math.min(1, part)) * total;
  };

  const progress = total ? Math.min(100, (pos / total) * 100) : 0;
  return (
    <div class="player">
      <audio ref={audio} src={src} preload="none"
             onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); setPos(0); }}
             onTimeUpdate={(e) => setPos(e.currentTarget.currentTime)}
             onLoadedMetadata={(e) => Number.isFinite(e.currentTarget.duration) && setTotal(e.currentTarget.duration)}
             onError={() => setFailed(true)} />
      <button class="play" onClick={toggle} aria-label={playing ? "Pause" : "Abspielen"}>
        <Icon name={playing ? "pause" : "play"} />
      </button>
      <div class="track" onClick={seek} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress)}>
        <div class="fill" style={{ width: `${progress}%` }} />
      </div>
      <span class="time">{failed ? "Fehler" : playing || pos ? duration(pos) : duration(total)}</span>
    </div>
  );
}
