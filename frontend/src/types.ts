/** Shapes of the JSON the API returns. They mirror the backend's schemas. */

export type User = {
  id: string;
  email: string;
  created_at: string;
  /** Can use the review screen. The server checks again on every admin call. */
  is_admin: boolean;
};

export type Topic = {
  id: number;
  slug: string;
  name: string;
};

export type Interests = {
  topics: Topic[];
};

export type Message = {
  message: string;
};

/** Something to use, play, or explore, or something to read. */
export type PageKind = "interactive" | "article";

export type Page = {
  id: string;
  url: string;
  title: string;
  summary: string | null;
  kind: PageKind;
  /** false: the site refuses iframes. null: not checked yet. */
  embeddable: boolean | null;
  topics: Topic[];
};

export type Reaction = "like" | "dislike";

/** How a page was picked: by the recommender, or at random (the A/B baseline). */
export type Strategy = "recommender" | "random";

/** What POST /hop returns: a page plus how it was picked. */
export type Hop = Page & { strategy: Strategy };

/* --- The review screen (admins only) --- */

export type PageStatus =
  "pending" | "approved" | "rejected" | "needs_review" | "dead";

export type CuratorStep = {
  tool: string;
  args: Record<string, unknown>;
  result: string;
};

export type CuratorReview = {
  id: number;
  proposed: "approve" | "reject" | "escalate";
  outcome: "approved" | "rejected" | "needs_review";
  reason: string;
  /** The guardrail that overrode the agent, if any. */
  blocked_by: string | null;
  topics: string[];
  quality: number | null;
  provider: string | null;
  steps: CuratorStep[];
  created_at: string;
};

export type ReviewAction = {
  id: number;
  actor_email: string;
  action: "approve" | "reject" | "remove" | "purge";
  from_status: PageStatus;
  to_status: PageStatus;
  reason: string | null;
  topics: string[];
  created_at: string;
};

export type AdminPage = {
  id: string;
  url: string;
  site: string | null;
  title: string;
  kind: PageKind;
  status: PageStatus;
  status_reason: string | null;
  quality_score: number | null;
  topics: Topic[];
  created_at: string;
  curated_at: string | null;
  purged_at: string | null;
  latest_review: CuratorReview | null;
};

export type AdminPageDetail = AdminPage & {
  summary: string | null;
  excerpt: string | null;
  reviews: CuratorReview[];
  actions: ReviewAction[];
};
