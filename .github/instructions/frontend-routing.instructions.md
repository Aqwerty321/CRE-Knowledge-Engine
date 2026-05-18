---
name: Frontend Routing
description: Guidance for combining React Bits and Frontend Design Vault without overlap.
applyTo: "**/*.{tsx,jsx,css,scss,md}"
---
# Frontend MCP pairing guidance

- Keep `reactBitsLocal` and `frontendDesignVault` separate in purpose.
- Use `frontendDesignVault` for direction: layout, composition, visual language, spacing, interaction style, and motion constraints.
- Use `reactBitsLocal` for concrete implementation candidates, normalized component docs, and code copy.
- When both are needed, use them sequentially: direction first, implementation second.
- Do not ask both tools the same vague prompt at the same abstraction level.
- Preserve the project’s design system. React Bits provides primitives, not permission to replace the visual language wholesale.

For broad frontend build-outs:

1. Query `frontendDesignVault` to produce a short pattern brief.
2. Turn that into 1-3 targeted `reactBitsLocal_search_components` queries.
3. Use `reactBitsLocal_get_component` only for shortlisted hits.
4. Copy a variant only after the target component is chosen.
