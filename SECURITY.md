# Security Policy — AGENTGATE

AGENTGATE is an authorization gateway designed to govern AI agent tool executions deterministically.
Because this project serves as a security-critical boundary, we hold security vulnerabilities to the highest standard.

---

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

---

## Core Security Invariants

All versions of AGENTGATE strictly enforce three mathematical boundaries:
1. **Document-Blind Authorization**: The policy gateway never inspects, parses, or evaluates document body text for authorization decisions. Decisions depend strictly on session principal badges, clearance tiers, and registered metadata.
2. **Dynamic Bell-LaPadula Provenance Supremum**: Artifact sensitivities irreversibly inherit the least upper bound ($\bigsqcup$) classification of all consulted documents and session read history.
3. **Out-of-Process Policy & Document Drift Defense**: Workflow resumption checkpoints persist proposed requests rather than authorizations, forcing live re-evaluation against disk policy and document hashes upon resumption.

---

## Reporting a Vulnerability

If you discover a security vulnerability or boundary bypass in AGENTGATE:

1. **Do not disclose publicly**: Do not create public GitHub issues or forum posts describing exploitable security flaws.
2. **Submit via Coordinated Disclosure**: Contact the project security maintainers or file a private security advisory through GitHub.
3. **Include Reproduction Steps**: Provide a minimal reproduction script or test case detailing:
   - The proposed `ActionRequest`
   - The active `policies.json` and `principals.json`
   - The unexpected authorization outcome (`ALLOWED` vs `BLOCKED`)
4. **Response Timeline**:
   - Initial acknowledgement: within 24 hours.
   - Root-cause assessment and mitigation plan: within 72 hours.
   - Patch release: prioritized based on CVSS / severity rating.

