import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, messageFor } from "../api";
import { ExternalIcon } from "../components/Icons";
import TopicChips from "../components/TopicChips";
import { toneFor } from "../topicTones";
import type { Page, Topic } from "../types";

export default function LikesPage() {
  const [pages, setPages] = useState<Page[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The topic to filter by, or null for all
  const [filter, setFilter] = useState<number | null>(null);

  useEffect(() => {
    api<Page[]>("/me/likes")
      .then(setPages)
      .catch((err: unknown) => setError(messageFor(err)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <p>Loading your likes…</p>;
  }

  // Filter buttons only for topics that appear in the likes, in first-seen order
  const topics = new Map<number, Topic>();
  for (const page of pages) {
    for (const topic of page.topics) {
      topics.set(topic.id, topic);
    }
  }
  const shown =
    filter === null
      ? pages
      : pages.filter((page) => page.topics.some((t) => t.id === filter));

  return (
    <section className="likes-page">
      <div className="page-title">
        <div>
          <h1>
            Your <span className="highlight">likes</span>
          </h1>
          {pages.length > 0 && (
            <p className="muted">
              {pages.length} {pages.length === 1 ? "page" : "pages"} you loved,
              newest first
            </p>
          )}
        </div>

        {topics.size > 1 && (
          <div className="filters" role="group" aria-label="Filter by topic">
            <button
              type="button"
              className="filter all"
              aria-pressed={filter === null}
              onClick={() => setFilter(null)}
            >
              All
            </button>
            {[...topics.values()].map((topic) => (
              <button
                key={topic.id}
                type="button"
                className={`filter tone-${toneFor(topic)}`}
                aria-pressed={filter === topic.id}
                onClick={() => setFilter(topic.id)}
              >
                {topic.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!error && pages.length === 0 && (
        <div className="empty-state">
          <p>
            No likes yet. Press the heart on pages you enjoy, and they'll show
            up here.
          </p>
          <Link to="/" className="button">
            Start hopping
          </Link>
        </div>
      )}

      <ul className="likes">
        {shown.map((page) => {
          const tone =
            page.topics.length > 0 ? toneFor(page.topics[0]) : "lilac";
          return (
            <li key={page.id} className={`like-card tone-${tone}`}>
              <p className="site-badge">{new URL(page.url).hostname}</p>
              <h2>
                <a href={page.url} target="_blank" rel="noopener noreferrer">
                  {page.title}
                </a>
              </h2>
              {page.summary && <p className="summary">{page.summary}</p>}
              <div className="like-card-footer">
                <TopicChips topics={page.topics} />
                <a
                  className="icon-button"
                  href={page.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Open ${page.title} in a new tab`}
                >
                  <ExternalIcon />
                </a>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
