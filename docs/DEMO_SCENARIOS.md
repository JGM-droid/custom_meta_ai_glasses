# Demo Scenarios

## Scenario 1: Workflow Continuity

Goal:
- Demonstrate that the assistant can classify continuity state across sequential screenshots.

Setup:
- Ensure Python environment and dependencies are installed.
- Ensure test images are present in [code/prototype_v1/test_images](code/prototype_v1/test_images).

Steps:
1. Run continuity smoke test: [code/prototype_v1/test_continuity_flow.py](code/prototype_v1/test_continuity_flow.py).
2. Observe output for continuation and new-task cases.

Expected Output:
- task_continuity should align with expected case labels in the script.
- Script reports pass/fail per case and overall result.

Why It Matters:
- Continuity is the foundation for stateful assistance and correct next-step guidance.

## Scenario 2: Stuck Detection

Goal:
- Demonstrate stuck detection behavior under repeated task progression.

Setup:
- Ensure a Razer task image exists (for repeated run).
- Use [code/prototype_v1/demo_scenario.py](code/prototype_v1/demo_scenario.py).

Steps:
1. Run [code/prototype_v1/demo_scenario.py](code/prototype_v1/demo_scenario.py).
2. Focus on the second run in the sequence (repeated Razer task image).

Expected Output:
- stuck_status is expected to show repeated next-step behavior for repeated task context.
- intervention message should reflect stuck-aware guidance when recommended.

Why It Matters:
- Detecting stalled progress is important for practical workflow assistance.

## Scenario 3: Resume Previous Task

Goal:
- Demonstrate that prior task context can be surfaced for continuation.

Setup:
- Ensure at least one prior observation has been generated.
- Use [code/prototype_v1/demo_scenario.py](code/prototype_v1/demo_scenario.py) or run sequential pipeline calls manually.

Steps:
1. Run a task image through the pipeline.
2. Run a follow-up image in the same workflow.
3. Inspect resume_previous_task in [code/prototype_v1/results/latest_response.json](code/prototype_v1/results/latest_response.json).

Expected Output:
- resume_previous_task should include availability, task name, prior completed steps, and next-step context when available.

Why It Matters:
- Resume support reduces cognitive overhead after interruptions.

## Scenario 4: Smart Intervention

Goal:
- Demonstrate concise intervention generation from workflow state.

Setup:
- Use [code/prototype_v1/demo_scenario.py](code/prototype_v1/demo_scenario.py) with repeated task image sequence.

Steps:
1. Run [code/prototype_v1/demo_scenario.py](code/prototype_v1/demo_scenario.py).
2. Inspect intervention output after each scenario stage.

Expected Output:
- intervention includes recommended, message, and reason fields.
- Repeated-task phase should commonly produce intervention-oriented messaging.
- Non-repeated/new-task phase should commonly produce continue-current-step messaging.

Why It Matters:
- Smart intervention translates state detection into actionable user guidance.
