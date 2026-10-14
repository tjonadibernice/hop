import { createContext, useContext } from "react";
import type { User } from "../types";

export type AuthState = {
  /** The logged-in user, or null when nobody is logged in. */
  user: User | null;
  /** True until we know whether someone is logged in. */
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const auth = useContext(AuthContext);
  if (auth === null) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return auth;
}
