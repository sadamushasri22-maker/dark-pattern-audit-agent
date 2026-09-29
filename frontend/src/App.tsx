import { useState, useEffect } from "react";
import "./style.css";

// ---------------------------------------------------------------------------
// Configuration: Backend Base URL
// ---------------------------------------------------------------------------
export const BACKEND_BASE_URL = "http://localhost:8000";

// ---------------------------------------------------------------------------
// Type Definitions
// ---------------------------------------------------------------------------
export interface Finding {
  id?: string | number;
  type: string;
  evidence: string;
  explanation: string;
  status: "new" | "regression" | "still present" | string;
  decision?: "confirmed" | "false_alarm" | "accepted" | null;
  previousDecision?: "confirmed" | "false_alarm" | "accepted" | null;
  isEditing?: boolean;
  reviewing?: boolean;
  savedToMemory?: boolean | null;
}

export interface VersionHistoryStat {
  version: string;
  counts: {
    new: number;
    "still present"?: number;
    regression: number;
  };
  total: number;
  last_audited?: string;
}

export default function App() {
  const [selectedVersion, setSelectedVersion] = useState<string>("store_v1");
  const [loading, setLoading] = useState<boolean>(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [warningMessage, setWarningMessage] = useState<string | null>(null);

  const [hasAudited, setHasAudited] = useState<boolean>(false);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [fixedIssues, setFixedIssues] = useState<string[]>([]);
  const [prevVersion, setPrevVersion] = useState<string | null>(null);
  const [recalledMemories, setRecalledMemories] = useState<string[]>([]);
  const [showAllMemories, setShowAllMemories] = useState<boolean>(false);
  const [historyStats, setHistoryStats] = useState<VersionHistoryStat[]>([]);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  // -------------------------------------------------------------------------
  // Fetch History from Backend
  // -------------------------------------------------------------------------
  const fetchHistory = async () => {
    try {
      const res = await fetch(`${BACKEND_BASE_URL}/history`);
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setBackendOnline(true);
      setErrorMessage(null);

      if (data.by_version) {
        const formatted: VersionHistoryStat[] = Object.entries(data.by_version).map(
          ([version, val]: [string, any]) => ({
            version,
            counts: {
              new: val.counts?.new || 0,
              "still present": val.counts?.["still present"] || val.counts?.still_present || 0,
              regression: val.counts?.regression || 0
            },
            total: val.total || (val.counts?.new || 0) + (val.counts?.["still present"] || 0) + (val.counts?.regression || 0),
            last_audited: val.last_audited
          })
        );
        setHistoryStats(formatted);
      }
    } catch (err) {
      console.warn("Could not reach backend /history:", err);
      setBackendOnline(false);
      setHistoryStats([]);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  // -------------------------------------------------------------------------
  // Run Audit
  // -------------------------------------------------------------------------
  const handleRunAudit = async () => {
    setLoading(true);
    setErrorMessage(null);
    setWarningMessage(null);
    setShowAllMemories(false);

    try {
      const res = await fetch(`${BACKEND_BASE_URL}/audit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          version: selectedVersion
        })
      });

      if (!res.ok) {
        throw new Error(`Audit endpoint returned error code ${res.status}`);
      }

      const data = await res.json();
      setBackendOnline(true);
      setHasAudited(true);

      const enrichedFindings: Finding[] = (data.findings || []).map((f: any, idx: number) => ({
        ...f,
        id: idx + 1,
        decision: null,
        reviewing: false,
        savedToMemory: null
      }));

      setFindings(enrichedFindings);
      setFixedIssues(data.fixed_issues || []);
      setPrevVersion(data.prev_version || null);
      setRecalledMemories(data.recalled_memories || []);

      if (data.warning) {
        setWarningMessage(data.warning);
      }

      fetchHistory();
    } catch (err: any) {
      console.error("Audit request failed:", err);
      setBackendOnline(false);
      setErrorMessage(
        `Unable to reach backend service at ${BACKEND_BASE_URL}. Ensure the backend service is running.`
      );
      setFindings([]);
      setFixedIssues([]);
      setPrevVersion(null);
      setRecalledMemories([]);
    } finally {
      setLoading(false);
    }
  };

  // -------------------------------------------------------------------------
  // Handle Review Decision & Corrections
  // -------------------------------------------------------------------------
  const handleReviewDecision = async (
    index: number,
    decision: "confirmed" | "false_alarm" | "accepted"
  ) => {
    const finding = findings[index];
    if (!finding) return;

    // Set reviewing state
    setFindings(prev =>
      prev.map((f, i) => (i === index ? { ...f, reviewing: true } : f))
    );

    let saveSuccess = false;
    const prevDecision = finding.previousDecision || (finding.decision && finding.decision !== decision ? finding.decision : null);

    try {
      const res = await fetch(`${BACKEND_BASE_URL}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          version: selectedVersion,
          finding_type: finding.type,
          evidence: finding.evidence,
          decision: decision,
          previous_decision: prevDecision || undefined,
          note: prevDecision
            ? `Reviewer changed decision on ${finding.type} in ${selectedVersion} from ${prevDecision} to ${decision}`
            : `Reviewer designated ${decision}`
        })
      });

      if (res.ok) {
        const data = await res.json();
        saveSuccess = data.saved_to_memory !== false;
        setBackendOnline(true);
      } else {
        saveSuccess = false;
      }
    } catch (err) {
      console.warn("POST /review call failed:", err);
      saveSuccess = false;
    } finally {
      setFindings(prev =>
        prev.map((f, i) =>
          i === index
            ? {
                ...f,
                decision: decision,
                previousDecision: decision,
                isEditing: false,
                reviewing: false,
                savedToMemory: saveSuccess
              }
            : f
        )
      );
    }
  };

  const handleEditDecision = (index: number) => {
    setFindings(prev =>
      prev.map((f, i) =>
        i === index
          ? {
              ...f,
              isEditing: true,
              previousDecision: f.decision || f.previousDecision
            }
          : f
      )
    );
  };

  const copyEvidence = (text: string, idx: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 1800);
  };

  const regressionCount = findings.filter(f => (f.status || "").toLowerCase() === "regression").length;
  const stillPresentCount = findings.filter(f => (f.status || "").toLowerCase().includes("still")).length;

  return (
    <div className="app-layout">
      {/* Background glow effects */}
      <div className="bg-glow" />
      <div className="grid-overlay" />

      <div className="app-container">
        {/* Top Navigation & Status */}
        <header className="app-header">
          <div className="header-left">
            <div className="brand-logo" title="EthixLens Logo">
              <img src="/logo.png" alt="EthixLens Logo" width="46" height="46" />
            </div>
            <div className="brand-identity">
              <div className="title-row">
                <h1 className="brand-primary-name">EthixLens</h1>
                <span className="version-tag">SYSTEM v0.4.1</span>
              </div>
              <div className="brand-sub-title">DARK PATTERN AUDIT AGENT</div>
              <p className="subtitle">
                Autonomous browser checker, compliance verification, and regression tracking
              </p>
            </div>
          </div>

          <div className="header-right">
            <div className={`connection-badge ${backendOnline === false ? "is-offline" : "is-online"}`}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
                <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
                <line x1="6" y1="6" x2="6.01" y2="6" />
                <line x1="6" y1="18" x2="6.01" y2="18" />
              </svg>
              <span className="connection-text">
                {backendOnline === false ? "DISCONNECTED" : "BACKEND CONNECTED"}
              </span>
            </div>
          </div>
        </header>

        {/* System Alerts */}
        {warningMessage && (
          <div className="alert-card warning">
            <div className="alert-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <div className="alert-body">
              <span className="alert-label">SYSTEM NOTICE</span>
              <p>{warningMessage}</p>
            </div>
          </div>
        )}

        {errorMessage && (
          <div className="alert-card error">
            <div className="alert-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <div className="alert-body">
              <span className="alert-label">CONNECTION FAILURE</span>
              <p>{errorMessage}</p>
            </div>
          </div>
        )}

        {/* Telemetry Metrics Bar */}
        <section className="metrics-hud">
          <div className="metric-box">
            <span className="metric-title">TOTAL PATTERNS</span>
            <span className="metric-value">{hasAudited ? findings.length : "—"}</span>
            <span className="metric-desc">detected in {selectedVersion}</span>
          </div>
          <div className="metric-box highlight-danger">
            <span className="metric-title">REGRESSIONS</span>
            <span className="metric-value text-red">{hasAudited ? regressionCount : "—"}</span>
            <span className="metric-desc">previously fixed reappeared</span>
          </div>
          <div className="metric-box highlight-neutral">
            <span className="metric-title">STILL PRESENT</span>
            <span className="metric-value text-slate">{hasAudited ? stillPresentCount : "—"}</span>
            <span className="metric-desc">carried over unaddressed</span>
          </div>
          <div className="metric-box highlight-success">
            <span className="metric-title">RESOLVED ISSUES</span>
            <span className="metric-value text-green">{hasAudited ? fixedIssues.length : "—"}</span>
            <span className="metric-desc">cleared since {prevVersion || "baseline"}</span>
          </div>
          <div className="metric-box highlight-purple">
            <span className="metric-title">MEMORY CONTEXT</span>
            <span className="metric-value text-purple">{recalledMemories.length}</span>
            <span className="metric-desc">authoritative records active</span>
          </div>
        </section>

        {/* Audit Controls Bar */}
        <section className="control-bar">
          <div className="control-left">
            <span className="control-caption">TARGET VERSION:</span>
            <div className="select-wrapper">
              <select
                id="versionSelect"
                className="version-selector"
                value={selectedVersion}
                onChange={(e) => setSelectedVersion(e.target.value)}
                disabled={loading}
              >
                <option value="store_v1">UrbanKart store_v1.html</option>
                <option value="store_v2">UrbanKart store_v2.html</option>
                <option value="store_v3">UrbanKart store_v3.html</option>
              </select>
              <svg className="select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </div>
          </div>

          <button
            className={`btn-action-primary ${loading ? "is-loading" : ""}`}
            onClick={handleRunAudit}
            disabled={loading}
            id="runAuditBtn"
          >
            {loading ? (
              <>
                <div className="radar-spinner" />
                <span>OBSERVING & AUDITING...</span>
              </>
            ) : (
              <>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                </svg>
                <span>RUN AUDIT</span>
              </>
            )}
          </button>
        </section>

        {/* Main Content Layout */}
        <div className="core-layout">
          {/* Neural Compliance Memory Panel */}
          <section className="card-panel memory-console">
            <div className="panel-header">
              <div className="panel-title-group">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="4" y="4" width="16" height="16" rx="2" />
                  <rect x="9" y="9" width="6" height="6" />
                  <line x1="9" y1="1" x2="9" y2="4" />
                  <line x1="15" y1="1" x2="15" y2="4" />
                  <line x1="9" y1="20" x2="9" y2="23" />
                  <line x1="15" y1="20" x2="15" y2="23" />
                  <line x1="20" y1="9" x2="23" y2="9" />
                  <line x1="20" y1="14" x2="23" y2="14" />
                  <line x1="1" y1="9" x2="4" y2="9" />
                  <line x1="1" y1="14" x2="4" y2="14" />
                </svg>
                <h2>Hindsight Compliance Memory</h2>
              </div>
              <span className="badge-counter">{recalledMemories.length} RECORDS</span>
            </div>

            {recalledMemories.length === 0 ? (
              <div className="empty-console">
                <p className="empty-lead">No memories active in memory bank.</p>
                <p className="empty-sub">
                  Reviewer decisions and version comparisons are retained in Hindsight to prevent repeat violations and track regressions.
                </p>
              </div>
            ) : (() => {
              const scoreMemory = (text: string): number => {
                const lower = text.toLowerCase();
                let score = 0;
                if (lower.includes("false_alarm") || lower.includes("accepted") || lower.includes("confirmed") || lower.includes("reviewer")) score += 10;
                if (lower.includes("fixed") || lower.includes("regression") || lower.includes("earlier version") || lower.includes("later version")) score += 8;
                return score;
              };

              const sorted = [...recalledMemories].sort((a, b) => scoreMemory(b) - scoreMemory(a));
              const displayed = showAllMemories ? sorted : sorted.slice(0, 5);

              return (
                <>
                  <div className="memory-stream">
                    {displayed.map((mem, idx) => (
                      <div key={idx} className="memory-record">
                        <div className="memory-meta">
                          <span className="record-tag">ENTRY #{String(idx + 1).padStart(2, "0")}</span>
                        </div>
                        <p className="record-body">{mem}</p>
                      </div>
                    ))}
                  </div>

                  {sorted.length > 5 && (
                    <button
                      className="btn-toggle-stream"
                      onClick={() => setShowAllMemories(!showAllMemories)}
                      type="button"
                      id="toggleAllMemoriesBtn"
                    >
                      {showAllMemories ? "COLLAPSE TO TOP 5" : `EXPAND ALL ${sorted.length} RECORDS`}
                    </button>
                  )}
                </>
              );
            })()}
          </section>

          {/* Audit Findings List */}
          <section className="card-panel findings-console">
            <div className="panel-header">
              <div className="panel-title-group">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                  <polyline points="10 9 9 9 8 9" />
                </svg>
                <h2>Audit Findings {hasAudited && `(${findings.length})`}</h2>
              </div>
              {hasAudited && (
                <div className="scope-badge">
                  <span>SCOPE:</span> <code>{selectedVersion}</code>
                </div>
              )}
            </div>

            {/* Fixed Issues Card */}
            {prevVersion && (
              <div className="fixed-diff-card">
                <div className="diff-header">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  <span>Resolved Issues Since {prevVersion}:</span>
                </div>
                {fixedIssues.length > 0 ? (
                  <div className="diff-tags-row">
                    {fixedIssues.map((issue, i) => (
                      <span key={i} className="diff-pill-cleared">
                        {issue}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="diff-empty-note">
                    None (no issue types from {prevVersion} were resolved in this version).
                  </p>
                )}
              </div>
            )}

            {!hasAudited && !loading ? (
              <div className="awaiting-state">
                <div className="crosshair-icon">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="22" y1="12" x2="18" y2="12" />
                    <line x1="6" y1="12" x2="2" y2="12" />
                    <line x1="12" y1="6" x2="12" y2="2" />
                    <line x1="12" y1="22" x2="12" y2="18" />
                  </svg>
                </div>
                <h3>READY FOR AUDIT</h3>
                <p>Select target version and initialize the audit engine to inspect dark pattern compliance.</p>
              </div>
            ) : findings.length === 0 && !loading ? (
              <div className="clean-state">
                <div className="clean-shield">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                    <polyline points="9 12 11 14 15 10" />
                  </svg>
                </div>
                <h3>NO DARK PATTERNS DETECTED</h3>
                <p>All scanned components in {selectedVersion} comply with standard patterns.</p>
              </div>
            ) : (
              <div className="findings-stream">
                {findings.map((item, idx) => {
                  const statusLower = (item.status || "new").toLowerCase();
                  return (
                    <article key={idx} className={`finding-entry status-${statusLower.replace(" ", "-")}`}>
                      <div className="finding-topbar">
                        <div className="type-group">
                          <span className="finding-index">#{String(idx + 1).padStart(2, "0")}</span>
                          <h3 className="finding-name">{item.type}</h3>
                        </div>

                        <div className="status-badge-wrap">
                          {statusLower === "regression" && (
                            <span className="badge-pill regression">
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                                <line x1="12" y1="9" x2="12" y2="13" />
                                <line x1="12" y1="17" x2="12.01" y2="17" />
                              </svg>
                              REGRESSION
                            </span>
                          )}
                          {(statusLower === "still present" || statusLower === "still_present") && (
                            <span className="badge-pill still-present">
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                <polyline points="1 4 1 10 7 10" />
                                <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
                              </svg>
                              STILL PRESENT
                            </span>
                          )}
                          {statusLower === "new" && (
                            <span className="badge-pill new">
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                <line x1="12" y1="5" x2="12" y2="19" />
                                <line x1="5" y1="12" x2="19" y2="12" />
                              </svg>
                              NEW
                            </span>
                          )}
                        </div>
                      </div>

                      <p className="finding-desc">{item.explanation}</p>

                      {/* Evidence Terminal Box */}
                      <div className="terminal-box">
                        <div className="terminal-header">
                          <div className="terminal-prompt-badge">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                              <polyline points="4 17 10 12 4 7" />
                              <line x1="12" y1="19" x2="20" y2="19" />
                            </svg>
                            <span>EVIDENCE</span>
                          </div>
                          <span className="terminal-caption">INSPECTED DOM & RUNTIME PROOF</span>
                          <button
                            type="button"
                            className="btn-copy-code"
                            onClick={() => copyEvidence(item.evidence, idx)}
                            title="Copy evidence snippet"
                          >
                            {copiedIdx === idx ? "COPIED" : "COPY"}
                          </button>
                        </div>
                        <pre className="terminal-code">
                          <code>{item.evidence}</code>
                        </pre>
                      </div>

                      {/* Human Review Decision Row */}
                      <div className="review-dock">
                        <span className="review-label">VERIFICATION DECISION:</span>

                        {item.decision && !item.isEditing ? (
                          <div className="decision-outcome">
                            <span className={`decision-tag ${item.decision}`}>
                              {item.decision === "confirmed" && "CONFIRMED PATTERN"}
                              {item.decision === "false_alarm" && "FALSE ALARM"}
                              {item.decision === "accepted" && "ACCEPTED DESIGN"}
                            </span>
                            {item.savedToMemory === true && (
                              <span className="memory-ack success">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                  <polyline points="20 6 9 17 4 12" />
                                </svg>
                                SAVED TO MEMORY
                              </span>
                            )}
                            {item.savedToMemory === false && (
                              <span className="memory-ack failure">
                                MEMORY SYNC FAILED
                              </span>
                            )}
                            <button
                              type="button"
                              className="btn-edit-verdict"
                              onClick={() => handleEditDecision(idx)}
                              title="Change review decision"
                            >
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                              </svg>
                              Edit
                            </button>
                          </div>
                        ) : (
                          <div className="review-button-row">
                            <button
                              className={`btn-verdict confirm ${item.decision === "confirmed" ? "active-choice" : ""}`}
                              onClick={() => handleReviewDecision(idx, "confirmed")}
                              disabled={item.reviewing}
                            >
                              Confirm Pattern
                            </button>
                            <button
                              className={`btn-verdict false_alarm ${item.decision === "false_alarm" ? "active-choice" : ""}`}
                              onClick={() => handleReviewDecision(idx, "false_alarm")}
                              disabled={item.reviewing}
                            >
                              False Alarm
                            </button>
                            <button
                              className={`btn-verdict accepted ${item.decision === "accepted" ? "active-choice" : ""}`}
                              onClick={() => handleReviewDecision(idx, "accepted")}
                              disabled={item.reviewing}
                            >
                              Accept Design
                            </button>
                            {item.isEditing && (
                              <button
                                type="button"
                                className="btn-cancel-edit"
                                onClick={() =>
                                  setFindings(prev =>
                                    prev.map((f, i) => (i === idx ? { ...f, isEditing: false } : f))
                                  )
                                }
                                title="Cancel edit"
                              >
                                Cancel
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          {/* Version History Table */}
          <section className="card-panel history-console">
            <div className="panel-header">
              <div className="panel-title-group">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="20" x2="18" y2="10" />
                  <line x1="12" y1="20" x2="12" y2="4" />
                  <line x1="6" y1="20" x2="6" y2="14" />
                </svg>
                <h2>Telemetry & Version History</h2>
              </div>
              <span className="badge-counter">{historyStats.length} AUDITS LOGGED</span>
            </div>

            <div className="table-responsive">
              <table className="telemetry-table">
                <thead>
                  <tr>
                    <th>VERSION</th>
                    <th>NEW</th>
                    <th>STILL PRESENT</th>
                    <th>REGRESSIONS</th>
                    <th>TOTAL</th>
                    <th>STATUS DISTRIBUTION</th>
                  </tr>
                </thead>
                <tbody>
                  {historyStats.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="table-empty-row">
                        No telemetry history recorded yet. Complete an audit to record history metrics.
                      </td>
                    </tr>
                  ) : (
                    historyStats.map((stat, idx) => {
                      const newCount = stat.counts.new || 0;
                      const stillCount = stat.counts["still present"] || 0;
                      const regCount = stat.counts.regression || 0;
                      const total = stat.total || newCount + stillCount + regCount;
                      const newPct = total > 0 ? (newCount / total) * 100 : 0;
                      const stillPct = total > 0 ? (stillCount / total) * 100 : 0;
                      const regPct = total > 0 ? (regCount / total) * 100 : 0;

                      return (
                        <tr key={idx}>
                          <td className="cell-version">{stat.version}</td>
                          <td>
                            <span className="pill-metric new">{newCount}</span>
                          </td>
                          <td>
                            <span className="pill-metric still">{stillCount}</span>
                          </td>
                          <td>
                            <span className={`pill-metric ${regCount > 0 ? "regression" : "still"}`}>
                              {regCount}
                            </span>
                          </td>
                          <td className="cell-total">{total}</td>
                          <td>
                            <div className="spectrum-bar" title={`New: ${newCount}, Still Present: ${stillCount}, Regressions: ${regCount}`}>
                              <div className="segment new" style={{ width: `${newPct}%` }} />
                              <div className="segment still" style={{ width: `${stillPct}%` }} />
                              <div className="segment regression" style={{ width: `${regPct}%` }} />
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
