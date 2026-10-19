import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api, messageFor } from "../api";
import AuthShell from "../components/AuthShell";
import type { Message } from "../types";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); // stop the browser's own full-page form submit
    setError(null);
    setSubmitting(true);
    try {
      await api<Message>("/auth/signup", {
        method: "POST",
        body: { email, password },
      });
      setDone(true);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <AuthShell>
        <h1>Check your email</h1>
        <p>
          We sent a message to <strong>{email}</strong>. Open the link inside
          within 24 hours to finish signing up.
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <h1>Sign up</h1>
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
            autoComplete="new-password"
            required
            minLength={8}
            maxLength={128}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <span className="hint">At least 8 characters.</span>
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={submitting}>
          {submitting ? "Signing up…" : "Sign up"}
        </button>
      </form>
      <p>
        Already have an account? <Link to="/login">Log in</Link>
      </p>
    </AuthShell>
  );
}
