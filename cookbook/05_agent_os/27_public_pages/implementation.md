# Public Control Plane integration

- [x] Optional credential verification on selected anonymous routes with JWT authorization enabled.
- [x] Verified JWT REST access preserves native endpoint permissions and response schemas.
- [x] Public MCP limits and tool selection remain independent of JWT REST access.
- [x] Discovery and the existing authenticated workflow WebSocket protocol are reachable in mixed mode.
- [x] Composed HTTP tests cover public access, scoped JWTs, invalid credentials, mounts and CORS.
- [x] Public workflow WebSocket admission, authentication deadlines and attempt limits.
- [x] Composed public authorization suite runs in PR CI.
- [x] Mounted runtime scope checks cover JWTs and service accounts outside mixed mode.
- [x] Anonymous discovery counts only public components while retaining the discovery schema.
- [ ] Live hosted Control Plane connection after framework release and deployment configuration.
