import { useEffect, useState, type FormEvent } from "react";
import {
  approvePage,
  pageDetail,
  purgePage,
  rejectPage,
  removePage,
  reviewQueue,
  searchPages,
  type QueueView,
} from "../admin";
import { api, messageFor } from "../api";
import { useAuth } from "../auth/AuthContext";
import ActionDialog from "../components/ActionDialog";
import { ExternalIcon } from "../components/Icons";
import TopicChips from "../components/TopicChips";
import type {
  AdminPage,
  AdminPageDetail,
  CuratorReview,
  Topic,
} from "../types";

type Dialog = "reject" | "remove" | "purge" | null;

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  approved: "Live",
  rejected: "Rejected",
  needs_review: "Needs review",
  dead: "Dead",
};

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default function ReviewPage() {
  const { user } = useAuth();
  const [view, setView] = useState<QueueView>("escalated");
  const [search, setSearch] = useState("");
  const [searched, setSearched] = useState<string | null>(null);
  const [pages, setPages] = useState<AdminPage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<AdminPageDetail | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);

  // Bumped after every action, to reload the list
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!user?.is_admin) {
      return;
    }
    let cancelled = false;
    const request = searched ? searchPages(searched) : reviewQueue(view);
    request
      .then((result) => {
        if (!cancelled) {
          setPages(result);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(messageFor(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    // A newer request replaces this one; ignore its late answer
    return () => {
      cancelled = true;
    };
  }, [user, view, searched, reloadKey]);

  useEffect(() => {
    api<Topic[]>("/topics")
      .then(setTopics)
      .catch(() => {});
  }, []);

  if (!user?.is_admin) {
    return (
      <div className="empty-state">
        <h1>Admins only</h1>
        <p>
          The review screen is for the people listed in ADMIN_EMAILS on the
          server.
        </p>
      </div>
    );
  }

  async function open(page: AdminPage) {
    setError(null);
    try {
      setSelected(await pageDetail(page.id));
    } catch (err) {
      setError(messageFor(err));
    }
  }

  // After an action: show the new state and refresh the list
  function done(detail: AdminPageDetail) {
    setSelected(detail);
    setLoading(true);
    setReloadKey((key) => key + 1);
  }

  function showQueue(next: QueueView) {
    setLoading(true);
    setSearched(null);
    setView(next);
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSelected(null);
    setLoading(true);
    setSearched(search.trim().length >= 2 ? search.trim() : null);
  }

  return (
    <section className="review-page">
      <div className="page-title">
        <div>
          <h1>
            <span className="highlight">Review</span>
          </h1>
          <p className="muted">
            Pages the curator handed to a person, and any page you need to take
            out of Hop.
          </p>
        </div>
        <form className="review-search" role="search" onSubmit={handleSearch}>
          <label className="visually-hidden" htmlFor="review-search">
            Find a page by URL or title
          </label>
          <input
            id="review-search"
            type="search"
            placeholder="Find any page by URL or title"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button type="submit">Find</button>
        </form>
      </div>

      <div className="review-layout">
        <div className="review-list">
          {searched ? (
            <p className="review-list-heading">
              Results for “{searched}”{" "}
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  setSearch("");
                  showQueue(view);
                }}
              >
                Back to the queue
              </button>
            </p>
          ) : (
            <div className="filters" role="group" aria-label="Which pages">
              <button
                type="button"
                className="filter all"
                aria-pressed={view === "escalated"}
                onClick={() => showQueue("escalated")}
              >
                Waiting for you
              </button>
              <button
                type="button"
                className="filter all"
                aria-pressed={view === "all"}
                onClick={() => showQueue("all")}
              >
                All under review
              </button>
            </div>
          )}

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {loading ? (
            <p>Loading…</p>
          ) : pages.length === 0 ? (
            <p className="muted">
              {searched ? "No pages match." : "Nothing waiting. Nice work!"}
            </p>
          ) : (
            <ul className="review-items">
              {pages.map((page) => (
                <li key={page.id}>
                  <button
                    type="button"
                    className="review-item"
                    aria-current={selected?.id === page.id}
                    onClick={() => open(page)}
                  >
                    <span className="review-item-title">{page.title}</span>
                    <span className="review-item-meta">
                      {page.site ?? new URL(page.url).hostname} ·{" "}
                      {page.kind === "interactive" ? "Interactive" : "Article"}{" "}
                      · {STATUS_LABELS[page.status]}
                    </span>
                    {page.latest_review && (
                      <span className="review-item-meta">
                        Curator: {verdict(page.latest_review)}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="review-detail">
          {selected ? (
            <PageReview
              key={selected.id}
              page={selected}
              topics={topics}
              onDone={done}
            />
          ) : (
            <div className="empty-state">
              <p>Pick a page to see the curator's reasoning and decide.</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function verdict(review: CuratorReview) {
  if (review.blocked_by) {
    return `wanted to ${review.proposed}, blocked: ${review.blocked_by}`;
  }
  return review.proposed === "escalate"
    ? "unsure, asks you to decide"
    : `${review.proposed}d`;
}

function PageReview({
  page,
  topics,
  onDone,
}: {
  page: AdminPageDetail;
  topics: Topic[];
  onDone: (detail: AdminPageDetail) => void;
}) {
  const review = page.latest_review;
  // Start from the curator's topics, or the page's current ones
  const [chosen, setChosen] = useState<string[]>(
    review?.topics.length ? review.topics : page.topics.map((t) => t.slug),
  );
  const [note, setNote] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const purged = page.purged_at !== null;
  const canApprove =
    !purged && (page.status === "needs_review" || page.status === "rejected");

  function toggle(slug: string) {
    setChosen((current) =>
      current.includes(slug)
        ? current.filter((s) => s !== slug)
        : [...current, slug].slice(-3),
    );
  }

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      onDone(await approvePage(page.id, chosen, note.trim()));
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card review-card">
      <p className="site-badge">{page.site ?? new URL(page.url).hostname}</p>
      <h2>{page.title}</h2>
      <p className="review-status">
        <span className={`status-pill status-${page.status}`}>
          {STATUS_LABELS[page.status]}
        </span>
        {page.status_reason && (
          <span className="muted">{page.status_reason}</span>
        )}
      </p>
      {!purged && (
        <a
          className="button secondary"
          href={page.url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open the page
          <ExternalIcon />
        </a>
      )}
      {page.summary && <p className="summary">{page.summary}</p>}
      {page.topics.length > 0 && <TopicChips topics={page.topics} />}

      {review && (
        <section className="curator-verdict" aria-label="The curator's review">
          <h3>The curator's review</h3>
          <p>
            <strong>Proposed {review.proposed}</strong>
            {review.quality !== null && (
              <> · quality {review.quality.toFixed(2)}</>
            )}
            {review.provider && <> · {review.provider}</>}
            {" · "}
            {when(review.created_at)}
          </p>
          {review.blocked_by && (
            <p className="blocked">
              Blocked by a guardrail: {review.blocked_by}
            </p>
          )}
          <p>{review.reason}</p>
          {review.steps.length > 0 && (
            <details>
              <summary>
                What it looked up ({review.steps.length}{" "}
                {review.steps.length === 1 ? "step" : "steps"})
              </summary>
              <ol className="curator-steps">
                {review.steps.map((step, index) => (
                  <li key={index}>
                    <code>{step.tool}</code>
                    <pre>{step.result}</pre>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </section>
      )}

      {page.excerpt && (
        <details>
          <summary>The stored text (first part)</summary>
          <pre className="excerpt">{page.excerpt}</pre>
        </details>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {canApprove && (
        <fieldset className="approve-box">
          <legend>Approve with 1 to 3 topics</legend>
          <div className="topic-pick">
            {topics.map((topic) => (
              <label key={topic.slug}>
                <input
                  type="checkbox"
                  checked={chosen.includes(topic.slug)}
                  onChange={() => toggle(topic.slug)}
                />
                {topic.name}
              </label>
            ))}
          </div>
          <label>
            Note (optional)
            <input
              type="text"
              maxLength={300}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={approve}
            disabled={busy || chosen.length === 0}
          >
            {busy ? "Approving…" : "Approve"}
          </button>
        </fieldset>
      )}

      {!purged && (
        <div className="review-actions">
          {page.status === "needs_review" && (
            <button
              type="button"
              className="button secondary"
              onClick={() => setDialog("reject")}
            >
              Reject
            </button>
          )}
          {page.status !== "rejected" && page.status !== "needs_review" && (
            <button
              type="button"
              className="button secondary"
              onClick={() => setDialog("remove")}
            >
              Remove from Hop
            </button>
          )}
          <button
            type="button"
            className="danger"
            onClick={() => setDialog("purge")}
          >
            Purge…
          </button>
        </div>
      )}

      {page.actions.length > 0 && (
        <section aria-label="History">
          <h3>History</h3>
          <ul className="history">
            {page.actions.map((action) => (
              <li key={action.id}>
                <strong>{action.action}</strong> by {action.actor_email},{" "}
                {when(action.created_at)}: {action.from_status} →{" "}
                {action.to_status}
                {action.reason && <> — “{action.reason}”</>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {dialog === "reject" && (
        <ActionDialog
          title="Reject this page"
          description="It won't appear in Hop, and Hop won't fetch it again."
          confirmLabel="Reject"
          onConfirm={async (reason) =>
            onDone(await rejectPage(page.id, reason))
          }
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === "remove" && (
        <ActionDialog
          title="Remove from Hop"
          description="The page disappears from Hop and from everyone's likes right away. Its history is kept, and Hop won't fetch it again."
          confirmLabel="Remove from Hop"
          onConfirm={async (reason) =>
            onDone(await removePage(page.id, reason))
          }
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === "purge" && (
        <ActionDialog
          title="Purge this page"
          description="For takedown requests. The stored text, summary, embedding, and the curator's excerpts are erased for good; only the URL is kept, so the page can't come back. This can't be undone."
          confirmLabel="Purge for good"
          danger
          confirmText={page.url}
          onConfirm={async (reason, typed) =>
            onDone(await purgePage(page.id, reason, typed))
          }
          onClose={() => setDialog(null)}
        />
      )}
    </article>
  );
}
