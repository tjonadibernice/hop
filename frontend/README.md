# Hop Frontend

React + TypeScript app for Hop, built with Vite. It currently shows the system status from the API's readiness check.

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

## How the frontend reaches the API

In development, Vite **proxies** requests that start with `/api` to the backend, so the browser only talks to one origin and CORS isn't needed.

| The browser requests | Vite forwards it to                  |
| -------------------- | ------------------------------------ |
| `/api/health/ready`  | `http://localhost:8000/health/ready` |

The proxy is configured in `vite.config.ts`. Frontend code should always call `/api/...`, never `http://localhost:8000` directly.

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
├── App.tsx                   # Root component
└── components/
    └── HealthStatus.tsx      # Shows API, Postgres, and Redis status
```
