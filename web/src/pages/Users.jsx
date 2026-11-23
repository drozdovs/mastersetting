import { useEffect, useState } from "react";
import { api } from "../api.js";

const ROLES = ["admin", "manager", "viewer"];

export default function Users() {
  const [users, setUsers] = useState([]);
  const [groups, setGroups] = useState([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ login: "", password: "", full_name: "", role: "viewer", group_id: "" });

  function load() {
    api.users().then(setUsers).catch((e) => setError(e.message));
    api.groups().then(setGroups).catch(() => {});
  }
  useEffect(load, []);

  async function create(e) {
    e.preventDefault();
    setError("");
    try {
      await api.createUser({
        ...form,
        group_id: form.group_id ? Number(form.group_id) : null,
      });
      setForm({ login: "", password: "", full_name: "", role: "viewer", group_id: "" });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function changeRole(u, role) {
    try {
      await api.updateUser(u.id, { role });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function toggleActive(u) {
    try {
      await api.updateUser(u.id, { is_active: !u.is_active });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(u) {
    if (!confirm(`Удалить пользователя ${u.login}?`)) return;
    try {
      await api.deleteUser(u.id);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <>
      <h2>Пользователи</h2>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <h3>Новый пользователь</h3>
        <form className="row wrap" onSubmit={create}>
          <input placeholder="Логин" value={form.login}
                 onChange={(e) => setForm({ ...form, login: e.target.value })} required />
          <input placeholder="Пароль" type="password" value={form.password}
                 onChange={(e) => setForm({ ...form, password: e.target.value })} required />
          <input placeholder="Имя" value={form.full_name}
                 onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <select value={form.group_id} onChange={(e) => setForm({ ...form, group_id: e.target.value })}>
            <option value="">— группа —</option>
            {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
          <button type="submit">Создать</button>
        </form>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr><th>Логин</th><th>Имя</th><th>Роль</th><th>Группа</th><th>Статус</th><th></th></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.login}</td>
                <td>{u.full_name}</td>
                <td>
                  <select value={u.role} onChange={(e) => changeRole(u, e.target.value)}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </td>
                <td>{groups.find((g) => g.id === u.group_id)?.name || "—"}</td>
                <td>
                  <span className={"badge " + (u.is_active ? "ok" : "err")}>
                    {u.is_active ? "активен" : "отключён"}
                  </span>
                </td>
                <td className="row">
                  <button className="ghost" onClick={() => toggleActive(u)}>
                    {u.is_active ? "Отключить" : "Включить"}
                  </button>
                  <button className="danger" onClick={() => remove(u)}>Удалить</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
