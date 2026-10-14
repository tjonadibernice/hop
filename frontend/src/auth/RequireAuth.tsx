import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useAuth } from "./AuthContext";

/** Shows its children only to logged-in users; sends others to /login. */
export default function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <p>Loading…</p>;
  }
  if (user === null) {
    // Remember where they were going, so login can send them back there
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return children;
}
