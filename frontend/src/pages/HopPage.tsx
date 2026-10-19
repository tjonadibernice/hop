import { useEffect, useState } from "react";
import { Link } from "react-router";
import { removePage } from "../admin";
import { ApiError, api, messageFor } from "../api";
import { useAuth } from "../auth/AuthContext";
import ActionDialog from "../components/ActionDialog";
import {
  ExternalIcon,
  HeartIcon,
  HopArrow,
  ShuffleIcon,
  StarIcon,
  ThumbDownIcon,
} from "../components/Icons";
import TopicChips from "../components/TopicChips";
import { toneFor } from "../topicTones";
import type { Hop, Interests, Reaction, Topic } from "../types";

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
  const [page, setPage] = useState<Hop | null>(null);
  const [reaction, setReaction] = useState<Reaction | null>(null);
  const [reacting, setReacting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function hop() {
    setError(null);
    setStatus("hopping");
    try {
      const next = await api<Hop>("/hop", { method: "POST" });
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
      {error && status !== "all-seen" && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {status === "idle" && !page && <Welcome />}

      {status === "no-interests" && (
        <div className="empty-state">
          <h1>Pick your interests first</h1>
          <p>Hop needs at least 3 topics to choose from.</p>
          <Link to="/interests" className="button">
            Choose your interests
          </Link>
        </div>
      )}

      {status === "all-seen" && (
        <div className="empty-state">
          <div className="dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <h1>You've seen it all (for now)</h1>
          <p>{error}</p>
          <Link to="/interests" className="button">
            Add more interests
          </Link>
        </div>
      )}

      {page && <PageView page={page} onRemoved={hop} />}

      {/* The controls float at the bottom, where a thumb or mouse can always
          find them without scrolling */}
      <div className="dock-area">
        <div className="dock" role="toolbar" aria-label="Hop controls">
          {page && (
            <button
              type="button"
              className="dock-reaction dislike"
              aria-label="Dislike"
              aria-pressed={reaction === "dislike"}
              onClick={() => react("dislike")}
              disabled={busy}
            >
              <ThumbDownIcon size={22} />
            </button>
          )}
          <button
            type="button"
            className="hop-button"
            onClick={hop}
            disabled={busy}
          >
            <HopArrow />
            {status === "hopping" ? "Hopping…" : page ? "Hop again" : "Hop!"}
          </button>
          {page && (
            <button
              type="button"
              className="dock-reaction like"
              aria-label="Like"
              aria-pressed={reaction === "like"}
              onClick={() => react("like")}
              disabled={busy}
            >
              <HeartIcon size={22} filled={reaction === "like"} />
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

/** The first screen: a big promise and the user's topics as stickers. */
function Welcome() {
  const [topics, setTopics] = useState<Topic[]>([]);

  useEffect(() => {
    // Only decoration, so a failure here just means no stickers
    api<Interests>("/me/interests")
      .then((interests) => setTopics(interests.topics))
      .catch(() => {});
  }, []);

  return (
    <div className="welcome">
      {topics.length > 0 && (
        <ul className="stickers" aria-label="Your topics">
          {topics.slice(0, 5).map((topic) => (
            <li key={topic.id} className={`sticker tone-${toneFor(topic)}`}>
              {topic.name}
            </li>
          ))}
        </ul>
      )}
      <h1>
        One click. <span className="highlight">One good page.</span>
      </h1>
      <p>
        Press Hop to land somewhere new. Like or dislike what you find, and Hop
        learns what to show you next.
      </p>
    </div>
  );
}

function PageView({ page, onRemoved }: { page: Hop; onRemoved: () => void }) {
  const { user } = useAuth();
  const [removing, setRemoving] = useState(false);
  const site = new URL(page.url).hostname;
  // The first topic colors the header card
  const tone = page.topics.length > 0 ? toneFor(page.topics[0]) : "lilac";

  return (
    <article className="hop-result">
      <header className={`page-header tone-${tone}`}>
        <div className="page-header-text">
          <div className="badges">
            <p className="site-badge">{site}</p>
            <p className={`pick-badge ${page.strategy}`}>
              {page.strategy === "recommender" ? (
                <>
                  <StarIcon />
                  Picked for you
                </>
              ) : (
                <>
                  <ShuffleIcon />
                  Random find
                </>
              )}
            </p>
          </div>
          <h1>{page.title}</h1>
          {page.summary && <p className="summary">{page.summary}</p>}
          <TopicChips topics={page.topics} />
        </div>
        <div className="page-header-actions">
          <a
            className="button secondary"
            href={page.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open in new tab
            <ExternalIcon />
          </a>
          {/* Admins can take a bad page out of Hop without leaving it */}
          {user?.is_admin && (
            <button
              type="button"
              className="link-button"
              onClick={() => setRemoving(true)}
            >
              Remove from Hop
            </button>
          )}
        </div>
      </header>
      {removing && (
        <ActionDialog
          title="Remove from Hop"
          description="The page disappears from Hop and from everyone's likes right away. Its history is kept, and Hop won't fetch it again."
          confirmLabel="Remove and hop on"
          onConfirm={async (reason) => {
            await removePage(page.id, reason);
            onRemoved();
          }}
          onClose={() => setRemoving(false)}
        />
      )}

      {page.embeddable === false ? (
        <div className="embed-blocked">
          <div>
            <h2>This one opens in its own tab</h2>
            <p>
              {site} doesn't let other sites show its pages, so Hop can't
              display it here. The summary above tells you what you'll find.
            </p>
          </div>
          <a
            className="button"
            href={page.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Read it on {site}
            <ExternalIcon />
          </a>
        </div>
      ) : (
        <>
          {page.embeddable === null && (
            <p className="hint">
              If the page stays blank, open it in a new tab.
            </p>
          )}
          <div className="frame-ring">
            {/* key: a new iframe for every page, so the old one never flashes */}
            <iframe
              key={page.id}
              className="page-frame"
              src={page.url}
              title={page.title}
              sandbox={SANDBOX}
              referrerPolicy="no-referrer"
            />
          </div>
        </>
      )}
    </article>
  );
}
