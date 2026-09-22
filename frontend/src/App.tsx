import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { Menu, X, Activity, Map, TrendingDown, IndianRupee, Database, TerminalSquare, BookOpen, BarChart2 } from "lucide-react";
import { Banner } from "./components/Banner";
import { ThemeToggle } from "./components/ThemeToggle";
import { BacktestPage } from "./pages/Backtest";
import { CollectionPage } from "./pages/Collection";
import { ElasticityPage } from "./pages/Elasticity";
import { FaresPage } from "./pages/Fares";
import { HeatmapPage } from "./pages/Heatmap";
import { MethodologyPage } from "./pages/Methodology";
import { OverviewPage } from "./pages/Overview";
import { SourcesPage } from "./pages/Sources";

export default function App() {
  const [navOpen, setNavOpen] = useState(false);
  const toggleNav = () => setNavOpen(!navOpen);

  return (
    <div className="app-shell">
      <Banner />
      <nav className="top-nav">
        <div className="nav-brand">
          <div className="brand-kicker">SIH 2026 · SIH26056</div>
          <h1>Nabhsetu</h1>
          <p>MoSPI real-time airfare price index</p>
        </div>
        
        <div className={`nav-links ${navOpen ? 'open' : ''}`}>
          <NavLink to="/" end onClick={() => setNavOpen(false)}>
            <Activity size={18} /> Index trend
          </NavLink>
          <NavLink to="/heatmap" onClick={() => setNavOpen(false)}>
            <Map size={18} /> Route heatmap
          </NavLink>
          <NavLink to="/elasticity" onClick={() => setNavOpen(false)}>
            <TrendingDown size={18} /> Lead-time
          </NavLink>
          <NavLink to="/fares" onClick={() => setNavOpen(false)}>
            <IndianRupee size={18} /> Fares
          </NavLink>
          <NavLink to="/sources" onClick={() => setNavOpen(false)}>
            <Database size={18} /> Sources
          </NavLink>
          <NavLink to="/collection" onClick={() => setNavOpen(false)}>
            <TerminalSquare size={18} /> Console
          </NavLink>
          <NavLink to="/methodology" onClick={() => setNavOpen(false)}>
            <BookOpen size={18} /> Method
          </NavLink>
          <NavLink to="/backtest" onClick={() => setNavOpen(false)}>
            <BarChart2 size={18} /> Back-test
          </NavLink>
        </div>

        <div className="nav-actions">
          <ThemeToggle />
          <button className="mobile-nav-toggle" onClick={toggleNav}>
            {navOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>
      </nav>

      <div className="layout">
        <main className="fade-in">
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
