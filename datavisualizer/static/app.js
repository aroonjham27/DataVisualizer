(function () {
  const starterPrompts = [
    "What is win rate by close month and account segment?",
    "How do quoted discount rates and annualized quote amounts vary by product family and line role?",
    "Which competitors appear most often in lost enterprise opportunities, and how are they positioned on price?",
  ];

  const state = {
    messages: [],
    conversationState: null,
    isLoading: false,
  };

  const threadEl = document.getElementById("chat-thread");
  const formEl = document.getElementById("chat-form");
  const inputEl = document.getElementById("chat-input");
  const sendButtonEl = document.getElementById("send-button");
  const statusBannerEl = document.getElementById("status-banner");
  const starterEl = document.getElementById("starter-prompts");
  const emptyStateTemplate = document.getElementById("empty-state-template");

  function init() {
    renderStarterPrompts();
    render();
    formEl.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = inputEl.value.trim();
      if (!text) {
        return;
      }
      inputEl.value = "";
      await sendUserMessage(text);
    });
  }

  function renderStarterPrompts() {
    starterEl.innerHTML = "";
    starterPrompts.forEach((prompt) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "prompt-chip";
      button.textContent = prompt;
      button.addEventListener("click", () => {
        inputEl.value = prompt;
        inputEl.focus();
      });
      starterEl.appendChild(button);
    });
  }

  async function sendUserMessage(text, options = {}) {
    if (state.isLoading) {
      return;
    }
    hideStatus();
    state.messages.push({ role: "user", content: text });
    state.isLoading = true;
    render();
    try {
      const payload = {
        messages: state.messages.map((message) => ({
          role: message.role,
          content: message.content,
        })),
        conversation_state: state.conversationState,
      };
      if (options.selectedMember) {
        payload.selected_member = options.selectedMember;
      }
      const response = await fetch("/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      const envelope = await response.json();
      if (!response.ok || !envelope.ok) {
        const message = envelope.error && envelope.error.message ? envelope.error.message : "Chat request failed.";
        throw new Error(message);
      }
      state.conversationState = envelope.data.conversation_state;
      state.messages.push({
        role: "assistant",
        content: envelope.data.assistant_message,
        payload: envelope.data,
      });
    } catch (error) {
      state.messages.push({
        role: "assistant",
        content: "",
        error: error instanceof Error ? error.message : String(error),
      });
      showStatus(error instanceof Error ? error.message : String(error));
    } finally {
      state.isLoading = false;
      render();
    }
  }

  function render() {
    threadEl.innerHTML = "";
    if (state.messages.length === 0) {
      threadEl.appendChild(emptyStateTemplate.content.cloneNode(true));
    } else {
      state.messages.forEach((message) => threadEl.appendChild(renderMessage(message)));
    }
    if (state.isLoading) {
      threadEl.appendChild(renderLoadingCard());
    }
    inputEl.disabled = state.isLoading;
    sendButtonEl.disabled = state.isLoading;
    threadEl.scrollTop = threadEl.scrollHeight;
  }

  function renderMessage(message) {
    const card = document.createElement("article");
    card.className = `message-card ${message.role}`;

    const head = document.createElement("div");
    head.className = "message-head";
    const role = document.createElement("span");
    role.className = "message-role";
    role.textContent = message.role === "user" ? "You" : "Assistant";
    head.appendChild(role);
    card.appendChild(head);

    if (message.error) {
      const error = document.createElement("p");
      error.className = "message-copy";
      error.textContent = message.error;
      card.appendChild(error);
      return card;
    }

    const copy = document.createElement("p");
    copy.className = "message-copy";
    copy.textContent = message.content;
    card.appendChild(copy);

    if (message.role === "assistant" && message.payload && message.payload.tool_result && message.payload.tool_result.ok) {
      card.appendChild(renderAssistantPayload(message.payload));
    }
    return card;
  }

  function renderLoadingCard() {
    const card = document.createElement("article");
    card.className = "message-card assistant";
    const role = document.createElement("span");
    role.className = "message-role";
    role.textContent = "Assistant";
    card.appendChild(role);
    const copy = document.createElement("p");
    copy.className = "message-copy loading-copy";
    copy.textContent = "Thinking through the governed tool call...";
    card.appendChild(copy);
    return card;
  }

  function renderAssistantPayload(payload) {
    const wrapper = document.createElement("div");
    wrapper.className = "assistant-stack";

    const toolEnvelope = payload.tool_result;
    if (!toolEnvelope || !toolEnvelope.data) {
      return wrapper;
    }
    const data = toolEnvelope.data;

    const inspector = buildInspectorModel(payload, data);
    wrapper.appendChild(renderWarningSummary(inspector));

    const grid = document.createElement("div");
    grid.className = "assistant-grid";
    grid.appendChild(renderResultPanel(data));
    grid.appendChild(renderMetaPanel(payload, data));
    wrapper.appendChild(grid);
    wrapper.appendChild(renderInspector(inspector));

    return wrapper;
  }

  function renderResultPanel(data) {
    const panel = document.createElement("section");
    panel.className = "subpanel";

    const chartShell = document.createElement("div");
    chartShell.className = "chart-shell";
    const chartHeading = document.createElement("h3");
    chartHeading.textContent = data.chart_spec && data.chart_spec.title ? data.chart_spec.title : "Chart";
    chartShell.appendChild(chartHeading);

    const chartCopy = document.createElement("p");
    chartCopy.className = "chart-copy";
    const fallbackReasons = chartFallbackReasons(data);
    if (fallbackReasons.length > 0) {
      chartCopy.textContent = `Table view selected because ${fallbackReasons.join(" ")}`;
    } else if (data.chart_spec && data.chart_spec.chart_choice_explanation) {
      chartCopy.textContent = data.chart_spec.chart_choice_explanation;
    } else {
      chartCopy.textContent = data.plan && data.plan.drill && data.plan.drill.next_level
        ? "Click or double-click a chart mark to drill one level deeper."
        : "Rendered from the backend chart spec.";
    }
    chartShell.appendChild(chartCopy);

    chartShell.appendChild(renderChart(data));
    panel.appendChild(chartShell);

    const tableHeading = document.createElement("h3");
    tableHeading.textContent = "Result Table";
    panel.appendChild(tableHeading);
    panel.appendChild(renderTable(data));

    return panel;
  }

  function renderMetaPanel(payload, data) {
    const panel = document.createElement("section");
    panel.className = "subpanel";

    const heading = document.createElement("h3");
    heading.textContent = "Metadata";
    panel.appendChild(heading);

    const pills = document.createElement("div");
    pills.className = "metadata-list";
    [
      `Executed tool: ${payload.executed_tool_name || "unknown"}`,
      `Query mode: ${data.query_mode || "unknown"}`,
      `Chart: ${data.chart_spec ? data.chart_spec.chart_type : "unknown"}`,
      `Rows: ${data.limit ? data.limit.returned_rows : 0}/${data.limit ? data.limit.row_limit : 0}`,
      data.limit && data.limit.truncated ? "Truncated" : "Full result",
    ].forEach((text) => {
      const pill = document.createElement("div");
      pill.className = "metadata-pill";
      pill.textContent = text;
      pills.appendChild(pill);
    });
    panel.appendChild(pills);
    panel.appendChild(renderFilterSummary(data));

    if (data.plan && data.plan.drill && data.plan.drill.next_level) {
      const actions = document.createElement("div");
      actions.className = "action-row";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "action-button";
      button.textContent = `Go deeper to ${data.plan.drill.next_level}`;
      button.addEventListener("click", () => sendUserMessage("Go one level deeper"));
      actions.appendChild(button);
      panel.appendChild(actions);
    }

    return panel;
  }

  function renderChart(data) {
    const chartType = data.chart_spec ? data.chart_spec.chart_type : "table";
    if (!data.chart_spec || chartType === "table") {
      const fallback = document.createElement("div");
      fallback.className = "subpanel";
      fallback.textContent = "Table view selected by the backend chart contract.";
      return fallback;
    }
    if (chartType === "bar") {
      return renderBarChart(data);
    }
    if (chartType === "grouped_bar") {
      return renderGroupedBarChart(data);
    }
    if (chartType === "heatmap") {
      return renderHeatmap(data);
    }
    if (chartType === "line") {
      return renderLineChart(data);
    }
    const unsupported = document.createElement("div");
    unsupported.className = "subpanel";
    unsupported.textContent = `Unsupported chart type: ${chartType}`;
    return unsupported;
  }

  function renderBarChart(data) {
    const rows = rowObjects(data);
    const xField = data.chart_spec.x;
    const yField = data.chart_spec.y[0];
    const values = rows.map((row) => Number(row[yField]) || 0);
    const maxValue = Math.max(...values, 1);
    const width = 720;
    const height = 280;
    const margin = { top: 24, right: 20, bottom: 68, left: 56 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const band = plotWidth / Math.max(rows.length, 1);
    const barWidth = Math.max(18, band * 0.62);

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "chart-svg" });
    drawAxes(svg, width, height, margin, plotWidth, plotHeight);

    rows.forEach((row, index) => {
      const value = Number(row[yField]) || 0;
      const x = margin.left + index * band + (band - barWidth) / 2;
      const barHeight = plotHeight * (value / maxValue);
      const y = margin.top + (plotHeight - barHeight);
      const rect = svgEl("rect", {
        x,
        y,
        width: barWidth,
        height: barHeight,
        fill: "#0d6c63",
        rx: 6,
        class: "chart-target",
        tabindex: 0,
      });
      bindDrillTarget(rect, data, index);
      svg.appendChild(rect);

      const label = svgEl("text", {
        x: x + barWidth / 2,
        y: height - 24,
        "text-anchor": "middle",
        class: "axis-label",
      });
      label.textContent = truncateLabel(String(row[xField]), 12);
      svg.appendChild(label);
    });
    return svg;
  }

  function renderGroupedBarChart(data) {
    const rows = rowObjects(data);
    const xField = data.chart_spec.x;
    const seriesField = data.chart_spec.series;
    const measureFields = data.chart_spec.y || [];
    const entries = [];
    rows.forEach((row, rowIndex) => {
      measureFields.forEach((measureName, measureIndex) => {
        const seriesValue = seriesField ? row[seriesField] : null;
        const seriesKey = seriesValue ? `${seriesValue} / ${measureName}` : measureName;
        entries.push({
          category: row[xField],
          seriesKey,
          value: Number(row[measureName]) || 0,
          rowIndex,
          colorIndex: seriesField ? measureIndex + hashCode(String(seriesValue || "")) : measureIndex,
        });
      });
    });
    const categories = unique(entries.map((entry) => String(entry.category)));
    const seriesKeys = unique(entries.map((entry) => String(entry.seriesKey)));
    const maxValue = Math.max(...entries.map((entry) => entry.value), 1);

    const width = 720;
    const height = 300;
    const margin = { top: 24, right: 20, bottom: 72, left: 56 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const groupBand = plotWidth / Math.max(categories.length, 1);
    const innerBand = groupBand / Math.max(seriesKeys.length, 1);
    const barWidth = Math.max(12, innerBand * 0.68);

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "chart-svg" });
    drawAxes(svg, width, height, margin, plotWidth, plotHeight);

    entries.forEach((entry) => {
      const categoryIndex = categories.indexOf(String(entry.category));
      const seriesIndex = seriesKeys.indexOf(String(entry.seriesKey));
      const x = margin.left + categoryIndex * groupBand + seriesIndex * innerBand + (innerBand - barWidth) / 2;
      const barHeight = plotHeight * (entry.value / maxValue);
      const y = margin.top + (plotHeight - barHeight);
      const rect = svgEl("rect", {
        x,
        y,
        width: barWidth,
        height: barHeight,
        fill: palette(entry.colorIndex),
        rx: 5,
        class: "chart-target",
        tabindex: 0,
      });
      bindDrillTarget(rect, data, entry.rowIndex);
      svg.appendChild(rect);
    });

    categories.forEach((category, index) => {
      const label = svgEl("text", {
        x: margin.left + index * groupBand + groupBand / 2,
        y: height - 24,
        "text-anchor": "middle",
        class: "axis-label",
      });
      label.textContent = truncateLabel(category, 12);
      svg.appendChild(label);
    });

    return svg;
  }

  function renderHeatmap(data) {
    const rows = rowObjects(data);
    const xField = data.chart_spec.x;
    const yField = data.chart_spec.series;
    const measureField = data.chart_spec.y[0];
    const xValues = sortedUniqueValues(rows.map((row) => row[xField]));
    const yValues = sortedUniqueValues(rows.map((row) => row[yField]));
    const values = rows.map((row) => Number(row[measureField]) || 0);
    const maxValue = Math.max(...values, 1);
    const width = 720;
    const height = 320;
    const margin = { top: 24, right: 24, bottom: 72, left: 112 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const cellWidth = plotWidth / Math.max(xValues.length, 1);
    const cellHeight = plotHeight / Math.max(yValues.length, 1);

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "chart-svg" });
    const valueByCell = new Map();
    rows.forEach((row, rowIndex) => {
      valueByCell.set(`${row[xField]}|||${row[yField]}`, {
        value: Number(row[measureField]) || 0,
        rowIndex,
      });
    });

    yValues.forEach((yValue, yIndex) => {
      const label = svgEl("text", {
        x: margin.left - 10,
        y: margin.top + yIndex * cellHeight + cellHeight / 2 + 4,
        "text-anchor": "end",
        class: "axis-label",
      });
      label.textContent = truncateLabel(String(yValue), 18);
      svg.appendChild(label);
    });

    xValues.forEach((xValue, xIndex) => {
      const label = svgEl("text", {
        x: margin.left + xIndex * cellWidth + cellWidth / 2,
        y: height - 28,
        "text-anchor": "middle",
        class: "axis-label",
      });
      label.textContent = truncateLabel(String(xValue), 14);
      svg.appendChild(label);
    });

    yValues.forEach((yValue, yIndex) => {
      xValues.forEach((xValue, xIndex) => {
        const cell = valueByCell.get(`${xValue}|||${yValue}`) || { value: 0, rowIndex: -1 };
        const intensity = Math.max(0.12, Math.min(1, cell.value / maxValue));
        const rect = svgEl("rect", {
          x: margin.left + xIndex * cellWidth + 2,
          y: margin.top + yIndex * cellHeight + 2,
          width: Math.max(1, cellWidth - 4),
          height: Math.max(1, cellHeight - 4),
          fill: heatColor(intensity),
          rx: 4,
          class: cell.rowIndex >= 0 ? "chart-target" : "",
          tabindex: cell.rowIndex >= 0 ? 0 : -1,
        });
        if (cell.rowIndex >= 0) {
          bindDrillTarget(rect, data, cell.rowIndex);
        }
        svg.appendChild(rect);

        if (cellWidth > 46 && cellHeight > 24 && cell.value > 0) {
          const valueLabel = svgEl("text", {
            x: margin.left + xIndex * cellWidth + cellWidth / 2,
            y: margin.top + yIndex * cellHeight + cellHeight / 2 + 4,
            "text-anchor": "middle",
            class: "axis-label heatmap-value",
          });
          valueLabel.textContent = formatCompactNumber(cell.value);
          svg.appendChild(valueLabel);
        }
      });
    });
    return svg;
  }

  function renderLineChart(data) {
    const rows = rowObjects(data);
    const xField = data.chart_spec.x;
    const seriesField = data.chart_spec.series;
    const measureFields = data.chart_spec.y || [];
    const xValues = sortedUniqueValues(rows.map((row) => row[xField]));
    const rawLines = new Map();

    rows.forEach((row, rowIndex) => {
      measureFields.forEach((measureName, measureIndex) => {
        const seriesValue = seriesField ? row[seriesField] : null;
        const key = seriesValue ? `${seriesValue} / ${measureName}` : measureName;
        if (!rawLines.has(key)) {
          rawLines.set(key, {
            key,
            measureName,
            seriesValue,
            pointsByX: new Map(),
          });
        }
        rawLines.get(key).pointsByX.set(String(row[xField]), {
          x: row[xField],
          y: Number(row[measureName]) || 0,
          rowIndex,
          colorIndex: seriesField ? measureIndex + hashCode(String(seriesValue || "")) : measureIndex,
        });
      });
    });

    const lines = Array.from(rawLines.values()).map((line) => ({
      ...line,
      points: xValues
        .map((xValue) => line.pointsByX.get(String(xValue)))
        .filter(Boolean),
    })).filter((line) => line.points.length > 0);
    const flatPoints = lines.flatMap((line) => line.points);
    const maxValue = Math.max(...flatPoints.map((point) => point.y), 1);
    const width = 720;
    const height = 300;
    const margin = { top: 24, right: 20, bottom: 72, left: 56 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const pointCount = Math.max(xValues.length - 1, 1);
    const tickEvery = Math.max(1, Math.ceil(xValues.length / 6));

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "chart-svg" });
    drawAxes(svg, width, height, margin, plotWidth, plotHeight);

    lines.forEach((line, lineIndex) => {
      const pathPoints = line.points.map((point) => {
        const xIndex = xValues.findIndex((value) => String(value) === String(point.x));
        const x = margin.left + (plotWidth * (Math.max(xIndex, 0) / pointCount));
        const y = margin.top + (plotHeight - (plotHeight * (point.y / maxValue)));
        return { x, y, rowIndex: point.rowIndex };
      });
      const path = svgEl("path", {
        d: pathPoints.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" "),
        fill: "none",
        stroke: palette(lineIndex),
        "stroke-width": 3,
      });
      svg.appendChild(path);

      pathPoints.forEach((point) => {
        const circle = svgEl("circle", {
          cx: point.x,
          cy: point.y,
          r: 5,
          fill: "#fff",
          stroke: palette(lineIndex),
          "stroke-width": 2,
          class: "chart-target",
          tabindex: 0,
        });
        bindDrillTarget(circle, data, point.rowIndex);
        svg.appendChild(circle);
      });

      if (lines.length > 1) {
        const legend = svgEl("text", {
          x: width - 18,
          y: margin.top + 18 + lineIndex * 16,
          "text-anchor": "end",
          class: "axis-label",
        });
        legend.textContent = truncateLabel(line.key, 24);
        svg.appendChild(legend);
      }
    });

    xValues.forEach((xValue, index) => {
      if (index % tickEvery !== 0 && index !== xValues.length - 1) {
        return;
      }
      const label = svgEl("text", {
        x: margin.left + (plotWidth * (index / pointCount)),
        y: height - 24,
        "text-anchor": "middle",
        class: "axis-label",
      });
      label.textContent = formatMonthLabel(xValue);
      svg.appendChild(label);
    });

    return svg;
  }

  function renderFilterSummary(data) {
    const filters = data.plan && Array.isArray(data.plan.filters) ? data.plan.filters : [];
    const section = document.createElement("div");
    section.className = "filter-summary";
    if (filters.length === 0) {
      return section;
    }
    const heading = document.createElement("h4");
    heading.textContent = "Active Filters";
    section.appendChild(heading);
    const list = document.createElement("div");
    list.className = "metadata-list";
    filters.forEach((filter) => {
      const pill = document.createElement("div");
      pill.className = "metadata-pill";
      pill.textContent = formatFilter(filter);
      list.appendChild(pill);
    });
    section.appendChild(list);
    return section;
  }

  function formatFilter(filter) {
    const label = filter.field && filter.field.label ? filter.field.label : "Filter";
    const operator = filter.operator === "=" ? "=" : String(filter.operator || "").toUpperCase();
    const value = Array.isArray(filter.value) ? filter.value.join(", ") : filter.value;
    return `${label} ${operator} ${value}`;
  }

  function buildInspectorModel(payload, data) {
    const queryMetadata = data.query_metadata || {};
    const routing = data.routing || {};
    const limit = data.limit || {};
    const chartSpec = data.chart_spec || {};
    return {
      executedTool: payload.executed_tool_name || data.tool_name || "unknown",
      queryMode: data.query_mode || "unknown",
      routingPolicy: routing.policy || "not provided",
      sql: data.sql || "",
      fallbackReason: data.fallback_reason || "",
      sourceResultTool: data.source_result_tool || "",
      sourceQueryMode: data.source_query_mode || "",
      visualizationFollowUp: Boolean(data.visualization_follow_up),
      noNewSqlExecuted: Boolean(data.no_new_sql_executed),
      chartOverrideRequested: data.chart_override_requested || "",
      filters: (data.plan && Array.isArray(data.plan.filters)) ? data.plan.filters.map(filterSummary) : [],
      involvedEntities: Array.isArray(queryMetadata.involved_entities) ? queryMetadata.involved_entities : [],
      rowLimit: limit.row_limit,
      returnedRows: limit.returned_rows,
      truncated: Boolean(limit.truncated),
      chartType: chartSpec.chart_type || "none",
      chartTitle: chartSpec.title || "",
      chartChoiceExplanation: chartSpec.chart_choice_explanation || "",
      fallbackReasons: chartFallbackReasons(data),
      plan: data.plan ? planSummary(data.plan) : null,
      warningGroups: warningGroups(data),
    };
  }

  function renderWarningSummary(inspector) {
    const groups = inspector.warningGroups;
    const hasWarnings = Object.values(groups).some((items) => items.length > 0);
    const wrapper = document.createElement("section");
    wrapper.className = "subpanel notice-panel";
    if (!hasWarnings) {
      wrapper.hidden = true;
      return wrapper;
    }
    const heading = document.createElement("h3");
    heading.textContent = "Warnings And Notes";
    wrapper.appendChild(heading);
    [
      ["Plan warnings", groups.plan],
      ["Chart warnings", groups.chart],
      ["Fallback explanations", groups.fallback],
      ["Routing notes", groups.routing],
      ["Query notes", groups.query],
    ].forEach(([label, items]) => {
      if (!items.length) {
        return;
      }
      const group = document.createElement("div");
      group.className = "notice-group";
      const title = document.createElement("h4");
      title.textContent = label;
      group.appendChild(title);
      const list = document.createElement("div");
      list.className = "warning-list";
      items.forEach((item) => {
        const pill = document.createElement("div");
        pill.className = "warning-pill";
        pill.textContent = item.message || item;
        if (item.code) {
          pill.title = `${item.source}:${item.code}`;
        }
        list.appendChild(pill);
      });
      group.appendChild(list);
      wrapper.appendChild(group);
    });
    return wrapper;
  }

  function renderInspector(inspector) {
    const details = document.createElement("details");
    details.className = "subpanel inspector";
    const summary = document.createElement("summary");
    summary.textContent = "What did the system do?";
    details.appendChild(summary);

    const pills = document.createElement("div");
    pills.className = "metadata-list inspector-pills";
    [
      `Tool: ${inspector.executedTool}`,
      `Query mode: ${inspector.queryMode}`,
      `Routing: ${inspector.routingPolicy}`,
      `Chart: ${inspector.chartType}`,
      `Rows: ${inspector.returnedRows || 0}/${inspector.rowLimit || 0}`,
      inspector.truncated ? "Truncated" : "Full result",
      inspector.visualizationFollowUp ? "Reused prior result" : "",
      inspector.noNewSqlExecuted ? "No new SQL" : "",
    ].forEach((text) => {
      if (!text) {
        return;
      }
      const pill = document.createElement("div");
      pill.className = "metadata-pill";
      pill.textContent = text;
      pills.appendChild(pill);
    });
    details.appendChild(pills);

    if (inspector.filters.length > 0) {
      details.appendChild(renderInspectorSection("Applied Filters", inspector.filters.map((filter) => filter.text)));
    }
    if (inspector.involvedEntities.length > 0) {
      details.appendChild(renderInspectorSection("Involved Entities", inspector.involvedEntities));
    }
    if (inspector.fallbackReasons.length > 0) {
      details.appendChild(renderInspectorSection("Chart Fallback", inspector.fallbackReasons));
    }
    if (inspector.chartChoiceExplanation) {
      details.appendChild(renderInspectorSection("Chart Choice", [inspector.chartChoiceExplanation]));
    }
    if (inspector.fallbackReason) {
      details.appendChild(renderInspectorSection("Fallback Reason", [inspector.fallbackReason]));
    }
    if (inspector.visualizationFollowUp) {
      const reuseDetails = [
        `Source result tool: ${inspector.sourceResultTool || "unknown"}`,
        `Source query mode: ${inspector.sourceQueryMode || inspector.queryMode}`,
        `No new SQL executed: ${inspector.noNewSqlExecuted ? "true" : "false"}`,
      ];
      if (inspector.chartOverrideRequested) {
        reuseDetails.push(`Chart override requested: ${inspector.chartOverrideRequested}`);
      }
      details.appendChild(renderInspectorSection("Reused Result", reuseDetails));
    }
    if (inspector.plan) {
      details.appendChild(renderPlanSummary(inspector.plan));
    }
    if (inspector.sql) {
      const sqlSection = document.createElement("section");
      sqlSection.className = "inspector-section";
      const heading = document.createElement("h4");
      heading.textContent = "SQL Executed";
      sqlSection.appendChild(heading);
      const pre = document.createElement("pre");
      pre.className = "sql-block";
      pre.textContent = inspector.sql;
      sqlSection.appendChild(pre);
      details.appendChild(sqlSection);
    }
    return details;
  }

  function renderInspectorSection(title, values) {
    const section = document.createElement("section");
    section.className = "inspector-section";
    const heading = document.createElement("h4");
    heading.textContent = title;
    section.appendChild(heading);
    const list = document.createElement("ul");
    list.className = "inspector-list";
    values.forEach((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      list.appendChild(item);
    });
    section.appendChild(list);
    return section;
  }

  function renderPlanSummary(plan) {
    const section = document.createElement("section");
    section.className = "inspector-section";
    const heading = document.createElement("h4");
    heading.textContent = "Analysis Plan";
    section.appendChild(heading);
    const rows = [
      ["Question", plan.question],
      ["Status", plan.status],
      ["Primary entity", plan.primaryEntity],
      ["Measures", plan.measures.join(", ")],
      ["Dimensions", plan.dimensions.join(", ") || "none"],
      ["Time", plan.timeDimension ? `${plan.timeDimension} (${plan.timeGrain || "day"})` : "none"],
    ];
    const dl = document.createElement("dl");
    dl.className = "inspector-definition-list";
    rows.forEach(([label, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value || "none";
      dl.appendChild(dt);
      dl.appendChild(dd);
    });
    section.appendChild(dl);
    return section;
  }

  function warningGroups(data) {
    const groups = {
      plan: [],
      chart: [],
      fallback: [],
      routing: [],
      query: [],
    };
    (data.warnings || []).forEach((warning) => {
      const item = {
        code: warning.code || "",
        source: warning.source || "query",
        message: businessWarningText(warning),
      };
      if (item.source === "plan") {
        groups.plan.push(item);
      } else if (item.source === "chart") {
        groups.chart.push(item);
      } else {
        groups.query.push(item);
      }
    });
    chartFallbackReasons(data).forEach((reason) => groups.fallback.push(reason));
    const notes = data.query_metadata && Array.isArray(data.query_metadata.validation_notes)
      ? data.query_metadata.validation_notes
      : [];
    notes.forEach((note) => {
      if (String(note).startsWith("Active filter:")) {
        return;
      }
      if (String(note).toLowerCase().includes("routing") || String(note).toLowerCase().includes("restricted sql was allowed")) {
        groups.routing.push(note);
      } else {
        groups.query.push({ code: "", source: "query", message: note });
      }
    });
    return groups;
  }

  function businessWarningText(warning) {
    const message = warning.message || "";
    if (warning.source === "chart") {
      return `Chart note: ${message}`;
    }
    if (warning.source === "plan") {
      return `Plan note: ${message}`;
    }
    return message;
  }

  function chartFallbackReasons(data) {
    const chartSpec = data.chart_spec || {};
    if (chartSpec.chart_type !== "table" || !Array.isArray(chartSpec.warnings)) {
      return [];
    }
    return chartSpec.warnings;
  }

  function planSummary(plan) {
    return {
      question: plan.question || "",
      status: plan.status || "",
      primaryEntity: plan.primary_entity || "",
      measures: (plan.measures || []).map((measure) => fieldId(measure.field)),
      dimensions: (plan.dimensions || []).map(fieldId),
      timeDimension: plan.time_dimension ? fieldId(plan.time_dimension) : "",
      timeGrain: plan.time_grain || "",
    };
  }

  function filterSummary(filter) {
    return {
      text: formatFilter(filter),
      fieldId: fieldId(filter.field),
      source: filter.source || "question",
    };
  }

  function fieldId(field) {
    if (!field) {
      return "";
    }
    return field.entity && field.name ? `${field.entity}.${field.name}` : "";
  }

  function renderTable(data) {
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    (data.columns || []).forEach((column) => {
      const th = document.createElement("th");
      th.textContent = column.label || column.name;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    rowObjects(data).forEach((record) => {
      const tr = document.createElement("tr");
      (data.columns || []).forEach((column) => {
        const td = document.createElement("td");
        const value = record[column.name];
        td.textContent = value === null || value === undefined ? "—" : String(value);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function rowObjects(data) {
    return (data.rows || []).map((row) => {
      const record = {};
      (data.columns || []).forEach((column, index) => {
        record[column.name] = row[index];
      });
      return record;
    });
  }

  function buildSelectedMember(data, rowIndex) {
    const byName = new Map((data.columns || []).map((column) => [column.name, column]));
    const xColumn = data.chart_spec && data.chart_spec.x ? byName.get(data.chart_spec.x) : null;
    const seriesColumn = data.chart_spec && data.chart_spec.series ? byName.get(data.chart_spec.series) : null;
    let drillColumn = null;
    if (xColumn && xColumn.role === "dimension") {
      drillColumn = xColumn;
    } else if (seriesColumn && seriesColumn.role === "dimension") {
      drillColumn = seriesColumn;
    } else if (xColumn) {
      drillColumn = xColumn;
    } else if (seriesColumn) {
      drillColumn = seriesColumn;
    }
    if (!drillColumn) {
      return null;
    }
    const record = rowObjects(data)[rowIndex];
    const value = record ? record[drillColumn.name] : null;
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const lineage = Array.isArray(drillColumn.semantic_lineage) && drillColumn.semantic_lineage.length > 0
      ? drillColumn.semantic_lineage[0]
      : drillColumn.name;
    const parts = String(lineage).split(".");
    const entity = parts[0] || "unknown";
    const name = parts[1] || drillColumn.name;
    return {
      field: {
        entity,
        name,
        label: drillColumn.label || drillColumn.name,
        kind: drillColumn.role === "time" ? "time_dimension" : drillColumn.role,
      },
      values: [value],
      source: "visual_member",
    };
  }

  function bindDrillTarget(element, data, rowIndex) {
    const drill = () => {
      const selectedMember = buildSelectedMember(data, rowIndex);
      if (!selectedMember) {
        return;
      }
      sendUserMessage("Go one level deeper", { selectedMember });
    };
    element.addEventListener("click", drill);
    element.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        drill();
      }
    });
  }

  function drawAxes(svg, width, height, margin, plotWidth, plotHeight) {
    svg.appendChild(svgEl("line", {
      x1: margin.left,
      y1: margin.top + plotHeight,
      x2: margin.left + plotWidth,
      y2: margin.top + plotHeight,
      stroke: "#b8ab98",
      "stroke-width": 1,
    }));
    svg.appendChild(svgEl("line", {
      x1: margin.left,
      y1: margin.top,
      x2: margin.left,
      y2: margin.top + plotHeight,
      stroke: "#b8ab98",
      "stroke-width": 1,
    }));
    const title = svgEl("text", {
      x: width / 2,
      y: 16,
      "text-anchor": "middle",
      class: "axis-label",
    });
    title.textContent = "Governed chart view";
    svg.appendChild(title);
  }

  function svgEl(name, attributes) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attributes).forEach(([key, value]) => {
      element.setAttribute(key, String(value));
    });
    return element;
  }

  function unique(values) {
    return Array.from(new Set(values));
  }

  function sortedUniqueValues(values) {
    return unique(values.filter((value) => value !== null && value !== undefined && value !== "")).sort((left, right) => {
      const leftTime = Date.parse(left);
      const rightTime = Date.parse(right);
      if (!Number.isNaN(leftTime) && !Number.isNaN(rightTime)) {
        return leftTime - rightTime;
      }
      return String(left).localeCompare(String(right));
    });
  }

  function formatMonthLabel(value) {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toLocaleDateString(undefined, { month: "short", year: "numeric", timeZone: "UTC" });
    }
    return truncateLabel(String(value), 12);
  }

  function truncateLabel(value, maxLength) {
    return value.length > maxLength ? `${value.slice(0, maxLength - 1)}…` : value;
  }

  function palette(index) {
    const colors = ["#0d6c63", "#ba5f06", "#5a6fd4", "#a03d7b", "#3d7d35", "#7c4d2f"];
    return colors[Math.abs(index) % colors.length];
  }

  function heatColor(intensity) {
    const start = [232, 244, 241];
    const end = [13, 108, 99];
    const rgb = start.map((channel, index) => Math.round(channel + ((end[index] - channel) * intensity)));
    return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
  }

  function formatCompactNumber(value) {
    return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
  }

  function hashCode(value) {
    let hash = 0;
    for (let index = 0; index < value.length; index += 1) {
      hash = ((hash << 5) - hash) + value.charCodeAt(index);
      hash |= 0;
    }
    return hash;
  }

  function showStatus(message) {
    statusBannerEl.hidden = false;
    statusBannerEl.textContent = message;
  }

  function hideStatus() {
    statusBannerEl.hidden = true;
    statusBannerEl.textContent = "";
  }

  init();
})();
