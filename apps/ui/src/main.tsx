import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "@fontsource/noto-serif-sc/600.css";   // 决策 #5：思源宋体 SemiBold（logo/标题用 --font-serif）
import "./theme/tokens.css";
import "./components/base.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
