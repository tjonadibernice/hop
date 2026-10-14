import type { Topic } from "../types";

export default function TopicChips({ topics }: { topics: Topic[] }) {
  return (
    <ul className="chips" aria-label="Topics">
      {topics.map((topic) => (
        <li key={topic.id} className="chip">
          {topic.name}
        </li>
      ))}
    </ul>
  );
}
