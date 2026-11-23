import { useEffect, useState } from "react";
import { api, getToken } from "../api.js";

export default function Events() {
  const [events, setEvents] = useState([]);
  const [limit, setLimit] = useState(100);
  const [error, setError] = useState("");

  function load() {
    api.events(limit).then(setEvents).catch((e) => setError(e.message));
  }
  useEffect(load, [limit]);

  function download(path, name) {
    // Скачиваем с токеном через fetch -> blob
    fetch(path, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = name;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((e) => setError(e.message));
  }

  return (
    <>
      <h2>Журнал операций</h2>
      {error && <div className="error">{error}</div>}

      <div className="card row wrap">
        <span className="muted">Показать последних:</span>
        <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}
                style={{ width: 120 }}>
          {[50, 100, 250, 500].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <button className="ghost" onClick={load}>Обновить</button>
        <div className="grow" />
        <button className="ghost"
                onClick={() => download(api.exportCsvUrl(), "events.csv")}>
          Экспорт CSV
        </button>
        <button onClick={() => download(api.exportXlsUrl(), "events.xls")}>
          Экспорт Excel
        </button>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Время</th><th>Тип</th><th>Статус</th><th>Оператор</th>
              <th>Камера</th><th>Настройки</th><th>Файлов</th><th>Размер</th><th>Сообщение</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}>
                <td>{new Date(e.created_at).toLocaleString("ru-RU")}</td>
                <td>{e.kind === "save" ? "Сохранение" : "Загрузка"}</td>
                <td>
                  <span className={"badge " + (e.status === "ok" ? "ok" : "err")}>
                    {e.status}
                  </span>
                </td>
                <td>{e.operator}</td>
                <td>{e.camera}</td>
                <td>{e.settings_name}</td>
                <td>{e.files}</td>
                <td>{Math.round((e.bytes || 0) / 1024)} КБ</td>
                <td className="muted">{e.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
