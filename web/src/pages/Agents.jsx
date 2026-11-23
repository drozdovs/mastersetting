import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Agents() {
  const [agents, setAgents] = useState([]);
  const [error, setError] = useState("");

  function load() {
    api.agents().then(setAgents).catch((e) => setError(e.message));
  }
  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  function online(lastSeen) {
    const diff = (Date.now() - new Date(lastSeen).getTime()) / 1000;
    return diff < 120;
  }

  return (
    <>
      <h2>Агенты</h2>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>ID</th><th>Компьютер</th><th>ОС</th>
              <th>Версия</th><th>Последняя связь</th><th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => {
              const on = online(a.last_seen);
              return (
                <tr key={a.id}>
                  <td className="muted">{a.agent_id}</td>
                  <td>{a.hostname}</td>
                  <td>{a.os_info}</td>
                  <td>{a.version}</td>
                  <td>{new Date(a.last_seen).toLocaleString("ru-RU")}</td>
                  <td>
                    <span className={"badge " + (on ? "ok" : "err")}>
                      {on ? "онлайн" : "офлайн"}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {agents.length === 0 && <div className="muted mt">Агенты ещё не регистрировались</div>}
      </div>
    </>
  );
}
