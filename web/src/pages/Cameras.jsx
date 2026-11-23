import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Cameras() {
  const [cameras, setCameras] = useState([]);
  const [form, setForm] = useState({ name: "", model: "", notes: "" });
  const [error, setError] = useState("");

  function load() {
    api.cameras().then(setCameras).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function create(e) {
    e.preventDefault();
    setError("");
    try {
      await api.createCamera(form);
      setForm({ name: "", model: "", notes: "" });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function toggle(c) {
    try {
      await api.updateCamera(c.id, { is_active: !c.is_active });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(c) {
    if (!confirm(`Удалить камеру ${c.name}?`)) return;
    try {
      await api.deleteCamera(c.id);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <>
      <h2>Камеры</h2>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <h3>Новая камера</h3>
        <form className="row wrap" onSubmit={create}>
          <input placeholder="Название" value={form.name}
                 onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          <input placeholder="Модель" value={form.model}
                 onChange={(e) => setForm({ ...form, model: e.target.value })} />
          <input placeholder="Заметки" value={form.notes}
                 onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <button type="submit">Добавить</button>
        </form>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr><th>Название</th><th>Модель</th><th>Заметки</th><th>Статус</th><th></th></tr>
          </thead>
          <tbody>
            {cameras.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td>{c.model}</td>
                <td>{c.notes}</td>
                <td>
                  <span className={"badge " + (c.is_active ? "ok" : "warn")}>
                    {c.is_active ? "активна" : "в архиве"}
                  </span>
                </td>
                <td className="row">
                  <button className="ghost" onClick={() => toggle(c)}>
                    {c.is_active ? "В архив" : "Активировать"}
                  </button>
                  <button className="danger" onClick={() => remove(c)}>Удалить</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
