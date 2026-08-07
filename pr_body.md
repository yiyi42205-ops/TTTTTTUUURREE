## Overview
This PR introduces a complete **Dual-mode PWA Architecture**, bringing native mobile app behaviors to TrueRating while maintaining the standard desktop web experience. 

## Key Technical Changes
- **Adaptive App Shell**: Engineered a hybrid routing strategy that renders the Bottom Navigation Bar exclusively under PWA `standalone` display modes, guaranteeing zero layout pollution on standard mobile web browsers.
- **Fluid Horizontal Carousel**: Re-architected the `Results.tsx` Viewport. Migrated from discrete React renders to a unified CSS Flexbox slider (`w-[300%]`, `translateX`). This delivers native-tier 60FPS fluid swipe transitions with isolated, uncoupled `overflow-y-auto` scrolling vectors per panel (Dashboard/Anomalies/Reviews).
- **Clipboard Inference Pipeline**: Implemented an automated background scanner (`navigator.clipboard.readText()`) tied to the Analyzer viewport mounting lifecycle, which securely captures valid Google Maps URLs to accelerate the "audit-to-funnel" user flow on mobile.
- **UI Decoupling & Debloat**: Aggressively pruned non-critical explanatory UI elements (Status Banners, AI Pipeline configuration cards) specifically within the PWA viewport to maximize actionable mobile screen real estate.
- **Routing Integrity Fix**: Reparented the `/analyzer` router node directly into the `Layout` hierarchy to orchestrate unified context sharing and nav-bar propagation across the core audit funnel.
- **Vite Setup Clean up**: Purged stale `allowedHosts` proxy configuration artifacts from `vite.config.ts`.
