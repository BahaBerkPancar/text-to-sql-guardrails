"use strict";

const normalExamples = [
  {
    label: "Products and prices",
    sql: "SELECT id, name, category, price FROM products ORDER BY id",
  },
  {
    label: "Customer locations",
    sql: "SELECT id, name, city, country FROM customers WHERE id <= 25 ORDER BY id",
  },
  {
    label: "Orders by status",
    sql: "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY status",
  },
  {
    label: "Order customer names",
    sql: "SELECT o.id, c.name, o.status, o.total FROM orders AS o JOIN customers AS c ON c.id = o.customer_id WHERE o.id <= 50 ORDER BY o.id",
  },
];

const attackExamples = [
  { label: "Denied column", sql: "SELECT email FROM customers" },
  {
    label: "Whole-row ORDER BY",
    sql: "SELECT id AS c FROM customers AS c ORDER BY c",
  },
  { label: "Stacked DROP", sql: "SELECT 1; DROP TABLE orders" },
  { label: "pg_sleep", sql: "SELECT pg_sleep(5)" },
  { label: "System catalog", sql: "SELECT * FROM pg_catalog.pg_user" },
  {
    label: "Modifying CTE",
    sql: "WITH removed AS (DELETE FROM orders RETURNING id) SELECT * FROM removed",
  },
];

const elements = {
  askTab: document.querySelector("#ask-tab"),
  sqlTab: document.querySelector("#sql-tab"),
  askPanel: document.querySelector("#ask-panel"),
  sqlPanel: document.querySelector("#sql-panel"),
  askForm: document.querySelector("#ask-form"),
  sqlForm: document.querySelector("#sql-form"),
  question: document.querySelector("#question"),
  sql: document.querySelector("#sql"),
  result: document.querySelector("#result"),
  requestState: document.querySelector("#request-state"),
  modelNotice: document.querySelector("#model-notice"),
  modelFallback: document.querySelector("#model-fallback"),
  schema: document.querySelector("#schema"),
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = String(text);
  }
  return element;
}

function setMode(mode) {
  const isAsk = mode === "ask";
  elements.askTab.setAttribute("aria-selected", String(isAsk));
  elements.sqlTab.setAttribute("aria-selected", String(!isAsk));
  elements.askPanel.hidden = !isAsk;
  elements.sqlPanel.hidden = isAsk;
}

function fillAndRun(sql) {
  setMode("sql");
  elements.sql.value = sql;
  elements.sqlForm.requestSubmit();
}

function renderExampleButtons(containerId, examples) {
  const container = document.querySelector(containerId);
  const buttons = examples.map((example) => {
    const button = node("button", "example-button", example.label);
    button.type = "button";
    button.title = example.sql;
    button.addEventListener("click", () => fillAndRun(example.sql));
    return button;
  });
  container.replaceChildren(...buttons);
}

function renderLoading() {
  elements.requestState.textContent = "Running";
  elements.result.replaceChildren(node("p", "empty-state", "Validating and executing…"));
}

function focusResultForCapture() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  if (params.get("capture") === "1") {
    window.requestAnimationFrame(() => {
      document.body.classList.add("capture-mode");
      window.scrollTo(0, 0);
    });
  }
}

function renderRequestError(message) {
  const card = node("div", "blocked-card");
  card.append(
    node("p", "status-label", "Request failed"),
    node("h3", null, "The server could not complete the request"),
    node("p", null, message),
  );
  elements.requestState.textContent = "Error";
  elements.result.replaceChildren(card);
  focusResultForCapture();
}

function renderBlocked(data) {
  const stage = data.stage || "unknown";
  const card = node("div", "blocked-card");
  card.append(
    node("p", "status-label", `Blocked at ${stage}`),
    node("h3", null, "Query stopped safely"),
  );

  const violations = Array.isArray(data.violations)
    ? data.violations
    : data.error
      ? [data.error]
      : [];
  const list = node("ul", "violation-list");
  if (violations.length === 0) {
    list.append(node("li", null, "UNKNOWN: No diagnostic was returned."));
  } else {
    for (const violation of violations) {
      const item = node("li");
      item.append(
        node("code", null, violation.code || "UNKNOWN"),
        document.createTextNode(` — ${violation.message || "No message returned."}`),
      );
      list.append(item);
    }
  }
  card.append(list);
  elements.requestState.textContent = "Blocked";
  elements.result.replaceChildren(card);
  focusResultForCapture();
}

