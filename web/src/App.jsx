import { useEffect, useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { api, isAuthed, setToken } from "./api.js";
import Layout from "./components/Layout.jsx";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Users from "./pages/Users.jsx";
import Groups from "./pages/Groups.jsx";
import Cameras from "./pages/Cameras.jsx";
import Agents from "./pages/Agents.jsx";
import Events from "./pages/Events.jsx";
import Releases from "./pages/Releases.jsx";

export default function App() {
  const [authed, setAuthed] = useState(isAuthed());
  const [me, setMe] = useState(null);

  useEffect(() => {
    if (!authed) return;
    api.me().then(setMe).catch(() => {
      setToken("");
      setAuthed(false);
    });
  }, [authed]);

  if (!authed) {
    return <Login onLogin={() => setAuthed(true)} />;
  }

  return (
    <Layout me={me} onLogout={() => { setToken(""); setAuthed(false); }}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/users" element={<Users me={me} />} />
        <Route path="/groups" element={<Groups />} />
        <Route path="/cameras" element={<Cameras />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/events" element={<Events />} />
        <Route path="/releases" element={<Releases />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </Layout>
  );
}
