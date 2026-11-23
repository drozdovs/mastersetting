import { useEffect, useState } from "react";
import { api } from "../api.js";

function Stat({ num, lbl, color }) {
  return (
    <div className="stat">
      <div className="num" style={color ? { color } : undefined}>{num}</div>
      <div className="lbl">{lbl}</div>
    </div>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState("");

  function load() {
    api.stats().then(setStats).catch((e) => setError(e.message));
    api.events(8).then(setEvents).catch(() => {});
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!stats) return <div className="muted">Загрузка…</div>;

  return (
    <>
      <h2>Дашборд</h2>
      <div className="grid">
        <Stat num={stats.agents_online} lbl="Агентов онлайн" color="var(--ok)" />
        <Stat num={stats.agents_total} lbl="Агентов всего" />
        <Stat num={stats.saves_ok} lbl="Сохранений (ок)" />
        <Stat num={stats.loads_ok} lbl="Загрузок (ок)" />
        <Stat num={stats.errors} lbl="Ошибок" color="var(--err)" />
        <Stat num={stats.settings_count} lbl="Наборов настроек" />
      </div>

      <div className="card mt">
        <h3>Топ операторов</h3>
        {stats.top_operators.length === 0 ? (
          <div className="muted">Пока нет данных</div>
        ) : (
          <table>
            <thead>
              <tr><th>Оператор</th><th>Операций</th></tr>
            </thead>
            <tbody>
              {stats.top_operators.map((o) => (
                <tr key={o.operator}>
                  <td>{o.operator}</td>
                  <td>{o.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h3>Последние операции</h3>
        {events.length === 0 ? (
          <div className="muted">Пока нет операций</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Время</th><th>Тип</th><th>Оператор</th>
                <th>Камера</th><th>Настройки</th><th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td>{new Date(e.created_at).toLocaleString("ru-RU")}</td>
                  <td>{e.kind === "save" ? "Сохранение" : "Загрузка"}</td>
                  <td>{e.operator}</td>
                  <td>{e.camera}</td>
                  <td>{e.settings_name}</td>
                  <td>
                    <span className={"badge " + (e.status === "ok" ? "ok" : "err")}>
                      {e.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
