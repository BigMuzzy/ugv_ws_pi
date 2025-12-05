# Fleet Console - Minimal Angular Frontend

Minimal Angular implementation for testing fleet management functionality.

## Purpose

This is a **minimal, testing-only frontend**. A proper production UI will be built as a separate effort in Phase 4.

Current features:
- Basic dashboard layout
- API health check display
- Robot list placeholder
- Minimal styling for readability

## Development

### Install Dependencies

```bash
npm install
```

### Run Development Server

```bash
npm start
```

Navigate to `http://localhost:3000/`. The application will automatically reload if you change any source files.

API requests will be proxied to Workers dev server at `http://localhost:8787`.

### Build

```bash
npm run build
```

Build artifacts will be stored in `dist/fleet-console/`.

## Deployment

This frontend is configured to deploy to Cloudflare Pages via GitHub Actions.

Push to main branch will trigger automatic deployment.

## Project Structure

```
src/
├── app/
│   └── app.component.ts    # Main component (standalone)
├── index.html              # Entry HTML
├── main.ts                 # Bootstrap
└── styles.css              # Global styles
```

## What's Implemented

- ✅ Minimal dashboard UI
- ✅ Workers API health check
- ✅ Robot list placeholder
- ✅ Standalone Angular components (no modules)
- ✅ Simple, clean styling
- ✅ Proxy configuration for local dev

## What's NOT Implemented (for Phase 4)

- WebRTC video display
- Teleop controls
- Navigation interface
- Advanced UI components
- Proper state management
- Authentication
- Responsive design optimizations

## Notes

This is intentionally minimal to keep the focus on backend functionality during Phases 1-3.
The full-featured UI will be developed separately when the backend is stable.
