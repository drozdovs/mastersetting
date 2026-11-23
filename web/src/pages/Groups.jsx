import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Groups() {
  const [groups, setGroups] = useState([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");

  function load() {
    api.groups().then(setGroups).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function create(e) {
    e.preventDefault();
    setError("");
    try {
      await api.createGroup({ name, description });
      setName("");
      setDescription("");
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(g) {
    if (!confirm(`Удалить группу ${g.name}?`)) return;
    try {
      await api.deleteGroup(g.id);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <>
      <h2>Группы</h2>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <h3>Новая группа</h3>
        <form className="row wrap" onSubmit={create}>
          <input placeholder="Название" value={name}
                 onChange={(e) => setName(e.target.value)} required />
          <input placeholder="Описание" value={description}
                 onChange={(e) => setDescription(e.target.value)} />
          <button type="submit">Создать</button>
        </form>
      </div>

      <div className="card">
        <table>
          <thead><tr><th>Название</th><th>Описание</th><th></th></tr></thead>
          <tbody>
            {groups.map((g) => (
              <tr key={g.id}>
                <td>{g.name}</td>
                <td>{g.description}</td>
                <td><button className="danger" onClick={() => remove(g)}>Удалить</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
