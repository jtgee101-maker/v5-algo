# Product Requirements Document (PRD)
## ICT Trade Mission Control — Public.com Agentic Edition

Version: 2.0  
Date: March 24, 2026

This document defines the WHAT to build: design system, data contracts, pages, and states.

- Backend base URL: `https://v5-algo.onrender.com/api`
- Symbols: BTCUSD, NAS100, US30, EURUSD, XAUUSD, USOIL
- UX target: clean Public.com-style agentic interface (not Bloomberg-dense)
- Required pages (13): Dashboard, DRM, Charts, Scanner, Signals, Positions, Journal, News, Research, Reasoning, Performance, Risk, Settings
- Key state patterns: loading skeletons, API error cards with retry, empty states, connection indicator, scanning indicator

Core API shapes and page-by-page behavior are captured in the project PDP and implementation files.
