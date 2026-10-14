import { useState } from "react";
import { Link } from "react-router";
import { ApiError, api, messageFor } from "../api";
import TopicChips from "../components/TopicChips";
import type { Page, Reaction } from "../types";

type Status = "idle" | "hopping" | "ready" | "no-interests" | "all-seen";

/**
 * Sandbox rules for the iframe. The page can run its scripts and open links
 * in new tabs, but it can't navigate our tab, submit forms, or show popups
 * over Hop. "allow-same-origin" lets the page use its own cookies; it's only
 * risky for pages served from our own origin, which these never are.
 */
const SANDBOX =
  "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox";

export default function HopPage() {
  const [status, setStatus] = useState<Status>("idle");
  const [page, setPage] = useState<Page | null>(null);
  const [reaction, setReaction] = useState<Reaction | null>(null);
  const [reacting, setReacting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function hop() {
    setError(null);
    setStatus("hopping");
    try {
      const next = await api<Page>("/hop", { method: "POST" });
      setPage(next);
      setReaction(null);
      setStatus("ready");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setPage(null);
        setStatus("no-interests");
      } else if (err instanceof ApiError && err.status === 404) {
        setPage(null);
        setStatus("all-seen");
        setError(err.message);
      } else {
        // Network or server trouble: keep showing the current page, if any
        setError(messageFor(err));
        setStatus(page ? "ready" : "idle");
      }
    }
  }

  async function react(choice: Reaction) {
    if (!page) {
      return;
    }
    setError(null);
    setReacting(true);
    try {
      await api(`/pages/${page.id}/reaction`, {
        method: "PUT",
        body: { reaction: choice },
      });
      setReaction(choice);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setReacting(false);
    }
  }

  const busy = status === "hopping" || reacting;

  return (
    <section className="hop-page">
      <div className="hop-bar">
        <button
          type="button"
          className="hop-button"
          onClick={hop}
          disabled={busy}
        >
          {status === "hopping" ? "Hopping…" : page ? "Hop again" : "Hop"}
        </button>

        {page && (
          <div className="reactions" role="group" aria-label="Rate this page">
            <button
              type="button"
              className="reaction"
              aria-pressed={reaction === "like"}
              onClick={() => react("like")}
              disabled={busy}
            >
              Like
            </button>
            <button
              type="button"
              className="reaction"
              aria-pressed={reaction === "dislike"}
              onClick={() => react("dislike")}
              disabled={busy}
            >
              Dislike
            </button>
          </div>
        )}
      </div>

      {error && status !== "all-seen" && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {status === "idle" && !page && (
        <div className="card">
          <h1>Ready to explore?</h1>
          <p>Press Hop to land on a random page from your interests.</p>
        </div>
      )}

      {status === "no-interests" && (
        <div className="card">
          <h1>Pick your interests first</h1>
          <p>
            Hop needs at least 3 topics to choose from.{" "}
            <Link to="/interests">Choose your interests</Link>
          </p>
        </div>
      )}

      {status === "all-seen" && (
        <div className="card">
          <h1>You've seen it all</h1>
          <p>{error}</p>
          <Link to="/interests">Add more interests</Link>
        </div>
      )}

      {page && <PageView page={page} />}
    </section>
  );
}

function PageView({ page }: { page: Page }) {
  const site = new URL(page.url).hostname;

  return (
    <article className="hop-result">
      <header className="page-header">
        <h1>{page.title}</h1>
        <TopicChips topics={page.topics} />
        {page.summary && <p className="summary">{page.summary}</p>}
        <a href={page.url} target="_blank" rel="noopener noreferrer">
          Open in new tab ↗
        </a>
      </header>

      {page.embeddable === false ? (
        <div className="card embed-blocked">
          <p>{site} doesn't allow other sites to show its pages.</p>
          <a
            className="button"
            href={page.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Read it on {site}
          </a>
        </div>
      ) : (
        <>
          {page.embeddable === null && (
            <p className="hint">
              If the page stays blank, open it in a new tab.
            </p>
          )}
          {/* key: a new iframe for every page, so the old one never flashes */}
          <iframe
            key={page.id}
            className="page-frame"
            src={page.url}
            title={page.title}
            sandbox={SANDBOX}
            referrerPolicy="no-referrer"
          />
        </>
      )}
    </article>
  );
}
