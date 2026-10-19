import type { ReactNode } from "react";
import { HopMark } from "./Icons";

/**
 * The two-column frame shared by Log in, Sign up, and Confirm email:
 * a short pitch on the left and the form card on the right.
 */
export default function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="auth-shell">
      <div className="auth-hero">
        <span className="auth-shape auth-shape-a" aria-hidden="true" />
        <span className="auth-shape auth-shape-b" aria-hidden="true" />
        <span className="logo auth-logo">
          <span className="logo-mark">
            <HopMark size={24} />
          </span>
          <span className="logo-text">hop</span>
        </span>
        <p className="auth-headline">
          One click.
          <br />
          <span className="highlight">One good page.</span>
        </p>
        <p className="auth-pitch">
          Hop finds pages worth your time on the topics you pick, and learns
          from every like.
        </p>
      </div>
      <section className="card auth-card">{children}</section>
    </div>
  );
}
