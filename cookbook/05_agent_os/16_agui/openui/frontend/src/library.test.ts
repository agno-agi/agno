import { createParser } from "@openuidev/lang-core";
import { describe, expect, it } from "vitest";

import { library, promptOptions } from "./library";

const chartWithFollowUps = `root = Card([title, chart, followups])
title = TextContent("Quarterly revenue", "large-heavy")
chart = BarChart(labels, [revenue], "grouped")
labels = ["Q1", "Q2", "Q3", "Q4"]
revenue = Series("Revenue", [120, 180, 150, 240])
followups = FollowUpBlock([fu1, fu2])
fu1 = FollowUpItem("Compare the first and second half")
fu2 = FollowUpItem("Show quarter-over-quarter growth")`;

const validatedForm = `root = Card([header, form])
header = CardHeader("Project Estimate", "All fields are required")
form = Form("project_estimate", buttons, [nameField, sizeField, notesField])
nameField = FormControl("Project Name", Input("project_name", "Enter project name", "text", { required: true }))
sizeField = FormControl("Team Size", Input("team_size", "Enter team size", "number", { required: true, numeric: true, min: 1 }))
notesField = FormControl("Notes", TextArea("notes", "Add notes", 4, { required: true }))
buttons = Buttons([submit])
submit = Button("Submit", Action([@ToAssistant("Submit project estimate form")]), "primary")`;

describe("Agno OpenUI component contract", () => {
  it("parses the chart and follow-up response without errors", () => {
    const result = createParser(library.toJSONSchema(), "Card").parse(chartWithFollowUps);

    expect(result.meta.errors).toEqual([]);
    expect(result.meta.unresolved).toEqual([]);
    expect(result.root).toMatchObject({ type: "element", typeName: "Card" });
  });

  it("adds interaction-specific rules to the standard chat prompt", () => {
    expect(promptOptions.additionalRules).toEqual(
      expect.arrayContaining([
        expect.stringContaining("FollowUpItem"),
        expect.stringContaining("@ToAssistant"),
      ]),
    );
  });

  it("parses required form controls and a submit action without errors", () => {
    const result = createParser(library.toJSONSchema(), "Card").parse(validatedForm);

    expect(result.meta.errors).toEqual([]);
    expect(result.meta.unresolved).toEqual([]);
    expect(result.root).toMatchObject({ type: "element", typeName: "Card" });
  });
});
