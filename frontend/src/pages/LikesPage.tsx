import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, messageFor } from "../api";
import TopicChips from "../components/TopicChips";
import type { Page } from "../types";

export default function LikesPage() {
  const [pages, setPages] = useState<Page[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Page[]>("/me/likes")
      .then(setPages)
      .catch((err: unknown) => setError(messageFor(err)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <p>Loading your likes…</p>;
  }

  return (
    <section>
      <h1>Pages you liked</h1>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!error && pages.length === 0 && (
        <div className="card">
          <p>
            No likes yet. Press Like on pages you enjoy, and they'll show up
            here.
          </p>
          <Link to="/">Start hopping</Link>
        </div>
      )}

      <ul className="likes">
        {pages.map((page) => (
          <li key={page.id} className="card">
            <a href={page.url} target="_blank" rel="noopener noreferrer">
              <h2>{page.title}</h2>
            </a>
            <TopicChips topics={page.topics} />
            {page.summary && <p className="summary">{page.summary}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
