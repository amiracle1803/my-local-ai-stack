import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Run from "./pages/Run";
import Jobs from "./pages/Jobs";
import JobDetail from "./pages/JobDetail";
import Agents from "./pages/Agents";
import Knowledge from "./pages/Knowledge";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/run" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/run" element={<Run />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
