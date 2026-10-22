import { useEffect, useState } from "react";
import "./clock.css";

const pad = (n: number) => String(n).padStart(2, "0");

export function MiniClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const h = now.getHours(), m = now.getMinutes(), s = now.getSeconds();
  const dayPct = (h * 3600 + m * 60 + s) / 864;
  return (
    <div className="mini-clock">
      <div className="mc-orbit" role="img" aria-label="当前时间"
           style={{ "--hour-angle": `${(h % 12) * 30 + m * 0.5}deg`,
                    "--minute-angle": `${m * 6 + s * 0.1}deg`,
                    "--second-angle": `${s * 6}deg`,
                    "--day-angle": `${dayPct * 3.6}deg` } as React.CSSProperties}>
        <i className="mc-hand h" /><i className="mc-hand m" /><i className="mc-hand s" />
      </div>
      <div>
        <div className="mc-time" data-testid="clock-time">
          {pad(h)}:{pad(m)}<em>:{pad(s)}</em>
        </div>
        <div className="mc-label">LOCAL</div>
      </div>
    </div>
  );
}
