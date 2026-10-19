import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { api, messageFor } from "../api";
import { CheckIcon } from "../components/Icons";
import { TOPIC_GROUPS, toneFor } from "../topicTones";
import type { Interests, Topic } from "../types";

const MIN_INTERESTS = 3;

/** Sort topics into the groups from topicTones.ts, plus "More" for the rest. */
function groupTopics(topics: Topic[]) {
  const bySlug = new Map(topics.map((topic) => [topic.slug, topic]));
  const groups = TOPIC_GROUPS.map((group) => ({
    name: group.name,
    topics: group.slugs
      .map((slug) => bySlug.get(slug))
      .filter((topic): topic is Topic => topic !== undefined),
  }));
  const grouped = new Set(TOPIC_GROUPS.flatMap((group) => group.slugs));
  const rest = topics.filter((topic) => !grouped.has(topic.slug));
  if (rest.length > 0) {
    groups.push({ name: "More", topics: rest });
  }
  return groups.filter((group) => group.topics.length > 0);
}

export default function InterestsPage() {
  const navigate = useNavigate();
  const [topics, setTopics] = useState<Topic[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load all topics and the user's current picks at the same time
  useEffect(() => {
    Promise.all([api<Topic[]>("/topics"), api<Interests>("/me/interests")])
      .then(([allTopics, interests]) => {
        setTopics(allTopics);
        setSelected(new Set(interests.topics.map((topic) => topic.id)));
      })
      .catch((err: unknown) => setError(messageFor(err)))
      .finally(() => setLoading(false));
  }, []);

  function toggle(topicId: number) {
    // Build a new Set instead of changing the old one: React only re-renders
    // when state is replaced
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(topicId)) {
        next.delete(topicId);
      } else {
        next.add(topicId);
      }
      return next;
    });
  }

  async function handleSave() {
    setError(null);
    setSaving(true);
    try {
      await api<Interests>("/me/interests", {
        method: "PUT",
        body: { topic_ids: [...selected] },
      });
      navigate("/");
    } catch (err) {
      setError(messageFor(err));
      setSaving(false);
    }
  }

  if (loading) {
    return <p>Loading topics…</p>;
  }

  const remaining = Math.max(MIN_INTERESTS - selected.size, 0);

  return (
    <section className="interests-page">
      <div className="page-title">
        <div>
          <h1>
            What are you <span className="highlight">curious</span> about?
          </h1>
          <p className="muted">
            Pick at least {MIN_INTERESTS}. Hop mixes pages from all of them and
            leans toward the ones you like most.
          </p>
        </div>
      </div>

      {groupTopics(topics).map((group) => (
        <fieldset key={group.name} className="topic-group">
          <legend>{group.name}</legend>
          <div className="topic-grid">
            {group.topics.map((topic) => {
              const checked = selected.has(topic.id);
              return (
                <label
                  key={topic.id}
                  className={`topic tone-${toneFor(topic)}${checked ? " selected" : ""}`}
                >
                  {/* The real checkbox is visually hidden but still focusable
                      and announced; the box next to it is decoration */}
                  <input
                    type="checkbox"
                    className="visually-hidden"
                    checked={checked}
                    onChange={() => toggle(topic.id)}
                  />
                  <span className="topic-box" aria-hidden="true">
                    {checked && <CheckIcon />}
                  </span>
                  {topic.name}
                </label>
              );
            })}
          </div>
        </fieldset>
      ))}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="save-bar">
        <span aria-live="polite">
          {remaining > 0
            ? `${selected.size} picked · ${remaining} more to go`
            : `${selected.size} topics picked. Nice mix!`}
        </span>
        <button
          type="button"
          className="save-button"
          onClick={handleSave}
          disabled={remaining > 0 || saving}
        >
          {remaining > 0
            ? `Pick ${remaining} more`
            : saving
              ? "Saving…"
              : "Save and start hopping"}
        </button>
      </div>
    </section>
  );
}
