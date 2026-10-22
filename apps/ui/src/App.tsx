import { useState } from "react";
import { BackgroundLayer } from "./components/BackgroundLayer";
import { MiniClock } from "./components/MiniClock";
import { ThemeChips } from "./theme/ThemeChips";
import { Dashboard } from "./cards/Dashboard";
import { DraftsPage } from "./pages/DraftsPage";
import { WorkerProvider } from "./worker/WorkerProvider";
import { ThemeProvider } from "./theme/ThemeProvider";
import "./App.css";

function TopBar() {
  return (
    <header className="topbar">
      <span className="logo">AGENT://控制中心</span>
      <span className="spacer" />
      <MiniClock />
    </header>
  );
}

function Shell() {
  const [page, setPage] = useState<"dash" | "drafts">("dash");
  return (
    <>
      <BackgroundLayer />
      <TopBar />
      <ThemeChips />
      {page === "dash"
        ? <Dashboard onOpenDrafts={() => setPage("drafts")} />
        : <DraftsPage onBack={() => setPage("dash")} />}
    </>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <WorkerProvider>
        <Shell />
      </WorkerProvider>
    </ThemeProvider>
  );
}
