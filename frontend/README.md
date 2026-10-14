# Hop Frontend

React + TypeScript app for Hop, built with Vite and React Router. Users can sign up, confirm their email, log in, and choose their interests. The footer shows the system status from the API's readiness check.

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
| `/`                       | Yes   | Home (the Hop screen comes next)                                                    |
| `/interests`              | Yes   | Choose at least 3 topics                                                            |
| `/login`                  | No    | Log in; new users go to `/interests` next                                           |
| `/signup`                 | No    | Create an account; shows "Check your email"                                         |
| `/verify-email?token=...` | No    | Opened from the sign-up email; confirms the account when the user clicks the button |

Pages that need a login are wrapped in `RequireAuth`, which sends logged-out visitors to `/login` and back afterward. This only affects what the page shows; the backend enforces the real access rules.

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
│   └── HealthStatus.tsx      # Shows API, Postgres, and Redis status
└── pages/
    ├── HomePage.tsx
    ├── InterestsPage.tsx
    ├── LoginPage.tsx
    ├── SignupPage.tsx
    └── VerifyEmailPage.tsx
```
