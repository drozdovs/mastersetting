import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

export default function Releases() {
  const [releases, setReleases] = useState([]);
  const [form, setForm] = useState({ version: "", notes: "", mandatory: false });
  const [error, setError] = useState("");
  const fileInputs = useRef({});

  function load() {
    api.releases().then(setReleases).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function create(e) {
    e.preventDefault();
    setError("");
    try {
      await api.createRelease(form);
      setForm({ version: "", notes: "", mandatory: false });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function upload(r) {
    const input = fileInputs.current[r.id];
    if (!input || !input.files[0]) {
      setError("Выберите файл сборки");
      return;
    }
    try {
      await api.uploadRelease(r.id, input.files[0]);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function publish(r) {
    try {
      await api.publishRelease(r.id);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <>
      <h2>Обновления агента</h2>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <h3>Создать релиз</h3>
        <form className="row wrap" onSubmit={create}>
          <input placeholder="Версия (напр. 2.1.0)" value={form.version}
                 onChange={(e) => setForm({ ...form, version: e.target.value })} required />
          <input placeholder="Что нового" value={form.notes} className="grow"
                 onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <label className="row">
            <input type="checkbox" checked={form.mandatory} style={{ width: "auto" }}
                   onChange={(e) => setForm({ ...form, mandatory: e.target.checked })} />
            Обязательное
          </label>
          <button type="submit">Создать</button>
        </form>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Версия</th><th>Что нового</th><th>Файл</th>
              <th>SHA-256</th><th>Обяз.</th><th>Опубликован</th><th></th>
            </tr>
          </thead>
          <tbody>
            {releases.map((r) => (
              <tr key={r.id}>
                <td>{r.version}</td>
                <td>{r.notes}</td>
                <td className="muted">{r.filename || "— не загружен —"}</td>
                <td className="muted" style={{ fontFamily: "monospace", fontSize: 11 }}>
                  {r.sha256 ? r.sha256.slice(0, 12) + "…" : "—"}
                </td>
                <td>{r.mandatory ? "да" : "нет"}</td>
                <td>
                  <span className={"badge " + (r.is_published ? "ok" : "warn")}>
                    {r.is_published ? "да" : "нет"}
                  </span>
                </td>
                <td className="row">
                  <input type="file" style={{ width: 150 }}
                         ref={(el) => (fileInputs.current[r.id] = el)} />
                  <button className="ghost" onClick={() => upload(r)}>Загрузить</button>
                  {!r.is_published && (
                    <button onClick={() => publish(r)}>Опубликовать</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {releases.length === 0 && <div className="muted mt">Релизов пока нет</div>}
      </div>
    </>
  );
}
