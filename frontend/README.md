# Hop Frontend

React + TypeScript app for Hop, built with Vite and React Router. Users can sign up, confirm their email, log in, choose their interests, hop to random pages, like or dislike them, and see their liked pages. The footer shows the system status from the API's readiness check.

## Requirements

- Node.js 20.19+ or 22.12+ (current LTS recommended)
- The backend running on http://localhost:8000 (see [backend/README.md](../backend/README.md))

## Setup

From `frontend/`:

```bash
npm install
```

## Run

```bash
npm run dev
```

Open http://localhost:5173.

## Pages

| Path                      | Login | Purpose                                                                             |
| ------------------------- | ----- | ----------------------------------------------------------------------------------- |
| `/`                       | Yes   | The Hop screen: press Hop, read the page, like or dislike it                        |
| `/likes`                  | Yes   | Pages the user liked, newest first                                                  |
| `/interests`              | Yes   | Choose at least 3 topics                                                            |
| `/login`                  | No    | Log in; new users go to `/interests` next                                           |
| `/signup`                 | No    | Create an account; shows "Check your email"                                         |
| `/verify-email?token=...` | No    | Opened from the sign-up email; confirms the account when the user clicks the button |

Pages that need a login are wrapped in `RequireAuth`, which sends logged-out visitors to `/login` and back afterward. This only affects what the page shows; the backend enforces the real access rules.

## The Hop screen

Nothing happens until the user presses **Hop**, which calls `POST /hop`. Every hop is recorded as a view, so pages never load on their own.

| API response      | What the screen shows                                                       |
| ----------------- | --------------------------------------------------------------------------- |
| `200` with a page | Title, topic chips, summary, an "Open in new tab" link, and the page itself |
| `409`             | "Pick your interests first", with a link to `/interests`                    |
| `404`             | "You've seen it all", with a link to add more interests                     |

The page is shown according to its `embeddable` value (see the [backend README](../backend/README.md#showing-pages-in-an-iframe)): in an iframe when it's `true`, in an iframe with a hint when it's `null` (not checked), and as a card with an "Open in new tab" button when it's `false`. The "Open in new tab" link is always there, with `rel="noopener noreferrer"` so the other site can't control the Hop tab.

The iframe is locked down:

| Attribute                                                                               | Effect                                                                                              |
| --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"` | The page can run scripts and open links in new tabs, but can't navigate the Hop tab or submit forms |
| `referrerPolicy="no-referrer"`                                                          | The site isn't told the request came from Hop                                                       |
| `key={page.id}`                                                                         | React creates a fresh iframe for every page                                                         |

**Like** and **Dislike** call `PUT /pages/{id}/reaction`. The chosen button gets `aria-pressed="true"`, so screen readers announce it as pressed. Clicking the other one changes the reaction; the backend keeps the history.

## How the frontend reaches the API

In development, Vite **proxies** requests that start with `/api` to the backend, so the browser only talks to one origin and CORS isn't needed. It also means the session cookie is stored for `localhost:5173` and sent with every API request automatically.

| The browser requests | Vite forwards it to             |
| -------------------- | ------------------------------- |
| `/api/auth/me`       | `http://localhost:8000/auth/me` |

The proxy is configured in `vite.config.ts`. Frontend code calls the API through `api()` in `src/api.ts`, which adds the `/api` prefix, sends JSON, and turns error responses into readable messages.

## Login state

`AuthProvider` asks `GET /auth/me` once when the app loads and shares the result with every page through `useAuth()`. The session token lives in an `HttpOnly` cookie, so JavaScript never sees it.

Email confirmation needs a button click on purpose: some email security tools open links and run their JavaScript, which would use up the token if the page confirmed automatically.

## Scripts

| Command           | What it does                                       |
| ----------------- | -------------------------------------------------- |
| `npm run dev`     | Starts the dev server with hot reload              |
| `npm run build`   | Type-checks and builds for production into `dist/` |
| `npm run lint`    | Runs ESLint                                        |
| `npm run preview` | Serves the production build locally                |
| `npm run format`  | Formats all files with Prettier                    |

## Project structure

```
src/
├── main.tsx                  # Entry point
├── App.tsx                   # Routes
├── api.ts                    # API calls and error messages
├── types.ts                  # Shapes of API responses
├── index.css                 # Styles
├── auth/
│   ├── AuthContext.ts        # Login state and the useAuth() hook
│   ├── AuthProvider.tsx      # Loads and updates the login state
│   └── RequireAuth.tsx       # Redirects logged-out visitors to /login
├── components/
│   ├── Layout.tsx            # Header, navigation, and footer
│   ├── HealthStatus.tsx      # Shows API, Postgres, and Redis status
│   └── TopicChips.tsx        # A page's topics as small labels
└── pages/
    ├── HopPage.tsx           # The Hop button, the page, and reactions
    ├── InterestsPage.tsx
    ├── LikesPage.tsx
    ├── LoginPage.tsx
    ├── SignupPage.tsx
    └── VerifyEmailPage.tsx
```
