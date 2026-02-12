# TEST_LOG

## cloud — v2.5 Review

Tested: 2026-02-11 | Branch: cookbooks/v2.5-testing

---

### azure_blob.py

**Status:** SKIP

**Description:** Azure Blob Storage integration using AzureBlobConfig with .file() and .folder() factory methods.

**Result:** Skipped — requires Azure Blob Storage credentials and azure-storage-blob package.

---

### cloud_agentos.py

**Status:** SKIP

**Description:** Multi-source cloud content (SharePoint, GitHub, Azure) with AgentOS FastAPI integration.

**Result:** Skipped — requires multiple cloud service credentials plus AgentOS runtime.

---

### github.py

**Status:** SKIP

**Description:** GitHub repo content source using GitHubConfig with .file() and .folder() factory methods.

**Result:** Skipped — requires GitHub token with repo access and specific repository configuration.

---

### sharepoint.py

**Status:** SKIP

**Description:** SharePoint Document Library integration using SharePointConfig.

**Result:** Skipped — requires SharePoint credentials (client_id, client_secret, tenant_id).

---

## Summary

| Status | Count | Files |
|--------|-------|-------|
| SKIP   | 4     | azure_blob, cloud_agentos, github, sharepoint |

All files skipped due to cloud service credential requirements.
