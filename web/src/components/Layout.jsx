import { NavLink } from "react-router-dom";

const links = [
  { to: "/", label: "Дашборд", end: true },
  { to: "/agents", label: "Агенты" },
  { to: "/events", label: "Журнал" },
  { to: "/cameras", label: "Камеры" },
  { to: "/users", label: "Пользователи" },
  { to: "/groups", label: "Группы" },
  { to: "/releases", label: "Обновления" },
];

export default function Layout({ me, onLogout, children }) {
  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>Master<span>Setting</span></h1>
        {links.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.end}
            className={({ isActive }) => "navlink" + (isActive ? " active" : "")}
          >
            {l.label}
          </NavLink>
        ))}
        <div style={{ marginTop: "auto" }}>
          <div className="muted" style={{ padding: "8px 12px" }}>
            {me ? `${me.full_name || me.login} (${me.role})` : "…"}
          </div>
          <button className="ghost" style={{ width: "100%" }} onClick={onLogout}>
            Выйти
          </button>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
