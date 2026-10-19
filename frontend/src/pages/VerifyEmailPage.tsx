import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, messageFor } from "../api";
import AuthShell from "../components/AuthShell";
import type { Message } from "../types";

type Status = "ready" | "verifying" | "verified" | "failed";

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const [status, setStatus] = useState<Status>("ready");
  const [error, setError] = useState<string | null>(null);

  // Verification only happens when the user clicks the button. Email
  // scanners that open (and even run) the link can't use up the token.
  async function handleVerify() {
    setStatus("verifying");
    try {
      await api<Message>("/auth/verify-email", {
        method: "POST",
        body: { token },
      });
      setStatus("verified");
    } catch (err) {
      setError(messageFor(err));
      setStatus("failed");
    }
  }

  if (!token) {
    return (
      <AuthShell>
        <h1>Invalid link</h1>
        <p>
          This link is missing its token. Open the link from your email again.
        </p>
      </AuthShell>
    );
  }

  if (status === "verified") {
    return (
      <AuthShell>
        <h1>Email confirmed</h1>
        <p>Your account is ready.</p>
        <Link to="/login" className="button">
          Log in
        </Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <h1>Confirm your email</h1>
      <p>Click the button to finish creating your Hop account.</p>
      {status === "failed" && (
        <p className="error" role="alert">
          {error} You can <Link to="/signup">sign up again</Link> to get a new
          link.
        </p>
      )}
      <button
        type="button"
        onClick={handleVerify}
        disabled={status === "verifying"}
      >
        {status === "verifying" ? "Confirming…" : "Confirm my email"}
      </button>
    </AuthShell>
  );
}
