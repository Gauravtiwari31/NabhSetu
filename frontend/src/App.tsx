import { NavLink, Route, Routes } from "react-router-dom";
import { Banner } from "./components/Banner";
import { BacktestPage } from "./pages/Backtest";
import { CollectionPage } from "./pages/Collection";
import { ElasticityPage } from "./pages/Elasticity";
import { FaresPage } from "./pages/Fares";
import { HeatmapPage } from "./pages/Heatmap";
import { MethodologyPage } from "./pages/Methodology";
import { OverviewPage } from "./pages/Overview";
import { SourcesPage } from "./pages/Sources";

export default function App() {
  return (
    <div className="app-shell">
      <Banner />
      <div className="layout">
        <nav>
          <div className="brand">
            <div className="brand-kicker">SIH 2026 · SIH26056</div>
            <h1>Nabhsetu</h1>
            <p>MoSPI real-time airfare price index</p>
          </div>
          <NavLink to="/" end>
            Index trend
          </NavLink>
          <NavLink to="/heatmap">Route heatmap</NavLink>
          <NavLink to="/elasticity">Lead-time elasticity</NavLink>
          <NavLink to="/fares">Fare drill-down</NavLink>
          <NavLink to="/sources">Source health</NavLink>
          <NavLink to="/collection">Collection console</NavLink>
          <NavLink to="/methodology">Methodology</NavLink>
          <NavLink to="/backtest">Back-test</NavLink>
          <div className="nav-foot">Identified research User-Agent. No CAPTCHA solving, no rotate-on-block.</div>
        </nav>
        <main>
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/heatmap" element={<HeatmapPage />} />
            <Route path="/elasticity" element={<ElasticityPage />} />
            <Route path="/fares" element={<FaresPage />} />
            <Route path="/sources" element={<SourcesPage />} />
            <Route path="/collection" element={<CollectionPage />} />
            <Route path="/methodology" element={<MethodologyPage />} />
            <Route path="/backtest" element={<BacktestPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
