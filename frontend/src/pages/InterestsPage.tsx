import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { api, messageFor } from "../api";
import type { Interests, Topic } from "../types";

const MIN_INTERESTS = 3;

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

  const remaining = MIN_INTERESTS - selected.size;

  return (
    <section>
      <h1>What are you curious about?</h1>
      <p>
        Pick at least {MIN_INTERESTS} topics. Hop will find pages from them.
      </p>

      <div className="topic-grid">
        {topics.map((topic) => (
          <label
            key={topic.id}
            className={selected.has(topic.id) ? "topic selected" : "topic"}
          >
            <input
              type="checkbox"
              checked={selected.has(topic.id)}
              onChange={() => toggle(topic.id)}
            />
            {topic.name}
          </label>
        ))}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button
        type="button"
        onClick={handleSave}
        disabled={remaining > 0 || saving}
      >
        {remaining > 0
          ? `Pick ${remaining} more`
          : saving
            ? "Saving…"
            : "Save and start hopping"}
      </button>
    </section>
  );
}
