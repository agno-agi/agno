# Public Control Plane integration

- [x] Optional credential verification on selected anonymous routes with JWT authorization enabled.
- [x] Verified JWT REST access preserves native endpoint permissions and response schemas.
- [x] Public MCP limits and tool selection remain independent of JWT REST access.
- [x] Discovery and the existing authenticated workflow WebSocket protocol are reachable in mixed mode.
- [x] Composed HTTP tests cover public access, scoped JWTs, invalid credentials, mounts and CORS.
- [x] Public workflow WebSocket admission, authentication deadlines and attempt limits.
- [x] Composed public authorization suite runs in PR CI.
- [ ] Live hosted Control Plane connection after framework release and deployment configuration.