function displayValue(value) {
  if (value === null) {
    return "NULL";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function renderSuccess(data) {
  const fragment = document.createDocumentFragment();
  const meta = node("div", "result-meta");
  meta.append(
    node("span", null, `${data.row_count} row${data.row_count === 1 ? "" : "s"}`),
    node("span", null, `${data.elapsed_ms} ms`),
    node("span", data.truncated ? "warning" : null, data.truncated ? "Truncated at row cap" : "Complete result"),
  );
  fragment.append(meta, node("p", "sql-label", "Rewritten SQL that ran"));
  fragment.append(node("pre", "executed-sql", data.sql));

  const wrapper = node("div", "table-scroll");
  const table = node("table");
  const head = node("thead");
  const headerRow = node("tr");
  for (const column of data.columns || []) {
    headerRow.append(node("th", null, column));
  }
  head.append(headerRow);
  const body = node("tbody");
  for (const row of data.rows || []) {
    const tableRow = node("tr");
    for (const value of row) {
      tableRow.append(node("td", value === null ? "null-value" : null, displayValue(value)));
    }
    body.append(tableRow);
  }
  table.append(head, body);
  wrapper.append(table);
  fragment.append(wrapper);

  elements.requestState.textContent = "Allowed";
  elements.result.replaceChildren(fragment);
  focusResultForCapture();
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data;
  try {
    data = await response.json();
  } catch (_error) {
    throw new Error(`Server returned HTTP ${response.status} without JSON.`);
  }
  return { response, data };
}

async function run(path, body) {
  renderLoading();
  elements.modelNotice.hidden = true;
  try {
    const { response, data } = await postJson(path, body);
    if (response.status === 503 && data.error?.code === "LLM_NOT_CONFIGURED") {
      elements.modelNotice.hidden = false;
      renderBlocked(data);
      return;
    }
    if (!response.ok && response.status === 422) {
      renderRequestError("Check the input length and try again.");
      return;
    }
    if (!response.ok && data.ok !== false) {
      renderRequestError(`Server returned HTTP ${response.status}.`);
      return;
    }
    if (data.ok) {
      renderSuccess(data);
    } else {
      renderBlocked(data);
    }
  } catch (_error) {
    renderRequestError("The API is unavailable. Confirm the server is running and try again.");
  }
}

async function loadSchema() {
  try {
    const response = await fetch("/schema");
    if (!response.ok) {
      throw new Error("schema request failed");
    }
    const data = await response.json();
    const grid = node("div", "schema-grid");
    for (const [tableName, columns] of Object.entries(data.tables || {})) {
      const card = node("section", "schema-table");
      card.append(node("h3", null, tableName), node("code", null, columns.join(", ")));
      grid.append(card);
    }
    elements.schema.replaceChildren(grid);
  } catch (_error) {
    elements.schema.replaceChildren(node("p", "muted", "Schema is unavailable."));
  }
}

function runFromHash() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const sql = params.get("sql");
  if (params.get("capture") === "1") {
    document.body.classList.add("capture-mode");
  }
  if (sql) {
    setMode("sql");
    elements.sql.value = sql;
    if (params.get("run") === "1") {
      elements.sqlForm.requestSubmit();
    }
  }
}

elements.askTab.addEventListener("click", () => setMode("ask"));
elements.sqlTab.addEventListener("click", () => setMode("sql"));
elements.askForm.addEventListener("submit", (event) => {
  event.preventDefault();
  run("/ask", { question: elements.question.value });
});
elements.sqlForm.addEventListener("submit", (event) => {
  event.preventDefault();
  run("/query", { sql: elements.sql.value });
});
elements.modelFallback.addEventListener("click", () => fillAndRun(normalExamples[2].sql));

renderExampleButtons("#normal-examples", normalExamples);
renderExampleButtons("#attack-examples", attackExamples);
loadSchema();
runFromHash();
