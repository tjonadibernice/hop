import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError } from "../api";
import type { User } from "../types";
import { AuthContext } from "./AuthContext";

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // On page load, ask the API who's logged in. The session cookie is sent
  // automatically, so this works after a refresh too.
  useEffect(() => {
    api<User>("/auth/me")
      .then(setUser)
      .catch((error: unknown) => {
        if (!(error instanceof ApiError && error.status === 401)) {
          console.error("Couldn't check the session", error);
        }
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const loggedIn = await api<User>("/auth/login", {
      method: "POST",
      body: { email, password },
    });
    setUser(loggedIn);
    return loggedIn;
  }, []);

  const logout = useCallback(async () => {
    await api("/auth/logout", { method: "POST" });
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, logout }),
    [user, loading, login, logout],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
