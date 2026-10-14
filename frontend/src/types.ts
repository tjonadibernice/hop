/** Shapes of the JSON the API returns. They mirror the backend's schemas. */

export type User = {
  id: string;
  email: string;
  created_at: string;
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

export type Page = {
  id: string;
  url: string;
  title: string;
  summary: string | null;
  /** false: the site refuses iframes. null: not checked yet. */
  embeddable: boolean | null;
  topics: Topic[];
};

export type Reaction = "like" | "dislike";
