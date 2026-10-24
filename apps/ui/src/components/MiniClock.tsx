import { useEffect, useRef, useState } from "react";
import "./clock.css";

const pad = (n: number) => String(n).padStart(2, "0");

export function MiniClock() {
  const [now, setNow] = useState(() => new Date());
  // 决策 #30：秒角连续累积——59s→0s 直接回 0 会让 CSS 按数值插值反向扫过 354°（每分钟闪跳一次），
  // 跨分钟时累加一圈抵消回卷。prevSec 用 ref 记上一拍秒数，保持 setNow/setTurns 更新纯净。
  const [turns, setTurns] = useState(0);
  const prevSec = useRef(now.getSeconds());
  useEffect(() => {
    const t = setInterval(() => {
      const next = new Date();
      const s = next.getSeconds();
      if (s < prevSec.current) setTurns((x) => x + 1);   // 跨分钟：新秒数 < 旧秒数
      prevSec.current = s;
      setNow(next);
    }, 1000);
    return () => clearInterval(t);
  }, []);

  const h = now.getHours(), m = now.getMinutes(), s = now.getSeconds();
  const dayPct = (h * 3600 + m * 60 + s) / 864;
  return (
    <div className="mini-clock">
      <div className="mc-orbit" role="img" aria-label="当前时间"
           style={{ "--hour-angle": `${(h % 12) * 30 + m * 0.5}deg`,
                    "--minute-angle": `${m * 6 + s * 0.1}deg`,
                    "--second-angle": `${s * 6 + turns * 360}deg`,
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
