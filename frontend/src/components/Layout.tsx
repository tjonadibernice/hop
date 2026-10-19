import { Link, NavLink, Outlet, useNavigate } from "react-router";
import { useAuth } from "../auth/AuthContext";
import HealthStatus from "./HealthStatus";
import { HopMark } from "./Icons";
import ThemeToggle from "./ThemeToggle";

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
        <div className="header-inner">
          <Link to="/" className="logo">
            <span className="logo-mark">
              <HopMark />
            </span>
            <span className="logo-text">hop</span>
          </Link>

          {user && (
            <nav className="nav" aria-label="Main">
              <NavLink to="/" end>
                Hop
              </NavLink>
              <NavLink to="/likes">Likes</NavLink>
              <NavLink to="/interests">Interests</NavLink>
            </nav>
          )}

          <div className="header-actions">
            <ThemeToggle />
            {user ? (
              <>
                <span className="avatar" title={user.email} aria-hidden="true">
                  {user.email[0].toUpperCase()}
                </span>
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
              <nav className="nav" aria-label="Account">
                <NavLink to="/login">Log in</NavLink>
                <NavLink to="/signup">Sign up</NavLink>
              </nav>
            )}
          </div>
        </div>
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
