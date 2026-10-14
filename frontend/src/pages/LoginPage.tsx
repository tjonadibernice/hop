import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { api, messageFor } from "../api";
import { useAuth } from "../auth/AuthContext";
import type { Interests } from "../types";

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Where RequireAuth was sending them before it redirected here
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (user && !submitting) {
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      // New users haven't picked interests yet: send them there first
      const interests = await api<Interests>("/me/interests");
      navigate(interests.topics.length === 0 ? "/interests" : from, {
        replace: true,
      });
    } catch (err) {
      setError(messageFor(err));
      setSubmitting(false);
    }
  }

  return (
    <section className="card">
      <h1>Log in</h1>
      <form onSubmit={handleSubmit} className="form">
        <label>
          Email
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={submitting}>
          {submitting ? "Logging in…" : "Log in"}
        </button>
      </form>
      <p>
        New to Hop? <Link to="/signup">Sign up</Link>
      </p>
    </section>
  );
}
