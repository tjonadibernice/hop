import { Link } from "react-router";
import { useAuth } from "../auth/AuthContext";

export default function HomePage() {
  const { user } = useAuth();

  return (
    <section className="card">
      <h1>Welcome, {user?.email}</h1>
      <p>The Hop button arrives in the next step.</p>
      <Link to="/interests">Change your interests</Link>
    </section>
  );
}
