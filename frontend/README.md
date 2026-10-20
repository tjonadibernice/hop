# Hop Frontend

React + TypeScript app for Hop, built with Vite and React Router. Users can sign up, confirm their email, log in, choose their interests, hop to random pages, like or dislike them, and see their liked pages. The app has two looks, a light **Sticker pop** style and a dark **Night glow** style, switched with the night mode button in the header. The footer shows the system status from the API's readiness check.

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
| `/review`                 | Admin | The review queue: the curator's reasoning, then approve, reject, remove, or purge   |

Pages that need a login are wrapped in `RequireAuth`, which sends logged-out visitors to `/login` and back afterward. This only affects what the page shows; the backend enforces the real access rules.

## Look and feel

| Mode  | Style       | Fonts                        | Feel                                                         |
| ----- | ----------- | ---------------------------- | ------------------------------------------------------------ |
| Light | Sticker pop | Bricolage Grotesque, DM Sans | Cream background, bold outlines, solid offset shadows        |
| Dark  | Night glow  | Sora, Manrope                | Deep navy background, glowing gradients, frosted-glass cards |

**How the switch works.** `src/theme.ts` writes the theme to `<html data-theme="light|dark">`. `index.css` defines every color, font, border, and shadow as a CSS variable on `:root`, and redefines them under `[data-theme="dark"]`, so components never choose colors themselves.

| Situation                         | Theme used                                              |
| --------------------------------- | ------------------------------------------------------- |
| The user never pressed the toggle | The operating system's light or dark setting, live      |
| The user pressed the toggle       | Their choice, saved in `localStorage` under `hop-theme` |
| Another Hop tab changes the theme | This tab follows (the browser's `storage` event)        |

A small inline script in `index.html` picks the theme before the first paint, so the page never flashes the wrong colors. The toggle is a real `<button>` with `aria-pressed`, so screen readers announce night mode as on or off.

**Topic colors.** Every topic has a tone (sun, mint, rose, peach, lilac, sky, lime, or coral), set in `src/topicTones.ts`. Chips, Likes cards, the Hop screen's header card, and the Interests tiles all use it, so a topic looks the same everywhere. In light mode a tone is a pastel fill; in dark mode it's a tinted glow with a gradient stripe. Topics added later get a stable tone from their slug.

Fonts load from Google Fonts. Text colors meet WCAG AA contrast in both modes, every control is at least 44 px tall, and the pressed-button animation is skipped when the OS asks for reduced motion.

## The Hop screen

Nothing happens until the user presses **Hop**, which calls `POST /hop`. Every hop is recorded as a view, so pages never load on their own. The **Dislike**, **Hop**, and **Like** buttons sit in a dock that floats at the bottom of the screen, so they're always in the same place, even on a phone.

| API response      | What the screen shows                                                                                                                                                                                                                                                        |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `200` with a page | A card with the site, a **Picked for you** or **Random find** badge (from the response's `strategy`), a yellow **Try it** badge for interactive pages (`kind`), title, summary, and topic chips (colored by the first topic), an "Open in new tab" link, and the page itself |
| `409`             | "Pick your interests first", with a link to `/interests`                                                                                                                                                                                                                     |
| `404`             | "You've seen it all (for now)", with a link to add more interests                                                                                                                                                                                                            |

Before the first hop, the screen shows a welcome message with the user's topics as stickers.

The page is shown according to its `embeddable` value (see the [backend README](../backend/README.md#showing-pages-in-an-iframe)): in an iframe when it's `true`, in an iframe with a hint when it's `null` (not checked), and as a card with an "Open in new tab" button when it's `false`. The "Open in new tab" link is always there, with `rel="noopener noreferrer"` so the other site can't control the Hop tab.

The iframe is locked down:

| Attribute                                                                               | Effect                                                                                              |
| --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"` | The page can run scripts and open links in new tabs, but can't navigate the Hop tab or submit forms |
| `referrerPolicy="no-referrer"`                                                          | The site isn't told the request came from Hop                                                       |
| `key={page.id}`                                                                         | React creates a fresh iframe for every page                                                         |

**Like** (the heart) and **Dislike** call `PUT /pages/{id}/reaction`. They're icon buttons with `aria-label`s. The chosen one gets `aria-pressed="true"`, so screen readers announce it as pressed, and it fills with color. Clicking the other one changes the reaction; the backend keeps the history.

## Likes and Interests

**Likes** shows liked pages as cards, tinted by their first topic. Filter buttons for the topics in your likes narrow the list on the page (no extra API call).

**Interests** groups the topics into "Study and thinking" and "Tech" (any topic not listed in `TOPIC_GROUPS` goes under "More"). Each tile is a `<label>` around a visually hidden checkbox, so it works with the keyboard and screen readers while looking like a colored tile. A bar at the bottom counts the picks and unlocks **Save** at 3.

Log in, Sign up, and Confirm email share `AuthShell`: a short pitch on one side and the form card on the other.

## Review (admins only)

Users whose email is in the backend's `ADMIN_EMAILS` see a **Review** link (`user.is_admin` from `GET /auth/me`). Hiding the link isn't security: every `/admin/...` call is checked again by the server, which answers `403` to anyone else.

- **The list** shows the pages the curator handed to a person ("Waiting for you"), or everything under review, each marked Interactive or Article. The search box finds any page by URL or title, including live ones.
- **The detail panel** shows the page's summary and status, the curator's review (what it proposed, which guardrail blocked it, its reason, quality, and provider), every tool call it made with the result, and the stored text.
- **Actions:**
  - **Approve:** the topic boxes start with the curator's choice; pick 1–3.
  - **Reject** and **Remove from Hop:** each asks for a reason in `ActionDialog`, a native `<dialog>` that traps focus and closes with Escape.
  - **Purge:** red, and it stays disabled until you type the page's exact URL. The server checks the typed URL too.
- **History** lists every human action on the page: who, when, and why.

Admins also get a small **Remove from Hop** button on the Hop screen, which removes the current page and hops on.

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
├── admin.ts                  # Review screen calls (admins only)
├── types.ts                  # Shapes of API responses
├── index.css                 # Styles and the light and dark theme variables
├── theme.ts                  # Night mode: pick, save, and apply the theme
├── topicTones.ts             # A color for each topic, and the Interests groups
├── auth/
│   ├── AuthContext.ts        # Login state and the useAuth() hook
│   ├── AuthProvider.tsx      # Loads and updates the login state
│   └── RequireAuth.tsx       # Redirects logged-out visitors to /login
├── components/
│   ├── Layout.tsx            # Header, navigation, and footer
│   ├── ThemeToggle.tsx       # The night mode button
│   ├── AuthShell.tsx         # Shared frame for the login and sign-up pages
│   ├── ActionDialog.tsx      # Asks for a reason (and a typed confirmation) before an admin action
│   ├── Icons.tsx             # Inline SVG icons
│   ├── HealthStatus.tsx      # Shows API, Postgres, and Redis status
│   └── TopicChips.tsx        # A page's topics as colored labels
└── pages/
    ├── HopPage.tsx           # The page, the welcome screen, and the dock
    ├── InterestsPage.tsx
    ├── LikesPage.tsx
    ├── LoginPage.tsx
    ├── ReviewPage.tsx        # The review queue and admin actions
    ├── SignupPage.tsx
    └── VerifyEmailPage.tsx
```
