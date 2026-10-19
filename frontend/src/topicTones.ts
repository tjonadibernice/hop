import type { Topic } from "./types";

/**
 * Every topic gets a color ("tone") so it's easy to recognize on every
 * screen. A tone is just a CSS class, like "tone-sun"; index.css defines
 * what each tone looks like in light and in dark mode.
 */
export type Tone =
  "sun" | "mint" | "rose" | "peach" | "lilac" | "sky" | "lime" | "coral";

const TONES: Tone[] = [
  "sun",
  "mint",
  "rose",
  "peach",
  "lilac",
  "sky",
  "lime",
  "coral",
];

/** Hand-picked tones for the launch topics, so neighbors look different. */
const TOPIC_TONES: Record<string, Tone> = {
  "productivity-focus": "sun",
  "learning-how-to-learn": "mint",
  "note-taking-knowledge-management": "rose",
  "habits-routines": "peach",
  "mental-models-decision-making": "lilac",
  "writing-communication": "sky",
  "language-learning": "lime",
  "programming-software-engineering": "sky",
  "computer-science-fundamentals": "rose",
  "ai-machine-learning": "lilac",
  cybersecurity: "mint",
  "networking-linux": "sun",
  "cloud-devops": "sky",
  "data-databases": "coral",
  "career-growth-in-tech": "lime",
};

/** The tone for a topic. Topics added later get a stable tone from the slug. */
export function toneFor(topic: Topic): Tone {
  const known = TOPIC_TONES[topic.slug];
  if (known) {
    return known;
  }
  let hash = 0;
  for (const char of topic.slug) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return TONES[hash % TONES.length];
}

/** How the Interests page groups topics. Unlisted topics go under "More". */
export const TOPIC_GROUPS: { name: string; slugs: string[] }[] = [
  {
    name: "Study and thinking",
    slugs: [
      "productivity-focus",
      "learning-how-to-learn",
      "note-taking-knowledge-management",
      "habits-routines",
      "mental-models-decision-making",
      "writing-communication",
      "language-learning",
    ],
  },
  {
    name: "Tech",
    slugs: [
      "programming-software-engineering",
      "computer-science-fundamentals",
      "ai-machine-learning",
      "cybersecurity",
      "networking-linux",
      "cloud-devops",
      "data-databases",
      "career-growth-in-tech",
    ],
  },
];
