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
