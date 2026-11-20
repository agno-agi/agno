# Twelve sample evaluation suites

Use the Math Tutor agent (`math-tutor`) on the local suite backend and `suite-db`. Suites 1-9 have two cases each; suites 10-12 have three each (27 cases total). Suites 10-12 are intentionally negative suites for testing failure displays; these are expected outcomes, not guarantees of model behavior.

In **Evaluations > Suites > New Suite**, enter a suite name, then add the cases below. The **Input** is the prompt; the **Case name** is just its label. Choose Math Tutor for every case. Leave any omitted checks blank. Use a 90-second timeout.

The JSON bundle is `suite_api_samples.json`. POST each entry’s `payload` object, not the full bundle, to `/eval-suites?db_id=suite-db`. The runner below does this for you.

```bash
.venv/bin/python cookbook/09_evals/suite/suite_api_samples.py --list
.venv/bin/python cookbook/09_evals/suite/suite_api_samples.py --url http://localhost:7780 --suite 1
# Execute all 12 suites and save their results:
.venv/bin/python cookbook/09_evals/suite/suite_api_samples.py --url http://localhost:7780
```

Running the loader makes live model calls and adds suite runs to the UI. Repeating it creates additional runs. The last three suites are expected to show FAIL.

## 01 - Basic arithmetic

Binary judge and tool checks.

Expected suite status: **PASS**.

### addition

**Input:** Use the add tool to calculate 17 + 25. State the result.

- Expected tool calls: add
- Allow additional tool calls: Yes
- Judge criteria: States that 17 + 25 equals 42.
- Judge mode: Binary (if criteria are configured)

### subtraction

**Input:** Use the subtract tool to calculate 100 - 37. State the result.

- Expected tool calls: subtract
- Allow additional tool calls: Yes
- Judge criteria: States that 100 - 37 equals 63.
- Judge mode: Binary (if criteria are configured)

## 02 - Multiplication and division

Strict tool-only checks; no judge calls.

Expected suite status: **PASS**.

### multiply

**Input:** Use only the multiply tool to calculate 12 times 8.

- Expected tool calls: multiply
- Allow additional tool calls: No
- Judge criteria: Leave blank
- Judge mode: Binary (if criteria are configured)

### divide

**Input:** Use only the divide tool to calculate 144 divided by 12.

- Expected tool calls: divide
- Allow additional tool calls: No
- Judge criteria: Leave blank
- Judge mode: Binary (if criteria are configured)

## 03 - Decimals and negatives

Correctness checks for less trivial numeric inputs.

Expected suite status: **PASS**.

### decimal_sum

**Input:** Use the add tool to calculate 7.5 + 2.25.

- Expected tool calls: add
- Allow additional tool calls: Yes
- Judge criteria: States that the result is 9.75.
- Judge mode: Binary (if criteria are configured)

### negative_sum

**Input:** Use the add tool to calculate -8 + 3.

- Expected tool calls: add
- Allow additional tool calls: Yes
- Judge criteria: States that the result is -5.
- Judge mode: Binary (if criteria are configured)

## 04 - Powers and roots

Two numeric judge scores plus tool checks.

Expected suite status: **PASS**.

### power

**Input:** Use exponentiate to calculate 2 to the power of 10. Briefly explain the result.

- Expected tool calls: exponentiate
- Allow additional tool calls: Yes
- Judge criteria: Gives 1024 as the result and clearly explains that 2 is raised to the tenth power.
- Judge mode: Numeric, passing score 8

### root

**Input:** Use square_root to calculate the square root of 81. Briefly explain the result.

- Expected tool calls: square_root
- Allow additional tool calls: Yes
- Judge criteria: Gives the principal square root as 9 and explains that 9 squared equals 81.
- Judge mode: Numeric, passing score 8

## 05 - Number theory boundaries

Factorial and prime boundary values.

Expected suite status: **PASS**.

### zero_factorial

**Input:** Use the factorial tool to calculate 0 factorial.

