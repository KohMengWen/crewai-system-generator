#!/usr/bin/env python
import os
import argparse
import json  # NEW
import traceback
import gradio as gr

from crewai import Crew, Process  # NEW
from engineering_team.crew import EngineeringTeam, DesignPlan  # NEW

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

DEFAULT_MODULE = "accounts.py"
DEFAULT_CLASS = "Account"

def _ensure_py_extension(name: str) -> str:
    return name if name.endswith(".py") else f"{name}.py"

def generate_system(requirements: str) -> str:
    if not requirements.strip():
        return "❌ Please enter the requirements."

    try:
        # PHASE 1: run design task only (EngineeringTeam.crew() returns a crew with the design task)
        team = EngineeringTeam()
        crew1 = team.crew()
        crew1.kickoff(inputs={
            "requirements": requirements.strip()
        })

        # Get the structured plan (prefer in-memory pydantic; fallback to file)
        try:
            plan = crew1.tasks[0].output.pydantic  # DesignPlan
        except Exception:
            with open(os.path.join(OUTPUT_DIR, "design_plan.json"), "r", encoding="utf-8") as f:
                plan = DesignPlan(**json.load(f))

        # PHASE 2: build dynamic tasks from the plan and run them
        # (requires you added EngineeringTeam.build_dynamic_tasks(plan) in crew.py)
        dyn_tasks = team.build_dynamic_tasks(plan)
        crew2 = Crew(agents=team.agents, tasks=dyn_tasks, process=Process.sequential, verbose=True)
        crew2.kickoff()

        # Verify key artifacts exist
        expected = [m.module_name for m in plan.modules]
        expected += [f"test_{m.module_name}" for m in plan.modules]
        expected += ["app.py"]

        missing = [f for f in expected if not os.path.exists(os.path.join(OUTPUT_DIR, f))]
        if missing:
            return "⚠️ Generation finished, but missing files: " + ", ".join(missing)

        return "✅ The system has been generated successfully."
    except Exception as e:
        print("\n--- FULL ERROR TRACEBACK ---")
        traceback.print_exc()
        print("--- END TRACEBACK ---\n")
        return f"❌ An error occurred: {e}"

def build_ui(share: bool = False):
    with gr.Blocks(title="CrewAI System Generator") as demo:
        gr.Markdown("# 🛠️ CrewAI System Generator")
        gr.Markdown("Enter the requirements for your system and click **Generate System**.")

        req = gr.Textbox(label="Requirements", lines=10, placeholder="Describe your system here...")

        run_btn = gr.Button("🚀 Generate System", variant="primary")
        status_box = gr.Textbox(label="Status", value="", interactive=False)

        def run_with_status(requirements):
            yield "⏳ Generating your system, please wait..."
            yield generate_system(requirements)

        run_btn.click(run_with_status, inputs=[req], outputs=status_box)

    demo.launch(share=share, debug=True)

def run():
    parser = argparse.ArgumentParser(description="CrewAI System Generator UI")
    parser.add_argument("--share", action="store_true", help="Create a public share URL")
    args, _ = parser.parse_known_args()
    build_ui(share=args.share or os.getenv("SHARE", "").lower() in {"1", "true", "yes"})

if __name__ == "__main__":
    run()
