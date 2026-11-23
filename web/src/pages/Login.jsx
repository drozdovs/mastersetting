import { useState } from "react";
import { api, setToken } from "../api.js";

export default function Login({ onLogin }) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const res = await api.login(login.trim(), password);
      setToken(res.access_token);
      onLogin();
    } catch (err) {
      setError(err.message || "Ошибка входа");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit}>
        <h2>Master<span style={{ color: "var(--accent)" }}>Setting</span></h2>
        <div className="muted" style={{ marginBottom: 16, textAlign: "center" }}>
          Вход в админку
        </div>
        <input
          placeholder="Логин"
          value={login}
          onChange={(e) => setLogin(e.target.value)}
          autoFocus
        />
        <div className="mt" />
        <input
          type="password"
          placeholder="Пароль"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <div className="error">{error}</div>}
        <div className="mt">
          <button type="submit" style={{ width: "100%" }} disabled={busy}>
            {busy ? "Вход…" : "Войти"}
          </button>
        </div>
      </form>
    </div>
  );
}
