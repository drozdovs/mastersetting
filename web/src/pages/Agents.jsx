import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Agents() {
  const [agents, setAgents] = useState([]);
  const [groups, setGroups] = useState([]);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState(null);
  const [settings, setSettings] = useState([]);

  function load() {
    api.agents().then(setAgents).catch((e) => setError(e.message));
    api.groups().then(setGroups).catch(() => {});
  }
  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  function online(lastSeen) {
    return (Date.now() - new Date(lastSeen).getTime()) / 1000 < 120;
  }

  async function setGroup(a, groupId) {
    try {
      await api.updateAgent(a.id, { group_id: groupId ? Number(groupId) : null });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function rename(a) {
    const name = prompt("Новое имя компьютера:", a.hostname);
    if (!name) return;
    try {
      await api.updateAgent(a.id, { hostname: name });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(a) {
    if (!confirm(`Удалить агент ${a.hostname || a.agent_id}?`)) return;
    try {
      await api.deleteAgent(a.id);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function toggleSettings(a) {
    if (openId === a.id) {
      setOpenId(null);
      return;
    }
    try {
      const s = await api.agentSettings(a.id);
      setSettings(s);
      setOpenId(a.id);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <>
      <h2>Агенты</h2>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>ID</th><th>Компьютер</th><th>ОС</th><th>Версия</th>
              <th>Группа</th><th>Последняя связь</th><th>Статус</th><th></th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.id}>
                <td className="muted">{a.agent_id}</td>
                <td>{a.hostname}</td>
                <td>{a.os_info}</td>
                <td>{a.version}</td>
                <td>
                  <select value={a.group_id || ""}
                          onChange={(e) => setGroup(a, e.target.value)}>
                    <option value="">— нет —</option>
                    {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                  </select>
                </td>
                <td>{new Date(a.last_seen).toLocaleString("ru-RU")}</td>
                <td>
                  <span className={"badge " + (online(a.last_seen) ? "ok" : "err")}>
                    {online(a.last_seen) ? "онлайн" : "офлайн"}
                  </span>
                </td>
                <td className="row">
                  <button className="ghost" onClick={() => toggleSettings(a)}>
                    {openId === a.id ? "Скрыть" : "Настройки"}
                  </button>
                  <button className="ghost" onClick={() => rename(a)}>Переименовать</button>
                  <button className="danger" onClick={() => remove(a)}>Удалить</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {agents.length === 0 && <div className="muted mt">Агенты ещё не регистрировались</div>}
      </div>

      {openId && (
        <div className="card">
          <h3>Наборы настроек агента</h3>
          {settings.length === 0 ? (
            <div className="muted">Нет зарегистрированных наборов</div>
          ) : (
            <table>
              <thead>
                <tr><th>Оператор</th><th>Камера</th><th>Настройки</th><th>Размер</th><th>Дата</th></tr>
              </thead>
              <tbody>
                {settings.map((s) => (
                  <tr key={s.id}>
                    <td>{s.operator}</td>
                    <td>{s.camera}</td>
                    <td>{s.settings_name}</td>
                    <td>{Math.round((s.size_bytes || 0) / 1024)} КБ</td>
                    <td>{new Date(s.created_at).toLocaleString("ru-RU")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  );
}
