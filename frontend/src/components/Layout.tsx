import { Link, NavLink, Outlet, useNavigate } from "react-router";
import { useAuth } from "../auth/AuthContext";
import HealthStatus from "./HealthStatus";

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <div className="layout">
      <header className="header">
        <Link to="/" className="logo">
          Hop
        </Link>
        <nav className="nav">
          {user ? (
            <>
              <NavLink to="/" end>
                Hop
              </NavLink>
              <NavLink to="/likes">Likes</NavLink>
              <NavLink to="/interests">Interests</NavLink>
              <span className="nav-email">{user.email}</span>
              <button
                type="button"
                className="link-button"
                onClick={handleLogout}
              >
                Log out
              </button>
            </>
          ) : (
            <>
              <NavLink to="/login">Log in</NavLink>
              <NavLink to="/signup">Sign up</NavLink>
            </>
          )}
        </nav>
      </header>

      <main className="main">
        <Outlet />
      </main>

      <footer className="footer">
        <HealthStatus />
      </footer>
    </div>
  );
}
