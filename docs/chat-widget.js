/**
 * CMS Claims Report Pal — Standalone Chat Widget
 *
 * Self-contained chat widget that can be included on any page.
 * Persists conversation across page navigations via sessionStorage.
 * Features: copy SQL, double-click SQL → SQL Explorer, section navigation.
 *
 * Usage: <script src="chat-widget.js"></script>
 */
(function () {
  'use strict';

  var LAMBDA_URL = 'https://zn5ugmlfnpuwwpabueyzgzaar40ovvmo.lambda-url.us-east-1.on.aws';
  var SESSION_LAMBDA_URL = 'https://wexuzysr2w6zfqp3e4xdxu7zva0ulpqy.lambda-url.us-east-1.on.aws';
  var SESSION_KEY = 'cms_chat_session';
  var HISTORY_KEY = 'cms_chat_history';
  var API_URL_KEY = 'cms_chat_api_url';

  // ── Page navigation map (like healthresourcepal's [[page_id]] tokens) ──
  var PAGE_MAP = {
    // Documentation pages
    sql:            { label: 'SQL Explorer',      url: 'sql_explorer.html' },
    schema:         { label: 'Schema Explorer',   url: 'schema_explorer.html' },
    parquet:        { label: 'Parquet Viewer',     url: 'parquet_viewer.html' },
    report:         { label: 'Comparison Report',  url: '../reports/comparison_report.html' },
    architecture:   { label: 'Architecture',       url: 'architecture.html' },
    data_dictionary:{ label: 'Data Dictionary',    url: 'data_dictionary.html' },
    solution:       { label: 'Solution Design',    url: 'solution.html' },
    pipeline:       { label: 'Pipeline Reference', url: 'pipeline.html' },
    reviewer:       { label: 'Reviewer Guide',     url: 'reviewer_readme.html' },
    requirements:   { label: 'Requirements',       url: 'requirements_traceability.html' },
    feedback:       { label: 'Feedback',            url: 'feedback.html' },
    index:          { label: 'Documentation Hub',   url: 'index.html' },

    // Report top-level sections (scroll-to on report page, or navigate+hash from other pages)
    discrepancies:          { label: 'Discrepancies',         section: 'discrepancies' },
    financial:              { label: 'Financial Analysis',    section: 'financial' },
    validation:             { label: 'Validation',            section: 'validation' },
    trends:                 { label: 'YoY Trends',            section: 'trends' },
    comparison:             { label: 'System Comparison',     section: 'comparison' },
    profiles:               { label: 'Data Profiles',         section: 'profiles' },
    summary:                { label: 'Executive Summary',     section: 'summary' },
    data_context:           { label: 'Data Context',          section: 'data-context' },

    // Report subsections
    key_findings:           { label: 'Key Findings',                section: 'key-findings' },
    accuracy_assessment:    { label: 'Accuracy Assessment',         section: 'accuracy-assessment' },
    record_matching:        { label: 'Record Matching',             section: 'record-matching' },
    issues_attention:       { label: 'Issues Requiring Attention',  section: 'issues-requiring-attention' },
    beneficiaries_affected: { label: 'Beneficiaries Affected',      section: 'beneficiaries-affected' },
    claims_payment:         { label: 'Claims Payment Discrepancy',  section: 'claims-payment-discrepancy' },
    payment_changes:        { label: 'Claims with Payment Changes', section: 'claims-with-payment-changes' },
    phantom_records:        { label: 'Phantom Records',             section: 'kpi-phantom' },
    test_records:           { label: 'Injected Test Records',       section: 'injected-test-records' },

    // KPI cards
    bene_mismatch:          { label: 'Beneficiary Mismatches',      section: 'kpi-bene-mismatch' },
    claims_pmt_mismatch:    { label: 'Payment Mismatches',          section: 'kpi-claims-pmt' },
    financial_divergence:   { label: 'Financial Divergence',        section: 'kpi-fin-diverge' },

    // Charts (container wrappers for better scroll targeting)
    field_mismatches_chart: { label: 'Field Mismatches Chart',      section: 'container-field-mismatches' },
    discrepancy_trend_chart:{ label: 'Discrepancy Trend Chart',     section: 'container-discrepancy-trend' },
    fin_divergence_chart:   { label: 'Financial Divergence Chart',  section: 'container-fin-divergence' },
    reimb_comparison_chart: { label: 'Reimbursement Comparison',    section: 'container-reimb-comparison' },
    discrepancy_charts:     { label: 'Discrepancy Charts',          section: 'discrepancy-charts' },

    // Financial sub-charts
    financial_trends_chart: { label: 'Financial Trends Chart',      section: 'container-financial-trends' },
    payment_distribution:   { label: 'Payment Distribution',        section: 'container-financial-dist' },
    chronic_conditions:     { label: 'Chronic Conditions',          section: 'container-chronic' },

    // YoY sub-charts
    yoy_beneficiaries:      { label: 'Beneficiaries by Year',       section: 'container-yoy-bene' },
    yoy_claims:             { label: 'Claims by Year',              section: 'container-yoy-claims' },

    // Validation
    validation_table:       { label: 'Validation Table',            section: 'validation-table' },
    issues_by_check:        { label: 'Issues by Check',             section: 'issues-by-check' },

    // Comparison detail
    comparison_checks:      { label: 'Comparison Checks',           section: 'comparison-checks-detail' },

    // Headings
    financial_heading:      { label: 'Financial Analysis',          section: 'financial-analysis-heading' },
    validation_heading:     { label: 'Validation Results',          section: 'validation-results-heading' },
    yoy_heading:            { label: 'YoY Trends',                  section: 'yoy-trends-heading' }
  };

  // ── Bold-text auto-linking: map common phrases to [[page_id]] ──
  // When AI uses **bold text** that matches these patterns, auto-link to the section
  var BOLD_LINK_PATTERNS = [
    { pattern: /beneficiary\s+discrepanc/i,   id: 'discrepancies',  reportHash: 'kpi-bene-mismatch' },
    { pattern: /claim\s+count\s+diff/i,       id: 'discrepancies',  reportHash: 'kpi-claims-pmt' },
    { pattern: /financial\s+discrepanc/i,      id: 'financial',      reportHash: 'kpi-fin-diverge' },
    { pattern: /financial\s+analysis/i,         id: 'financial',      reportHash: 'financial' },
    { pattern: /financial\s+reconcil/i,         id: 'financial',      reportHash: 'financial' },
    { pattern: /payment\s+(?:ratio|mismatch)/i,id: 'financial',      reportHash: 'kpi-claims-pmt' },
    { pattern: /payment\s+distribution/i,      id: 'financial',      reportHash: 'container-financial-dist' },
    { pattern: /chronic\s+condition/i,          id: 'financial',      reportHash: 'container-chronic' },
    { pattern: /reimbursement\s+(?:total|comparison)/i, id: 'financial', reportHash: 'container-financial-trends' },
    { pattern: /phantom\s+record/i,            id: 'discrepancies',  reportHash: 'kpi-phantom' },
    { pattern: /data\s+quality/i,              id: 'validation',     reportHash: 'validation' },
    { pattern: /key\s+finding/i,               id: 'discrepancies',  reportHash: 'key-findings' },
    { pattern: /executive\s+summary/i,         id: 'summary',        reportHash: 'summary' },
    { pattern: /system\s+comparison/i,         id: 'comparison',     reportHash: 'comparison' },
    { pattern: /year.over.year|yoy\s+trend/i,  id: 'trends',         reportHash: 'trends' },
    { pattern: /data\s+profile/i,              id: 'profiles',       reportHash: 'profiles' },
    { pattern: /record\s+match/i,              id: 'data_context',   reportHash: 'record-matching' },
    { pattern: /accuracy\s+assess/i,           id: 'discrepancies',  reportHash: 'accuracy-assessment' },
    { pattern: /validation\s+result/i,         id: 'validation',     reportHash: 'validation' },
    { pattern: /injected\s+test/i,             id: 'discrepancies',  reportHash: 'injected-test-records' },
    { pattern: /zz.*beneficiar/i,              id: 'discrepancies',  reportHash: 'injected-test-records' }
  ];

  // Resolve relative path based on current page location
  function resolvePageUrl(pageId) {
    var entry = PAGE_MAP[pageId];
    if (!entry) return null;
    // Section navigation (scroll-to on report page)
    if (entry.section) return { section: entry.section, label: entry.label };
    // Page navigation — adjust relative path based on current location
    var loc = window.location.pathname;
    var url = entry.url;
    if (loc.indexOf('/docs/') !== -1) {
      // Already in docs/, urls are relative
      return { url: url, label: entry.label };
    }
    if (loc.indexOf('/reports/') !== -1) {
      // In reports/, prefix with ../docs/ unless url already has ../
      if (url.indexOf('../') === 0) return { url: url, label: entry.label };
      return { url: '../docs/' + url, label: entry.label };
    }
    // Root level
    if (url.indexOf('../') === 0) return { url: url.replace('../', ''), label: entry.label };
    return { url: 'docs/' + url, label: entry.label };
  }

  function getSqlExplorerUrl() {
    var r = resolvePageUrl('sql');
    return r ? r.url : 'docs/sql_explorer.html';
  }

  // Clipboard helper with fallback for non-HTTPS sites
  function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // Fallback: textarea + execCommand for HTTP sites
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      try {
        document.execCommand('copy') ? resolve() : reject();
      } catch (e) { reject(e); }
      ta.remove();
    });
  }

  // ── Inject CSS ──
  var style = document.createElement('style');
  style.textContent = [
    '.chat-fab{position:fixed;bottom:24px;right:24px;z-index:9999;width:56px;height:56px;border-radius:50%;background:linear-gradient(135deg,#38bdf8,#818cf8);border:none;cursor:pointer;box-shadow:0 4px 20px rgba(56,189,248,0.4);display:flex;align-items:center;justify-content:center;transition:transform .2s,box-shadow .2s}',
    '.chat-fab:hover{transform:scale(1.08);box-shadow:0 6px 28px rgba(56,189,248,0.55)}',
    '.chat-fab svg{width:26px;height:26px;fill:white}',
    '.chat-panel{position:fixed;bottom:24px;right:24px;z-index:10000;width:400px;height:560px;max-height:calc(100vh - 80px);background:#1e293b;border:1px solid #334155;border-radius:16px;display:none;flex-direction:column;overflow:hidden;box-shadow:0 8px 40px rgba(0,0,0,0.5);font-family:"Inter",system-ui,sans-serif}',
    '.chat-panel.open{display:flex}',
    '.chat-header{display:flex;align-items:center;gap:10px;padding:14px 16px;background:linear-gradient(135deg,#1e3a5f,#1e293b);border-bottom:1px solid #334155;flex-shrink:0}',
    '.chat-header-icon{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#38bdf8,#818cf8);display:flex;align-items:center;justify-content:center;flex-shrink:0}',
    '.chat-header-icon svg{width:18px;height:18px;fill:white}',
    '.chat-header-title{flex:1}',
    '.chat-header-title h4{margin:0;font-size:.9rem;color:#e2e8f0;font-weight:600}',
    '.chat-header-title span{font-size:.7rem;color:#94a3b8}',
    '.chat-close,.chat-reset{background:none;border:none;color:#94a3b8;cursor:pointer;padding:4px;border-radius:6px;transition:all .15s;display:flex;align-items:center;justify-content:center}',
    '.chat-close:hover,.chat-reset:hover{color:#e2e8f0;background:rgba(255,255,255,0.08)}',
    '.chat-close svg,.chat-reset svg{width:18px;height:18px}',
    '.chat-stop-voice{background:none;border:none;color:#f87171;cursor:pointer;padding:4px;border-radius:6px;transition:all .15s;display:none;align-items:center;justify-content:center}',
    '.chat-stop-voice:hover{color:#fca5a5;background:rgba(248,113,113,0.12)}',
    '.chat-stop-voice svg{width:18px;height:18px}',
    '.chat-stop-voice.visible{display:flex}',
    '.chat-messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;scrollbar-width:thin;scrollbar-color:#334155 transparent}',
    '.chat-messages::-webkit-scrollbar{width:6px}',
    '.chat-messages::-webkit-scrollbar-thumb{background:#334155;border-radius:3px}',
    '.chat-msg{max-width:85%;padding:10px 14px;border-radius:12px;font-size:.85rem;line-height:1.5;word-wrap:break-word}',
    '.chat-msg.user{align-self:flex-end;background:#38bdf8;color:#0f172a;border-bottom-right-radius:4px}',
    '.chat-msg.assistant{align-self:flex-start;background:#334155;color:#e2e8f0;border-bottom-left-radius:4px}',
    '.chat-msg.assistant p{margin:0 0 8px 0}.chat-msg.assistant p:last-child{margin-bottom:0}',
    '.chat-msg.assistant code{background:rgba(0,0,0,0.3);padding:1px 5px;border-radius:3px;font-size:.8rem}',
    '.chat-msg.assistant pre{background:rgba(0,0,0,0.3);padding:8px 10px 8px 10px;border-radius:6px;overflow-x:auto;margin:6px 0;position:relative;white-space:pre-wrap;word-wrap:break-word;word-break:break-all}',
    '.chat-msg.assistant pre code{background:none;padding:0}',
    '.chat-msg.assistant strong{color:#38bdf8}',
    '.chat-msg.assistant ul,.chat-msg.assistant ol{margin:4px 0 4px 18px}.chat-msg.assistant li{margin-bottom:2px}',
    '.chat-msg.assistant table{border-collapse:collapse;margin:6px 0;font-size:.78rem;width:100%}',
    '.chat-msg.assistant th,.chat-msg.assistant td{border:1px solid #475569;padding:3px 8px;text-align:left}',
    '.chat-msg.assistant th{background:rgba(0,0,0,0.3);color:#38bdf8;font-size:.72rem}',
    '.chat-msg.system{align-self:center;background:transparent;color:#94a3b8;font-size:.78rem;text-align:center;padding:4px 10px}',
    '.chat-quick{display:flex;flex-wrap:wrap;gap:6px;padding:0 16px 12px}',
    '.chat-quick button{background:rgba(56,189,248,0.1);border:1px solid rgba(56,189,248,0.25);color:#38bdf8;padding:6px 12px;border-radius:20px;font-size:.75rem;cursor:pointer;transition:all .15s;white-space:nowrap}',
    '.chat-quick button:hover{background:rgba(56,189,248,0.2);border-color:#38bdf8}',
    '.chat-loading{display:flex;gap:4px;padding:10px 14px;align-self:flex-start}',
    '.chat-loading span{width:8px;height:8px;border-radius:50%;background:#94a3b8;animation:chatBounce 1.2s infinite}',
    '.chat-loading span:nth-child(2){animation-delay:.2s}.chat-loading span:nth-child(3){animation-delay:.4s}',
    '@keyframes chatBounce{0%,60%,100%{transform:translateY(0);opacity:.4}30%{transform:translateY(-6px);opacity:1}}',
    '.chat-input-area{display:flex;align-items:flex-end;gap:8px;padding:12px 16px;border-top:1px solid #334155;background:#1a2332;flex-shrink:0}',
    '.chat-input-area textarea{flex:1;resize:none;border:1px solid #334155;border-radius:10px;background:#0f172a;color:#e2e8f0;padding:10px 12px;font-family:inherit;font-size:.85rem;line-height:1.4;max-height:100px;outline:none;transition:border-color .15s}',
    '.chat-input-area textarea:focus{border-color:#38bdf8}',
    '.chat-input-area textarea::placeholder{color:#64748b}',
    '.chat-send{width:38px;height:38px;border-radius:50%;border:none;background:#38bdf8;color:#0f172a;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s;flex-shrink:0}',
    '.chat-send:hover{background:#60ccf8}.chat-send:disabled{opacity:.4;cursor:not-allowed}',
    '.chat-send svg{width:18px;height:18px}',
    '.chat-config-drawer{flex-shrink:0;position:relative}',
    '.chat-config-handle{height:8px;background:#0f172a;cursor:pointer;display:flex;align-items:center;justify-content:center;border-radius:0 0 16px 16px}',
    '.chat-config-handle::after{content:"";width:28px;height:2px;background:#334155;border-radius:1px;transition:background .2s}',
    '.chat-config-drawer:hover .chat-config-handle::after{background:#64748b}',
    '.chat-config{display:flex;align-items:center;gap:6px;padding:0 16px;background:#0f172a;flex-shrink:0;font-size:.7rem;color:#64748b;max-height:0;overflow:hidden;transition:max-height .25s ease,padding .25s ease}',
    '.chat-config-drawer:hover .chat-config{max-height:60px;padding:5px 16px}',
    '.chat-config input{flex:1;background:#1e293b;border:1px solid #334155;border-radius:4px;color:#94a3b8;padding:3px 6px;font-size:.7rem;font-family:monospace;outline:none}',
    '.chat-config input:focus{border-color:#38bdf8}',
    '.chat-config select{background:#1e293b;border:1px solid #334155;border-radius:4px;color:#94a3b8;padding:3px 4px;font-size:.7rem;outline:none;max-width:180px;cursor:pointer}',
    '.chat-config select:focus{border-color:#38bdf8}',
    '.chat-config select optgroup{color:#64748b;font-style:normal}',
    '.chat-config select option{color:#94a3b8;background:#1e293b}',
    '.chat-config-row{display:flex;align-items:center;gap:6px;width:100%}',
    '.chat-config-rows{display:flex;flex-direction:column;gap:4px;width:100%}',
    '.chat-config .dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}',
    '.chat-config .dot.connected{background:#4ade80}.chat-config .dot.disconnected{background:#f87171}',
    '.chat-suggest{display:none;max-height:0;overflow:hidden;transition:max-height .2s ease;background:#0f172a;border-top:1px solid #334155}',
    '.chat-suggest.open{display:block;max-height:180px;overflow-y:auto}',
    '.chat-suggest-item{padding:7px 16px;font-size:.78rem;color:#94a3b8;cursor:pointer;transition:all .1s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.chat-suggest-item:hover,.chat-suggest-item.active{background:rgba(56,189,248,0.08);color:#e2e8f0}',
    '.chat-suggest-item .suggest-match{color:#38bdf8}',
    '.chat-suggest-hint{padding:3px 16px;font-size:.58rem;color:#475569;display:flex;align-items:center;gap:4px}',
    '.chat-suggest-hint kbd{background:#1e293b;border:1px solid #334155;border-radius:3px;padding:0 4px;font-size:.56rem;font-family:inherit;color:#64748b}',
    '.chat-followup-bar{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}',
    '.chat-followup-btn{display:flex;align-items:center;gap:5px;padding:6px 12px;background:rgba(129,140,248,0.1);border:1px solid rgba(129,140,248,0.25);border-radius:8px;color:#818cf8;font-size:.73rem;cursor:pointer;transition:all .15s;font-family:inherit;flex:1;min-width:0}',
    '.chat-followup-btn:hover{background:rgba(129,140,248,0.2);border-color:#818cf8;color:#a5b4fc}',
    '.chat-followup-btn.sql-btn{background:rgba(56,189,248,0.08);border-color:rgba(56,189,248,0.25);color:#38bdf8}',
    '.chat-followup-btn.sql-btn:hover{background:rgba(56,189,248,0.15);border-color:#38bdf8;color:#7dd3fc}',
    '.chat-followup-btn svg{width:13px;height:13px;flex-shrink:0}',
    '.chat-cached-badge{display:inline-block;font-size:.58rem;color:#64748b;margin-bottom:4px;letter-spacing:.03em}',
    '.chat-cached-badge svg{width:10px;height:10px;vertical-align:middle;margin-right:2px}',
    '.chat-sql-reveal{margin-top:8px;border:1px solid #334155;border-radius:8px;overflow:hidden}',
    '.chat-sql-reveal summary{padding:6px 12px;font-size:.7rem;color:#64748b;cursor:pointer;user-select:none;background:#0f172a}',
    '.chat-sql-reveal summary:hover{color:#94a3b8}',
    '.chat-sql-reveal pre{margin:0;padding:8px 12px;background:rgba(0,0,0,0.3);font-size:.72rem;overflow-x:auto;border-top:1px solid #334155}',
    '.chat-sql-reveal .sql-label{display:block;color:#475569;font-size:.6rem;margin-bottom:2px;font-family:inherit}',
    '.chat-history-overlay{display:none;position:absolute;inset:0;z-index:10;background:#0f172af0;flex-direction:column}',
    '.chat-history-overlay.open{display:flex}',
    '.chat-history-header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #334155;flex-shrink:0}',
    '.chat-history-header h4{margin:0;color:#f1f5f9;font-size:.9rem}',
    '.chat-history-header button{background:none;border:none;color:#94a3b8;cursor:pointer;padding:4px}',
    '.chat-history-header button:hover{color:#f1f5f9}',
    '.chat-history-list{flex:1;overflow-y:auto;padding:8px 12px}',
    '.chat-history-empty{color:#64748b;text-align:center;padding:40px 16px;font-size:.85rem}',
    '.chat-history-card{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:10px 12px;margin-bottom:8px;cursor:pointer;transition:border-color .15s}',
    '.chat-history-card:hover{border-color:#38bdf8}',
    '.chat-history-card .h-time{font-size:.65rem;color:#64748b;margin-bottom:4px}',
    '.chat-history-card .h-question{font-size:.8rem;color:#e2e8f0;font-weight:500;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.chat-history-card .h-sql{font-size:.68rem;color:#38bdf8;font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.chat-history-card .h-nosql{font-size:.68rem;color:#475569;font-style:italic}',
    '.chat-history-clear{display:block;width:100%;padding:8px;margin-top:4px;background:none;border:1px solid #334155;border-radius:6px;color:#f87171;font-size:.75rem;cursor:pointer;text-align:center}',
    '.chat-history-clear:hover{background:#1e293b;border-color:#f87171}',
    '.chat-sql-copy{position:absolute;top:6px;right:6px;background:rgba(56,189,248,0.12);border:1px solid rgba(56,189,248,0.2);color:#94a3b8;border-radius:5px;padding:4px;cursor:pointer;opacity:.5;transition:all .15s;z-index:2;display:flex;align-items:center;justify-content:center;line-height:0}',
    '.chat-msg.assistant pre:hover .chat-sql-copy{opacity:.8}',
    '.chat-sql-copy:hover{opacity:1;color:#38bdf8;background:rgba(56,189,248,0.2);border-color:rgba(56,189,248,0.4)}',
    '.chat-sql-copy svg{width:14px;height:14px}',
    '.chat-sql-copy.copied{background:rgba(74,222,128,0.15);border-color:rgba(74,222,128,0.3);color:#4ade80;opacity:1}',
    '.chat-choice-bar{display:flex;gap:8px;margin-top:8px}',
    '.chat-choice-btn{display:flex;align-items:center;gap:6px;padding:8px 16px;border-radius:10px;border:1px solid rgba(56,189,248,0.3);background:rgba(56,189,248,0.08);color:#38bdf8;font-size:.8rem;cursor:pointer;transition:all .15s;font-family:inherit}',
    '.chat-choice-btn:hover{background:rgba(56,189,248,0.2);border-color:#38bdf8}',
    '.chat-choice-btn svg{width:16px;height:16px;flex-shrink:0}',
    '.chat-mic-btn{width:38px;height:38px;border-radius:50%;border:none;background:transparent;color:#64748b;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s;flex-shrink:0}',
    '.chat-mic-btn:hover{color:#38bdf8;background:rgba(56,189,248,0.1)}',
    '.chat-mic-btn.recording{color:#f87171;background:rgba(248,113,113,0.15);animation:chatPulse 1.5s infinite}',
    '.chat-mic-btn svg{width:18px;height:18px}',
    '@keyframes chatPulse{0%,100%{opacity:1}50%{opacity:.5}}',
    '.chat-voice-badge{display:inline-flex;align-items:center;gap:4px;font-size:.58rem;color:#4ade80;margin-bottom:4px;letter-spacing:.03em}',
    '.chat-voice-badge svg{width:10px;height:10px}',
    '.chat-nav-pill{display:inline-block;margin-top:6px}',
    '.chat-nav-pill button{background:rgba(56,189,248,0.15);color:#38bdf8;border:1px solid rgba(56,189,248,0.3);border-radius:12px;padding:3px 10px;font-size:.7rem;cursor:pointer;font-family:inherit}',
    '.chat-nav-pill button:hover{background:rgba(56,189,248,0.25)}',
    '.chat-nav-tag{display:inline-flex;align-items:center;gap:3px;padding:1px 8px;margin:0 1px;background:rgba(56,189,248,0.12);color:#38bdf8;border:1px solid rgba(56,189,248,0.25);border-radius:6px;font-size:.72rem;cursor:pointer;font-family:inherit;text-decoration:none;transition:all .15s;vertical-align:baseline;line-height:1.6}',
    '.chat-nav-tag:hover{background:rgba(56,189,248,0.25);border-color:#38bdf8;text-decoration:none}',
    '.chat-nav-tag svg{width:10px;height:10px;flex-shrink:0}',
    '@media(max-width:500px){.chat-panel{width:calc(100vw - 16px);right:8px;bottom:8px;height:calc(100vh - 16px);max-height:none;border-radius:12px}}'
  ].join('\n');
  document.head.appendChild(style);

  // ── Build DOM ──
  var fab = document.createElement('button');
  fab.className = 'chat-fab';
  fab.id = 'chatFab';
  fab.title = 'Chat with Report Pal';
  fab.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/><path d="M7 9h2v2H7zm4 0h2v2h-2zm4 0h2v2h-2z"/></svg>';

  var panel = document.createElement('div');
  panel.className = 'chat-panel';
  panel.id = 'chatPanel';
  panel.innerHTML = [
    '<div class="chat-header">',
    '  <div class="chat-header-icon"><svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg></div>',
    '  <div class="chat-header-title"><h4>Report Pal</h4></div>',
    '  <button class="chat-reset" id="chatHistory" title="Query history" style="margin-right:-4px"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></button>',
    '  <button class="chat-reset" id="chatReset" title="Reset conversation"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg></button>',
    '  <button class="chat-stop-voice" id="chatStopVoice" title="Stop AI voice"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg></button>',
    '  <button class="chat-close" id="chatClose" title="Close chat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg></button>',
    '</div>',
    '<div class="chat-messages" id="chatMessages">',
    '',
    '</div>',
    '<div class="chat-quick" id="chatQuick">',
    '  <button data-q="Draft a go/no-go recommendation for the system migration">Go/No-Go memo</button>',
    '  <button data-q="Synthesize the financial, clinical, and demographic findings into a risk scorecard">Risk scorecard</button>',
    '  <button data-q="Based on the Codebook, which discrepancies represent true data corruption?">Evaluate corruption</button>',
    '  <button data-q="How would you prioritize the identified issues for remediation?">Prioritize fixes</button>',
    '  <button data-q="Please summarize all validation checks">Validation summary</button>',
    '  <button data-q="What does BENE_HMO_CVRAGE_TOT_MONS mean?">Codebook lookup</button>',
    '</div>',
    '<div class="chat-suggest" id="chatSuggest"></div>',
    '<div class="chat-input-area">',
    '  <textarea id="chatInput" rows="1" placeholder="Ask about the report findings..." maxlength="2000"></textarea>',
    '  <button class="chat-mic-btn" id="chatMic" title="Voice input"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg></button>',
    '  <button class="chat-send" id="chatSend" title="Send"><svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" fill="currentColor"/></svg></button>',
    '</div>',
    '<div class="chat-config-drawer">',
    '  <div class="chat-config" id="chatConfig">',
    '    <div class="chat-config-rows">',
    '      <div class="chat-config-row">',
    '        <span class="dot disconnected" id="chatDot"></span>',
    '        <span>API:</span>',
    '        <input type="text" id="chatApiUrl" value="' + LAMBDA_URL + '" placeholder="' + LAMBDA_URL + '">',
    '      </div>',
    '      <div class="chat-config-row">',
    '        <span>Model:</span>',
    '        <select id="chatModelSelect">',
    '          <optgroup label="OpenAI">',
    '            <option value="openai/gpt-4o" selected>GPT-4o</option>',
    '            <option value="openai/gpt-4o-mini">GPT-4o Mini</option>',
    '          </optgroup>',
    '          <optgroup label="OpenRouter">',
    '            <option value="openrouter/anthropic/claude-sonnet-4">Claude Sonnet 4</option>',
    '            <option value="openrouter/google/gemini-2.0-flash-001">Gemini 2.0 Flash</option>',
    '            <option value="openrouter/meta-llama/llama-3.3-70b-instruct">Llama 3.3 70B</option>',
    '          </optgroup>',
    '          <optgroup label="AWS Bedrock">',
    '            <option value="bedrock/amazon.nova-pro-v1:0">Nova Pro</option>',
    '            <option value="bedrock/amazon.nova-lite-v1:0">Nova Lite</option>',
    '            <option value="bedrock/amazon.nova-micro-v1:0">Nova Micro</option>',
    '          </optgroup>',
    '        </select>',
    '      </div>',
    '    </div>',
    '  </div>',
    '  <div class="chat-config-handle" title="API settings"></div>',
    '</div>',
    '<div class="chat-history-overlay" id="chatHistoryOverlay">',
    '  <div class="chat-history-header"><h4>Query History</h4><button id="chatHistoryClose" title="Close history"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg></button></div>',
    '  <div class="chat-history-list" id="chatHistoryList"></div>',
    '</div>'
  ].join('\n');

  document.body.appendChild(fab);
  document.body.appendChild(panel);

  // ── Get elements ──
  var closeBtn = document.getElementById('chatClose');
  var resetBtn = document.getElementById('chatReset');
  var messagesEl = document.getElementById('chatMessages');
  var inputEl = document.getElementById('chatInput');
  var sendBtn = document.getElementById('chatSend');
  var quickEl = document.getElementById('chatQuick');
  var apiUrlInput = document.getElementById('chatApiUrl');
  var dotEl = document.getElementById('chatDot');
  var historyBtn = document.getElementById('chatHistory');
  var historyOverlay = document.getElementById('chatHistoryOverlay');
  var historyCloseBtn = document.getElementById('chatHistoryClose');
  var historyListEl = document.getElementById('chatHistoryList');
  var suggestEl = document.getElementById('chatSuggest');
  var micBtn = document.getElementById('chatMic');
  var modelSelectEl = document.getElementById('chatModelSelect');

  var conversationHistory = [];
  var isLoading = false;
  var voiceMode = false;
  var introShown = false;
  // WebRTC Realtime API state
  var rtcPeer = null;        // RTCPeerConnection
  var rtcDataChannel = null; // data channel for events
  var rtcAudioEl = null;     // <audio> element for AI voice output
  var rtcLocalStream = null; // local microphone stream
  var rtcConnected = false;  // true when data channel is open
  var rtcMuted = false;      // microphone mute state

  // ── Suggested questions for autocomplete ──
  var SUGGESTIONS = [
    // ── Bloom Level 6: Create / Synthesize ──
    'Draft a go/no-go recommendation for the system migration',
    'Propose a remediation plan that addresses the most critical issues first',
    'What acceptance criteria would you define for a production-ready migration?',
    'What additional validation checks should be added before the next comparison run?',
    'Synthesize the financial, clinical, and demographic findings into a risk scorecard',
    // ── Bloom Level 5: Evaluate / Judge ──
    'Based on the Codebook, which discrepancies represent true data corruption?',
    'Is the new system\'s data quality acceptable for CMS reporting requirements?',
    'How would you prioritize the identified issues for remediation?',
    'Does the synthetic nature of DE-SynPUF data affect our confidence in these findings?',
    'Evaluate whether the 0.90 ratio could be an intentional policy change rather than a bug',
    // ── Bloom Level 4: Analyze ──
    'What patterns connect the different types of data scrubbing in the new system?',
    'How do the financial discrepancies correlate with the clinical data changes?',
    'Why does the 0.90 payment ratio affect all claim lines uniformly?',
    'What does the cross-year stability of discrepancies tell us about root cause?',
    // ── Bloom Level 3: Explain / Summarize (Understand) ──
    'Please summarize the executive summary',
    'Please summarize all validation checks',
    'Please summarize the claim line utilization analysis',
    'Can you explain the most critical findings?',
    'Can you explain the payment discrepancy between systems?',
    'Can you explain the 0.90 payment ratio pattern?',
    'Can you explain the financial reconciliation distribution?',
    'Can you explain whether the discrepancies are random or systematic?',
    'Can you explain what bugs should be fixed before production cutover?',
    // Validation-specific explain
    'Can you explain the coverage period validation?',
    'Can you explain the ESRD consistency check?',
    'Can you explain the state code validation?',
    'Can you explain the death temporal chain check?',
    'Can you explain the ICD-9 diagnosis code validation?',
    'Can you explain the NPI format validation?',
    // Data topics
    'Can you explain the ZZ fabricated beneficiaries?',
    'Can you explain how claims are matched between systems?',
    'Can you explain the chronic condition trends?',
    // ── Bloom Level 1–2: Codebook lookups and data retrieval ──
    'What does BENE_HMO_CVRAGE_TOT_MONS mean?',
    'What does BENE_HI_CVRAGE_TOT_MONS mean?',
    'What does BENE_SMI_CVRAGE_TOT_MONS mean?',
    'What does PLAN_CVRG_MOS_NUM mean?',
    'What does BENE_ESRD_IND mean?',
    'What does SP_STATE_CODE mean?',
    'What does LINE_NCH_PMT_AMT_1 mean?',
    'Which fields have the most mismatches?',
    'Which validation checks failed?',
    'How many records are in each system?',
    'Suggest SQL queries to investigate further'
  ];
  var suggestActiveIdx = -1;

  // ── Session persistence (survives page navigation) ──
  function saveSession() {
    var data = {
      messages: messagesEl.innerHTML,
      conversationHistory: conversationHistory,
      isOpen: panel.classList.contains('open'),
      quickHidden: quickEl.style.display === 'none'
    };
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(data));
  }

  function restoreSession() {
    try {
      var data = JSON.parse(sessionStorage.getItem(SESSION_KEY));
      if (!data) return false;
      if (data.messages) messagesEl.innerHTML = data.messages;
      if (data.conversationHistory) conversationHistory = data.conversationHistory;
      if (data.isOpen) {
        panel.classList.add('open');
        fab.style.display = 'none';
      }
      if (data.quickHidden) quickEl.style.display = 'none';
      // Re-attach event listeners on restored SQL blocks
      reattachSqlListeners();
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return true;
    } catch (e) { return false; }
  }

  // Save session before navigating away
  window.addEventListener('beforeunload', saveSession);

  // ── API URL persistence ──
  var savedUrl = localStorage.getItem(API_URL_KEY);
  if (savedUrl) apiUrlInput.value = savedUrl;
  apiUrlInput.addEventListener('change', function () {
    localStorage.setItem(API_URL_KEY, apiUrlInput.value);
    checkConnection();
  });

  // ── Model selection persistence ──
  var MODEL_KEY = 'cms_chat_model';
  var savedModel = localStorage.getItem(MODEL_KEY);
  if (savedModel && modelSelectEl.querySelector('option[value="' + savedModel + '"]')) {
    modelSelectEl.value = savedModel;
  }
  modelSelectEl.addEventListener('change', function () {
    localStorage.setItem(MODEL_KEY, modelSelectEl.value);
  });

  // ── Pre-warm Lambda ──
  (function preWarm() {
    var baseUrl = apiUrlInput.value.replace(/\/+$/, '');
    var apiUrl = baseUrl.indexOf('lambda-url') !== -1 ? baseUrl : baseUrl + '/api/chat';
    fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{"message":"ping","conversationHistory":[]}'
    })
      .then(function (res) {
        dotEl.className = 'dot ' + (res.ok || res.status === 500 ? 'connected' : 'disconnected');
      })
      .catch(function () { dotEl.className = 'dot disconnected'; });
  })();

  // ── History persistence ──
  function loadHistory() {
    try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); }
    catch (e) { return []; }
  }
  function saveHistoryEntry(question, answer, queries) {
    var h = loadHistory();
    h.unshift({ ts: Date.now(), question: question, answer: answer.substring(0, 500), queries: queries || [] });
    if (h.length > 100) h = h.slice(0, 100);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(h));
  }
  function renderHistory() {
    var h = loadHistory();
    if (!h.length) {
      historyListEl.innerHTML = '<div class="chat-history-empty">No queries yet. Ask the assistant a question!</div>';
      return;
    }
    var html = '';
    h.forEach(function (entry, idx) {
      var d = new Date(entry.ts);
      var timeStr = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      var sqlHtml = '';
      if (entry.queries && entry.queries.length > 0) {
        entry.queries.forEach(function (q) {
          sqlHtml += '<div class="h-sql">' + (q.sql || '').replace(/</g, '&lt;').substring(0, 120) + '</div>';
        });
      } else {
        sqlHtml = '<div class="h-nosql">No SQL executed</div>';
      }
      html += '<div class="chat-history-card" data-idx="' + idx + '">' +
        '<div class="h-time">' + timeStr + '</div>' +
        '<div class="h-question">' + (entry.question || '').replace(/</g, '&lt;') + '</div>' +
        sqlHtml + '</div>';
    });
    html += '<button class="chat-history-clear" id="chatHistoryClear">Clear all history</button>';
    historyListEl.innerHTML = html;
    var clearBtn = document.getElementById('chatHistoryClear');
    if (clearBtn) clearBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      localStorage.removeItem(HISTORY_KEY);
      renderHistory();
    });
    historyListEl.querySelectorAll('.chat-history-card').forEach(function (card) {
      card.addEventListener('click', function () {
        var idx = parseInt(card.dataset.idx);
        var entry = loadHistory()[idx];
        if (entry) {
          historyOverlay.classList.remove('open');
          sendMessage(entry.question);
        }
      });
    });
  }

  // ── History panel ──
  historyBtn.addEventListener('click', function () { renderHistory(); historyOverlay.classList.add('open'); });
  historyCloseBtn.addEventListener('click', function () { historyOverlay.classList.remove('open'); });

  // ── Open / close / reset ──
  fab.addEventListener('click', function () {
    panel.classList.add('open');
    fab.style.display = 'none';
    inputEl.focus();
    checkConnection();
  });
  closeBtn.addEventListener('click', function () {
    panel.classList.remove('open');
    fab.style.display = 'flex';
    saveSession();
  });
  resetBtn.addEventListener('click', function () {
    if (rtcConnected || voiceMode) disconnectRealtime();
    conversationHistory = [];
    messagesEl.innerHTML = '';
    introShown = false;
    quickEl.style.display = 'flex';
    showIntro();
    saveSession();
  });

  // ── Quick questions ──
  quickEl.addEventListener('click', function (e) {
    var btn = e.target.closest('button[data-q]');
    if (btn) sendMessage(btn.dataset.q);
  });

  // ── Navigation tag click delegation (for [[page_id]] tokens) ──
  messagesEl.addEventListener('click', function (e) {
    var tag = e.target.closest('.chat-nav-tag');
    if (!tag) return;
    e.preventDefault();
    // Section navigation (scroll-to)
    var sectionId = tag.getAttribute('data-nav-section');
    if (sectionId) {
      navigateToSection(sectionId);
      return;
    }
    // Page navigation (save session, then navigate)
    var pageId = tag.getAttribute('data-nav-page');
    if (pageId) {
      saveSession();
      // If it's the SQL page, check if there's a SQL code block nearby to pre-fill
      if (pageId === 'sql') {
        var msgDiv = tag.closest('.chat-msg');
        if (msgDiv) {
          var codeEl = msgDiv.querySelector('pre code');
          if (codeEl && /^\s*(SELECT|WITH)/i.test(codeEl.textContent)) {
            sessionStorage.setItem('cms_prefill_sql', codeEl.textContent);
          }
        }
      }
      window.location.href = tag.getAttribute('href');
    }
  });

  // ── Autocomplete helpers ──
  function filterSuggestions(query) {
    if (!query || query.length < 2) return [];
    var q = query.toLowerCase();
    var words = q.split(/\s+/);
    return SUGGESTIONS.filter(function (s) {
      var sl = s.toLowerCase();
      return words.every(function (w) { return sl.indexOf(w) !== -1; });
    }).slice(0, 5);
  }

  function highlightMatch(text, query) {
    if (!query) return text.replace(/&/g,'&amp;').replace(/</g,'&lt;');
    var words = query.toLowerCase().split(/\s+/).filter(Boolean).sort(function(a,b){ return b.length - a.length; });
    var result = '';
    var i = 0;
    while (i < text.length) {
      var matched = false;
      for (var w = 0; w < words.length; w++) {
        var wl = words[w].length;
        if (text.substring(i, i + wl).toLowerCase() === words[w]) {
          var seg = text.substring(i, i + wl).replace(/&/g,'&amp;').replace(/</g,'&lt;');
          result += '<span class="suggest-match">' + seg + '</span>';
          i += wl;
          matched = true;
          break;
        }
      }
      if (!matched) {
        var ch = text[i];
        result += ch === '&' ? '&amp;' : ch === '<' ? '&lt;' : ch;
        i++;
      }
    }
    return result;
  }

  function showSuggestions(matches) {
    if (!matches.length) { hideSuggestions(); return; }
    suggestActiveIdx = -1;
    var html = matches.map(function (m, i) {
      return '<div class="chat-suggest-item" data-idx="' + i + '">' + highlightMatch(m, inputEl.value) + '</div>';
    }).join('');
    html += '<div class="chat-suggest-hint"><kbd>Tab</kbd> to complete &middot; <kbd>\u2191\u2193</kbd> to navigate</div>';
    suggestEl.innerHTML = html;
    suggestEl.classList.add('open');
    suggestEl.querySelectorAll('.chat-suggest-item').forEach(function (item) {
      item.addEventListener('click', function () {
        inputEl.value = matches[parseInt(item.dataset.idx)];
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 100) + 'px';
        hideSuggestions();
        inputEl.focus();
      });
    });
  }

  function hideSuggestions() {
    suggestEl.classList.remove('open');
    suggestEl.innerHTML = '';
    suggestActiveIdx = -1;
  }

  // ── Input handling ──
  inputEl.addEventListener('keydown', function (e) {
    // Autocomplete navigation
    var items = suggestEl.querySelectorAll('.chat-suggest-item');
    if (items.length && suggestEl.classList.contains('open')) {
      if (e.key === 'Tab') {
        e.preventDefault();
        var idx = suggestActiveIdx >= 0 ? suggestActiveIdx : 0;
        inputEl.value = items[idx].textContent;
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 100) + 'px';
        hideSuggestions();
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        suggestActiveIdx = (suggestActiveIdx + 1) % items.length;
        items.forEach(function (it, i) { it.classList.toggle('active', i === suggestActiveIdx); });
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        suggestActiveIdx = suggestActiveIdx <= 0 ? items.length - 1 : suggestActiveIdx - 1;
        items.forEach(function (it, i) { it.classList.toggle('active', i === suggestActiveIdx); });
        return;
      }
      if (e.key === 'Escape') { hideSuggestions(); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); hideSuggestions(); sendMessage(inputEl.value); }
  });
  sendBtn.addEventListener('click', function () { hideSuggestions(); sendMessage(inputEl.value); });
  inputEl.addEventListener('input', function () {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 100) + 'px';
    // Autocomplete
    var matches = filterSuggestions(inputEl.value.trim());
    showSuggestions(matches);
  });
  inputEl.addEventListener('blur', function () {
    // Delay to allow click on suggestion
    setTimeout(hideSuggestions, 150);
  });

  // ── Core functions ──
  function addMessage(role, content) {
    var div = document.createElement('div');
    div.className = 'chat-msg ' + role;
    if (role === 'assistant') {
      div.innerHTML = renderMarkdown(content);
      addSqlInteractivity(div);
    } else {
      div.textContent = content;
    }
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function showLoading() {
    var div = document.createElement('div');
    div.className = 'chat-loading';
    div.id = 'chatLoadingDots';
    div.innerHTML = '<span></span><span></span><span></span>';
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function hideLoading() {
    var dots = document.getElementById('chatLoadingDots');
    if (dots) dots.remove();
  }

  // ── SQL interactivity: copy button + double-click → SQL Explorer ──
  function addSqlInteractivity(container) {
    container.querySelectorAll('pre').forEach(function (pre) {
      var code = pre.querySelector('code');
      if (!code) return;
      var text = code.textContent || '';
      // Only add to SQL-looking blocks
      if (!/^\s*(SELECT|WITH|DESCRIBE|EXPLAIN|SHOW|PRAGMA|INSERT|CREATE)/i.test(text)) return;

      // Copy button
      var copyBtn = document.createElement('button');
      copyBtn.className = 'chat-sql-copy';
      copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
      copyBtn.title = 'Copy to clipboard';
      copyBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        e.preventDefault();
        copyToClipboard(text).then(function () {
          copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
          copyBtn.classList.add('copied');
          setTimeout(function () { copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'; copyBtn.classList.remove('copied'); }, 1500);
        });
      });
      pre.style.position = 'relative';
      pre.appendChild(copyBtn);

      // Double-click → fill SQL Explorer directly if on that page, otherwise navigate
      pre.style.cursor = 'pointer';
      pre.title = 'Double-click to run in SQL Explorer';
      pre.addEventListener('dblclick', function () {
        var onSqlPage = window.location.pathname.indexOf('sql_explorer') !== -1;
        if (onSqlPage) {
          // Already on SQL Explorer — dispatch custom event for the module script to handle
          window.dispatchEvent(new CustomEvent('chat-fill-sql', { detail: { sql: text } }));
        } else {
          sessionStorage.setItem('cms_prefill_sql', text);
          window.location.href = getSqlExplorerUrl();
        }
      });
    });
  }

  function reattachSqlListeners() {
    messagesEl.querySelectorAll('.chat-msg.assistant').forEach(function (msg) {
      // Only re-attach if no copy buttons exist yet
      if (!msg.querySelector('.chat-sql-copy')) addSqlInteractivity(msg);
    });
    // Re-attach nav pill buttons
    messagesEl.querySelectorAll('[data-nav-section]').forEach(function (btn) {
      btn.addEventListener('click', function () { navigateToSection(btn.dataset.navSection); });
    });
  }

  // ── Send message ──
  // ── Cached answers lookup ──
  var cachedAnswers = (typeof CACHED_ANSWERS !== 'undefined') ? CACHED_ANSWERS : {};
  var cachedKeys = Object.keys(cachedAnswers);

  function findCachedAnswer(query) {
    if (!cachedKeys.length) return null;
    var q = query.toLowerCase().replace(/[?!.,;:]+/g, '').trim();
    // Exact match first
    for (var i = 0; i < cachedKeys.length; i++) {
      var k = cachedKeys[i].toLowerCase().replace(/[?!.,;:]+/g, '').trim();
      if (q === k) return cachedAnswers[cachedKeys[i]];
    }
    // Fuzzy: all words in query appear in a key (and vice versa, 70%+ overlap)
    var qWords = q.split(/\s+/).filter(function(w) { return w.length > 2; });
    if (qWords.length < 2) return null;
    var bestScore = 0;
    var bestAnswer = null;
    for (var i = 0; i < cachedKeys.length; i++) {
      var kWords = cachedKeys[i].toLowerCase().replace(/[?!.,;:]+/g, '').split(/\s+/).filter(function(w) { return w.length > 2; });
      var matchCount = 0;
      for (var j = 0; j < qWords.length; j++) {
        for (var m = 0; m < kWords.length; m++) {
          if (kWords[m].indexOf(qWords[j]) !== -1 || qWords[j].indexOf(kWords[m]) !== -1) {
            matchCount++;
            break;
          }
        }
      }
      var score = matchCount / Math.max(qWords.length, kWords.length);
      if (score > bestScore && score >= 0.6) {
        bestScore = score;
        bestAnswer = cachedAnswers[cachedKeys[i]];
      }
    }
    return bestAnswer;
  }

  function sendMessage(text) {
    text = (text || '').trim();
    if (!text || isLoading) return;

    inputEl.value = '';
    inputEl.style.height = 'auto';
    quickEl.style.display = 'none';

    addMessage('user', text);
    conversationHistory.push({ role: 'user', content: text });

    // Check cached answers first for instant response
    var cached = findCachedAnswer(text);
    if (cached) {
      var answerText = cached.answer || cached;
      var answerQueries = cached.queries || [];

      var badge = document.createElement('div');
      badge.className = 'chat-cached-badge';
      badge.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg> Instant answer';
      messagesEl.appendChild(badge);

      var msgDiv = addMessage('assistant', answerText);
      conversationHistory.push({ role: 'assistant', content: answerText });
      speakText(answerText);

      // Auto-navigate to relevant report section
      var combinedText = text + ' ' + answerText;
      var section = detectSection(combinedText);
      if (section && document.getElementById(section.id)) {
        addSectionPill(msgDiv, section);
        navigateToSection(section.id);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }

      // Follow-up buttons bar
      var bar = document.createElement('div');
      bar.className = 'chat-followup-bar';

      // Button 1: Explain in more detail (AI)
      var deepBtn = document.createElement('button');
      deepBtn.className = 'chat-followup-btn';
      deepBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg> Explain in more detail';
      deepBtn.addEventListener('click', function () {
        bar.remove();
        sendToApi(text);
      });
      bar.appendChild(deepBtn);

      // Button 2: Review SQL queries
      if (answerQueries.length > 0) {
        var sqlBtn = document.createElement('button');
        sqlBtn.className = 'chat-followup-btn sql-btn';
        sqlBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg> Review SQL queries';
        sqlBtn.addEventListener('click', function () {
          sqlBtn.remove();
          var details = document.createElement('details');
          details.className = 'chat-sql-reveal';
          details.open = true;
          var summary = document.createElement('summary');
          summary.textContent = answerQueries.length + ' SQL quer' + (answerQueries.length === 1 ? 'y' : 'ies') + ' used for this answer';
          details.appendChild(summary);
          answerQueries.forEach(function (sql, idx) {
            var label = document.createElement('span');
            label.className = 'sql-label';
            label.textContent = 'Query ' + (idx + 1);
            details.appendChild(label);
            var pre = document.createElement('pre');
            var code = document.createElement('code');
            code.textContent = sql;
            pre.appendChild(code);
            details.appendChild(pre);
          });
          msgDiv.appendChild(details);
          addSqlInteractivity(details);

          // Offer to navigate to SQL Explorer
          var navPrompt = document.createElement('div');
          navPrompt.style.cssText = 'margin-top:8px;padding:8px 12px;background:rgba(56,189,248,0.08);border:1px solid rgba(56,189,248,0.2);border-radius:8px;font-size:.78rem;color:#e2e8f0;';
          navPrompt.innerHTML = 'Want to run these yourself? ' +
            '<button style="margin-left:6px;padding:4px 12px;background:rgba(56,189,248,0.15);border:1px solid #38bdf8;border-radius:6px;color:#38bdf8;font-size:.75rem;cursor:pointer;font-family:inherit;transition:all .15s;" ' +
            'onmouseover="this.style.background=\'rgba(56,189,248,0.3)\'" onmouseout="this.style.background=\'rgba(56,189,248,0.15)\'">' +
            '\u279C Open SQL Explorer</button>';
          navPrompt.querySelector('button').addEventListener('click', function () {
            sessionStorage.setItem('cms_prefill_sql', answerQueries[0]);
            window.location.href = getSqlExplorerUrl();
          });
          msgDiv.appendChild(navPrompt);

          messagesEl.scrollTop = messagesEl.scrollHeight;
        });
        bar.appendChild(sqlBtn);
      }

      // Button 3: Open SQL Explorer (when question is about SQL)
      if (/sql|quer/i.test(text)) {
        var sqlNavBtn = document.createElement('button');
        sqlNavBtn.className = 'chat-followup-btn sql-btn';
        sqlNavBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg> Open SQL Explorer';
        sqlNavBtn.addEventListener('click', function () {
          window.location.href = getSqlExplorerUrl();
        });
        bar.appendChild(sqlNavBtn);
      }

      msgDiv.appendChild(bar);

      saveHistoryEntry(text, answerText, []);
      saveSession();
      return;
    }

    // No cached answer — call the API
    sendToApi(text);
  }

  function sendToApi(text) {
    isLoading = true;
    sendBtn.disabled = true;
    showLoading();

    var baseUrl = apiUrlInput.value.replace(/\/+$/, '');
    var apiUrl = baseUrl.indexOf('lambda-url') !== -1 ? baseUrl : baseUrl + '/api/chat';

    // Parse provider/model from selector (format: "provider/model")
    var modelVal = modelSelectEl.value;
    var slashIdx = modelVal.indexOf('/');
    var provider = modelVal.substring(0, slashIdx);
    var model = modelVal.substring(slashIdx + 1);

    fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        conversationHistory: conversationHistory.slice(0, -1),
        provider: provider,
        model: model
      })
    })
      .then(function (res) {
        if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || d.error || 'API error'); });
        return res.json();
      })
      .then(function (data) {
        hideLoading();
        // Show SQL queries the AI ran
        if (data.queries && data.queries.length > 0) {
          data.queries.forEach(function (q, qi) {
            var qDiv = document.createElement('div');
            qDiv.className = 'chat-msg assistant';
            qDiv.style.fontSize = '0.78rem';
            qDiv.style.background = 'rgba(56,189,248,0.06)';
            qDiv.style.borderLeft = '3px solid #38bdf8';
            qDiv.style.padding = '8px 12px';
            var resultLine = '';
            if (q.result_preview.error) {
              resultLine = '<span style="color:#f87171;">Error: ' + q.result_preview.error + '</span>';
            } else {
              resultLine = '<span style="color:#4ade80;">' + q.result_preview.row_count + ' row(s) returned</span>' +
                (q.result_preview.truncated ? ' <span style="color:#fbbf24;">(truncated to 50)</span>' : '');
            }
            var explainHtml = q.explanation
              ? '<div style="color:#e2e8f0;margin-bottom:6px;">' + q.explanation.replace(/</g, '&lt;') + '</div>'
              : '';
            qDiv.innerHTML =
              '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">' +
              '<strong style="color:#38bdf8;font-size:0.7rem;">QUERY ' + (qi + 1) + '</strong>' +
              resultLine +
              '</div>' +
              explainHtml +
              '<details style="margin:0;"><summary style="cursor:pointer;color:#64748b;font-size:0.7rem;user-select:none;">Show SQL</summary>' +
              '<pre style="margin:4px 0 0;background:rgba(0,0,0,0.3);padding:6px 8px;border-radius:4px;overflow-x:auto;font-size:0.72rem;position:relative;"><code>' +
              q.sql.replace(/</g, '&lt;') + '</code></pre></details>';
            messagesEl.appendChild(qDiv);
            addSqlInteractivity(qDiv);
          });
        }

        var msgDiv = addMessage('assistant', data.content);
        conversationHistory.push({ role: 'assistant', content: data.content });
        speakText(data.content);
        saveHistoryEntry(text, data.content, data.queries || []);
        dotEl.className = 'dot connected';

        // Auto-navigate to relevant report section (only on report page)
        var combinedText = text + ' ' + data.content;
        var section = detectSection(combinedText);
        if (section && document.getElementById(section.id)) {
          addSectionPill(msgDiv, section);
          navigateToSection(section.id);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }

        // Add "Open in SQL Explorer" link if response contains SQL
        if (data.queries && data.queries.length > 0) {
          var sqlPill = document.createElement('div');
          sqlPill.className = 'chat-nav-pill';
          sqlPill.innerHTML = '<button data-goto-sql="1">\u279C Open SQL Explorer</button>';
          msgDiv.appendChild(sqlPill);
          sqlPill.querySelector('button').addEventListener('click', function () {
            // Pre-fill with the first query
            sessionStorage.setItem('cms_prefill_sql', data.queries[0].sql);
            window.location.href = getSqlExplorerUrl();
          });
        }

        saveSession();
      })
      .catch(function (err) {
        hideLoading();
        addMessage('system', 'Error: ' + err.message + '. Make sure the web server is running (pip install -r requirements-web.txt && OPENAI_API_KEY=sk-... uvicorn web.server:app --port 8000)');
        dotEl.className = 'dot disconnected';
        saveSession();
      })
      .finally(function () {
        isLoading = false;
        sendBtn.disabled = false;
        inputEl.focus();
      });
  }

  function checkConnection() {
    var baseUrl = apiUrlInput.value.replace(/\/+$/, '');
    var apiUrl = baseUrl.indexOf('lambda-url') !== -1 ? baseUrl : baseUrl + '/api/chat';
    fetch(apiUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"ping"}' })
      .then(function (res) { dotEl.className = 'dot ' + (res.ok || res.status === 500 ? 'connected' : 'disconnected'); })
      .catch(function () { dotEl.className = 'dot disconnected'; });
  }

  // ── Section navigation (report page only) ──
  var SECTION_KEYWORDS = {
    'discrepancies': { id: 'discrepancies', label: 'Discrepancies', patterns: /discrepanc|mismatch|diff(?:erence|s\b)|data.?mismatch/i },
    'financial': { id: 'financial', label: 'Financial Analysis', patterns: /financial|payment|reimburs|cost|dollar|reimb|pppymt|benres|medreimb|0\.90.*ratio|payment.*ratio/i },
    'validation': { id: 'validation', label: 'Validation', patterns: /validat|quality.?check|integrity|check.?result/i },
    'trends': { id: 'trends', label: 'YoY Trends', patterns: /trend|year.?over|yoy|annual|yearly/i },
    'comparison': { id: 'comparison', label: 'System Comparison', patterns: /system.?compar|old.?vs|new.?vs|side.?by.?side/i },
    'profiles': { id: 'profiles', label: 'Data Profiles', patterns: /profile|column.?stat|data.?type|schema.?detail/i },
    'summary': { id: 'summary', label: 'Executive Summary', patterns: /executive.?summary|overview|total.?beneficiar|total.?claim/i },
    'data-context': { id: 'data-context', label: 'Data Context', patterns: /data.?context|file.?list|source.?file|csv.?file|under.?comparison/i }
  };

  function detectSection(text) {
    var order = ['discrepancies', 'financial', 'validation', 'trends', 'comparison', 'profiles', 'summary', 'data-context'];
    for (var i = 0; i < order.length; i++) {
      var sec = SECTION_KEYWORDS[order[i]];
      if (sec.patterns.test(text)) return sec;
    }
    return null;
  }

  function navigateToSection(sectionId) {
    var el = document.getElementById(sectionId);
    if (!el) return;

    // Find the parent .section div so we scroll to its heading first
    var parentSection = el.closest('.section');
    var scrollTarget = el;
    // If the target is inside a section but is NOT the section itself,
    // scroll to the section heading so the header is visible, then highlight the target
    if (parentSection && parentSection !== el && parentSection.id !== sectionId) {
      var heading = parentSection.querySelector('h2[id]');
      if (heading) scrollTarget = heading;
    }

    scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'start' });

    // Update sidebar active state
    var sideLinks = document.querySelectorAll('#sidebar a[data-section]');
    var closestSectionId = parentSection ? parentSection.id : sectionId;
    sideLinks.forEach(function (a) { a.classList.toggle('active', a.getAttribute('data-section') === closestSectionId); });

    // Highlight the target element with CSS animation
    setTimeout(function () {
      if (scrollTarget !== el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      el.classList.remove('highlight-target');
      void el.offsetWidth; // force reflow
      el.classList.add('highlight-target');
      el.addEventListener('animationend', function () { el.classList.remove('highlight-target'); }, { once: true });
    }, scrollTarget !== el ? 600 : 300);
  }

  function addSectionPill(parentEl, section) {
    var pill = document.createElement('div');
    pill.className = 'chat-nav-pill';
    pill.innerHTML = '<button data-nav-section="' + section.id + '">\u279C Go to ' + section.label + '</button>';
    parentEl.appendChild(pill);
    pill.querySelector('button').addEventListener('click', function () { navigateToSection(section.id); });
  }

  // ── Markdown renderer with [[page_id]] navigation tokens ──
  // Block-level parser inspired by healthresourcepal/markdownParser.ts
  function renderMarkdown(text) {
    if (!text) return '';

    // First extract code blocks so they don't get parsed
    var codeBlocks = [];
    text = text.replace(/```(\w*)\n([\s\S]*?)```/g, function (m, lang, code) {
      codeBlocks.push(code);
      return '%%CODEBLOCK_' + (codeBlocks.length - 1) + '%%';
    });

    // Extract tables
    var tables = [];
    text = text.replace(/\|(.+)\|\n\|[-| :]+\|\n((?:\|.+\|\n?)*)/g, function (match, headerLine, bodyLines) {
      var headers = headerLine.split('|').map(function (h) { return h.trim(); }).filter(Boolean);
      var rows = bodyLines.trim().split('\n').map(function (row) {
        return row.split('|').map(function (c) { return c.trim(); }).filter(Boolean);
      });
      var table = '<table><thead><tr>' + headers.map(function (h) { return '<th>' + h + '</th>'; }).join('') + '</tr></thead><tbody>';
      rows.forEach(function (r) { table += '<tr>' + r.map(function (c) { return '<td>' + c + '</td>'; }).join('') + '</tr>'; });
      tables.push(table + '</tbody></table>');
      return '%%TABLE_' + (tables.length - 1) + '%%';
    });

    // Parse blocks line by line
    var lines = text.split('\n');
    var blocks = [];
    var currentPara = [];
    var currentList = [];

    function flushPara() {
      if (currentPara.length > 0) {
        blocks.push({ type: 'paragraph', text: currentPara.join(' ').trim() });
        currentPara = [];
      }
    }
    function flushList() {
      if (currentList.length > 0) {
        blocks.push({ type: 'list', items: currentList.slice() });
        currentList = [];
      }
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();

      if (line === '') { flushList(); flushPara(); continue; }

      // Headings
      var hm = line.match(/^(#{1,3})\s+(.+)$/);
      if (hm) { flushList(); flushPara(); blocks.push({ type: 'heading', level: hm[1].length, text: hm[2] }); continue; }

      // List items
      if (line.match(/^[-*•]\s+/)) { flushPara(); currentList.push(line.replace(/^[-*•]\s+/, '')); continue; }
      if (line.match(/^\d+\.\s+/)) { flushPara(); currentList.push(line.replace(/^\d+\.\s+/, '')); continue; }

      // Code block / table placeholders
      if (line.match(/^%%CODEBLOCK_\d+%%$/) || line.match(/^%%TABLE_\d+%%$/)) { flushList(); flushPara(); blocks.push({ type: 'raw', text: line }); continue; }

      // Regular paragraph line
      flushList();
      currentPara.push(line);
    }
    flushList();
    flushPara();

    // Render blocks to HTML
    var html = blocks.map(function (block) {
      if (block.type === 'heading') {
        var cls = block.level === 1 ? 'font-size:1rem;font-weight:700;margin:10px 0 4px;color:#38bdf8;' :
                  block.level === 2 ? 'font-size:.92rem;font-weight:700;margin:8px 0 4px;color:#38bdf8;' :
                  'font-size:.85rem;font-weight:600;margin:6px 0 3px;color:#38bdf8;';
        return '<div style="' + cls + '">' + renderInline(block.text) + '</div>';
      }
      if (block.type === 'list') {
        return '<ul>' + block.items.map(function (item) { return '<li>' + renderInline(item) + '</li>'; }).join('') + '</ul>';
      }
      if (block.type === 'raw') {
        var cbm = block.text.match(/^%%CODEBLOCK_(\d+)%%$/);
        if (cbm) return '<pre><code>' + codeBlocks[parseInt(cbm[1])].replace(/</g, '&lt;') + '</code></pre>';
        var tbm = block.text.match(/^%%TABLE_(\d+)%%$/);
        if (tbm) return tables[parseInt(tbm[1])];
        return '';
      }
      // paragraph
      return '<p>' + renderInline(block.text) + '</p>';
    }).join('');

    return html;
  }

  // Convert **bold text** to a clickable link if it matches a known section pattern
  function boldToLink(boldText) {
    for (var i = 0; i < BOLD_LINK_PATTERNS.length; i++) {
      var bp = BOLD_LINK_PATTERNS[i];
      if (bp.pattern.test(boldText)) {
        var isOnReport = window.location.pathname.indexOf('comparison_report') !== -1;
        if (isOnReport) {
          // On report page — scroll to the section
          return '<a class="chat-nav-tag" href="#" data-nav-section="' + bp.reportHash + '" style="font-weight:600;">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 5l7 7-7 7"/></svg>' +
            boldText + '</a>';
        } else {
          // On other page — navigate to report with hash
          var reportUrl = resolvePageUrl('report');
          var href = (reportUrl ? reportUrl.url : '../reports/comparison_report.html') + '#' + bp.reportHash;
          return '<a class="chat-nav-tag" href="' + href + '" data-nav-page="report" style="font-weight:600;">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>' +
            boldText + '</a>';
        }
      }
    }
    // No match — render as plain bold
    return '<strong>' + boldText + '</strong>';
  }

  // Inline markdown + [[page_id]] navigation tokens
  function renderInline(text) {
    if (!text) return '';
    // Split on [[page_id]] tokens first
    var parts = text.split(/(\[\[[a-z_]+\]\])/g);
    var result = '';
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i];
      var tagMatch = part.match(/^\[\[([a-z_]+)\]\]$/);
      if (tagMatch && PAGE_MAP[tagMatch[1]]) {
        var pageId = tagMatch[1];
        var entry = PAGE_MAP[pageId];
        var resolved = resolvePageUrl(pageId);
        if (resolved && resolved.section) {
          // Section navigation button
          result += '<a class="chat-nav-tag" href="#" data-nav-section="' + resolved.section + '">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 5l7 7-7 7"/></svg>' +
            entry.label + '</a>';
        } else if (resolved && resolved.url) {
          // Page navigation button (save session before navigating)
          result += '<a class="chat-nav-tag" href="' + resolved.url + '" data-nav-page="' + pageId + '">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>' +
            entry.label + '</a>';
        }
      } else if (part) {
        // Apply inline markdown with auto-linking for bold text
        result += part
          .replace(/`([^`]+)`/g, '<code>$1</code>')
          .replace(/\*\*(.+?)\*\*/g, function (m, boldText) {
            return boldToLink(boldText);
          })
          .replace(/\*(.+?)\*/g, '<em>$1</em>');
      }
    }
    return result;
  }

  // ── Voice mode (OpenAI Realtime API via WebRTC) ──
  // Same pattern as PurlPal: ephemeral token → WebRTC peer connection → full-duplex voice

  // Condensed Report Pal instructions for Realtime voice session
  var REALTIME_INSTRUCTIONS = 'You are Report Pal, a friendly and knowledgeable data analyst assistant ' +
    'embedded in the CMS Claims Comparison Report. You help reviewers understand findings from comparing ' +
    'an old Medicare claims processing system (CMS DE-SynPUF) against a new replacement system.\n\n' +
    'IMPORTANT: Always respond in English. Do NOT switch to any other language unless the user explicitly ' +
    'asks you to respond in a different language. Even if the user speaks in another language, reply in English ' +
    'unless they request otherwise.\n\n' +
    'Key findings you know about:\n' +
    '- Overall accuracy ~85-90% between old and new systems\n' +
    '- Systematic 0.90 payment ratio: new system payments = old * 0.90 (10% reduction across the board)\n' +
    '- "ZZ" prefix beneficiaries are fabricated test records injected by the new system\n' +
    '- Phantom records exist in the new system with no match in old\n' +
    '- Chronic condition flags mostly match, some discrepancies in diabetes and depression\n' +
    '- Financial reconciliation shows consistent 10% divergence pattern\n\n' +
    'When discussing report sections, mention them by name so the user can find them:\n' +
    '- Discrepancy Dashboard, Financial Analysis, Data Quality Validation\n' +
    '- Year-over-Year Trends, System Comparison, Data Profiles, Executive Summary\n\n' +
    'Be concise, warm, and data-driven. Explain technical terms in plain language. ' +
    'If the user asks about specific data queries, suggest they type the question for detailed SQL-backed answers.\n\n' +
    'IMPORTANT: When discussing SQL queries, NEVER read the raw SQL code aloud verbatim. ' +
    'Instead, describe what the query does naturally. For example, say "This query joins the beneficiary table ' +
    'with the claims table to compare payment amounts" or "The SELECT statement pulls together data from ' +
    'three different tables." Keep SQL discussion conversational and high-level.';
  var rtcConnecting = false; // guard against double-click

  // Streaming state for assistant voice transcript
  var rtcAssistantDiv = null;
  var rtcAssistantText = '';

  function speakText(text) {
    // No-op: Realtime API handles voice output through WebRTC audio stream.
    // Browser TTS has been removed.
  }

  micBtn.addEventListener('click', function () {
    if (rtcConnected) {
      // Toggle microphone mute (no chat messages — just visual state)
      rtcMuted = !rtcMuted;
      if (rtcLocalStream) {
        rtcLocalStream.getAudioTracks().forEach(function (t) { t.enabled = !rtcMuted; });
      }
      micBtn.classList.toggle('recording', !rtcMuted);
      micBtn.title = rtcMuted ? 'Unmute microphone' : 'Mute microphone';
    } else {
      initVoiceMode();
    }
  });

  // Stop AI voice button — immediately cancels the current response
  document.getElementById('chatStopVoice').addEventListener('click', function () {
    if (rtcConnected && rtcDataChannel && rtcDataChannel.readyState === 'open') {
      rtcDataChannel.send(JSON.stringify({ type: 'response.cancel' }));
      // Also truncate the last assistant item to stop any residual audio
      if (rtcAssistantDiv) {
        rtcAssistantDiv.innerHTML = renderMarkdown(rtcAssistantText + ' *[stopped]*');
        addSqlInteractivity(rtcAssistantDiv);
        conversationHistory.push({ role: 'assistant', content: rtcAssistantText });
        rtcAssistantDiv = null;
        rtcAssistantText = '';
      }
    }
  });

  function initVoiceMode() {
    // Prevent double-click race condition
    if (rtcConnecting) return;
    // Require HTTPS (navigator.mediaDevices is undefined on HTTP)
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      addMessage('assistant', '**Voice mode requires a secure connection (HTTPS).** \n\nThis page is served over HTTP, so the browser blocks microphone access. You can still type your questions below!\n\nTo use voice mode, access the report via HTTPS.');
      conversationHistory.push({ role: 'assistant', content: 'Voice mode unavailable — page not served over HTTPS.' });
      saveSession();
      return;
    }

    rtcConnecting = true;
    addMessage('assistant', 'Connecting to Report Pal voice...');
    conversationHistory.push({ role: 'assistant', content: 'Connecting to voice...' });
    micBtn.classList.add('recording');

    // 1. Fetch ephemeral Realtime API token from our session Lambda
    fetch(SESSION_LAMBDA_URL + '/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ voice: 'coral' })
    })
    .then(function (res) {
      if (!res.ok) throw new Error('Session API returned ' + res.status);
      return res.json();
    })
    .then(function (data) {
      if (!data.client_secret || !data.client_secret.value) {
        throw new Error('No ephemeral token received');
      }
      return connectWebRTC(data.client_secret.value);
    })
    .catch(function (err) {
      console.error('Voice connection failed:', err);
      rtcConnecting = false;
      micBtn.classList.remove('recording');
      addMessage('assistant', '**Could not connect to voice.** ' + err.message + '\n\nYou can still type your questions below.');
      conversationHistory.push({ role: 'assistant', content: 'Voice connection failed: ' + err.message });
      saveSession();
    });
  }

  function connectWebRTC(ephemeralToken) {
    // 2. Create RTCPeerConnection
    rtcPeer = new RTCPeerConnection();

    // 3. Audio output element
    rtcAudioEl = document.createElement('audio');
    rtcAudioEl.autoplay = true;
    rtcPeer.ontrack = function (e) {
      rtcAudioEl.srcObject = e.streams[0];
    };

    // 4. Microphone input
    return navigator.mediaDevices.getUserMedia({ audio: true })
    .then(function (stream) {
      rtcLocalStream = stream;
      stream.getTracks().forEach(function (track) {
        rtcPeer.addTrack(track, stream);
      });

      // 5. Data channel for events
      rtcDataChannel = rtcPeer.createDataChannel('oai-events');
      rtcDataChannel.onopen = onRtcDataChannelOpen;
      rtcDataChannel.onmessage = onRtcDataChannelMessage;
      rtcDataChannel.onclose = function () {
        console.log('Realtime data channel closed');
        disconnectRealtime();
        addMessage('assistant', '*Voice session ended.* Click the mic button to reconnect, or type your questions below.');
      };

      // 6. Create SDP offer
      return rtcPeer.createOffer();
    })
    .then(function (offer) {
      return rtcPeer.setLocalDescription(offer);
    })
    .then(function () {
      // 7. Exchange SDP with OpenAI Realtime API
      return fetch('https://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2025-06-03', {
        method: 'POST',
        body: rtcPeer.localDescription.sdp,
        headers: {
          'Authorization': 'Bearer ' + ephemeralToken,
          'Content-Type': 'application/sdp',
        },
      });
    })
    .then(function (res) {
      if (!res.ok) throw new Error('OpenAI Realtime SDP exchange failed: ' + res.status);
      return res.text();
    })
    .then(function (sdp) {
      return rtcPeer.setRemoteDescription({ type: 'answer', sdp: sdp });
    })
    .then(function () {
      voiceMode = true;
      console.log('WebRTC peer connection established');
    });
  }

  function onRtcDataChannelOpen() {
    rtcConnected = true;
    rtcConnecting = false;
    console.log('Realtime data channel open — sending session.update');

    // Configure the Realtime session with Report Pal instructions
    rtcDataChannel.send(JSON.stringify({
      type: 'session.update',
      session: {
        instructions: REALTIME_INSTRUCTIONS,
        voice: 'coral',
        turn_detection: {
          type: 'server_vad',
          threshold: 0.5,
          prefix_padding_ms: 300,
          silence_duration_ms: 500,
        },
        input_audio_transcription: {
          model: 'whisper-1',
        },
      }
    }));

    // Prompt the AI to greet the user with a voice message
    var greetingText = 'Hello. What would you like to discuss about the report? ' +
      'You can ask me questions about the data and how we came to our conclusions, ' +
      'and I will do my best to explain. You can talk to me naturally, ' +
      'and interrupt me at any time if I am getting off track.';
    rtcDataChannel.send(JSON.stringify({
      type: 'conversation.item.create',
      item: {
        type: 'message',
        role: 'user',
        content: [{ type: 'input_text', text: 'Greet me briefly. Say exactly: ' + greetingText }]
      }
    }));
    rtcDataChannel.send(JSON.stringify({ type: 'response.create' }));

    // Update UI — show stop button
    micBtn.classList.add('recording');
    var stopBtn = document.getElementById('chatStopVoice');
    if (stopBtn) stopBtn.classList.add('visible');
    conversationHistory.push({ role: 'assistant', content: 'Voice connected via OpenAI Realtime API.' });
    saveSession();
  }

  function onRtcDataChannelMessage(e) {
    var event;
    try { event = JSON.parse(e.data); } catch (err) { return; }

    switch (event.type) {
      // User's spoken words transcribed
      // NOTE: This event often arrives AFTER assistant response starts streaming,
      // so we insert it before the streaming assistant div to maintain correct order.
      case 'conversation.item.input_audio_transcription.completed':
        var userText = event.transcript && event.transcript.trim() ? event.transcript.trim() : '[inaudible]';
        if (userText !== '[inaudible]') {
          var userDiv = document.createElement('div');
          userDiv.className = 'chat-msg user';
          userDiv.textContent = userText;
          if (rtcAssistantDiv && rtcAssistantDiv.parentNode === messagesEl) {
            // Insert before the currently-streaming assistant message
            messagesEl.insertBefore(userDiv, rtcAssistantDiv);
          } else {
            messagesEl.appendChild(userDiv);
          }
          messagesEl.scrollTop = messagesEl.scrollHeight;
          conversationHistory.push({ role: 'user', content: userText });
        }
        break;

      // Assistant voice transcript streaming
      case 'response.audio_transcript.delta':
        if (!rtcAssistantDiv) {
          rtcAssistantDiv = addMessage('assistant', '');
        }
        rtcAssistantText += (event.delta || '');
        rtcAssistantDiv.innerHTML = renderMarkdown(rtcAssistantText);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        break;

      // Assistant voice transcript complete
      case 'response.audio_transcript.done':
        var finalText = event.transcript || rtcAssistantText;
        if (rtcAssistantDiv) {
          rtcAssistantDiv.innerHTML = renderMarkdown(finalText);
          addSqlInteractivity(rtcAssistantDiv);
        }
        conversationHistory.push({ role: 'assistant', content: finalText });
        rtcAssistantDiv = null;
        rtcAssistantText = '';
        messagesEl.scrollTop = messagesEl.scrollHeight;
        break;

      // Full response complete
      case 'response.done':
        saveSession();
        break;

      // Errors
      case 'error':
        console.error('Realtime API error:', event.error || event);
        break;

      default:
        // Log other events for debugging
        if (event.type && event.type.indexOf('session.') === 0) {
          console.log('Realtime session event:', event.type);
        }
        break;
    }
  }

  function disconnectRealtime() {
    if (rtcDataChannel) { try { rtcDataChannel.close(); } catch (e) {} }
    if (rtcPeer) { try { rtcPeer.close(); } catch (e) {} }
    if (rtcLocalStream) {
      rtcLocalStream.getTracks().forEach(function (t) { t.stop(); });
    }
    if (rtcAudioEl) {
      rtcAudioEl.srcObject = null;
      rtcAudioEl = null;
    }
    rtcPeer = null;
    rtcDataChannel = null;
    rtcLocalStream = null;
    rtcConnected = false;
    rtcMuted = false;
    voiceMode = false;
    rtcAssistantDiv = null;
    rtcAssistantText = '';
    micBtn.classList.remove('recording');
    var stopBtn = document.getElementById('chatStopVoice');
    if (stopBtn) stopBtn.classList.remove('visible');
    console.log('Realtime session disconnected');
  }

  // ── Intro flow ──
  function showIntro() {
    if (introShown) return;
    introShown = true;

    var introMsg = addMessage('assistant', 'Hi there! I\'m **Report Pal**, your friendly data analyst assistant. \n\n' +
      'I\'ve already analyzed this report and I\'m ready to help you understand the findings, explore discrepancies, review SQL queries, and more.\n\n' +
      'We can have this conversation via **text** or **voice**. What do you prefer?');
    conversationHistory.push({ role: 'assistant', content: 'Hi there! I\'m Report Pal, your friendly data analyst assistant. I\'ve already analyzed this report and I\'m ready to help. We can have this conversation via text or voice. What do you prefer?' });

    var bar = document.createElement('div');
    bar.className = 'chat-choice-bar';

    var textBtn = document.createElement('button');
    textBtn.className = 'chat-choice-btn';
    textBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> Text';
    textBtn.addEventListener('click', function () {
      bar.remove();
      addMessage('user', 'Text');
      conversationHistory.push({ role: 'user', content: 'Text' });
      var reply = addMessage('assistant', 'Great choice! Just type your question below and I\'ll give you an instant answer. You can also click the suggested questions above, or start typing to see autocomplete suggestions.\n\nWhat would you like to know about the report?');
      conversationHistory.push({ role: 'assistant', content: 'Text mode selected. Type your question below.' });
      saveSession();
    });

    var voiceBtn = document.createElement('button');
    voiceBtn.className = 'chat-choice-btn';
    voiceBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg> Voice';
    voiceBtn.addEventListener('click', function () {
      bar.remove();
      addMessage('user', 'Voice');
      conversationHistory.push({ role: 'user', content: 'Voice' });
      initVoiceMode();
    });

    bar.appendChild(textBtn);
    bar.appendChild(voiceBtn);
    introMsg.appendChild(bar);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    saveSession();
  }

  // ── Restore previous session or show intro ──
  var restored = restoreSession();
  if (!restored) showIntro();

  // ── Check if SQL Explorer should pre-fill a query ──
  if (window.location.pathname.indexOf('sql_explorer') !== -1) {
    var prefill = sessionStorage.getItem('cms_prefill_sql');
    if (prefill) {
      sessionStorage.removeItem('cms_prefill_sql');
      // Wait for SQL Explorer to initialize, then fill the query
      var attempts = 0;
      var fillInterval = setInterval(function () {
        var editor = document.getElementById('queryEditor');
        if (editor) {
          editor.value = prefill;
          clearInterval(fillInterval);
          // Try to trigger run
          var runBtn = document.getElementById('runBtn');
          if (runBtn && !runBtn.disabled) runBtn.click();
        }
        if (++attempts > 50) clearInterval(fillInterval);
      }, 100);
    }
  }

})();