- Expected tool calls: factorial
- Allow additional tool calls: Yes
- Judge criteria: Correctly states that 0 factorial equals 1.
- Judge mode: Binary (if criteria are configured)

### one_not_prime

**Input:** Call is_prime with n=1 and explain the result.

- Expected tool calls: is_prime
- Allow additional tool calls: Yes
- Judge criteria: Correctly states that 1 is not prime because it has only one positive divisor.
- Judge mode: Binary (if criteria are configured)

## 06 - Multiple tool calls

Each case requires more than one calculator tool.

Expected suite status: **PASS**.

### sum_then_multiply

**Input:** Use add to calculate 2 + 3, then multiply that result by 4 using multiply. State the final result.

- Expected tool calls: add, multiply
- Allow additional tool calls: Yes
- Judge criteria: States that (2 + 3) times 4 equals 20.
- Judge mode: Binary (if criteria are configured)

### average

**Input:** Use add to sum 10 and 20, then use divide to divide the sum by 2. State the average.

- Expected tool calls: add, divide
- Allow additional tool calls: Yes
- Judge criteria: States that the average of 10 and 20 is 15.
- Judge mode: Binary (if criteria are configured)

## 07 - Percentages

Everyday percentage calculations with combined checks.

Expected suite status: **PASS**.

### percentage

**Input:** Use multiply to calculate 20 percent of 200, by multiplying 200 by 0.2.

- Expected tool calls: multiply
- Allow additional tool calls: Yes
- Judge criteria: States that 20 percent of 200 is 40.
- Judge mode: Binary (if criteria are configured)

### tip

**Input:** Use multiply to calculate a 12.5 percent tip on 80, by multiplying 80 by 0.125.

- Expected tool calls: multiply
- Allow additional tool calls: Yes
- Judge criteria: States that the tip is 10.
- Judge mode: Binary (if criteria are configured)

## 08 - Binary explanations

Judge-only cases; expected tool calls should be left blank.

Expected suite status: **PASS**.

### prime_definition

**Input:** In two sentences explain what a prime number is. No calculations are needed.

- Expected tool calls: Leave blank
- Allow additional tool calls: Yes
- Judge criteria: Explains that a prime is an integer greater than 1 with exactly two distinct positive divisors, 1 and itself.
- Judge mode: Binary (if criteria are configured)

### zero_division

**Input:** Explain why dividing by zero is undefined. Do not use a numeric example or calculator.

- Expected tool calls: Leave blank
- Allow additional tool calls: Yes
- Judge criteria: Explains that division by zero is undefined and does not present infinity as its arithmetic result.
- Judge mode: Binary (if criteria are configured)

## 09 - Numeric explanations

Judge-only cases with a passing score of 8/10.

Expected suite status: **PASS**.

### fraction_definition

**Input:** Explain numerator and denominator in two short sentences, without numerical examples.

- Expected tool calls: Leave blank
- Allow additional tool calls: Yes
- Judge criteria: Clearly distinguishes the numerator as the count of selected equal parts and the denominator as the number of equal parts in a whole.
- Judge mode: Numeric, passing score 8

### area_vs_perimeter

**Input:** In two sentences explain the difference between area and perimeter. No calculations are needed.

- Expected tool calls: Leave blank
- Allow additional tool calls: Yes
- Judge criteria: Clearly describes area as the amount of surface inside a shape and perimeter as the length around its boundary.
- Judge mode: Numeric, passing score 8

## 10 - Intentional tool failure

One positive control, one wrong tool expectation, and one missing required tool.

Expected suite status: **FAIL**.

### control

**Input:** Use only add to calculate 2 + 2.

- Expected tool calls: add
- Allow additional tool calls: No
- Judge criteria: Leave blank
- Judge mode: Binary (if criteria are configured)

### wrong_tool_expectation

**Input:** Use only add to calculate 2 + 2. Do not call subtract.

- Expected tool calls: subtract
- Allow additional tool calls: No
- Judge criteria: Leave blank
- Judge mode: Binary (if criteria are configured)

### missing_second_tool

**Input:** Use only add to calculate 6 + 4. Do not call multiply.

- Expected tool calls: add, multiply
- Allow additional tool calls: Yes
- Judge criteria: Leave blank
- Expected outcome: FAIL because the required multiply call is missing.

## 11 - Intentional judge failure

One positive control, one binary judge failure, and one numeric score below the passing threshold.

Expected suite status: **FAIL**.

### control

**Input:** Use add to calculate 2 + 2 and state the result.

- Expected tool calls: add
- Allow additional tool calls: Yes
- Judge criteria: Correctly states that 2 + 2 equals 4.
- Judge mode: Binary (if criteria are configured)

### wrong_answer_expectation

**Input:** Use add to calculate 2 + 2. State only the actual result returned by the tool.

- Expected tool calls: add
- Allow additional tool calls: Yes
- Judge criteria: The response explicitly states that the result of 2 + 2 is 5.
- Judge mode: Binary (if criteria are configured)

### numeric_score_below_threshold

**Input:** Use multiply to calculate 3 times 3. State only the actual result returned by the tool.

- Expected tool calls: multiply
- Allow additional tool calls: Yes
- Judge criteria: The response explicitly states that 3 times 3 equals 12. Score 1 if it instead gives 9; score 10 only if it explicitly gives 12.
- Judge mode: Numeric, passing score 8
- Expected outcome: FAIL with a low judge score despite passing the tool check.

## 12 - Intentional strict-tool failure

The same two-tool task passes with extra tools allowed and fails when only add is permitted.

Expected suite status: **FAIL**.

### additional_tools_allowed

**Input:** Call add to calculate 2 + 3, then call multiply to multiply the result by 4. State the final result.

- Expected tool calls: add
- Allow additional tool calls: Yes
- Judge criteria: Leave blank
- Judge mode: Binary (if criteria are configured)

### additional_tools_forbidden

**Input:** Call add to calculate 2 + 3, then call multiply to multiply the result by 4. State the final result.

- Expected tool calls: add
- Allow additional tool calls: No
- Judge criteria: Leave blank
- Judge mode: Binary (if criteria are configured)

### judge_and_tool_failure

**Input:** Use only subtract to calculate 10 - 3. State only the actual result returned by the tool.

- Expected tool calls: add
- Allow additional tool calls: No
- Judge criteria: The response explicitly states that the result is 99.
- Judge mode: Binary
- Expected outcome: FAIL for both the tool check and judge check.

## Running the failure examples

Each of suites 10-12 should show one passing control and two failures. Cases are tagged
`sample` plus `control` or `negative`. In the form, set **Run a subset > Tag** to
`negative` to run only failures, or leave it blank to include the passing control.
These deliberately incorrect expectations test failure displays even when the agent answers correctly.

```bash
.venv/bin/python cookbook/09_evals/suite/suite_api_samples.py --url http://localhost:7780 --suite 10
.venv/bin/python cookbook/09_evals/suite/suite_api_samples.py --url http://localhost:7780 --suite 11
.venv/bin/python cookbook/09_evals/suite/suite_api_samples.py --url http://localhost:7780 --suite 12
```

## Uploading cases in the UI

In the suite editor, choose **Upload cases** and select
[suite_api_failure_cases.json](suite_api_failure_cases.json) to add all six
intentional failure cases. Choose a suite name and review the cases before
clicking **Run Suite**. These cases target the local Math Tutor (`math-tutor`).

Uploads accept a JSON array of case definitions or a single suite object with a
`cases` array. The twelve-suite bundle must be split into individual `payload`
objects first. Uploaded cases are appended to your draft, replacing only the
initial untouched blank case; suite settings stay as entered. Invalid files,
duplicate case names, and more than 100 total cases are rejected without changing
the draft. Files must be no larger than 1 MB. Saved result reports are not case
definitions; use **Rerun** to load their original inputs.
